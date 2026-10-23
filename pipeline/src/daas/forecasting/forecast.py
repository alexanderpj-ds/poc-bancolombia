"""Camino unico de pronostico de una unidad: horizonte, backtest y banda.

Es la unica copia del camino de pronostico que usan `run_u1_u2`, `run_u3` y `run_u4_u5`.
Trabaja sobre la matriz fecha x entidad de UN objetivo y hace tres cosas con la misma receta:

  1. HORIZONTE: pronostica las fechas pedidas con toda la historia anterior a ellas.
  2. BACKTEST : corta la historia `dias` dias antes del ultimo dia con datos y pronostica esa VENTANA DE
                FECHAS (no "las ultimas N filas" de cada serie, que con huecos no es una ventana).
  3. BANDA    : segun `bandas.metodo` de `conf/pronosticadores.yml`.

Anti-fuga: todo pronostico usado para medir o calibrar se hace con datos <= su origen (`_evaluate_origin`
corta la matriz antes de llamar al pronosticador).
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from daas.forecasting import explain as explain_mod
from daas.forecasting import forecasters as forecasters
from daas.forecasting import intervals as bands_mod

logger = logging.getLogger(__name__)

_HORIZON_COLS = ["entidad", "fecha", "yhat", "band_low", "band_high"]
_COLS_BACKTEST = ["entidad", "fecha", "y", "yhat"]


@dataclass
class Forecast:
    """Resultado del pronostico de un objetivo para todas sus entidades.

    Attributes:
        horizonte: `entidad`, `fecha` (date), `yhat`, `band_low`, `band_high`.
        backtest: `entidad`, `fecha` (date), `y` (NaN si no hubo dato real), `yhat`.
        modelo: Nombre de la receta usada.
        banda: Metodo de banda que se aplico de verdad (puede ser el respaldo).
        evaluaciones: Todos los pronosticos fuera de muestra hechos en la corrida (backtest y, con banda
            conformal, los origenes de calibracion): `origen`, `entidad`, `fecha`, `h`, `y`, `yhat`.
        explicacion: Importancia por grupo de variables en la ventana de backtest (`forecasting.explain`);
            vacia si la receta no tiene boosting o la explicabilidad esta apagada.
    """

    horizon: pd.DataFrame
    backtest: pd.DataFrame
    model: str
    band: str
    evaluations: pd.DataFrame
    explanation: pd.DataFrame

    def of(self, entity: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Devuelve `(forecast, backtest)` de una entidad, ordenados por fecha y sin la columna `entidad`."""
        fc = self.horizon[self.horizon["entidad"] == entity]
        bt = self.backtest[self.backtest["entidad"] == entity]
        return (
            fc.drop(columns="entidad").sort_values("fecha").reset_index(drop=True),
            bt.drop(columns="entidad").sort_values("fecha").reset_index(drop=True),
        )


def _matrix(long: pd.DataFrame, entity: str, target: str) -> pd.DataFrame:
    """Matriz fecha x entidad del objetivo, con rejilla diaria completa y NaN donde no hay dato."""
    d = long[[entity, "fecha", target]].copy()
    d["fecha"] = pd.to_datetime(d["fecha"])
    d[target] = pd.to_numeric(d[target], errors="coerce")
    width = d.groupby(["fecha", entity])[target].sum(min_count=1).unstack(entity)
    if width.empty:
        return width
    return width.reindex(pd.date_range(width.index.min(), width.index.max(), freq="D"))


def _evaluate_origin(
    width: pd.DataFrame, origin: pd.Timestamp, days: int, model: str, conf: dict, by_default: dict
) -> pd.DataFrame:
    """Pronostica los `dias` dias posteriores a `origen` con datos <= `origen` y los cruza con el real.

    Universo: entidades con al menos un dato <= origen. Devuelve `entidad`, `fecha`, `h`, `yhat`, `y`.
    """
    hist = width.loc[:origin].dropna(axis=1, how="all")
    if hist.empty:
        return pd.DataFrame(columns=["entidad", "fecha", "h", "yhat", "y"])
    dates = pd.date_range(origin + pd.Timedelta(days=1), periods=days, freq="D")
    pred = forecasters.predict(model, hist, dates, conf=conf, por_defecto=by_default)
    long = pred.rename_axis(index="fecha", columns="entidad").stack().rename("yhat").reset_index()
    long["h"] = (long["fecha"] - origin).dt.days
    real = width.reindex(dates)[hist.columns].rename_axis(index="fecha", columns="entidad")
    real = real.stack(future_stack=True).rename("y").reset_index()
    return long.merge(real, on=["entidad", "fecha"], how="left")


def _calibration_origins(width: pd.DataFrame, origin_bt: pd.Timestamp, days: int, cb: dict) -> list[pd.Timestamp]:
    """Fines de mes anteriores al backtest cuya ventana de `dias` dias cierra antes de que empiece la suya."""
    first = width.index.min() + pd.Timedelta(days=int(cb["historia_minima_dias"]))
    last = origin_bt - pd.Timedelta(days=days)
    if first > last:
        return []
    candidates = list(pd.date_range(first, last, freq="ME"))
    return candidates[-int(cb["origenes_calibracion"]) :]


def _with_scale(ev: pd.DataFrame, width: pd.DataFrame, origin: pd.Timestamp, cb: dict) -> pd.DataFrame:
    """Agrega la escala conocida en el origen (`nivel`) y el tramo de horizonte (`bloque`)."""
    level = width.loc[:origin].tail(int(cb["dias_nivel"])).mean()
    out = ev.assign(nivel=ev["entidad"].map(level), bloque="fuera")
    for name, (a, b) in cb["bloques"].items():
        out.loc[out["h"].between(a, b), "bloque"] = name
    return out


def _band_mae(horizon: pd.DataFrame, backtest: pd.DataFrame) -> pd.DataFrame:
    """Banda original: semiamplitud = error absoluto medio del backtest de cada entidad (0 si no hay)."""
    valid_ids = backtest.dropna(subset=["y", "yhat"])
    semi = (valid_ids["y"] - valid_ids["yhat"]).abs().groupby(valid_ids["entidad"]).mean()
    s = horizon["entidad"].map(semi).fillna(0.0)
    return horizon.assign(
        band_low=(horizon["yhat"] - s).clip(lower=0.0), band_high=(horizon["yhat"] + s).clip(lower=0.0)
    )


def generate_forecast(
    long: pd.DataFrame,
    entity: str,
    target: str,
    dates: list[_dt.date],
    *,
    model: str,
    min_obs: int,
    backtest_days: int,
    exclude_calibration: Iterable[Any] = (),
    conf: dict[str, Any] | None = None,
) -> Forecast:
    """Pronostica un objetivo para todas las entidades: horizonte con banda + backtest.

    Args:
        long: Series diarias en formato largo con `entidad`, `fecha` y `objetivo`.
        entity: Columna del id de entidad (`cod_cajero`, `cod_sucursal`, `fondo_id`...).
        target: Columna objetivo.
        dates: Dias calendario consecutivos del horizonte.
        model: Receta de `conf/pronosticadores.yml` (ver `pronosticadores.resolver_modelo`).
        min_obs: Umbral del respaldo estacional de la unidad (`forecaster.min_obs`).
        backtest_days: Tamano de la ventana de backtest.
        exclude_calibration: Entidades que no aportan residuos a la banda (p.ej. conflicto RN-07).
        conf: `pronosticadores.yml` ya cargado (se carga si es `None`).

    Returns:
        Pronostico: Horizonte (una fila por entidad-dia, sin NaN) y backtest.
    """
    conf = conf if conf is not None else forecasters.load_recipes()
    by_default = {"min_obs": int(min_obs)}
    width = _matrix(long, entity, target)
    entities = list(pd.unique(long[entity].dropna()))
    days_h = pd.DatetimeIndex(pd.to_datetime(dates))
    start = days_h[0]

    # 1. HORIZONTE: solo historia anterior al primer dia pedido. Si los datos terminan antes, la cola
    #    queda NaN (el pronosticador ve que no hay dato; no se rellena).
    hist = width.loc[: start - pd.Timedelta(days=1)].dropna(axis=1, how="all") if not width.empty else width
    if hist.empty:
        pred = pd.DataFrame(0.0, index=days_h, columns=entities)
    else:
        eve = start - pd.Timedelta(days=1)
        if hist.index.max() < eve:
            logger.warning(
                "pronosticar(%s): los datos terminan el %s y el horizonte empieza el %s.",
                target,
                hist.index.max().date(),
                start.date(),
            )
        hist = hist.reindex(pd.date_range(hist.index.min(), eve, freq="D"))
        pred = forecasters.predict(model, hist, days_h, conf=conf, por_defecto=by_default)
        pred = pred.reindex(columns=entities).fillna(0.0)  # entidad sin ningun dato -> 0
    horizon = pred.rename_axis(index="fecha", columns="entidad").stack().rename("yhat").reset_index()
    horizon["h"] = (horizon["fecha"] - (start - pd.Timedelta(days=1))).dt.days

    # 2. BACKTEST: ventana de fechas al final de los datos.
    if width.empty or (width.index.max() - width.index.min()).days < backtest_days:
        ev_bt, origin_bt = pd.DataFrame(columns=["entidad", "fecha", "h", "yhat", "y"]), None
    else:
        origin_bt = width.index.max() - pd.Timedelta(days=backtest_days)
        ev_bt = _evaluate_origin(width, origin_bt, backtest_days, model, conf, by_default)
    backtest = ev_bt[_COLS_BACKTEST].copy()
    evaluations = [ev_bt.assign(origen=origin_bt)]

    # 3. BANDA.
    cb = conf.get("bandas") or {"metodo": "mae_backtest"}
    method = cb.get("metodo", "mae_backtest")
    if method == "conformal" and origin_bt is not None and not hist.empty:
        origins = _calibration_origins(width, origin_bt, backtest_days, cb)
        if len(origins) + 1 < int(cb["calibracion_minima"]):
            logger.warning(
                "pronosticar(%s): %d origenes de calibracion (minimo %s); la banda cae a mae_backtest.",
                target,
                len(origins) + 1,
                cb["calibracion_minima"],
            )
            method = "mae_backtest"
        else:
            parts = [_with_scale(ev_bt, width, origin_bt, cb)]
            for o in origins:
                ev = _evaluate_origin(width, o, backtest_days, model, conf, by_default)
                parts.append(_with_scale(ev, width, o, cb))
                evaluations.append(ev.assign(origen=o))
            cal = pd.concat(parts, ignore_index=True).dropna(subset=["y", "yhat"])
            cal = cal[~cal["entidad"].isin(set(exclude_calibration))]
            test = _with_scale(horizon, hist, hist.index.max(), cb)
            b = bands_mod.bands(cal, test, {"escala": cb["escala"], "grupo": list(cb["grupo"])}, float(cb["nivel"]))
            horizon = horizon.assign(band_low=b["lo"], band_high=b["hi"])
    elif method == "conformal":
        method = "mae_backtest"
    if method == "mae_backtest":
        horizon = _band_mae(horizon, backtest)
    elif method != "conformal":
        raise ValueError(f"Metodo de banda desconocido en pronosticadores.yml: '{method}'.")

    for df in (horizon, backtest):
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    explanation = (
        explain_mod.explain(width, origin_bt, backtest_days, model, conf, exclude_calibration)
        if origin_bt is not None
        else pd.DataFrame(columns=explain_mod.COLUMNS)
    )
    evs = pd.concat(evaluations, ignore_index=True)[["origen", "entidad", "fecha", "h", "y", "yhat"]]
    return Forecast(
        horizon=horizon[_HORIZON_COLS],
        backtest=backtest,
        model=model,
        band=method,
        evaluations=evs,
        explanation=explanation,
    )
