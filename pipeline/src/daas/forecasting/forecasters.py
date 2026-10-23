"""Pronosticadores seleccionables por configuracion.

Todos cumplen el mismo contrato, el del lab (`lab/modelos.py`):

    predecir(hist, fechas) -> DataFrame (indice = fechas, columnas = entidades)

`hist` es la matriz fecha x entidad con SOLO datos <= origen y NaN donde no hay
dato; `fechas` es el tramo contiguo que empieza el dia siguiente al ultimo dia
de `hist`. Ningun pronosticador recibe el futuro (regla F1).

Las recetas (familia + parametros) son dato: viven en `conf/pronosticadores.yml`
y cada `conf/model_*.yml` elige una por nombre en `forecaster.modelo`. Agregar un
modelo = agregar una entrada. Si la clave falta se usa `prophet`, que es el
pronosticador original (`forecasting.forecaster`) sin cambios.
"""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from daas import alx
from daas.forecasting import forecaster
from daas.forecasting.global_gbm import calendar, forecast_global_gbm
from daas.forecasting.global_ml import forecast_global_ml
from daas.forecasting.laboratorio import forecast_laboratorio

logger = logging.getLogger(__name__)

#: Archivo de recetas dentro de ``conf/``.
_FILE = "pronosticadores.yml"

#: Receta usada cuando la configuracion no elige ninguna (comportamiento original).
DEFAULT_MODEL = "prophet"


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``)."""
    return Path(__file__).resolve().parents[3]


def load_recipes(conf_dir: Path | None = None) -> dict[str, Any]:
    """Carga `conf/pronosticadores.yml`.

    Busca primero en ``DAAS_CONF`` y, si ahi no esta, en el `conf/` del paquete:
    las recetas son configuracion publica del modelo, no dependen del entorno.

    Args:
        conf_dir: Directorio ``conf/`` a usar; ``None`` aplica la busqueda.

    Returns:
        dict[str, Any]: `{'paralelo': int, 'recetas': {nombre: parametros}}`.

    Raises:
        FileNotFoundError: Si el archivo no existe en ningun `conf/`.
    """
    candidates = [conf_dir] if conf_dir is not None else []
    if os.environ.get("DAAS_CONF"):
        candidates.append(Path(os.environ["DAAS_CONF"]).expanduser().resolve())
    candidates.append(_package_root() / "conf")
    for directory in candidates:
        file_path = directory / _FILE
        if file_path.is_file():
            with file_path.open("r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
    raise FileNotFoundError(f"No se encontro {_FILE} en {[str(c) for c in candidates]}.")


def resolve_model(cfg_forecaster: dict, *keys: str) -> str:
    """Nombre de la receta para un modelo/objetivo segun `forecaster.modelo`.

    `forecaster.modelo` puede ser un nombre (vale para todo) o un mapa anidado
    por `keys` (p.ej. modelo y objetivo). Lo que no este declarado usa
    `DEFAULT_MODEL`.

    Args:
        cfg_forecaster: Bloque `forecaster` de la configuracion de la unidad.
        *keys: Claves por las que se desciende (p.ej. ``'m2', 'cash_in'``).

    Returns:
        str: Nombre de la receta.
    """
    node = cfg_forecaster.get("modelo", DEFAULT_MODEL)
    # ALX (PARTE 7, SUP-39): con el interruptor `campeones_ml`, `forecaster.modelo_alx` (champions finales) manda
    # sobre `forecaster.modelo` (receta de Santiago). Lo no declarado en `modelo_alx` cae a `modelo`.
    if "modelo_alx" in cfg_forecaster and alx.interruptor("campeones_ml"):
        node_alx = cfg_forecaster["modelo_alx"]
        for key in keys:
            if not isinstance(node_alx, dict):
                break
            node_alx = node_alx.get(key)
        if isinstance(node_alx, str):
            return node_alx
    for key in keys:
        if not isinstance(node, dict):
            break
        node = node.get(key, DEFAULT_MODEL)
    return node if isinstance(node, str) else DEFAULT_MODEL


def _fallback(hist: pd.DataFrame) -> pd.Series:
    """Media de los ultimos 28 dias por entidad; 0 si no hay dato. Evita yhat NaN."""
    return hist.tail(28).mean().fillna(0.0)


def _by_weekday(hist: pd.DataFrame, dates: pd.DatetimeIndex, days: int, statistic: str) -> pd.DataFrame:
    """Nivel por dia de la semana (media o mediana) de los ultimos `dias` dias."""
    tail = hist.tail(days)
    level = getattr(tail.groupby(tail.index.dayofweek), statistic)()
    level = level.reindex(range(7))
    out = level.loc[dates.dayofweek].set_axis(dates)
    return out.fillna(_fallback(hist))


def weekday_dom_profile(hist: pd.DataFrame, dates: pd.DatetimeIndex, *, meses: int = 6) -> pd.DataFrame:
    """Mediana por dia de la semana (8 semanas) x factor de dia del mes de la red.

    El factor se estima con el total de la red en los ultimos `meses` meses
    completos <= origen: total del dia / mediana del total para ese dia de la
    semana en su mes; mediana entre meses.
    """
    base = _by_weekday(hist, dates, 56, "median")
    origin = hist.index.max()
    fin = origin if origin.is_month_end else origin.replace(day=1) - pd.Timedelta(days=1)
    network = hist.loc[fin - pd.DateOffset(months=meses) + pd.Timedelta(days=1) : fin].sum(axis=1, min_count=1)
    month = network.index.to_period("M")
    expected = network.groupby([month, network.index.dayofweek]).transform("median")
    ratio = (network / expected).replace([np.inf, -np.inf], np.nan)
    factor = ratio.groupby(ratio.index.day).median()
    f = pd.Series(factor.reindex(dates.day).to_numpy(), index=dates).fillna(1.0)
    return base.mul(f, axis=0)


def _silence_prophet() -> None:
    """Silencia el registro de Prophet/cmdstanpy (un mensaje por serie)."""
    for name in ("cmdstanpy", "prophet"):
        logging.getLogger(name).setLevel(logging.ERROR)
    logging.getLogger("cmdstanpy").disabled = True


def _prophet_single(series: pd.Series, dates: list, min_obs: int) -> np.ndarray:
    _silence_prophet()
    df = pd.DataFrame({"fecha": series.index.date, "y": series.to_numpy()})
    model = forecaster.train(df, target="y", min_obs=min_obs)
    return forecaster.forecast(model, horizon=len(dates), dates=dates)["yhat"].to_numpy()


def _by_series(function: Callable, hist: pd.DataFrame, dates: pd.DatetimeIndex, n_jobs: int, *args) -> pd.DataFrame:
    """Aplica `funcion(serie, *args)` a cada entidad, en paralelo si `n_jobs != 1`."""
    if n_jobs == 1 or hist.shape[1] <= 1:
        cols = [function(hist[e], *args) for e in hist.columns]
    else:
        from joblib import Parallel, delayed

        cols = Parallel(n_jobs=n_jobs)(delayed(function)(hist[e], *args) for e in hist.columns)
    return pd.DataFrame(dict(zip(hist.columns, cols, strict=False)), index=dates)


def prophet_per_series(
    hist: pd.DataFrame, dates: pd.DatetimeIndex, *, min_obs: int = 30, n_jobs: int = 1
) -> pd.DataFrame:
    """El pronosticador original (`forecasting.forecaster`), una serie por entidad."""
    return _by_series(_prophet_single, hist, dates, n_jobs, [d.date() for d in dates], min_obs)


def _regressors(cal: pd.DataFrame, window_payment: int) -> pd.DataFrame:
    """Indicadores de calendario para Prophet (es lineal: una columna por efecto)."""
    r = pd.DataFrame({"festivo": cal["festivo"], "vispera": cal["vispera"], "post": cal["post"]}, index=cal.index)
    for k in range(window_payment + 1):
        r[f"pago_mas_{k}"] = (cal["dias_desde_pago"] == k).astype(int)
    r["pago_menos_1"] = (cal["dias_hasta_pago"] == 1).astype(int)
    return r


def _prophet_cal_single(
    series: pd.Series, reg: pd.DataFrame, dates: pd.DatetimeIndex, min_obs: int, fourier_monthly: int
) -> np.ndarray:
    valid_ids = series.dropna()
    if len(valid_ids) < min_obs:  # mismo respaldo que `forecaster`: media por dia de la semana
        profile = valid_ids.groupby(valid_ids.index.dayofweek).mean()
        return profile.reindex(dates.dayofweek).fillna(valid_ids.mean() if len(valid_ids) else 0.0).to_numpy()
    _silence_prophet()
    from prophet import Prophet

    np.random.seed(42)
    m = Prophet(weekly_seasonality=True, yearly_seasonality=False, daily_seasonality=False)
    if fourier_monthly:
        m.add_seasonality(name="mensual", period=30.5, fourier_order=fourier_monthly)
    used = [c for c in reg.columns if reg.loc[valid_ids.index, c].nunique() > 1]  # sin variacion no se estima
    for c in used:
        m.add_regressor(c, standardize=False)
    m.fit(reg.loc[valid_ids.index, used].assign(ds=valid_ids.index, y=valid_ids.to_numpy()))
    return m.predict(reg.loc[dates, used].assign(ds=dates))["yhat"].to_numpy()


def prophet_with_calendar(
    hist: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    dias_pago: list,
    ventana_pago: int,
    fourier_mensual: int,
    min_obs: int,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """Prophet por serie, como el original, mas regresores de pago y festivos y estacionalidad mensual."""
    reg = _regressors(calendar(hist.index.min(), dates.max(), tuple(dias_pago)), ventana_pago)
    return _by_series(_prophet_cal_single, hist, dates, n_jobs, reg, dates, min_obs, fourier_mensual)


#: Familias disponibles. `combinacion` se resuelve en `predecir` (necesita las demas recetas).
FAMILIES: dict[str, Callable[..., pd.DataFrame]] = {
    "prophet_serie": prophet_per_series,
    "perfil_dom": weekday_dom_profile,
    "gbm_global": forecast_global_gbm,
    "prophet_calendario": prophet_with_calendar,
    "ml_global": forecast_global_ml,  # ALX fase 2 (FEAT-006)
    "ml_laboratorio": forecast_laboratorio,  # ALX PARTE 7: champions finales (ml.pronosticar), SUP-39
}


def predict(
    name: str,
    hist: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    conf: dict[str, Any] | None = None,
    por_defecto: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Pronostica `fechas` con la receta `nombre`. Salida no negativa y sin NaN.

    Args:
        name: Nombre de la receta en `conf/pronosticadores.yml`.
        hist: Matriz fecha x entidad con datos <= origen (NaN = sin dato).
        dates: Dias a pronosticar, contiguos desde el dia siguiente al origen.
        conf: Contenido ya cargado de `pronosticadores.yml` (se carga si es `None`).
        por_defecto: Parametros que pone la unidad (p.ej. `min_obs`); solo se
            aplican a la familia que los acepta y si la receta no los fija.

    Returns:
        pd.DataFrame: Indice `fechas`, columnas = entidades de `hist`.

    Raises:
        KeyError: Si la receta o su familia no existen.
    """
    conf = conf if conf is not None else load_recipes()
    recipes = conf.get("recetas", {})
    if name not in recipes:
        raise KeyError(f"Receta de pronostico desconocida: '{name}'. Disponibles: {sorted(recipes)}.")
    params = dict(recipes[name])
    family = params.pop("familia")

    if family == "combinacion":
        # Promedio simple, pesos iguales y fijos (no se ajustan: no hay nada que filtrar).
        members = params["miembros"]
        weights = params.get("pesos")  # ALX fase 2: pesos fijos opcionales (sin `pesos` = calculo original)
        if weights is None:
            pred = sum(predict(m, hist, dates, conf=conf, por_defecto=por_defecto) for m in members) / len(members)
        else:
            total = float(sum(weights))
            pred = sum(
                w / total * predict(m, hist, dates, conf=conf, por_defecto=por_defecto)
                for m, w in zip(members, weights, strict=True)
            )
    else:
        function = FAMILIES[family]
        accepted = inspect.signature(function).parameters
        extra = {"n_jobs": conf.get("paralelo", 1), **(por_defecto or {})}
        params = {**{k: v for k, v in extra.items() if k in accepted}, **params}
        pred = function(hist, dates, **params)

    pred = pred.clip(lower=0.0)
    return pred.fillna(_fallback(hist))
