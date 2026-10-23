"""ML global directo de la fase 2: un modelo para todas las entidades, varios motores y variables nuevas.

Es la UNICA copia del codigo (el lab lo importa desde aqui, mismo patron que `global_gbm.py`). Reutiliza sin
modificarlos `global_gbm.build_examples` (filas, objetivo relativo y peso), el orden y los pseudo-origenes de
`global_gbm.training_set` y el calendario de `global_gbm.calendar` (via `calendario_co.calendario_detallado`). Con el
conjunto V0 y el motor `hgb` reproduce `forecast_global_gbm` (receta `gbm_cal`) a 1e-9.

Motores (`crear_motor`): `lgbm` (LightGBM), `xgb` (XGBoost), `cat` (CatBoost), `rf` (RandomForest), `et`
(ExtraTrees) y `hgb` (HistGradientBoosting de Santiago, control). Objetivos: `l2`, `l1` y `tweedie` (p = 1,3);
RandomForest/ExtraTrees solo `l2`.

Reglas anti-fuga (D3 del plan de la fase 2; F1-F5 de docs/metodologia-valor.md):
- Estrategia DIRECTA con el horizonte h como variable: para cada pseudo-origen s < origen todas las variables de la
  entidad se calculan con datos <= s y el objetivo es y(s+h) / nivel(s); el peso es el nivel. Solo hay objetivos
  <= origen (los de fechas posteriores no existen en `hist`).
- Todo rezago efectivo es >= h por construccion: `lag_dow_rel` toma el mismo dia de semana mas reciente <= s,
  `lag364_rel` toma t-364 y `lag364_w7_rel` la media de t-367..t-361 (con t = s+h y h <= 15, siempre <= s).
- El calendario es determinista (fechas). Los atributos de `contexto` son una foto por entidad (supuesto F2 del
  maestro vigente, posible fuga leve declarada); la matriz `contexto['cruzada']` se corta en el origen y, para cada
  pseudo-origen, en s.
- Nada se rellena con 0: los NaN (Anexo C, dias sin dato) quedan NaN en las variables. LightGBM, XGBoost, CatBoost y
  HGB aceptan NaN; RandomForest/ExtraTrees imputan DENTRO del fit (`SimpleImputer(median, add_indicator=True)` en un
  `Pipeline`), es decir, solo con ejemplos <= origen. Las codificaciones de categorias son fijas (orden alfabetico
  de valores del maestro o de los ids), no usan el objetivo; CatBoost codifica la entidad con estadisticas
  ordenadas en el tiempo (`has_time=True`, filas ordenadas por fecha objetivo).
- Sin parada temprana ni particion aleatoria de validacion.

`fechas` debe ser el tramo contiguo que empieza el dia siguiente al ultimo dia de `hist`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from daas.forecasting.calendario_co import COLUMNAS as COLUMNAS_CALENDARIO
from daas.forecasting.calendario_co import calendario_detallado
from daas.forecasting.global_gbm import GROUPS, ROW_ORDER, InsufficientHistoryError, build_examples

logger = logging.getLogger(__name__)

#: Grupos de variables: los 4 de Santiago (reexportados de `global_gbm.GROUPS`) + los nuevos (D6).
GROUPS_ML: dict[str, list[str]] = {
    **{k: list(v) for k, v in GROUPS.items()},
    **{k: list(v) for k, v in COLUMNAS_CALENDARIO.items()},
    "rezagos": ["lag_dow_rel", "ewm7_rel", "ewm28_rel", "r14", "r91", "std7_rel", "pend28", "q90_28_rel", "max28_rel"],
    "anual": ["lag364_rel", "lag364_w7_rel", "yoy_nivel"],
    "perfil_entidad": ["pago_rel", "pago1_rel", "festivo_rel", "post_rel", "nohabil_rel"],
    "intermitencia": ["frac_cero_28", "frac_nan_28", "dias_desde_dato", "racha_nan", "frac_cerca_max"],
    "contexto": [
        "log_cupo", "cupo_rel", "ciudad", "disp_mf", "admon", "log_cupo_max_suc", "red_ciudad_r7", "red_ciudad_r28",
        "red_dow_rel", "otro_r7", "otro_r28", "log_razon_otro",
    ],
    "entidad_cat": ["entidad"],
    # ALX, marca de imputacion (workflow de imputacion, DI-06): solo se agrega si `contexto['mascara_imputacion']`
    # tiene algun dia imputado <= origen. Sin mascara el modelo es identico al de la fase 2.
    "marca_imputacion": ["frac_imp_7", "frac_imp_28", "imp_lag_dow"],
}

#: Conjuntos acumulativos de grupos (V0 = variables de Santiago).
CONJUNTOS: dict[str, list[str]] = {"V0": ["base", "calendario", "pago", "dom_entidad"]}
CONJUNTOS["V1"] = [*CONJUNTOS["V0"], "pago_detalle", "festivo_detalle", "temporada"]
CONJUNTOS["V2"] = [*CONJUNTOS["V1"], "rezagos", "anual"]
CONJUNTOS["V3"] = [*CONJUNTOS["V2"], "perfil_entidad", "intermitencia"]
CONJUNTOS["V4"] = [*CONJUNTOS["V3"], "contexto"]

MOTORES = ("lgbm", "xgb", "cat", "rf", "et", "hgb")
OBJETIVOS = ("l2", "l1", "tweedie")
TWEEDIE_P = 1.3
#: Motores que aceptan la entidad como categorica.
CON_CATEGORICA = ("lgbm", "cat")

#: Parametros por defecto (D4): 300 arboles y tasa 0,06 como `gbm_cal`; `params` los sobreescribe.
PARAMS_POR_DEFECTO: dict[str, dict] = {
    "lgbm": {
        "n_estimators": 300, "learning_rate": 0.06, "num_leaves": 31, "min_child_samples": 50, "subsample": 0.8,
        "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0, "deterministic": True,
        "force_col_wise": True, "verbose": -1, "random_state": 0,
    },
    "xgb": {
        "n_estimators": 300, "learning_rate": 0.06, "tree_method": "hist", "max_depth": 6, "subsample": 0.8,
        "colsample_bytree": 0.8, "random_state": 0,
    },
    "cat": {"iterations": 300, "learning_rate": 0.06, "depth": 6},
    "rf": {"n_estimators": 200, "min_samples_leaf": 20, "max_features": 0.5, "max_samples": 0.3, "random_state": 0},
    "et": {
        "n_estimators": 200, "min_samples_leaf": 20, "max_features": 0.5, "max_samples": 0.3, "bootstrap": True,
        "random_state": 0,
    },
    "hgb": {"max_iter": 300, "learning_rate": 0.06, "max_leaf_nodes": 31, "min_samples_leaf": 50},
}

_PERDIDAS = {
    "lgbm": {"l2": {"objective": "regression"}, "l1": {"objective": "l1"},
             "tweedie": {"objective": "tweedie", "tweedie_variance_power": TWEEDIE_P}},
    "xgb": {"l2": {"objective": "reg:squarederror"}, "l1": {"objective": "reg:absoluteerror"},
            "tweedie": {"objective": "reg:tweedie", "tweedie_variance_power": TWEEDIE_P}},
    "cat": {"l2": {"loss_function": "RMSE"}, "l1": {"loss_function": "MAE"},
            "tweedie": {"loss_function": f"Tweedie:variance_power={TWEEDIE_P}"}},
    "rf": {"l2": {"criterion": "squared_error"}},
    "et": {"l2": {"criterion": "squared_error"}},
    "hgb": {"l2": {"loss": "squared_error"}, "l1": {"loss": "absolute_error"}},
}

#: Columnas del calendario de Santiago que `build_examples` necesita siempre (dow, dia) + las de `calendario`/`pago`.
_CAL_BASE = [
    "dow", "dia", "dias_a_fin_mes", "festivo", "vispera", "post", "habil", "dias_desde_pago", "dias_hasta_pago",
]


# --------------------------------------------------------------------------- #
# Variables                                                                    #
# --------------------------------------------------------------------------- #
def resolver_grupos(conjunto: str | None, grupos: list[str] | None, entidad_categorica: bool) -> list[str]:
    """Lista de grupos a partir de `conjunto` (V0..V4) o `grupos` (uno de los dos) + `entidad_cat` si se pide."""
    if (conjunto is None) == (grupos is None):
        raise ValueError("Indica exactamente uno de `conjunto` o `grupos`.")
    salida = list(CONJUNTOS[conjunto]) if conjunto is not None else list(grupos)
    desconocidos = [g for g in salida if g not in GROUPS_ML]
    if desconocidos:
        raise KeyError(f"Grupos desconocidos: {desconocidos}. Disponibles: {sorted(GROUPS_ML)}.")
    if entidad_categorica and "entidad_cat" not in salida:
        salida.append("entidad_cat")
    return salida


def columnas_de(grupos: list[str]) -> list[str]:
    """Variables de los grupos, en orden y sin repetir."""
    return list(dict.fromkeys(v for g in grupos for v in GROUPS_ML[g]))


def _rel(valor: pd.Series | np.ndarray, nivel: np.ndarray) -> np.ndarray:
    """Valor / nivel con NaN (no inf) cuando el nivel es 0 o NaN."""
    with np.errstate(divide="ignore", invalid="ignore"):
        salida = np.asarray(valor, dtype=float) / nivel
    return np.where(np.isfinite(salida), salida, np.nan)


def _por_fecha(h0: pd.DataFrame, fuentes: pd.DatetimeIndex, nivel: np.ndarray) -> np.ndarray:
    """Valor de cada entidad en cada fecha fuente (todas <= s) / nivel, forma (horizonte, n)."""
    return _rel(h0.reindex(fuentes).to_numpy(), nivel)


def _pendiente(tramo: pd.DataFrame) -> np.ndarray:
    """Pendiente MCO de cada columna contra el dia (ignora NaN; NaN si hay < 2 datos)."""
    y = tramo.to_numpy(dtype=float)
    x = np.arange(len(tramo), dtype=float)[:, None]
    m = np.isfinite(y)
    n = m.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        xm = np.where(m, x, 0.0).sum(axis=0) / n
        ym = np.where(m, y, 0.0).sum(axis=0) / n
        cov = np.where(m, (x - xm) * (np.nan_to_num(y) - ym), 0.0).sum(axis=0)
        var = np.where(m, (x - xm) ** 2, 0.0).sum(axis=0)
        pend = cov / var
    return np.where((n >= 2) & np.isfinite(pend), pend, np.nan)


def _racha_maxima(faltante: np.ndarray) -> np.ndarray:
    """Racha mas larga de True por columna."""
    racha = np.zeros(faltante.shape[1])
    mejor = np.zeros(faltante.shape[1])
    for fila in faltante:
        racha = (racha + 1) * fila
        mejor = np.maximum(mejor, racha)
    return mejor


def _codigos(valores: pd.Series) -> np.ndarray:
    """Codigo fijo (orden alfabetico de los valores presentes) para una columna categorica; NaN se conserva."""
    if pd.api.types.is_numeric_dtype(valores):
        return valores.to_numpy(dtype=float)
    categorias = sorted(valores.dropna().astype(str).unique())
    mapa = {c: float(i) for i, c in enumerate(categorias)}
    return valores.map(lambda v: mapa.get(str(v), np.nan) if pd.notna(v) else np.nan).to_numpy(dtype=float)


def _variables_entidad(
    h0: pd.DataFrame, s: pd.Timestamp, fechas: pd.DatetimeIndex, cal: pd.DataFrame, nivel: np.ndarray, grupos: list,
    m0: pd.DataFrame | None = None,
) -> dict[str, np.ndarray]:
    """Variables nuevas de la entidad en s (solo datos <= s). Por entidad (n,) o por fecha objetivo (horizonte, n).

    `m0`: mascara de imputacion <= s (True = valor imputado) alineada a `h0`, o None. Con mascara, las variables de
    faltantes de `intermitencia` tratan lo imputado como faltante y el grupo `marca_imputacion` describe la marca.
    """
    salida: dict[str, np.ndarray] = {}
    if "rezagos" in grupos:
        dows = fechas.dayofweek.to_numpy()
        fuentes = pd.DatetimeIndex([s - pd.Timedelta(days=int((s.dayofweek - d) % 7)) for d in dows])
        salida["lag_dow_rel"] = _por_fecha(h0, fuentes, nivel)
        ventana = h0.tail(190)
        salida["ewm7_rel"] = _rel(ventana.ewm(span=7).mean().iloc[-1], nivel)
        salida["ewm28_rel"] = _rel(ventana.ewm(span=28).mean().iloc[-1], nivel)
        salida["r14"] = _rel(h0.tail(14).mean(), nivel)
        salida["r91"] = _rel(h0.tail(91).mean(), nivel)
        salida["std7_rel"] = _rel(h0.tail(7).std(), nivel)
        salida["pend28"] = _rel(_pendiente(h0.tail(28)), nivel)
        salida["q90_28_rel"] = _rel(h0.tail(28).quantile(0.9), nivel)
        salida["max28_rel"] = _rel(h0.tail(28).max(), nivel)
    if "anual" in grupos:
        salida["lag364_rel"] = _por_fecha(h0, fechas - pd.Timedelta(days=364), nivel)
        semanas = np.stack(
            [h0.reindex(pd.date_range(t - pd.Timedelta(days=367), t - pd.Timedelta(days=361))).mean().to_numpy()
             for t in fechas]
        )
        salida["lag364_w7_rel"] = _rel(semanas, nivel)
        previo = h0.loc[s - pd.Timedelta(days=364 + 27) : s - pd.Timedelta(days=364)]
        salida["yoy_nivel"] = _rel(h0.tail(28).mean(), previo.mean().reindex(h0.columns).to_numpy(dtype=float))
    if "perfil_entidad" in grupos:
        largo = h0.tail(190)
        c = cal.reindex(largo.index)
        for nombre, mascara in (
            ("pago_rel", c["es_pago"] == 1),
            ("pago1_rel", c["pago_mas_1"] == 1),
            ("festivo_rel", c["festivo"] == 1),
            ("post_rel", c["post_habil"] == 1),
            ("nohabil_rel", c["no_habil"] == 1),
        ):
            salida[nombre] = _rel(largo[mascara.to_numpy()].mean(), nivel)
    if "intermitencia" in grupos:
        t28, t90 = h0.tail(28), h0.tail(90)
        observados = t28.notna().sum()
        salida["frac_cero_28"] = _rel(t28.eq(0).sum(), observados.to_numpy(dtype=float))
        # Con marca, lo imputado cuenta como faltante en las variables de faltantes (DI-06).
        hn = h0 if m0 is None else h0.mask(m0.to_numpy(dtype=bool))
        salida["frac_nan_28"] = hn.tail(28).isna().mean().to_numpy(dtype=float)
        presentes = hn.notna().to_numpy()
        hay = presentes.any(axis=0)
        ultimo = len(hn) - 1 - np.argmax(presentes[::-1], axis=0)
        salida["dias_desde_dato"] = np.where(hay, len(hn) - 1 - ultimo, np.nan).astype(float)
        salida["racha_nan"] = _racha_maxima(hn.tail(90).isna().to_numpy())
        maximo = t90.max()
        cerca = t90.ge(0.9 * maximo).sum()
        salida["frac_cerca_max"] = np.where(maximo.notna(), _rel(cerca, t90.notna().sum().to_numpy(float)), np.nan)
    if "marca_imputacion" in grupos and m0 is not None:
        marca = m0.astype(float)
        salida["frac_imp_7"] = marca.tail(7).mean().to_numpy(dtype=float)
        salida["frac_imp_28"] = marca.tail(28).mean().to_numpy(dtype=float)
        dows = fechas.dayofweek.to_numpy()
        fuentes = pd.DatetimeIndex([s - pd.Timedelta(days=int((s.dayofweek - d) % 7)) for d in dows])
        salida["imp_lag_dow"] = marca.reindex(fuentes).to_numpy(dtype=float)  # marca del valor que usa lag_dow_rel
    return salida


def _mascara(contexto: dict | None, h0: pd.DataFrame) -> pd.DataFrame | None:
    """`contexto['mascara_imputacion']` alineada a `h0` (bool, faltante = False) o None si no hay."""
    mascara = (contexto or {}).get("mascara_imputacion")
    if mascara is None:
        return None
    return mascara.reindex(index=h0.index, columns=h0.columns).fillna(False).astype(bool)


def _variables_contexto(
    h0: pd.DataFrame, s: pd.Timestamp, fechas: pd.DatetimeIndex, nivel: np.ndarray, contexto: dict | None
) -> dict[str, np.ndarray]:
    """Grupo `contexto` (atributos del maestro, red de la ciudad y objetivo cruzado). Sin contexto todo es NaN."""
    n = h0.shape[1]
    salida = {v: np.full(n, np.nan) for v in GROUPS_ML["contexto"]}
    salida["red_dow_rel"] = np.full((len(fechas), n), np.nan)
    if not contexto:
        return salida
    atributos = contexto.get("atributos")
    if atributos is not None:
        a = atributos.reindex(h0.columns)
        if "cupo" in a:
            cupo = pd.to_numeric(a["cupo"], errors="coerce").to_numpy(dtype=float)
            salida["log_cupo"] = np.log1p(cupo)
            salida["cupo_rel"] = _rel(cupo, nivel)
        if "cupo_max_suc" in a:
            salida["log_cupo_max_suc"] = np.log1p(pd.to_numeric(a["cupo_max_suc"], errors="coerce").to_numpy(float))
        for col in ("ciudad", "disp_mf", "admon"):
            if col in atributos:
                codigos = pd.Series(_codigos(atributos[col]), index=atributos.index)
                salida[col] = codigos.reindex(h0.columns).to_numpy(dtype=float)
        if "ciudad" in a:
            tramo = h0.tail(56)
            ciudad = a["ciudad"].astype("object")
            red = tramo.T.groupby(ciudad.to_numpy(), dropna=True).sum(min_count=1).T
            nivel_red = red.mean()
            r7, r28 = red.tail(7).mean() / nivel_red, red.tail(28).mean() / nivel_red
            dow = red.groupby(red.index.dayofweek).median().reindex(range(7)) / nivel_red
            mapa = ciudad.to_numpy()
            salida["red_ciudad_r7"] = r7.reindex(mapa).to_numpy(dtype=float)
            salida["red_ciudad_r28"] = r28.reindex(mapa).to_numpy(dtype=float)
            salida["red_dow_rel"] = dow.reindex(columns=mapa).loc[fechas.dayofweek].to_numpy(dtype=float)
    cruzada = contexto.get("cruzada")
    if cruzada is not None:
        otro = cruzada.loc[:s].reindex(columns=h0.columns)
        nivel_otro = otro.tail(56).mean().to_numpy(dtype=float)
        salida["otro_r7"] = _rel(otro.tail(7).mean(), nivel_otro)
        salida["otro_r28"] = _rel(otro.tail(28).mean(), nivel_otro)
        with np.errstate(invalid="ignore"):
            razon = np.log1p(nivel_otro) - np.log1p(nivel)
        salida["log_razon_otro"] = np.where(np.isfinite(razon), razon, np.nan)
    for k, v in salida.items():
        salida[k] = np.where(np.isfinite(v), v, np.nan)
    return salida


def construir_ejemplos(
    hist: pd.DataFrame,
    s: pd.Timestamp,
    horizonte: int,
    cal: pd.DataFrame,
    grupos: list[str],
    contexto: dict | None = None,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """`global_gbm.build_examples` (mismas filas y orden) + las variables de los grupos nuevos, con datos <= s.

    Args:
        hist: Matriz fecha x entidad (datos <= origen; NaN = sin dato).
        s: Pseudo-origen (o el origen, para predecir).
        horizonte: Dias a pronosticar.
        cal: `calendario_detallado` que cubre la historia y el horizonte.
        grupos: Grupos de `GROUPS_ML` pedidos.
        contexto: {'atributos': DataFrame por entidad, 'cruzada': matriz fecha x entidad} o None.

    Returns:
        (X, y, nivel) como `build_examples`; X trae ademas las columnas de los grupos nuevos pedidos.
    """
    calendario = [c for g in grupos if g in COLUMNAS_CALENDARIO for c in COLUMNAS_CALENDARIO[g]]
    X, y, w = build_examples(hist, s, horizonte, cal[[*_CAL_BASE, *calendario]])
    h0 = hist.loc[:s]
    nivel = h0.tail(56).mean().to_numpy(dtype=float)
    fechas = pd.date_range(s + pd.Timedelta(days=1), periods=horizonte, freq="D")
    nuevas = _variables_entidad(h0, s, fechas, cal, nivel, grupos, _mascara(contexto, h0))
    if "contexto" in grupos:
        nuevas.update(_variables_contexto(h0, s, fechas, nivel, contexto))
    for nombre, valor in nuevas.items():
        valor = np.asarray(valor, dtype=float)
        X[nombre] = valor.ravel() if valor.ndim == 2 else np.tile(valor, horizonte)  # mismo layout que build_examples
    return X, y, w


def _huella_cache(hist: pd.DataFrame, horizonte: int, cols: list[str], extra: dict, contexto: dict | None) -> str:
    """Clave del cache de variables: datos, columnas, parametros de entrenamiento y contexto."""
    partes = [
        json.dumps({"h": horizonte, "cols": cols, **extra}, sort_keys=True, default=str),
        str(pd.util.hash_pandas_object(hist, index=True).sum()),
        "|".join(map(str, hist.columns)),
    ]
    claves = ("atributos", "cruzada", "mascara_imputacion") if (contexto or {}).get("mascara_imputacion") is not None \
        else ("atributos", "cruzada")  # sin mascara, la clave es la de la fase 2
    for clave in claves:
        valor = (contexto or {}).get(clave)
        partes.append("-" if valor is None else str(pd.util.hash_pandas_object(valor, index=True).sum()))
    return hashlib.sha256("\n".join(partes).encode()).hexdigest()[:16]


def conjunto_entrenamiento(
    hist: pd.DataFrame,
    horizonte: int,
    cal: pd.DataFrame,
    grupos: list[str],
    paso_dias: int,
    meses_entrenamiento: int,
    contexto: dict | None = None,
    cache_variables: str | Path | None = None,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Ejemplos de todos los pseudo-origenes s < origen, mismos s y mismo orden determinista que `training_set`.

    Args:
        hist: Matriz fecha x entidad (datos <= origen).
        horizonte: Dias a pronosticar.
        cal: `calendario_detallado`.
        grupos: Grupos de `GROUPS_ML`.
        paso_dias: Un pseudo-origen cada `paso_dias` dias.
        meses_entrenamiento: Meses hacia atras desde el origen.
        contexto: Ver `construir_ejemplos`.
        cache_variables: Directorio de cache (fuera de Drive). Si existe el parquet de la clave, se lee.

    Returns:
        (X, y, w): X con las columnas pedidas + `ROW_ORDER` (entidad, t_objetivo, h), ordenado por `ROW_ORDER`.

    Raises:
        InsufficientHistoryError: Si no hay ningun ejemplo.
    """
    cols = columnas_de(grupos)
    keep = list(dict.fromkeys([*cols, *ROW_ORDER]))
    origen = hist.index.max()
    ruta = None
    if cache_variables is not None:
        extra = {"paso": paso_dias, "meses": meses_entrenamiento, "grupos": grupos}
        clave = _huella_cache(hist, horizonte, cols, extra, contexto)
        ruta = Path(cache_variables) / f"{origen.date()}_{clave}.parquet"
        if ruta.exists():
            tabla = pd.read_parquet(ruta)
            return tabla[keep], tabla["__y"].to_numpy(), tabla["__w"].to_numpy()
    inicio = max(hist.index.min() + pd.Timedelta(days=56), origen - pd.DateOffset(months=meses_entrenamiento))
    Xs, ys, ws = [], [], []
    for s in pd.date_range(origen - pd.Timedelta(days=1), inicio, freq=f"-{paso_dias}D"):
        X, y, w = construir_ejemplos(hist, s, horizonte, cal, grupos, contexto)
        ok = np.isfinite(y) & np.isfinite(w) & (w > 0)
        Xs.append(X.loc[ok, keep])
        ys.append(y[ok])
        ws.append(w[ok])
    if not Xs or sum(len(y) for y in ys) == 0:
        raise InsufficientHistoryError(f"Sin ejemplos de entrenamiento para el origen {origen.date()}.")
    X, y, w = pd.concat(Xs, ignore_index=True), np.concatenate(ys), np.concatenate(ws)
    orden = X.sort_values(ROW_ORDER, kind="mergesort").index.to_numpy()
    X, y, w = X.loc[orden].reset_index(drop=True), y[orden], w[orden]
    if ruta is not None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_suffix(f".{os.getpid()}.tmp")
        X.assign(__y=y, __w=w).to_parquet(temporal, index=False)
        os.replace(temporal, ruta)  # atomico: otro proceso nunca lee un parquet a medias
    return X, y, w


# --------------------------------------------------------------------------- #
# Motores                                                                      #
# --------------------------------------------------------------------------- #
def crear_motor(motor: str, objetivo: str = "l2", params: dict | None = None, hilos: int = 2):
    """Estimador sin ajustar (D4/D5). `params` sobreescribe `PARAMS_POR_DEFECTO[motor]`.

    Args:
        motor: Uno de `MOTORES`.
        objetivo: 'l2', 'l1' o 'tweedie' (RF/ET solo 'l2'; HGB 'l2' o 'l1').
        params: Hiperparametros del motor.
        hilos: Hilos del motor (n_jobs / thread_count). HGB usa los de OpenMP del proceso.

    Returns:
        Estimador con `fit(X, y, sample_weight=...)` (RF/ET: `Pipeline` con el imputador dentro).
    """
    if motor not in MOTORES:
        raise ValueError(f"Motor desconocido: {motor}. Disponibles: {MOTORES}.")
    if objetivo not in _PERDIDAS[motor]:
        raise ValueError(f"El motor {motor} no admite el objetivo {objetivo}.")
    p = {**PARAMS_POR_DEFECTO[motor], **_PERDIDAS[motor][objetivo], **(params or {})}
    if motor == "lgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(n_jobs=hilos, **p)
    if motor == "xgb":
        from xgboost import XGBRegressor

        return XGBRegressor(n_jobs=hilos, **p)
    if motor == "cat":
        from catboost import CatBoostRegressor

        return CatBoostRegressor(
            has_time=True, random_seed=0, verbose=False, allow_writing_files=False, thread_count=hilos, **p
        )
    if motor in ("rf", "et"):
        from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline

        clase = RandomForestRegressor if motor == "rf" else ExtraTreesRegressor
        return Pipeline(
            [("imputar", SimpleImputer(strategy="median", add_indicator=True)), ("modelo", clase(n_jobs=hilos, **p))]
        )
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(early_stopping=False, random_state=0, **p)


def _matriz(X: pd.DataFrame, cols: list[str], motor: str, categorias: list[str]) -> pd.DataFrame:
    """Columnas del modelo; `entidad` como categoria fija (LightGBM) o texto (CatBoost)."""
    salida = X[cols].copy()
    if "entidad" in cols:
        valores = salida["entidad"].astype(str)
        salida["entidad"] = pd.Categorical(valores, categories=categorias) if motor == "lgbm" else valores
    return salida


def _ajustar(modelo, motor: str, X: pd.DataFrame, y: np.ndarray, w: np.ndarray, cols: list, categorias: list):
    """Ajusta el motor; pesos normalizados a media 1 salvo HGB (paridad con Santiago)."""
    peso = w if motor == "hgb" else w / w.mean()
    if motor == "cat":
        from catboost import Pool

        orden = np.argsort(X["t_objetivo"].to_numpy(), kind="stable")  # has_time: codificacion ordenada en el tiempo
        datos = _matriz(X.iloc[orden], cols, motor, categorias)
        cat = ["entidad"] if "entidad" in cols else []
        modelo.fit(Pool(datos, y[orden], weight=peso[orden], cat_features=cat))
    elif motor in ("rf", "et"):
        modelo.fit(_matriz(X, cols, motor, categorias), y, modelo__sample_weight=peso)
    else:
        modelo.fit(_matriz(X, cols, motor, categorias), y, sample_weight=peso)
    return modelo


def fit_global_ml(
    hist: pd.DataFrame,
    horizonte: int,
    hasta: pd.Timestamp,
    *,
    motor: str,
    grupos: list[str],
    objetivo: str = "l2",
    params: dict | None = None,
    paso_dias: int = 5,
    meses_entrenamiento: int = 18,
    dias_pago: tuple | list = ("15", "fin"),
    hilos: int = 2,
    contexto: dict | None = None,
    cache_variables: str | Path | None = None,
):
    """Ajusta el motor con ejemplos <= origen. Devuelve (modelo, calendario, columnas).

    `grupos` ya resuelto con `resolver_grupos` (incluye `entidad_cat` si se pidio la entidad categorica).
    """
    if "entidad_cat" in grupos and motor not in CON_CATEGORICA:
        raise ValueError(f"La entidad categorica solo se admite con {CON_CATEGORICA}, no con {motor}.")
    cal = calendario_detallado(hist.index.min(), hasta, tuple(dias_pago))
    cols = columnas_de(grupos)
    X, y, w = conjunto_entrenamiento(
        hist, horizonte, cal, grupos, paso_dias, meses_entrenamiento, contexto, cache_variables
    )
    categorias = sorted(map(str, hist.columns))
    modelo = _ajustar(crear_motor(motor, objetivo, params, hilos), motor, X, y, w, cols, categorias)
    return modelo, cal, cols


def predecir_ml(
    modelo, motor: str, hist: pd.DataFrame, fechas: pd.DatetimeIndex, cal: pd.DataFrame, grupos: list[str],
    contexto: dict | None = None,
) -> pd.DataFrame:
    """Pronostica `fechas` (mismo armado que `global_gbm.predict_gbm` + variables nuevas)."""
    X, _, nivel = construir_ejemplos(hist, hist.index.max(), len(fechas), cal, grupos, contexto)
    cols = columnas_de(grupos)
    yhat = modelo.predict(_matriz(X, cols, motor, sorted(map(str, hist.columns))))
    pred = pd.DataFrame((np.asarray(yhat) * nivel).reshape(len(fechas), hist.shape[1]), index=fechas,
                        columns=hist.columns)
    return pred.fillna(hist.tail(28).mean().fillna(0.0))


def forecast_global_ml(
    history: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    motor: str,
    conjunto: str | None = None,
    grupos: list[str] | None = None,
    objetivo: str = "l2",
    params: dict | None = None,
    paso_dias: int = 5,
    meses_entrenamiento: int = 18,
    dias_pago: tuple | list = ("15", "fin"),
    entidad_categorica: bool = False,
    hilos: int = 2,
    contexto: dict | None = None,
    cache_variables: str | Path | None = None,
) -> pd.DataFrame:
    """Pronostico del ML global (contrato del lab). Sin historia para entrenar cae a la media de 28 dias.

    Args:
        history: Matriz fecha x entidad con datos <= origen (NaN = sin dato).
        dates: Dias a pronosticar, contiguos desde el dia siguiente al origen.
        motor: 'lgbm', 'xgb', 'cat', 'rf', 'et' o 'hgb'.
        conjunto: 'V0'..'V4' (excluyente con `grupos`).
        grupos: Lista explicita de grupos de `GROUPS_ML`.
        objetivo: 'l2', 'l1' o 'tweedie'.
        params: Hiperparametros del motor (sobre `PARAMS_POR_DEFECTO`).
        paso_dias: Un pseudo-origen cada `paso_dias` dias.
        meses_entrenamiento: Meses de historia para entrenar.
        dias_pago: Dias nominales de pago ('15', 'fin').
        entidad_categorica: Agrega la entidad como categorica (solo lgbm y cat).
        hilos: Hilos del motor.
        contexto: {'atributos': DataFrame por entidad, 'cruzada': matriz del objetivo hermano}; se corta en el origen.
        cache_variables: Directorio del cache de variables de entrenamiento (fuera de Drive).

    Returns:
        pd.DataFrame: Indice `dates`, columnas = entidades de `history`, sin NaN.
    """
    lista = resolver_grupos(conjunto, grupos, entidad_categorica)
    if contexto and contexto.get("cruzada") is not None:
        contexto = {**contexto, "cruzada": contexto["cruzada"].loc[: history.index.max()]}
    if contexto and contexto.get("mascara_imputacion") is not None:
        # Marca de imputacion (DI-06): cortada en el origen; el grupo solo se activa si hay algun dia imputado.
        mascara = contexto["mascara_imputacion"].reindex(index=history.index, columns=history.columns)
        mascara = mascara.fillna(False).astype(bool)
        contexto = {k: v for k, v in contexto.items() if k != "mascara_imputacion"}
        if mascara.to_numpy().any():
            contexto["mascara_imputacion"] = mascara
            lista = [*lista, "marca_imputacion"]
    try:
        modelo, cal, _ = fit_global_ml(
            history, len(dates), dates.max(), motor=motor, grupos=lista, objetivo=objetivo, params=params,
            paso_dias=paso_dias, meses_entrenamiento=meses_entrenamiento, dias_pago=dias_pago, hilos=hilos,
            contexto=contexto, cache_variables=cache_variables,
        )
    except InsufficientHistoryError as exc:
        logger.warning("ml_global: %s Se usa la media de los ultimos 28 dias por entidad.", exc)
        nivel = history.tail(28).mean().fillna(0.0)
        return pd.DataFrame(np.tile(nivel.to_numpy(), (len(dates), 1)), index=dates, columns=history.columns)
    return predecir_ml(modelo, motor, history, dates, cal, lista, contexto)
