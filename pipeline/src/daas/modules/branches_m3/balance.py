"""Simulacion del saldo operativo de la boveda de sucursal fisica M3 (U3).

Adapta la disciplina corregida de `daas.modules.atm_m1_m2.balance.simular_saldo_m2`
(provision + recoleccion ENDOGENAS, saldo clipado y NUNCA negativo) al caso de
las sucursales fisicas:

- El cap superior de la boveda es `cupo_max_suc` (SUP-M3-01: `cupo_max_suc` ES
  el maximo de la boveda, no un tope del dispensador).
- `entradas` = efectivo que ingresa a la sucursal (cash-in).
- `salidas`  = efectivo pagado/entregado por la sucursal (equivalente al
  `pagado` de los ATM).
- `saldo_inicial = cupo_max_suc`.

ORDEN del dia (igual que M2, hecho #5 / RN-21), con provision/recoleccion
ENDOGENAS y clip en `[0, cupo_max_suc]`:

1. PROVISION en la manana: si `saldo_apertura < umbral_valor`
   (`= umbral_agotamiento * cupo_max_suc`) se recarga hasta `cupo_max_suc`.
2. Flujo del dia: `saldo += entradas_t - salidas_t`.
3. RECOLECCION al cierre: el disparador de recoleccion es el cap duro de la
   boveda (`cupo_max_suc`): `recoleccion_t = max(saldo - cupo_max_suc, 0)` y
   `saldo -= recoleccion_t`.
4. CLIP de `saldo` a `[0, cupo_max_suc]`: la boveda nunca queda negativa ni por
   encima del maximo.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Reglas que disparan cada accion (RN-40: "regla que la dispara").
_EXPECTED_RULE = "saldo_previsto_bajo_reserva"
_OPENING_RULE = "apertura_bajo_umbral"
_CAPACITY_EXCESS_RULE = "exceso_sobre_cupo"
_IDLE_RULE = "efectivo_ocioso_sobre_techo"

#: Umbral de agotamiento por defecto (fraccion del cupo) si falta en la config.
_DEFAULT_DEPLETION_THRESHOLD = 0.08


def _threshold_m3(params: dict[str, Any] | None) -> float:
    """Extrae `umbral_agotamiento` de la config M3 (fraccion del cupo_max_suc).

    Acepta tanto la config completa (`{'m3': {...}}`) como el sub-dict `m3`
    directamente; aplica el default documentado si falta la clave.

    Args:
        params: Config de modelo (completa o el sub-dict `m3`); puede ser `None`.

    Returns:
        float: `umbral_agotamiento` (fraccion del cupo_max_suc).
    """
    cfg = params or {}
    m3 = cfg.get("m3", cfg) if isinstance(cfg, dict) else {}
    return float(m3.get("umbral_agotamiento", _DEFAULT_DEPLETION_THRESHOLD))


def simulate_balance_m3(
    series_branch: pd.DataFrame,
    branch_max_capacity: float,
    params: dict[str, Any] | None = None,
    inflows_col: str = "entradas",
    outflows_col: str = "salidas",
    date_col: str = "fecha",
    code_branch: Any = None,
    policy: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Simula el saldo diario de la boveda de sucursal M3 (U3, SUP-M3-01).

    Reproduce la disciplina corregida de `simulate_balance_m2` con el cap superior
    en `cupo_max_suc` (SUP-M3-01). La PROVISION y la RECOLECCION son ENDOGENAS:
    la simulacion las decide y realimenta en el mismo paso, de forma
    determinista. Por cada dia del horizonte:

    1. `saldo_apertura = saldo_cierre_prev` (dia 0: `cupo_max_suc`).
    2. PROVISION (manana): si `saldo_apertura < umbral_valor`
       (`= umbral_agotamiento * cupo_max_suc`) -> `provision_t = cupo_max_suc -
       saldo_apertura`; `saldo_apertura += provision_t`.
    3. Flujo: `saldo = saldo_apertura + entradas_t - salidas_t`.
    4. RECOLECCION (cierre): `recoleccion_t = max(saldo - cupo_max_suc, 0)`;
       `saldo -= recoleccion_t` (el disparador es el cap duro de la boveda).
    5. CLIP de `saldo` a `[0, cupo_max_suc]`.

    `riesgo_agotamiento = saldo <= 0 o saldo < umbral_valor`;
    `riesgo_excedente  = recoleccion_t > 0 o saldo >= cupo_max_suc`.

    Args:
        series_branch: Serie diaria de UNA sucursal, ordenable por `fecha_col`
            y con las columnas de entradas/salidas pronosticadas.
        branch_max_capacity: Cap superior de la boveda (SUP-M3-01); tambien el saldo
            inicial.
        params: Config de modelo (completa o sub-dict `m3`) con
            `umbral_agotamiento`. Default documentado si falta.
        inflows_col: Nombre de la columna de entradas pronosticadas (cash-in).
        outflows_col: Nombre de la columna de salidas pronosticadas (pagado).
        date_col: Nombre de la columna de fecha.
        code_branch: Identificador de la sucursal (para logs/salida; si es
            `None` se intenta leer de `serie_sucursal['cod_sucursal']`).
        policy: Politica diferenciada de la sucursal (`modules.branches_m3.policy`): `reserva`,
            `objetivo`, `techo` (pesos enteros) y `usa_pronostico`. Con `None` rige la regla
            historica (reserva = umbral * cupo, llena al cupo, recoge sobre el cupo, sin pronostico).
            Con politica: PROVISION si `saldo_apertura (+ entradas - salidas pronosticadas) < reserva`,
            sube el saldo a `objetivo`; RECOLECCION de lo que pase de `techo`. `techo <= cupo` y
            `objetivo <= cupo`, asi el saldo nunca supera el cupo (RN-38).

    Returns:
        pd.DataFrame: Serie diaria con columnas `cod_sucursal`, `fecha`,
        `entradas`, `salidas`, `provision`, `recoleccion`, `saldo_inicial_dia`,
        `saldo`, `cupo_operativo` (= `cupo_max_suc`), `umbral_valor`,
        `saldo_antes_recoleccion`, `riesgo_agotamiento` (bool),
        `riesgo_excedente` (bool). `saldo` SIEMPRE en `[0, cupo_max_suc]`.
        Ordenada por fecha.
    """
    threshold = _threshold_m3(params)

    if code_branch is None and "cod_sucursal" in series_branch.columns:
        values = series_branch["cod_sucursal"].dropna().unique().tolist()
        code_branch = values[0] if values else None

    cap = float(branch_max_capacity)
    balance_initial = cap
    threshold_value = threshold * cap
    pol = policy or {}
    reserve = float(pol.get("reserva", threshold_value))
    target = float(pol.get("objetivo", cap))
    ceiling = float(pol.get("techo", cap))
    uses_forecast = bool(pol.get("usa_pronostico", False))

    series = series_branch.sort_values(date_col).reset_index(drop=True)
    # Flujos en pesos enteros (RN-01): saldos y montos quedan enteros.
    inflows = pd.to_numeric(series[inflows_col], errors="coerce").fillna(0.0).round()
    outflows = pd.to_numeric(series[outflows_col], errors="coerce").fillna(0.0).round()

    provisions: list[float] = []
    collections: list[float] = []
    balances: list[float] = []
    balances_initial_day: list[float] = []
    balances_before_collection: list[float] = []
    risks_depletion: list[bool] = []
    risks_surplus: list[bool] = []
    balances_expected: list[float] = []
    rules_provision: list[str | None] = []
    rules_rec: list[str | None] = []
    balance_previous = balance_initial
    for inflows_t, outflows_t in zip(inflows.tolist(), outflows.tolist(), strict=False):
        balances_initial_day.append(balance_previous)
        # 1-2) PROVISION ENDOGENA en la manana: recarga hasta cupo_max_suc si el
        #      saldo de apertura cruza el umbral de agotamiento.
        balance_opening = balance_previous
        expected = balance_opening + (float(inflows_t) - float(outflows_t) if uses_forecast else 0.0)
        balances_expected.append(expected)
        if expected < reserve:
            provision_t = float(np.floor(max(target - balance_opening, 0.0)))  # RN-13: entero
            balance_opening += provision_t
        else:
            provision_t = 0.0
        provisions.append(provision_t)
        rules_provision.append((_EXPECTED_RULE if uses_forecast else _OPENING_RULE) if provision_t > 0.0 else None)
        # 3) Flujo del dia: ingresan entradas (cash-in), salen salidas (pagado).
        balance_flow = balance_opening + float(inflows_t) - float(outflows_t)
        depleted_day = balance_flow < 0.0
        # 4) RECOLECCION ENDOGENA al cierre: se retira el exceso sobre el cap.
        balances_before_collection.append(max(balance_flow, 0.0))
        collection_t = float(np.ceil(max(balance_flow - ceiling, 0.0)))  # entero; deja el saldo <= techo <= cap
        rules_rec.append(None if collection_t <= 0.0 else (_CAPACITY_EXCESS_RULE if balance_flow > cap else _IDLE_RULE))
        balance_post = balance_flow - collection_t
        collections.append(collection_t)
        # 5) CLIP a [0, cupo_max_suc]: la boveda nunca es negativa ni supera el cap.
        balance_closing = min(max(balance_post, 0.0), cap)
        balances.append(balance_closing)
        risks_depletion.append(bool(depleted_day or balance_closing < threshold_value))
        risks_surplus.append(bool(collection_t > 0.0 or balance_closing >= cap))
        balance_previous = balance_closing

    out = pd.DataFrame(
        {
            "cod_sucursal": code_branch,
            "fecha": series[date_col].tolist(),
            "entradas": inflows.tolist(),
            "salidas": outflows.tolist(),
            "provision": provisions,
            "recoleccion": collections,
            "saldo_inicial_dia": balances_initial_day,
            "saldo_antes_recoleccion": balances_before_collection,
            "saldo": balances,
        }
    )
    out["saldo_previsto"] = balances_expected
    out["reserva"] = reserve
    out["objetivo"] = target
    out["techo"] = ceiling
    out["regla_provision"] = rules_provision
    out["regla_recoleccion"] = rules_rec
    out["cupo_operativo"] = cap
    out["umbral_valor"] = threshold_value
    out["riesgo_agotamiento"] = risks_depletion
    out["riesgo_excedente"] = risks_surplus
    return out
