"""Conversion de valores de celda del Anexo D: fechas, enteros y marcador de formula."""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from daas.publish.anexo_d.constants import FORMULA_PREFIX


def to_date_or_none(value: object) -> _dt.date | None:
    """Convierte un valor a ``datetime.date`` (para escribir con formato fecha).

    Args:
        value: Fecha ISO, ``date``/``datetime``/``Timestamp`` o nulo.

    Returns:
        datetime.date | None: Fecha, o ``None`` si falta.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts.date()


def to_integer(value: object) -> int | None:
    """Convierte un valor numerico a entero (COP); ``None`` si falta/NaN.

    Args:
        value: Numero o nulo.

    Returns:
        int | None: Entero redondeado, o ``None`` si no es numero valido.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(num):
        return None
    return int(round(num))


def mark_formula(sheet: str, column: str) -> str:
    """Devuelve el marcador de celda-formula para (hoja, columna).

    Args:
        sheet: Nombre de la hoja.
        column: Nombre de la columna.

    Returns:
        str: Marcador ``__FORMULA__:<nombre>`` que `_write_sheet` convierte en
        la formula Excel con el numero de fila real.
    """
    return f"{FORMULA_PREFIX}{sheet}::{column}"
