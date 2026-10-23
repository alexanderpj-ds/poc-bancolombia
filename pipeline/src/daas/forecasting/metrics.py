"""Metricas oficiales del subpaquete `forecasting`, `decision` y `modules` (reuse-analysis.md).

Reuso portado de la demo de 1a ronda SIN cambios en las formulas: WAPE, MAE y
Bias son las metricas oficiales de evaluacion de la PoC y NO deben alterarse.

Regla de negocio (formulas inalteradas):
  - WAPE = sum|y - yhat| / sum|y|
  - MAE  = mean|y - yhat|
  - Bias = sum(yhat - y) / sum|y|

Alineacion y faltantes (SUP-02):
  - Las dos series se alinean por indice y se descartan los pares con NaN en
    cualquiera de las dos (los dias `missing_anexo_c` llegan como NaN y NO
    entran ni al numerador ni al denominador).
  - Si tras la alineacion el denominador ``sum|y|`` es 0, WAPE y Bias devuelven
    ``float('nan')`` (NO 0): no hay demanda sobre la que medir el error
    relativo y forzar 0 falsearia la metrica.
"""

from __future__ import annotations

import pandas as pd


def _align(y_true: pd.Series, y_pred: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Alinea dos series por indice y descarta los pares con NaN (SUP-02).

    Args:
        y_true: Serie de valores observados.
        y_pred: Serie de valores pronosticados.

    Returns:
        tuple[pd.Series, pd.Series]: Par ``(y, yhat)`` alineado y sin NaN.
    """
    frame = pd.DataFrame({"y": y_true, "yhat": y_pred}).dropna()
    return frame["y"], frame["yhat"]


def wape(y_true: pd.Series, y_pred: pd.Series) -> float:
    """WAPE oficial = sum|y - yhat| / sum|y|. Formula inalterada.

    Args:
        y_true: Serie de valores observados.
        y_pred: Serie de valores pronosticados.

    Returns:
        float: WAPE; ``float('nan')`` si ``sum|y| == 0`` (no se devuelve 0).
    """
    y, yhat = _align(y_true, y_pred)
    denominator = y.abs().sum()
    if denominator == 0:
        return float("nan")
    return float((y - yhat).abs().sum() / denominator)


def zero_denominator_entities(y_true: pd.Series, entity: pd.Series) -> set:
    """ALX (SUP-02 / SUP-27): entidades cuyo sum|y| observado en la ventana es 0 (sus pares validos).

    Args:
        y_true: Valores observados (NaN = sin dato, no cuenta).
        entity: Entidad de cada fila, alineada con `y_true`.

    Returns:
        set: Entidades con al menos una observacion valida y sum|y| == 0.
    """
    frame = pd.DataFrame({"y": y_true, "e": entity}).dropna(subset=["y"])
    total = frame["y"].abs().groupby(frame["e"]).sum()
    return set(total.index[total == 0])


def wape_aggregate(y_true: pd.Series, y_pred: pd.Series, entity: pd.Series | None = None,
                   excluded: set | None = None) -> float:
    """WAPE agregado con la exclusion de SUP-02 (ALX, SUP-27) si el interruptor `sup02_denominador_cero` esta activo.

    Excluye del WAPE las entidades con denominador cero en la ventana (`excluded`, o las de
    `zero_denominator_entities`).

    MAE, Bias y `n` no cambian: los ceros de esas entidades siguen siendo observaciones validas (SUP-02). Sin el
    interruptor (o sin `entity`) es exactamente `wape`. La formula no cambia.
    """
    from daas import alx

    if entity is None or not alx.interruptor("sup02_denominador_cero"):
        return wape(y_true, y_pred)
    drop = excluded if excluded is not None else zero_denominator_entities(y_true, entity)
    keep = ~entity.isin(drop)
    return wape(y_true[keep], y_pred[keep])


def sup02_note(y_true: pd.Series, entity: pd.Series) -> str:
    """ALX: texto con las entidades excluidas del WAPE por SUP-02 ("" si no hay o el interruptor esta apagado)."""
    from daas import alx

    if not alx.interruptor("sup02_denominador_cero"):
        return ""
    drop = zero_denominator_entities(y_true, entity)
    if not drop:
        return ""
    n_rows = int(entity.isin(drop).sum())
    return (
        f" SUP-02: {len(drop)} entidad(es) con todos sus reales en 0 en la ventana ({n_rows} entidad-dias: "
        f"{', '.join(map(str, sorted(drop, key=str)))}) salen solo del WAPE agregado; MAE, Bias y n las incluyen."
    )


def mae(y_true: pd.Series, y_pred: pd.Series) -> float:
    """MAE oficial = mean|y - yhat|. Formula inalterada.

    Args:
        y_true: Serie de valores observados.
        y_pred: Serie de valores pronosticados.

    Returns:
        float: MAE; ``float('nan')`` si no hay pares validos.
    """
    y, yhat = _align(y_true, y_pred)
    if len(y) == 0:
        return float("nan")
    return float((y - yhat).abs().mean())


def bias(y_true: pd.Series, y_pred: pd.Series) -> float:
    """Bias oficial = sum(yhat - y) / sum|y|. Formula inalterada.

    Un Bias positivo indica sobre-prediccion (yhat > y en agregado); uno
    negativo, sub-prediccion.

    Args:
        y_true: Serie de valores observados.
        y_pred: Serie de valores pronosticados.

    Returns:
        float: Bias; ``float('nan')`` si ``sum|y| == 0`` (no se devuelve 0).
    """
    y, yhat = _align(y_true, y_pred)
    denominator = y.abs().sum()
    if denominator == 0:
        return float("nan")
    return float((yhat - y).sum() / denominator)
