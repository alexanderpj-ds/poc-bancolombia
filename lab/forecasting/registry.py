"""
Registro de pronosticadores del lab. Todos cumplen el mismo contrato.

    forecast(history, dates) -> DataFrame (índice = fechas, columnas = entidades)

`history` es la matriz fecha × entidad con SOLO datos <= origen (la corta el arnés), con NaN donde no hay
dato. Ningún modelo recibe el futuro, así que la regla F1 se cumple por construcción; la guarda
`test_no_future_leak` lo verifica de punta a punta.
"""

from __future__ import annotations

import logging
from functools import partial

import numpy as np
import pandas as pd
import yaml
from daas.forecasting.forecasters import _by_weekday, _fallback, weekday_dom_profile

from lab import CONF_DIR, PIPELINE_CONF_DIR

PIPELINE_CONF = PIPELINE_CONF_DIR / "model_u1_u2.yml"
EXPERIMENTS_DIR = CONF_DIR / "experimentos"


def naive_weekly(history: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Mismo día de la semana más reciente observado (retrocede hasta 4 semanas si falta)."""
    origin = history.index.max()
    rows = {}
    for date in dates:
        first_week = int(np.ceil((date - origin).days / 7))
        value = pd.Series(np.nan, index=history.columns)

        for weeks_back in range(first_week, first_week + 4):
            source_date = date - pd.Timedelta(days=7 * weeks_back)
            if source_date in history.index:
                value = value.fillna(history.loc[source_date])
        rows[date] = value

    return pd.DataFrame(rows).T.fillna(_fallback(history))


def mean_by_weekday_4w(history: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Media del mismo día de la semana en las últimas 4 semanas."""
    return _by_weekday(history, dates, 28, "mean")


def median_by_weekday_4w(history: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Mediana del mismo día de la semana en las últimas 4 semanas."""
    return _by_weekday(history, dates, 28, "median")


def _fit_prophet_series(series: pd.Series, dates: list, min_obs: int) -> np.ndarray:
    """Ajusta y pronostica una serie con el forecaster del pipeline."""
    from daas.forecasting import forecaster

    for logger_name in ("cmdstanpy", "prophet", "daas.forecasting.forecaster"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    logging.getLogger("cmdstanpy").disabled = True
    frame = pd.DataFrame({"fecha": series.index.date, "y": series.to_numpy()})
    fitted = forecaster.train(frame, target="y", min_obs=min_obs)
    return forecaster.forecast(fitted, horizon=len(dates), dates=dates)["yhat"].to_numpy()


def prophet_baseline(history: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """El pronosticador del pipeline tal cual (`daas.forecasting.forecaster`), una serie por entidad."""
    from joblib import Parallel, delayed

    min_obs = int(yaml.safe_load(PIPELINE_CONF.read_text())["forecaster"]["min_obs"])
    days = [d.date() for d in dates]
    forecasts = Parallel(n_jobs=-1)(delayed(_fit_prophet_series)(history[e], days, min_obs) for e in history.columns)
    return pd.DataFrame(dict(zip(history.columns, forecasts, strict=False)), index=dates)


#: Registro de pronosticadores. Agregar uno = agregar una entrada (la guarda no_futuro lo cubre sola).
MODELS = {
    "naive_7": naive_weekly,
    "media_dow_4s": mean_by_weekday_4w,
    "mediana_dow_4s": median_by_weekday_4w,
    "perfil_dom": weekday_dom_profile,
    "prophet_actual": prophet_baseline,
}


#: Experimento → modelo del que es variante cercana (declarado en su yml). Endurece la regla de adopción.
VARIANT_OF: dict[str, str] = {}


def _register_experiments() -> None:
    """Cada `conf/experimentos/<nombre>.yml` es un pronosticador más (dato, no código)."""
    from daas.forecasting import global_ml

    from lab.forecasting import challengers, gbm

    families = {
        "ml_global": global_ml.forecast_global_ml,  # ALX fase 2 (FEAT-006): ML global con variables nuevas
        "gbm_global": gbm.forecast_global_gbm,
        "lineal_global": gbm.ridge_global,
        "cat_global": gbm.catboost_global,
        "prophet_calendario": challengers.prophet_with_calendar,
        "combinacion": challengers.combination,
        "perfil_calibrado": challengers.calibrated_profile,
        "estadistico_local": challengers.local_statistical,
    }
    for path in sorted(EXPERIMENTS_DIR.glob("*.yml")):
        conf = yaml.safe_load(path.read_text())
        if "variante_de" in conf:
            VARIANT_OF[path.stem] = conf.pop("variante_de")
        MODELS[path.stem] = partial(families[conf.pop("familia")], **conf)


_register_experiments()
