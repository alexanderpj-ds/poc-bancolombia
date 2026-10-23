"""
Retadores de otras familias: estadístico local con calendario y combinación simple.

Mismo contrato que `registry.py`: `forecast(history, dates)` con `history` cortado en el origen. Los
argumentos con nombre en español son las claves del yml del experimento (`conf/experimentos/`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from daas.forecasting.forecasters import _fallback, prophet_with_calendar  # noqa: F401


def combination(
    history: pd.DataFrame, dates: pd.DatetimeIndex, *, miembros: list[str], pesos: list[float] | None = None
) -> pd.DataFrame:
    """Promedio simple, con pesos iguales y fijos (no se ajustan: no hay nada que filtrar).

    `pesos` (ALX fase 2, opcional): pesos fijos congelados fuera de muestra (`ml/ensambles.py`); se normalizan a
    suma 1. Sin `pesos` el calculo es el original, bit a bit.
    """
    from lab.forecasting.registry import MODELS

    if pesos is None:
        return sum(MODELS[m](history, dates).clip(lower=0.0) for m in miembros) / len(miembros)
    if len(pesos) != len(miembros):
        raise ValueError("`pesos` debe tener un valor por miembro.")
    total = float(sum(pesos))
    return sum(p / total * MODELS[m](history, dates).clip(lower=0.0) for m, p in zip(miembros, pesos, strict=True))


def calibrated_profile(
    history: pd.DataFrame, dates: pd.DatetimeIndex, *, base: str, lam: float, dias: int
) -> pd.DataFrame:
    """
    Lleva `base` (apunta a la mediana) hacia la media: × (1 + lam·(media/mediana − 1)) por entidad.

    La razón media/mediana se estima con los últimos `dias` días <= origen. lam=0 deja la base; lam=1 iguala
    el total esperado (sin sesgo si la razón se mantiene) a costa de más error absoluto.
    """
    from lab.forecasting.registry import MODELS

    tail = history.tail(dias)
    ratio = (tail.mean() / tail.median()).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    return MODELS[base](history, dates).clip(lower=0.0).mul(1.0 + lam * (ratio - 1.0), axis=1)


def _fill_gaps_by_weekday_median(series_matrix: pd.DataFrame) -> pd.DataFrame:
    """Rellena huecos con la mediana del mismo día de semana de la serie, sin crear serie antes del primer dato."""
    filled = series_matrix.fillna(series_matrix.groupby(series_matrix.index.dayofweek).transform("median")).fillna(0.0)
    return filled.where(series_matrix.notna().cumsum() > 0)


def local_statistical(
    history: pd.DataFrame, dates: pd.DatetimeIndex, *, modelo: str, params: dict, min_obs: int
) -> pd.DataFrame:
    """
    Un modelo estadístico clásico por entidad (`statsforecast.models.<modelo>`), sin calendario.

    Estos modelos no aceptan huecos: cada serie arranca en su primer dato y los huecos se rellenan con la
    mediana del mismo día de semana de la propia serie (solo datos <= origen). Menos de `min_obs` datos → respaldo.
    """
    from statsforecast import StatsForecast
    from statsforecast import models as statsforecast_models

    fallback = _fallback(history)
    prediction = pd.DataFrame(np.tile(fallback.to_numpy(), (len(dates), 1)), index=dates, columns=history.columns)
    fit_columns = history.columns[history.notna().sum() >= min_obs]
    if len(fit_columns) == 0:
        return prediction

    filled = _fill_gaps_by_weekday_median(history[fit_columns])
    filled.columns = range(len(fit_columns))
    long = filled.rename_axis(index="ds", columns="unique_id").stack().rename("y").reset_index()
    engine = StatsForecast(models=[getattr(statsforecast_models, modelo)(alias="m", **params)], freq="D", n_jobs=-1)

    forecast = engine.forecast(df=long, h=len(dates)).pivot(index="ds", columns="unique_id", values="m")
    prediction[fit_columns] = forecast.reindex(index=dates, columns=range(len(fit_columns))).to_numpy()
    return prediction.fillna(fallback)
