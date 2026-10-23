"""Escritura sobre la plantilla del Anexo D: validacion de encabezados, filas, formatos y validaciones."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, unescape

import pandas as pd
from openpyxl.utils import get_column_letter

from daas.publish.anexo_d.constants import FORMULA_PREFIX, FORMULA_VALUES, FORMULAS, HEADERS


def validate_headers(ws: Any, sheet: str) -> None:
    """Valida que la fila 2 de la plantilla sea EXACTA a los encabezados oficiales.

    Protege el formato oficial: si la plantilla cambia (columnas movidas o
    renombradas) se aborta con un error claro antes de escribir nada.

    Args:
        ws: Worksheet de openpyxl.
        sheet: Nombre de la hoja.

    Raises:
        ValueError: Si los encabezados de la fila 2 no coinciden.
    """
    expected = HEADERS[sheet]
    real = [ws.cell(row=2, column=c).value for c in range(1, len(expected) + 1)]
    if real != expected:
        raise ValueError(
            f"Hoja {sheet!r}: los encabezados de la plantilla no coinciden con los "
            f"oficiales.\n  esperado: {expected}\n  real:     {real}"
        )


def delete_example_rows(ws: Any) -> int:
    """Elimina las filas de ejemplo `PROVEEDOR_DEMO` (fila 3 en adelante).

    Conserva la fila 1 (titulo) y la fila 2 (encabezados). Borra todas las filas
    de datos (col A no vacia) desde la 3.

    Args:
        ws: Worksheet de openpyxl.

    Returns:
        int: Numero de filas de ejemplo borradas.
    """
    last = ws.max_row
    if last < 3:
        return 0
    n = last - 2
    ws.delete_rows(3, n)
    return n


def write_sheet(ws: Any, df: pd.DataFrame) -> dict[str, Any]:
    """Escribe `df` en la hoja desde la fila 3, preservando formato de columna.

    Las celdas marcadas como formula (`__FORMULA__:`) se escriben como la formula
    Excel con el numero de fila real; las fechas como `date`; el resto tal cual.
    El `number_format` de cada columna se copia de la fila 2 (encabezado) de la
    plantilla? No: openpyxl conserva el formato de las celdas existentes solo si
    no se borran; como borramos las filas de ejemplo, se re-aplica el formato de
    la columna leido de la plantilla ANTES de borrar (ver `_column_formats`).

    Args:
        ws: Worksheet de openpyxl.
        df: DataFrame con las columnas en el orden oficial.

    Returns:
        dict[str, Any]: valor calculado de cada celda con formula (``{"N3": 0.42}``), para guardarlo en
        cache con `embed_cached_values`. Las celdas cuya formula daria error en Excel no aparecen.
    """
    letters = [get_column_letter(j + 1) for j in range(len(df.columns))]
    cached: dict[str, Any] = {}
    for i, (_, row) in enumerate(df.iterrows()):
        r = 3 + i
        by_letter: dict[str, Any] = {}
        for j, column in enumerate(df.columns):
            c = j + 1
            value = row[column]
            cell = ws.cell(row=r, column=c)
            if isinstance(value, str) and value.startswith(FORMULA_PREFIX):
                _, rest = value.split(FORMULA_PREFIX, 1)
                sheet_f, col_f = rest.split("::", 1)
                template = FORMULAS[sheet_f][col_f]
                cell.value = template.format(r=r)
                try:
                    value = FORMULA_VALUES[sheet_f][col_f](by_letter)
                except (ValueError, ZeroDivisionError, KeyError):
                    value = None
                if value is not None:
                    cached[f"{letters[j]}{r}"] = value
            elif value is None or (isinstance(value, float) and pd.isna(value)):
                cell.value = None
                value = None
            else:
                cell.value = value
            by_letter[letters[j]] = value
    return cached


_ELEMENT = re.compile(r"<(sheet|Relationship)\b([^>]*)/?>")
_ATTRIBUTE = re.compile(r'\b([\w:]+)="([^"]*)"')
_FORMULA_CELL = re.compile(r'<c r="([A-Z]+[0-9]+)"([^>]*)><f>([^<]*)</f><v\s*/>(</c>)')


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """``{nombre_hoja: parte_xml}`` segun `workbook.xml` y sus relaciones."""
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {}
    for _, attrs in _ELEMENT.findall(rels):
        a = dict(_ATTRIBUTE.findall(attrs))
        targets[a["Id"]] = a["Target"]
    parts = {}
    for tag, attrs in _ELEMENT.findall(workbook):
        if tag != "sheet":
            continue
        a = dict(_ATTRIBUTE.findall(attrs))
        target = targets[a["r:id"]].lstrip("/")
        parts[unescape(a["name"])] = target if target.startswith("xl/") else f"xl/{target}"
    return parts


def _cell_with_value(match: re.Match[str], values: dict[str, Any]) -> str:
    ref, attrs, formula, close = match.groups()
    if ref not in values:
        return match.group(0)
    value = values[ref]
    attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
    if isinstance(value, str):
        return f'<c r="{ref}"{attrs} t="str"><f>{formula}</f><v>{escape(value)}</v>{close}'
    number = float(value)
    text = str(int(number)) if number.is_integer() else repr(number)
    return f'<c r="{ref}"{attrs}><f>{formula}</f><v>{text}</v>{close}'


def embed_cached_values(path: Path, cached: dict[str, dict[str, Any]]) -> None:
    """Guarda en el `.xlsx` el valor en cache de las celdas con formula (openpyxl las deja vacias).

    Sin cache, un lector que no recalcula (pandas, auditoria automatica) ve esas celdas vacias. La
    formula se conserva; Excel la recalcula al abrir.

    Args:
        path: Libro ya guardado.
        cached: ``{nombre_hoja: {celda: valor}}`` devuelto por `write_sheet`.
    """
    with zipfile.ZipFile(path) as archive:
        parts = _sheet_parts(archive)
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    by_part = {parts[sheet]: values for sheet, values in cached.items() if values and sheet in parts}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in entries:
            if info.filename in by_part:
                xml = data.decode("utf-8")
                values = by_part[info.filename]
                data = _FORMULA_CELL.sub(lambda m, v=values: _cell_with_value(m, v), xml).encode("utf-8")
            out.writestr(info, data)
    tmp.replace(path)


def column_formats(ws: Any, n_cols: int) -> dict[int, str]:
    """Lee el `number_format` de la primera fila de datos (fila 3) por columna.

    Se llama ANTES de borrar las filas de ejemplo, para re-aplicar el mismo
    formato a las filas reales (fechas `dd/mm/yyyy`, montos COP, etc.).

    Args:
        ws: Worksheet de openpyxl.
        n_cols: Numero de columnas de la hoja.

    Returns:
        dict[int, str]: ``{indice_columna (1-based): number_format}``.
    """
    formats: dict[int, str] = {}
    for c in range(1, n_cols + 1):
        formats[c] = ws.cell(row=3, column=c).number_format
    return formats


def apply_formats(ws: Any, formats: dict[int, str], n_rows: int) -> None:
    """Re-aplica el `number_format` por columna a las filas de datos escritas.

    Args:
        ws: Worksheet de openpyxl.
        formats: Mapa ``{columna: number_format}`` leido de la plantilla.
        n_rows: Numero de filas de datos escritas.
    """
    for i in range(n_rows):
        r = 3 + i
        for c, fmt in formats.items():
            ws.cell(row=r, column=c).number_format = fmt


def apply_unit_formats(ws: Any, df: pd.DataFrame, value_column: str, unit_column: str, by_unit: dict[str, str]) -> None:
    """Formato de numero de `value_column` segun la unidad de cada fila (``by_unit``: unidad -> formato).

    La plantilla trae un solo formato por columna; en la hoja de metricas conviven porcentajes y montos
    COP, asi que el formato se decide fila a fila. Las unidades sin entrada quedan en ``General``.
    """
    c = list(df.columns).index(value_column) + 1
    for i, unit in enumerate(df[unit_column]):
        ws.cell(row=3 + i, column=c).number_format = by_unit.get(str(unit), "General")


def extend_validations(ws: Any, last_row: int) -> None:
    """Extiende los rangos de las listas de validacion hasta la ultima fila escrita (A6).

    La plantilla trae las listas hasta ~la fila 1013 y `delete_rows` no las mueve: con mas filas de
    datos que eso, las ultimas quedarian sin validar.

    Args:
        ws: Worksheet de openpyxl.
        last_row: Ultima fila de datos escrita (1-based).
    """
    from openpyxl.worksheet.cell_range import CellRange, MultiCellRange

    for dv in ws.data_validations.dataValidation:
        ranges = []
        for rng in dv.sqref.ranges:
            if rng.min_row >= 3 and rng.max_row < last_row:
                rng = CellRange(min_col=rng.min_col, min_row=rng.min_row, max_col=rng.max_col, max_row=last_row)
            ranges.append(rng)
        dv.sqref = MultiCellRange(ranges=ranges)
