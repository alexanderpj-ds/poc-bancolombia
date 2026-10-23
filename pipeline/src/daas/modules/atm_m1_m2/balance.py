"""Simulacion del saldo operativo de los ATM M1 dispensador y M2 multifuncional.

M1 dispensador (Anexo B RN-09 a RN-13, RN-34):

- `cupo_operativo` = MENOR(cupo del maestro CP, `m1.tope_saldo_inicial` [500 M]) (RN-09, RN-10).
- `saldo_inicial` = `cupo_operativo` (RN-11).
- La politica (`m1.policy`, `decision.policies`) decide con el pronostico el dia de cada provision; la
  provision llega antes del pagado y lleva el saldo al cupo operativo (RN-11). El saldo nunca es
  negativo: si el pagado supera el disponible, el dia cierra en 0 (agotamiento).

M2 multifuncional (Anexo B RN-19 a RN-24, RN-30, RN-35):

- `cupo_operativo` = cupo del maestro CP; `saldo_inicial` = cupo (RN-19, RN-24).
- Saldo neto: el efectivo recibido se recicla (RN-30), no hay cassette aparte.
- Por dia: provision en la manana hasta el cupo si el saldo proyectado del dia bajaria del umbral
  (RN-19A, RN-21, RN-34); luego `saldo += cash_in - pagado`; al cierre se recoge lo que pase del
  cupo, hasta dejarlo en el cupo (RN-22, RN-35). Con las dos acciones el mismo dia, la provision va
  primero (manana) y la recoleccion despues (cierre), asi el saldo no cierra ni negativo ni sobre el
  cupo (RN-21, RN-28).

Montos en COP enteros (RN-01, RN-13): los flujos pronosticados se redondean a pesos al entrar, de modo
que saldos, provisiones y recolecciones quedan enteros y cada provision deja el saldo justo en el cupo.
Un cajero sin `cupo` emite un ``logging.warning`` y usa el tope como cupo (no se inventa un cupo).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from daas.decision import policies as policies

logger = logging.getLogger(__name__)

#: Tope del saldo inicial por defecto (COP) si falta en la config.
_DEFAULT_INITIAL_BALANCE_CAP = 500000000
#: Umbral de agotamiento por defecto (fraccion del cupo) si falta en la config.
_DEFAULT_DEPLETION_THRESHOLD = 0.08
#: Politica de provision de M2 si falta en la config: la regla del pliego (RN-21) decidida con el
#: pronostico neto, sin margen.
_DEFAULT_M2_POLICY = {"familia": "umbral_pronostico_a_cupo", "margen": 0.0}


def _weights(series: pd.Series) -> np.ndarray:
    """Flujo pronosticado en pesos enteros (RN-01): NaN -> 0, redondeo al peso."""
    return np.round(pd.to_numeric(series, errors="coerce").fillna(0.0).to_numpy(dtype=float))


def _params_m1(params: dict[str, Any] | None) -> tuple[float, float]:
    """Extrae `(tope_saldo_inicial, umbral_agotamiento)` de la config M1.

    Acepta tanto la config completa (`{'m1': {...}}`) como el sub-dict `m1`
    directamente; aplica los defaults documentados si falta alguna clave.

    Args:
        params: Config de modelo (completa o el sub-dict `m1`); puede ser `None`.

    Returns:
        tuple[float, float]: `(tope_saldo_inicial, umbral_agotamiento)`.
    """
    cfg = params or {}
    m1 = cfg.get("m1", cfg) if isinstance(cfg, dict) else {}
    cap = float(m1.get("tope_saldo_inicial", _DEFAULT_INITIAL_BALANCE_CAP))
    threshold = float(m1.get("umbral_agotamiento", _DEFAULT_DEPLETION_THRESHOLD))
    return cap, threshold


def _policy_m1(params: dict[str, Any] | None, threshold: float) -> tuple[Any, int]:
    """Resuelve la politica de provision de M1 y su lead time.

    Sin `politica` en la config se usa la regla original (`threshold_to_capacity` con el
    umbral de agotamiento y lead time 0), que reproduce el comportamiento previo.

    Args:
        params: Config de modelo (completa o el sub-dict `m1`); puede ser `None`.
        threshold: Umbral de agotamiento ya resuelto (default de `threshold_to_capacity`).

    Returns:
        tuple: `(politica, lead_time_dias)`.
    """
    cfg = params or {}
    cfg = cfg.get("m1", cfg) if isinstance(cfg, dict) else {}
    policy = policies.build_policy(cfg.get("politica") or {"familia": "umbral_a_cupo"}, umbral=threshold)
    return policy, int(cfg.get("lead_time_dias", 0))


def _params_m2(params: dict[str, Any] | None) -> tuple[float, Any]:
    """Extrae `(umbral_agotamiento, politica)` de la config M2 (completa o el sub-dict `m2`).

    Args:
        params: Config de modelo; puede ser `None`.

    Returns:
        tuple: `(umbral_agotamiento, politica)`; la politica ya construida con el umbral.
    """
    cfg = params or {}
    m2 = cfg.get("m2", cfg) if isinstance(cfg, dict) else {}
    threshold = float(m2.get("umbral_agotamiento", _DEFAULT_DEPLETION_THRESHOLD))
    policy = policies.build_policy(m2.get("politica") or _DEFAULT_M2_POLICY, umbral=threshold)
    return threshold, policy


def _operational_capacity(capacity: float | None, cap: float, code_atm: Any = None) -> float:
    """Resuelve el cupo operativo de un cajero (con fallback documentado).

    Un cajero sin `cupo` (NA/None) emite un WARNING y usa `tope` (500M) como
    cupo operativo; NO se inventa un cupo arbitrario.

    Args:
        capacity: Cupo del maestro CP (puede ser NA/None).
        cap: Tope del saldo inicial (500M por defecto), usado como fallback.
        code_atm: Identificador del cajero (solo para el mensaje de log).

    Returns:
        float: Cupo operativo a usar en la simulacion.
    """
    missing = capacity is None or (isinstance(capacity, float) and pd.isna(capacity)) or pd.isna(capacity)
    if missing:
        logger.warning(
            "Cajero %s sin cupo en el maestro CP; se usa el tope %s como cupo "
            "operativo (gap documentado, no se inventa cupo).",
            code_atm,
            cap,
        )
        return float(cap)
    return float(capacity)


def simulate_balance_m1(
    series_atm: pd.DataFrame,
    capacity: float | None,
    params: dict[str, Any] | None = None,
    paid_col: str = "yhat",
    date_col: str = "fecha",
    provision_col: str = "provision",
    code_atm: Any = None,
) -> pd.DataFrame:
    """Simula el saldo diario del ATM dispensador M1 (Anexo B RN-09 a RN-13, RN-34).

    `cupo_operativo = min(cupo del maestro, tope [500M])` (RN-09) y `saldo_inicial = cupo_operativo`
    (RN-11). El saldo NUNCA baja de 0 (clip inferior) y la provision es ENDOGENA (realimenta el saldo
    hasta el cupo operativo). Marca en riesgo de agotamiento los dias en que, sin provision, el saldo
    bajaria del umbral (RN-34), o en que el saldo se agota.

    La PROVISION es ENDOGENA: la simulacion decide y realimenta la
    provision en el mismo paso, de forma determinista y sin segunda pasada. Por
    cada dia del horizonte:

    1. `saldo_apertura = saldo_cierre_prev` (dia 0: `cupo_operativo`).
    2. La POLITICA (`m1.policy`, ver `decision.policies`) decide el pedido con
       la posicion (saldo + pedidos en transito) y el pronostico. Por defecto es
       la regla original: si `saldo_apertura < umbral_valor`, pide hasta el cupo
       operativo. Lo pedido llega `m1.lead_time_dias` dias despues (0 = en el
       acto). Lo que LLEGA cada dia se registra en la columna `provision`
       (insumo de recomendaciones + costo): su fecha es la de entrega.
    3. `saldo_cierre = max(saldo_apertura - pagado_t, 0.0)` (CLIP inferior en 0).
       Si el pagado del dia supera el disponible, el saldo del dia queda en 0 y
       eso es la senal de agotamiento (`agotado_dia`).

    El `saldo` devuelto SIEMPRE esta en `[0, cupo_operativo]`. Si el `serie_cajero`
    trae `provision_col`, se IGNORA (la provision ahora es endogena): la columna
    de salida reporta la provision realimentada por la simulacion.

    Args:
        series_atm: Serie diaria de UN cajero, ordenable por `fecha_col` y con
            la columna de pagado pronosticado `pagado_col`.
        capacity: Cupo del maestro CP (`interim/cp_historico`); NA -> fallback 500M.
        params: Config de modelo (completa o sub-dict `m1`) con
            `tope_saldo_inicial` y `umbral_agotamiento`. Defaults documentados.
        paid_col: Nombre de la columna de pagado pronosticado del horizonte.
        date_col: Nombre de la columna de fecha.
        provision_col: Nombre de la columna de provision diaria (ignorada: la
            provision es endogena).
        code_atm: Identificador del cajero (para logs/salida; si es `None` se
            intenta leer de `serie_cajero['cod_cajero']`).

    Returns:
        pd.DataFrame: Serie diaria con columnas `cod_cajero`, `fecha`,
        `pagado`, `provision`, `saldo_inicial_dia`, `saldo_sin_provision` (cierre del dia sin
        provision), `saldo`, `cupo_operativo`,
        `umbral_valor`, `riesgo_agotamiento` (bool). `saldo` en `[0,
        cupo_operativo]`; `provision` con el monto endogeno realimentado.
        Ordenada por fecha.
    """
    cap, threshold = _params_m1(params)

    if code_atm is None and "cod_cajero" in series_atm.columns:
        values = series_atm["cod_cajero"].dropna().unique().tolist()
        code_atm = values[0] if values else None

    # RN-09: el cupo operativo es el menor entre el cupo del maestro y el tope; es el saldo inicial (RN-11).
    capacity_op = min(_operational_capacity(capacity, cap, code_atm=code_atm), float(cap))
    balance_initial = capacity_op
    threshold_value = threshold * capacity_op

    series = series_atm.sort_values(date_col).reset_index(drop=True)
    yhat = _weights(series[paid_col])

    policy, lead_time = _policy_m1(params, threshold)
    # Pedidos en transito: lo pedido el dia d llega el dia d + lead_time.
    transit = np.zeros(len(yhat) + lead_time + 1)

    provisions: list[float] = []
    balances: list[float] = []
    balances_initial_day: list[float] = []
    balances_without_provision: list[float] = []
    risks: list[bool] = []
    balance_previous = balance_initial
    for d, paid_t in enumerate(yhat.tolist()):
        balance_opening = balance_previous
        balances_initial_day.append(balance_opening)
        # Cierre que tendria el dia sin provision: es lo que mira la alerta (RN-34).
        balances_without_provision.append(balance_opening - float(paid_t))
        # PROVISION ENDOGENA: la politica mira la posicion (saldo + transito) y
        # el pronostico, y pide. Con lead time 0 el pedido llega en el acto;
        # con lead time > 0 hoy solo llega lo pedido hace `lead_time` dias.
        # Lo que no cabe en el cupo no entra.
        if lead_time > 0:
            provision_t = min(float(transit[d]), capacity_op - balance_opening)
            balance_opening += provision_t
        position = balance_opening + float(transit[d + 1 : d + lead_time + 1].sum())
        # RN-13: el monto es entero; se redondea hacia abajo para no pasar del cupo.
        request = float(np.floor(max(float(policy(d, position, yhat, capacity_op, lead_time)), 0.0)))
        if lead_time == 0:
            provision_t = min(request, capacity_op - balance_opening)
            balance_opening += provision_t
        else:
            transit[d + lead_time] += request
        provisions.append(provision_t)
        # Flujo del dia con CLIP inferior en 0: si el pagado supera el
        # disponible, el saldo del dia queda en 0 (senal de agotamiento).
        gross = balance_opening - float(paid_t)
        depleted_day = gross < 0.0
        balance_closing = max(gross, 0.0)
        balances.append(balance_closing)
        # Riesgo de agotamiento: sin la provision el saldo bajaria del umbral, o el dia se agota igual.
        risks.append(bool(depleted_day or balances_without_provision[-1] < threshold_value))
        balance_previous = balance_closing

    out = pd.DataFrame(
        {
            "cod_cajero": code_atm,
            "fecha": series[date_col].tolist(),
            "pagado": yhat.tolist(),
            "provision": provisions,
            "saldo_inicial_dia": balances_initial_day,
            "saldo_sin_provision": balances_without_provision,
            "saldo": balances,
        }
    )
    out["cupo_operativo"] = capacity_op
    out["umbral_valor"] = threshold_value
    out["riesgo_agotamiento"] = risks
    return out


def simulate_balance_m2(
    series_atm: pd.DataFrame,
    capacity: float | None,
    params: dict[str, Any] | None = None,
    paid_col: str = "yhat",
    cash_in_col: str = "cash_in",
    date_col: str = "fecha",
    code_atm: Any = None,
) -> pd.DataFrame:
    """Simula el saldo neto diario del ATM multifuncional M2 (Anexo B RN-19 a RN-24, RN-30, RN-35).

    `saldo_inicial = cupo` (sin tope: RN-24). Por cada dia:

    1. PROVISION en la manana, antes del pagado (RN-19): la politica (`m2.politica`; por defecto la
       regla del pliego con margen 0) mira el saldo de apertura y el pronostico neto (pagado - cash_in)
       y, si el saldo del dia bajaria del umbral (RN-21, RN-34), completa hasta el cupo (RN-19A).
    2. Flujo neto del dia: `saldo += cash_in - pagado` (RN-30: el efectivo recibido se recicla).
    3. RECOLECCION al cierre: lo que pase del cupo, hasta dejar el saldo en el cupo (RN-22, RN-35).
    4. Piso en 0: si el pagado supera el disponible, el dia cierra en 0 (agotamiento).

    Los flujos se redondean a pesos al entrar (RN-01): saldos y montos quedan enteros.

    Args:
        series_atm: Serie diaria de UN cajero con `pagado_col` y `cash_in_col` pronosticados.
        capacity: Cupo del maestro CP; NA -> el tope de M1 con WARNING (no se inventa cupo).
        params: Config de modelo (completa o sub-dict `m2`) con `umbral_agotamiento` y `politica`.
        paid_col: Columna de pagado pronosticado.
        cash_in_col: Columna de cash_in pronosticado (si falta, 0).
        date_col: Columna de fecha.
        code_atm: Identificador del cajero (si es `None` se lee de `serie_cajero['cod_cajero']`).

    Returns:
        pd.DataFrame: Serie diaria con `cod_cajero`, `fecha`, `pagado`, `cash_in`, `provision`,
        `recoleccion`, `saldo_inicial_dia`, `saldo_sin_provision` (cierre sin provision ni
        recoleccion), `saldo_antes_recoleccion`, `saldo`, `cupo_operativo`, `umbral_valor`,
        `riesgo_agotamiento`, `riesgo_recoleccion`. `saldo` en `[0, cupo]`. Ordenada por fecha.
    """
    cap, _ = _params_m1(params)
    threshold, policy = _params_m2(params)

    if code_atm is None and "cod_cajero" in series_atm.columns:
        values = series_atm["cod_cajero"].dropna().unique().tolist()
        code_atm = values[0] if values else None

    capacity_op = _operational_capacity(capacity, cap, code_atm=code_atm)
    threshold_value = threshold * capacity_op

    series = series_atm.sort_values(date_col).reset_index(drop=True)
    paid = _weights(series[paid_col])
    cash_in = _weights(series[cash_in_col]) if cash_in_col in series.columns else np.zeros(len(series))
    net = paid - cash_in

    provisions: list[float] = []
    collections: list[float] = []
    balances: list[float] = []
    balances_initial_day: list[float] = []
    balances_without_provision: list[float] = []
    balances_before_collection: list[float] = []
    risks_depletion: list[bool] = []
    risks_collection: list[bool] = []
    balance_previous = capacity_op
    for d in range(len(series)):
        balances_initial_day.append(balance_previous)
        balances_without_provision.append(balance_previous - float(net[d]))
        # 1) Provision en la manana: hasta el cupo, si la politica la pide (RN-13: entero).
        request = float(np.floor(max(float(policy(d, balance_previous, net, capacity_op, 0)), 0.0)))
        provision_t = min(request, capacity_op - balance_previous)
        provisions.append(provision_t)
        # 2) Flujo neto del dia; piso en 0 (agotamiento).
        gross = balance_previous + provision_t - float(net[d])
        depleted_day = gross < 0.0
        flow = max(gross, 0.0)
        balances_before_collection.append(flow)
        # 3) Recoleccion al cierre de lo que pase del cupo.
        collection_t = max(flow - capacity_op, 0.0)
        collections.append(collection_t)
        balance_closing = flow - collection_t
        balances.append(balance_closing)
        risks_depletion.append(bool(depleted_day or balances_without_provision[-1] < threshold_value))
        risks_collection.append(bool(collection_t > 0.0))
        balance_previous = balance_closing

    out = pd.DataFrame(
        {
            "cod_cajero": code_atm,
            "fecha": series[date_col].tolist(),
            "pagado": paid.tolist(),
            "cash_in": cash_in.tolist(),
            "provision": provisions,
            "recoleccion": collections,
            "saldo_inicial_dia": balances_initial_day,
            "saldo_sin_provision": balances_without_provision,
            "saldo_antes_recoleccion": balances_before_collection,
            "saldo": balances,
        }
    )
    out["cupo_operativo"] = capacity_op
    out["umbral_valor"] = threshold_value
    out["riesgo_agotamiento"] = risks_depletion
    out["riesgo_recoleccion"] = risks_collection
    return out
