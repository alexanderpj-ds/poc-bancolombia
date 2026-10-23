"""Explicabilidad del boosting global, fuera de muestra (el metodo se mide en `lab/explicar.py`).

Sobre la ventana de backtest (modelo ajustado con datos <= origen) mide, por GRUPO de variables:

  - `permutacion`  : cuanto sube el WAPE al barajar el grupo (las columnas del grupo se mueven juntas).
  - `shap_centrado`: aporte SHAP medio absoluto del grupo, sin el corrimiento parejo, sobre sum|y|.

Se agrupa porque dentro de un grupo las variables llevan la misma informacion (p. ej. dia del mes y dias
al pago) y por separado se tapan entre si. Los grupos son dato (`explicabilidad` en `pronosticadores.yml`).
Explica el miembro de boosting de la receta; si la receta no tiene boosting, no hay explicacion.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from daas.forecasting import global_gbm

logger = logging.getLogger(__name__)

COLUMNS = ["receta", "tipo", "grupo", "valor", "n_obs"]


def _ml_recipe(name: str, recipes: dict[str, Any]) -> str | None:
    """ALX fase 2: receta `ml_global` que usa `nombre` (ella misma o un miembro de su combinacion), si hay."""
    recipe = recipes.get(name) or {}
    if recipe.get("familia") == "ml_global":
        return name
    for member in recipe.get("miembros", []) if recipe.get("familia") == "combinacion" else []:
        found = _ml_recipe(member, recipes)
        if found:
            return found
    return None


def boosting_recipe(name: str, recipes: dict[str, Any]) -> str | None:
    """Nombre de la receta de boosting que usa `nombre` (ella misma o un miembro de su combinacion).

    ALX fase 2: si la receta contiene un miembro `ml_global`, se explica ese (es el modelo nuevo); si no, el
    `gbm_global` de siempre (comportamiento original sin cambios).
    """
    found_ml = _ml_recipe(name, recipes)
    if found_ml:
        return found_ml
    recipe = recipes.get(name) or {}
    if recipe.get("familia") == "gbm_global":
        return name
    for member in recipe.get("miembros", []) if recipe.get("familia") == "combinacion" else []:
        found = boosting_recipe(member, recipes)
        if found:
            return found
    return None


def _fit_ml(hist: pd.DataFrame, origin: pd.Timestamp, days: int, dates: pd.DatetimeIndex, params: dict[str, Any],
            contexto: dict | None = None):
    """ALX fase 2: ajusta una receta `ml_global` con datos <= origen y arma la ventana a explicar.

    `contexto` (ALX PARTE 7): contexto V4 "as of" al origen para los champions `ml_laboratorio`; None = como antes.

    Returns:
        (modelo, calendario, columnas, X de la ventana con las columnas del modelo, nivel), con X en el mismo orden
        (fecha, entidad) que `global_gbm.build_examples`.
    """
    from daas.forecasting import global_ml

    p = dict(params)
    groups = global_ml.resolver_grupos(p.pop("conjunto", None), p.pop("grupos", None),
                                       bool(p.pop("entidad_categorica", False)))
    engine = p.pop("motor")
    extra = {"contexto": contexto} if contexto is not None else {}
    model, cal, cols = global_ml.fit_global_ml(hist, days, dates.max(), motor=engine, grupos=groups, **p, **extra)
    X, _, level = global_ml.construir_ejemplos(hist, origin, days, cal, groups, *([contexto] if contexto else []))
    X = global_ml._matriz(X, cols, engine, sorted(map(str, hist.columns)))
    return model, cal, cols, X, level


def _lab_explanation(model: str, conf: dict[str, Any], hist: pd.DataFrame, origin: pd.Timestamp):
    """ALX PARTE 7: (nombre, parametros, contexto, True) de la hoja `explicar` de un champion `ml_laboratorio`.

    Los parametros salen del yml congelado del laboratorio (`lab/conf/experimentos/<hoja>.yml`, los mismos que
    pronostica el champion) y el contexto V4 es el "as of" al origen. El nombre es la receta publicada si la hoja
    es el modelo entero (M1, M3 salidas) y el de la hoja si es un miembro del promedio. None si no aplica.
    """
    import inspect

    from daas.forecasting import global_ml, laboratorio

    rec = laboratorio.receta(model, conf)
    if rec is None or not rec.get("explicar"):
        return None
    from ml import pronosticar  # noqa: PLC0415 (raiz de ALX en sys.path)

    leaf = str(rec["explicar"])
    yml = pronosticar._yml(leaf) or {}
    if yml.get("familia") != "ml_global":
        return None
    accepted = set(inspect.signature(global_ml.fit_global_ml).parameters) | {"conjunto", "grupos", "entidad_categorica"}
    params = {k: v for k, v in yml.items() if k in accepted}
    contexto = laboratorio.contexto_al(str(rec["dataset"]), origin, hist.columns) if pronosticar.usa_contexto(leaf) \
        else None
    name = model if leaf == rec["modelo"] else leaf
    return name, params, contexto, True


def _wape(y: np.ndarray, pred: np.ndarray) -> float:
    return float(np.abs(y - pred).sum() / np.abs(y).sum())


def explain(
    width: pd.DataFrame,
    origin: pd.Timestamp,
    days: int,
    model: str,
    conf: dict[str, Any],
    exclude: Iterable[Any] = (),
) -> pd.DataFrame:
    """Importancia por grupo de variables en la ventana `origen+1 ... origen+dias`.

    Args:
        width: Matriz fecha x entidad completa (el real de la ventana solo se usa para medir).
        origin: Ultimo dia que ve el modelo.
        days: Tamano de la ventana.
        model: Receta de la unidad (se explica su miembro de boosting).
        conf: `pronosticadores.yml` cargado (usa `recetas` y `explicabilidad`).
        exclude: Entidades que no entran en la medicion (p.ej. conflicto RN-07).

    Returns:
        pd.DataFrame: `receta`, `tipo`, `grupo`, `valor`, `n_obs`. Vacio si no aplica.
    """
    empty = pd.DataFrame(columns=COLUMNS)
    cx = conf.get("explicabilidad") or {}
    hist = width.loc[:origin].dropna(axis=1, how="all")
    dates = pd.date_range(origin + pd.Timedelta(days=1), periods=days, freq="D")
    lab = _lab_explanation(model, conf, hist, origin)  # ALX PARTE 7: champions `ml_laboratorio`
    if lab is not None:
        name, params, contexto, is_ml = lab
    else:
        name, contexto = boosting_recipe(model, conf.get("recetas", {})), None
        params = {k: v for k, v in conf["recetas"][name].items() if k != "familia"} if name else {}
        is_ml = name is not None and conf["recetas"][name].get("familia") == "ml_global"
    if not cx.get("activo") or name is None:
        return empty
    try:
        if is_ml:  # ALX fase 2: explicacion via global_ml
            gbm, cal, cols, X, level = _fit_ml(hist, origin, days, dates, params, contexto)
        else:
            gbm, cal, cols = global_gbm.fit_global_gbm(hist, days, dates.max(), **params)
    except global_gbm.InsufficientHistoryError as exc:
        logger.warning("explicar(%s): %s No se calcula la explicabilidad.", name, exc)
        return empty
    if not is_ml:
        X, _, level = global_gbm.build_examples(hist, origin, days, cal)
    y = width.reindex(index=dates, columns=hist.columns).to_numpy().ravel()  # mismo orden que X: fecha, entidad
    outside = np.tile(hist.columns.isin(list(exclude)), days)
    ok = np.isfinite(y) & np.isfinite(level) & (level > 0) & ~outside
    if not ok.any() or np.abs(y[ok]).sum() == 0:
        return empty
    X, y, level = X.loc[ok, cols].reset_index(drop=True), y[ok], level[ok]
    n = int(len(y))
    base = gbm.predict(X) * level
    rows = [("base", "-", _wape(y, base))]

    rng = np.random.default_rng(int(cx["semilla"]))
    for group, variables in cx["grupos"].items():
        vs = [v for v in variables if v in cols]
        if not vs:
            continue
        rise = 0.0
        for _ in range(int(cx["repeticiones"])):
            Xp = X.copy()
            Xp[vs] = X[vs].to_numpy()[rng.permutation(n)]
            rise += _wape(y, gbm.predict(Xp) * level)
        rows.append(("permutacion", group, rise / int(cx["repeticiones"]) - _wape(y, base)))

    if cx.get("shap") and not hasattr(gbm, "steps"):  # ALX fase 2: RF/ET de ml_global (Pipeline) sin SHAP
        import shap

        exp = shap.TreeExplainer(gbm)
        sv = np.asarray(exp.shap_values(X))
        rest = np.abs(np.ravel(exp.expected_value)[0] + sv.sum(axis=1) - gbm.predict(X)).max()
        rows.append(("chequeo_aditividad", "-", float(rest)))
        for group, variables in cx["grupos"].items():
            idx = [cols.index(v) for v in variables if v in cols]
            if idx:
                rel = sv[:, idx].sum(axis=1)
                rows.append(("shap_centrado", group, float(np.abs((rel - rel.mean()) * level).sum() / np.abs(y).sum())))

    out = pd.DataFrame(rows, columns=["tipo", "grupo", "valor"])
    return out.assign(receta=name, n_obs=n)[COLUMNS]
