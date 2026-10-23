"""Boosting global directo: un solo modelo para todas las entidades, con el horizonte como variable.

Portado del lab (`lab/gbm.py`) sin cambios de logica. Es la UNICA copia del
codigo: el lab la importa desde aqui.

Anti-fuga por construccion (reglas F1-F5 de docs/metodologia-valor.md):
- La funcion solo recibe `hist` (datos <= origen). Los ejemplos de entrenamiento se arman con
  pseudo-origenes s < origen: variables con datos <= s, objetivo en s+h; todo objetivo > origen no existe.
- No hay rezagos menores que el horizonte: las variables de nivel se calculan en s, nunca en s+h-1.
- Sin escaladores ni codificadores ajustados aparte: el objetivo se divide por el nivel de la propia
  entidad en s. El calendario es determinista (conocido de antemano).
- Sin parada temprana: no hay particion aleatoria interna de validacion.

`fechas` debe ser el tramo contiguo que empieza el dia siguiente al ultimo dia de `hist`.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from daas.features.calendar import build_calendar

logger = logging.getLogger(__name__)


class InsufficientHistoryError(ValueError):
    """No hay ningun ejemplo de entrenamiento con datos <= origen (historia demasiado corta)."""


GROUPS = {
    "base": ["h", "dow", "log_nivel", "r7", "r28", "cv", "dow_rel", "frac_obs"],
    "calendario": ["dia", "dias_a_fin_mes", "festivo", "vispera", "post", "habil"],
    "pago": ["dias_desde_pago", "dias_hasta_pago"],
    "dom_entidad": ["dom_rel"],
}


#: Claves del orden determinista de las filas de entrenamiento.
ROW_ORDER = ["entidad", "t_objetivo", "h"]


@lru_cache(maxsize=8)
def calendar(since: pd.Timestamp, until: pd.Timestamp, days_payment: tuple) -> pd.DataFrame:
    """Variables de calendario por fecha. Las fechas de pago se corren al día hábil anterior."""
    margin = pd.Timedelta(days=45)
    cal = build_calendar((since - margin).date(), (until + margin).date())
    cal.index = pd.to_datetime(cal["fecha"])
    business = cal["es_habil"]
    payments = []
    for month in cal.index.to_period("M").unique():
        for d in days_payment:
            f = month.end_time.normalize() if d == "fin" else month.start_time + pd.Timedelta(days=int(d) - 1)
            while f in business.index and not business[f]:
                f -= pd.Timedelta(days=1)
            payments.append(f)
    payments = np.array(sorted(set(payments)), dtype="datetime64[ns]")
    dates = cal.index.to_numpy()
    pos = np.searchsorted(payments, dates, side="right")
    since_payment = (dates - payments[np.clip(pos - 1, 0, len(payments) - 1)]) / np.timedelta64(1, "D")
    until_payment = (
        payments[np.clip(np.searchsorted(payments, dates, side="left"), 0, len(payments) - 1)] - dates
    ) / np.timedelta64(1, "D")
    return pd.DataFrame(
        {
            "dow": cal["dia_semana"],
            "dia": cal["dia"],
            "dias_a_fin_mes": cal.index.days_in_month - cal["dia"],
            "festivo": cal["es_festivo_co"].astype(int),
            "vispera": cal["es_vispera_festivo"].astype(int),
            "post": cal["es_post_festivo"].astype(int),
            "habil": cal["es_habil"].astype(int),
            "dias_desde_pago": np.clip(since_payment, 0, 20),
            "dias_hasta_pago": np.clip(until_payment, 0, 20),
        },
        index=cal.index,
    )


def build_examples(
    hist: pd.DataFrame, s: pd.Timestamp, horizon: int, cal: pd.DataFrame
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Variables (datos <= s), objetivo relativo y nivel para los `horizonte` días posteriores a s."""
    h0 = hist.loc[:s]
    tail = h0.tail(56)
    level = tail.mean()
    n = len(hist.columns)
    dates = pd.date_range(s + pd.Timedelta(days=1), periods=horizon, freq="D")
    c = cal.loc[dates]

    dow_med = tail.groupby(tail.index.dayofweek).median().reindex(range(7))
    long = h0.tail(190)
    dom_mean = long.groupby(long.index.day).mean().reindex(range(1, 32))
    by_entity = {
        "log_nivel": np.log1p(level),
        "r7": h0.tail(7).mean() / level,
        "r28": h0.tail(28).mean() / level,
        "cv": tail.std() / level,
        "frac_obs": tail.notna().mean(),
    }
    X = {k: np.tile(v.to_numpy(), horizon) for k, v in by_entity.items()}
    X["h"] = np.repeat(np.arange(1, horizon + 1), n)
    for k in c.columns:
        X[k] = np.repeat(c[k].to_numpy(), n)
    X["dow_rel"] = (dow_med.loc[c["dow"]].to_numpy() / level.to_numpy()).ravel()
    X["dom_rel"] = (dom_mean.loc[c["dia"]].to_numpy() / level.to_numpy()).ravel()
    # Identificadores (no están en GROUPS: solo los usa quien los pida explícitamente).
    X["entidad"] = np.tile(hist.columns.astype(str), horizon)
    X["t_objetivo"] = np.repeat(dates.to_julian_date().to_numpy(), n)
    y = hist.reindex(dates).to_numpy() / level.to_numpy()  # fechas > fin de hist quedan NaN
    return pd.DataFrame(X), y.ravel(), np.tile(level.to_numpy(), horizon)


def training_set(
    hist: pd.DataFrame, horizon: int, cal: pd.DataFrame, cols: list[str], step_days: int, months_training: int
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Ejemplos de entrenamiento de todos los pseudo-orígenes s < origen (objetivo siempre <= origen)."""
    origin = hist.index.max()
    start = max(hist.index.min() + pd.Timedelta(days=56), origin - pd.DateOffset(months=months_training))
    Xs, ys, ws = [], [], []
    for s in pd.date_range(origin - pd.Timedelta(days=1), start, freq=f"-{step_days}D"):
        X, y, w = build_examples(hist, s, horizon, cal)
        ok = np.isfinite(y) & np.isfinite(w) & (w > 0)
        Xs.append(X.loc[ok, list(dict.fromkeys([*cols, *ROW_ORDER]))])
        ys.append(y[ok])
        ws.append(w[ok])
    if not Xs or sum(len(y) for y in ys) == 0:
        raise InsufficientHistoryError(f"Sin ejemplos de entrenamiento para el origen {origin.date()}.")
    X, y, w = pd.concat(Xs, ignore_index=True), np.concatenate(ys), np.concatenate(ws)
    # Con > 2e5 filas sklearn submuestrea para el binning y la muestra depende del orden de las filas.
    # Orden determinista (entidad, fecha objetivo, horizonte): el resultado ya no depende del orden de las
    # columnas de `hist` ni del orden de llegada de las entidades.
    order = X.sort_values(ROW_ORDER, kind="mergesort").index.to_numpy()
    return X.loc[order, cols].reset_index(drop=True), y[order], w[order]


def predict_gbm(model, hist: pd.DataFrame, dates: pd.DatetimeIndex, cal: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Pronostica `dates` con el modelo ajustado y devuelve un DataFrame fechas x entidades."""
    X, _, level = build_examples(hist, hist.index.max(), len(dates), cal)
    yhat = (model.predict(X[cols]) * level).reshape(len(dates), len(hist.columns))
    pred = pd.DataFrame(yhat, index=dates, columns=hist.columns)
    return pred.fillna(hist.tail(28).mean().fillna(0.0))


def fit_global_gbm(
    hist: pd.DataFrame,
    horizon: int,
    until: pd.Timestamp,
    *,
    grupos: list[str],
    perdida: str,
    paso_dias: int,
    meses_entrenamiento: int,
    dias_pago: list,
    hgb: dict,
):
    """Ajusta el boosting con ejemplos <= origen.

    Devuelve (modelo, calendario, columnas); lo reutiliza `forecasting.explain`.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor

    cal = calendar(hist.index.min(), until, tuple(dias_pago))
    cols = [v for g in grupos for v in GROUPS[g]]
    X, y, w = training_set(hist, horizon, cal, cols, paso_dias, meses_entrenamiento)
    model = HistGradientBoostingRegressor(loss=perdida, early_stopping=False, random_state=0, **hgb)
    # Peso = nivel de la entidad: la pérdida queda en pesos (COP), como el WAPE micro.
    model.fit(X, y, sample_weight=w)
    return model, cal, cols


def forecast_global_gbm(hist: pd.DataFrame, dates: pd.DatetimeIndex, **params) -> pd.DataFrame:
    """Pronostico del boosting global. Sin historia para entrenar, cae a la media de 28 dias y lo avisa."""
    try:
        model, cal, cols = fit_global_gbm(hist, len(dates), dates.max(), **params)
    except InsufficientHistoryError as exc:
        logger.warning("gbm_global: %s Se usa la media de los ultimos 28 dias por entidad.", exc)
        level = hist.tail(28).mean().fillna(0.0)
        return pd.DataFrame(np.tile(level.to_numpy(), (len(dates), 1)), index=dates, columns=hist.columns)
    return predict_gbm(model, hist, dates, cal, cols)
