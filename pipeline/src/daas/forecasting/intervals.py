"""Bandas conformal del pronostico (el metodo se valida en `lab/conformal.py`).

Residuo con signo dividido por una escala conocida en el origen; la banda de un punto nuevo es su
pronostico mas los cuantiles de esos residuos (del grupo al que pertenece) por su propia escala.
Portado de `lab/conformal.py` sin cambios de logica; el lab importa estas funciones.

Aqui no se pronostica nada: quien llama entrega residuos FUERA DE MUESTRA (cada uno de un pronostico
hecho con datos <= su origen). Con residuos de ajuste la banda saldria angosta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def quantiles(r: pd.Series, tails: list[float]) -> pd.Series:
    """Cuantiles empiricos con la correccion de muestra finita ((n+1)·tau, redondeado hacia afuera)."""
    v, n = np.sort(r.to_numpy()), len(r)
    idx = [np.floor((n + 1) * t) - 1 if t < 0.5 else np.ceil((n + 1) * t) - 1 for t in tails]
    return pd.Series(v[np.clip(idx, 0, n - 1).astype(int)], index=tails)


def quantile_table(cal: pd.DataFrame, var: dict, tails: list[float]) -> tuple[pd.DataFrame | None, pd.Series]:
    """Cuantiles del residuo relativo por grupo (o `None` si la variante no agrupa) y los de todos."""
    cal = cal[cal[var["escala"]] > 0]
    r = (cal["y"] - cal["yhat"]) / cal[var["escala"]]
    everything = quantiles(r, tails)
    if not var["grupo"]:
        return None, everything
    by_group = r.groupby([cal[c] for c in var["grupo"]]).apply(quantiles, tails=tails)
    return (by_group.unstack() if isinstance(by_group, pd.Series) else by_group), everything


def bands(cal: pd.DataFrame, test: pd.DataFrame, var: dict, level: float) -> pd.DataFrame:
    """Banda [lo, hi] para `prueba` con cuantiles de `cal`. Grupo no visto en `cal` -> cuantil de todos.

    Args:
        cal: Residuos de calibracion: `y`, `yhat`, la columna de escala y las de `var['grupo']`.
        test: Puntos a los que se les pone banda: `yhat`, la escala y las columnas de grupo.
        var: Variante `{'escala': columna, 'grupo': [columnas]}`.
        level: Cobertura nominal (dos colas iguales), p.ej. 0.90.

    Returns:
        pd.DataFrame: Columnas `lo` (>= 0) y `hi`, con el indice de `prueba`.
    """
    tails = [(1 - level) / 2, 1 - (1 - level) / 2]
    by_group, everything = quantile_table(cal, var, tails)
    q = pd.DataFrame({c: everything[c] for c in tails}, index=test.index)
    if by_group is not None:
        g = test[var["grupo"]].merge(by_group.reset_index(), on=var["grupo"], how="left")
        g.index = test.index
        q = g[tails].fillna(q)
    s = test[var["escala"]].fillna(0.0)
    return pd.DataFrame({"lo": (test["yhat"] + q[tails[0]] * s).clip(lower=0.0), "hi": test["yhat"] + q[tails[1]] * s})
