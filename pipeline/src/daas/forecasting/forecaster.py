"""Pronostico Prophet del subpaquete `forecasting`, `decision` y `modules` (reuse-analysis.md).

Reuso portado de la demo de 1a ronda, adaptado a los datos reales de la PoC
(ATM M1/M2). Regla de negocio:

- `train(df)` entrena un modelo por serie (una serie = `cod_cajero`, SUP-06)
  sobre la columna objetivo diaria densa. Si la serie tiene < `min_obs`
  observaciones NO nulas, usa el fallback `naive_estacional_7` (media por
  dia-de-semana) y marca el metodo usado.
- `forecast(model, horizon)` genera el horizonte pedido (p.ej. 1-15 sep, dias
  calendario) con columnas `(fecha, yhat)`.
- `backtest(df)` reserva la ultima ventana (`backtest.dias`) como pseudo-holdout
, entrena hasta antes y pronostica esa ventana devolviendo `(fecha, y,
  yhat)`.
- `band_from_backtest(bt)` deriva una banda de incertidumbre NO negativa desde
  el error de backtest.

La semilla esta fijada para reproducibilidad; sin sobre-ingenieria.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Semilla fija para reproducibilidad del fallback / muestreo.
_SEED = 42
#: Umbral de observaciones por defecto bajo el cual se usa el fallback.
_DEFAULT_MIN_OBS = 30
#: Periodo estacional del fallback (dias de la semana).
_SEASONAL_PERIOD = 7


@dataclass
class SeriesModel:
    """Modelo entrenado para una serie (Prophet o fallback estacional).

    Attributes:
        metodo: `'prophet'` o `'naive_estacional_7'`.
        target: Nombre de la columna objetivo.
        prophet: Instancia Prophet entrenada (si `metodo='prophet'`).
        perfil_estacional: Media por dia-de-semana (0=lunes) del fallback.
        media_global: Media global (respaldo del fallback si falta un dia).
        n_obs: Nº de observaciones NO nulas usadas en el entrenamiento.
        ultima_fecha: Ultima fecha observada en el entrenamiento.
    """

    method: str
    target: str
    prophet: Any | None = None
    profile_seasonal: dict[int, float] = field(default_factory=dict)
    mean_global: float = 0.0
    n_obs: int = 0
    last_date: _dt.date | None = None


def _clean_series(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Ordena por fecha y devuelve `(fecha, target)` como `date`/float.

    Args:
        df: Serie de una entidad con columnas `fecha` y `target`.
        target: Nombre de la columna objetivo.

    Returns:
        pd.DataFrame: Columnas `fecha` (date) y `target` (float, con NaN donde
        falte), ordenado por fecha.
    """
    out = df[["fecha", target]].copy()
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.date
    out[target] = pd.to_numeric(out[target], errors="coerce")
    return out.sort_values("fecha").reset_index(drop=True)


def _train_fallback(series: pd.DataFrame, target: str) -> SeriesModel:
    """Entrena el fallback `naive_estacional_7` (media por dia-de-semana).

    Args:
        series: Serie limpia `(fecha, target)`.
        target: Nombre de la columna objetivo.

    Returns:
        ModeloSerie: Modelo con `metodo='naive_estacional_7'`.
    """
    valid_ids = series.dropna(subset=[target])
    profile: dict[int, float] = {}
    if not valid_ids.empty:
        dow = pd.to_datetime(valid_ids["fecha"]).dt.dayofweek
        profile = {int(k): float(v) for k, v in valid_ids[target].groupby(dow).mean().items()}
    mean_global = float(valid_ids[target].mean()) if not valid_ids.empty else 0.0
    last = series["fecha"].max() if not series.empty else None
    return SeriesModel(
        method="naive_estacional_7",
        target=target,
        profile_seasonal=profile,
        mean_global=mean_global,
        n_obs=int(len(valid_ids)),
        last_date=last,
    )


def train(df: pd.DataFrame, target: str = "pagado", min_obs: int = _DEFAULT_MIN_OBS) -> SeriesModel:
    """Entrena un modelo para UNA serie (`cod_cajero`) sobre `target`.

    Si la serie tiene al menos `min_obs` observaciones NO nulas entrena Prophet;
    en caso contrario (serie corta o constante) usa el fallback estacional y lo
    marca en `ModeloSerie.metodo`.

    Args:
        df: Serie diaria densa de una entidad con columnas `fecha` y `target`.
        target: Columna objetivo (p.ej. `pagado`, `cash_in`).
        min_obs: Umbral de observaciones bajo el cual se usa el fallback.

    Returns:
        ModeloSerie: Modelo entrenado (Prophet o fallback) con `metodo` marcado.
    """
    series = _clean_series(df, target)
    valid_ids = series.dropna(subset=[target])
    n_obs = int(len(valid_ids))

    if n_obs < min_obs:
        logger.info(
            "Serie con %d obs (< min_obs=%d): se usa el fallback estacional.",
            n_obs,
            min_obs,
        )
        return _train_fallback(series, target)

    try:
        from prophet import Prophet
    except Exception as error:  # noqa: BLE001
        logger.warning("Prophet no disponible (%s); se usa el fallback estacional.", error)
        return _train_fallback(series, target)

    np.random.seed(_SEED)
    series_model = Prophet(
        weekly_seasonality=True,
        yearly_seasonality=False,
        daily_seasonality=False,
    )
    training = valid_ids.rename(columns={"fecha": "ds", target: "y"}).copy()
    training["ds"] = pd.to_datetime(training["ds"])
    series_model.fit(training)
    return SeriesModel(
        method="prophet",
        target=target,
        prophet=series_model,
        n_obs=n_obs,
        last_date=series["fecha"].max(),
    )


def _horizon_dates(last: _dt.date, horizon: int) -> list[_dt.date]:
    """Construye las `horizon` fechas calendario posteriores a `ultima`.

    Args:
        last: Ultima fecha observada en el entrenamiento.
        horizon: Nº de dias calendario a pronosticar.

    Returns:
        list[datetime.date]: Fechas consecutivas (dias calendario).
    """
    return [last + _dt.timedelta(days=k) for k in range(1, horizon + 1)]


def forecast(
    model: SeriesModel,
    horizon: int,
    dates: list[_dt.date] | None = None,
) -> pd.DataFrame:
    """Genera el pronostico de `forecasting`, `decision` y `modules` para `horizon` dias calendario.

    Args:
        model: Modelo entrenado por `train`.
        horizon: Nº de dias calendario a pronosticar.
        dates: Fechas explicitas a pronosticar (p.ej. 1-15 sep). Si es `None`
            se generan los `horizon` dias posteriores a la ultima observada.

    Returns:
        pd.DataFrame: Columnas `fecha` (date) y `yhat` (float, no negativo).
    """
    if dates is None:
        if model.last_date is None:
            raise ValueError("No se puede inferir el horizonte: serie sin fechas.")
        dates = _horizon_dates(model.last_date, horizon)

    if model.method == "prophet" and model.prophet is not None:
        future = pd.DataFrame({"ds": pd.to_datetime(dates)})
        pred = model.prophet.predict(future)
        yhat = pred["yhat"].to_numpy()
    else:
        dow = pd.to_datetime(pd.Series(dates)).dt.dayofweek
        yhat = dow.map(lambda d: model.profile_seasonal.get(int(d), model.mean_global)).to_numpy()

    yhat = np.clip(np.asarray(yhat, dtype=float), a_min=0.0, a_max=None)
    return pd.DataFrame({"fecha": list(dates), "yhat": yhat})


def backtest(
    df: pd.DataFrame,
    target: str = "pagado",
    days: int = 15,
    min_obs: int = _DEFAULT_MIN_OBS,
) -> pd.DataFrame:
    """Backtest de UNA serie reservando la ultima ventana como holdout.

    Reserva las ultimas `dias` fechas del entrenamiento como pseudo-holdout,
    entrena hasta antes de esa ventana y pronostica esos dias, devolviendo el
    observado real frente al pronostico. Las fechas sin observacion real
    (`missing_anexo_c`) salen como `y=NaN` (no entran a las metricas, SUP-02).

    Args:
        df: Serie diaria densa de una entidad con `fecha` y `target`.
        target: Columna objetivo.
        days: Tamano de la ventana de backtest.
        min_obs: Umbral de fallback para el reentrenamiento.

    Returns:
        pd.DataFrame: Columnas `fecha`, `y`, `yhat`. Vacio si no hay suficientes
        fechas para separar la ventana.
    """
    series = _clean_series(df, target)
    if len(series) <= days:
        return pd.DataFrame(columns=["fecha", "y", "yhat"])

    window = series.iloc[-days:]
    training = series.iloc[:-days]
    series_model = train(training, target=target, min_obs=min_obs)
    pred = forecast(series_model, horizon=days, dates=list(window["fecha"]))
    out = window.rename(columns={target: "y"}).merge(pred, on="fecha", how="left")
    return out[["fecha", "y", "yhat"]].reset_index(drop=True)


def band_from_backtest(backtest_result: pd.DataFrame) -> pd.DataFrame:
    """Deriva una banda de incertidumbre NO negativa desde el error de backtest.

    La semi-amplitud de la banda es el error absoluto medio (MAE) del backtest;
    `band_low`/`band_high` se centran en `yhat` recortando el limite inferior a
    0 (demanda no negativa).

    Args:
        backtest_result: Salida de `backtest` con columnas `fecha`, `y`, `yhat`.

    Returns:
        pd.DataFrame: `backtest_result` con columnas adicionales `band_low` y
        `band_high` (no negativas, `band_low <= yhat <= band_high`).
    """
    out = backtest_result.copy()
    if out.empty:
        out["band_low"] = pd.Series(dtype="float64")
        out["band_high"] = pd.Series(dtype="float64")
        return out
    error_abs = (out["y"] - out["yhat"]).abs()
    half_width = float(error_abs.mean()) if error_abs.notna().any() else 0.0
    half_width = max(half_width, 0.0)
    out["band_low"] = (out["yhat"] - half_width).clip(lower=0.0)
    out["band_high"] = (out["yhat"] + half_width).clip(lower=0.0)
    return out
