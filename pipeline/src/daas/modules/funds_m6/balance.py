"""Simulacion del balance de boveda por fondo+denominacion de M6 (U6).

Evoluciona el saldo dia a dia por (`fondo_id`, `denominacion`) sobre el
horizonte (dias corridos), partiendo del saldo inicial (SUP-07) y aplicando el
efecto neto distribuido por denominacion (SUP-09). El saldo NUNCA es negativo:
si el efecto empuja a negativo, el remanente se registra como `deficit` (senal
de provision) y el saldo cierra en 0 (clip, igual disciplina que `m3/saldo.py`).

Los umbrales minimo/maximo operativos los propone Pragma (SUP-10 / D-MINMAX-1):
percentiles del saldo diario historico por fondo+denominacion, parametrizables,
con fallback que mantiene el `maximo` SIEMPRE finito (nunca NaN) para que el lado
`exceso` no se desactive en silencio.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def operational_minmax(
    available_cash: pd.DataFrame,
    balance_initial: pd.DataFrame,
    cutoff: _dt.date,
    config: dict,
) -> pd.DataFrame:
    """Minimos/maximos operativos por fondo+denominacion (SUP-10 / D-MINMAX-1).

    Regla por defecto: `minimo = percentil p_min` y `maximo = percentil p_max`
    del SALDO DIARIO por (fondo_id, denominacion), donde el saldo diario = suma de
    `valor` sobre calidad x familia de ese dia, en una ventana parametrizable que
    termina en el corte (`minmax.ventana_dias`). Fallback sin dejar hueco en el
    lado `exceso`: si un fondo+den no tiene historico, `minimo = fallback_minimo`
    (0.0) y `maximo = k_fallback_maximo * saldo_inicial` (k=3.0 por defecto), de
    modo que el `maximo` NUNCA es NaN; WARNING en ambos casos.

    Args:
        available_cash: Salida de `dataset.cargar_disponibles` (saldo historico).
        balance_initial: Salida de `initial_balance_by_fund_denomination` (para el
            fallback del maximo).
        cutoff: Fecha de corte de la ventana.
        config: Configuracion de M6 (usa `minmax`).

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `denominacion`, `minimo`, `maximo`
        (`maximo` nunca NaN).
    """
    cfg = config.get("minmax", {})
    p_min = float(cfg.get("p_min", 0.10))
    p_max = float(cfg.get("p_max", 0.90))
    window_days = int(cfg.get("ventana_dias", 180))
    fallback_min = float(cfg.get("fallback_minimo", 0.0))
    k_fallback_max = float(cfg.get("k_fallback_maximo", 3.0))
    if not (0.0 <= p_min <= p_max <= 1.0):
        logger.warning(
            "minmax: percentiles fuera de rango (p_min=%s, p_max=%s); se " "reajustan al default 0.10/0.90.",
            p_min,
            p_max,
        )
        p_min, p_max = 0.10, 0.90

    base = available_cash[available_cash["fecha"] <= cutoff].copy()
    # ALX (SUP-29): dias marcados como no validos (blanco o doble formato) no entran a la ventana de percentiles.
    if "fuera_ventana_minmax" in base.columns:
        base = base[~base["fuera_ventana_minmax"].fillna(False).astype(bool)]
    if window_days and window_days > 0:
        since = cutoff - _dt.timedelta(days=window_days - 1)
        base = base[base["fecha"] >= since]
    # Saldo diario = suma de valor sobre calidad x familia por (fondo, den, dia).
    daily = base.groupby(["fondo_id", "denominacion", "fecha"], as_index=False)["valor"].sum()

    saldo0 = {
        (str(f), int(d)): float(s)
        for f, d, s in zip(
            balance_initial["fondo_id"],
            balance_initial["denominacion"],
            balance_initial["saldo_inicial"],
            strict=False,
        )
    }

    rows: list[dict[str, Any]] = []
    for fund, denom in saldo0:
        sub = daily[(daily["fondo_id"].astype(str) == fund) & (daily["denominacion"] == denom)]
        if not sub.empty and sub["valor"].notna().any():
            min_value = float(sub["valor"].quantile(p_min))
            max_value = float(sub["valor"].quantile(p_max))
        else:
            min_value = fallback_min
            max_value = k_fallback_max * saldo0[(fund, denom)]
            logger.warning(
                "minmax: fondo %s denominacion %s sin historico; minimo=%s, "
                "maximo=%s*saldo_inicial (SUP-10, no se inventa umbral).",
                fund,
                denom,
                fallback_min,
                k_fallback_max,
            )
        rows.append(
            {
                "fondo_id": fund,
                "denominacion": int(denom),
                "minimo": min_value,
                "maximo": max_value,
            }
        )
    return pd.DataFrame(rows, columns=["fondo_id", "denominacion", "minimo", "maximo"])


def simulate_fund_denomination_balance(
    balance_initial: pd.DataFrame,
    effect_denom: pd.DataFrame,
    minmax: pd.DataFrame,
    dates: list[_dt.date],
) -> pd.DataFrame:
    """Simula el balance diario por fondo+denominacion sobre el horizonte (RF-3).

    Por cada (fondo_id, denominacion) evoluciona el saldo dia a dia partiendo del
    `saldo_inicial` y aplicando el `efecto_neto_den` del dia. CLIP a 0: si el
    efecto empuja a negativo, se registra `deficit = max(0, -(saldo_prev +
    efecto))` y el saldo cierra en 0. Marca `riesgo_deficit` (saldo < minimo) y
    `riesgo_exceso` (saldo > maximo).

    Args:
        balance_initial: Salida de `initial_balance_by_fund_denomination`.
        effect_denom: Salida de `distribute_effect_by_denomination`.
        minmax: Salida de `operational_minmax`.
        dates: Fechas del horizonte (dias calendario, orden ascendente).

    Returns:
        pd.DataFrame: Una fila por (fondo_id, denominacion, fecha) con columnas
        `saldo_inicial_dia`, `efecto_neto_den`, `saldo_proyectado`, `deficit`,
        `minimo`, `maximo`, `riesgo_deficit` (bool), `riesgo_exceso` (bool).
        `saldo_proyectado` SIEMPRE >= 0.
    """
    dates_sorted = sorted(dates)
    saldo0 = {
        (str(f), int(d)): float(s)
        for f, d, s in zip(
            balance_initial["fondo_id"],
            balance_initial["denominacion"],
            balance_initial["saldo_inicial"],
            strict=False,
        )
    }
    minmax_map = {
        (str(f), int(d)): (float(mn), float(mx))
        for f, d, mn, mx in zip(
            minmax["fondo_id"],
            minmax["denominacion"],
            minmax["minimo"],
            minmax["maximo"],
            strict=False,
        )
    }
    effect_map: dict[tuple[str, int, _dt.date], float] = {}
    if not effect_denom.empty:
        for f, fe, d, v in zip(
            effect_denom["fondo_id"],
            effect_denom["fecha"],
            effect_denom["denominacion"],
            effect_denom["efecto_neto_den"],
            strict=False,
        ):
            effect_map[(str(f), fe, int(d))] = float(v)

    rows: list[dict[str, Any]] = []
    for (fund, denom), s0 in saldo0.items():
        min_value, max_value = minmax_map.get((fund, denom), (0.0, float("nan")))
        balance_prev = s0
        for date in dates_sorted:
            effect = effect_map.get((fund, date, denom), 0.0)
            gross = balance_prev + effect
            if gross < 0.0:
                deficit = -gross
                balance_closing = 0.0
            else:
                deficit = 0.0
                balance_closing = gross
            risk_deficit = bool(balance_closing < min_value)
            risk_excess = bool((not pd.isna(max_value)) and balance_closing > max_value)
            rows.append(
                {
                    "fondo_id": fund,
                    "denominacion": int(denom),
                    "fecha": date,
                    "saldo_inicial_dia": balance_prev,
                    "efecto_neto_den": effect,
                    "saldo_proyectado": balance_closing,
                    "deficit": deficit,
                    "minimo": min_value,
                    "maximo": max_value,
                    "riesgo_deficit": risk_deficit,
                    "riesgo_exceso": risk_excess,
                }
            )
            balance_prev = balance_closing

    columns = [
        "fondo_id",
        "denominacion",
        "fecha",
        "saldo_inicial_dia",
        "efecto_neto_den",
        "saldo_proyectado",
        "deficit",
        "minimo",
        "maximo",
        "riesgo_deficit",
        "riesgo_exceso",
    ]
    return pd.DataFrame(rows, columns=columns).sort_values(["fondo_id", "denominacion", "fecha"]).reset_index(drop=True)
