"""Lector del contrato C-12 `costos_anexo_e`.

Fuente real: `anexos/Anexos/Anexo_E_Parametros costos.xlsx` (nombre con
espacio; vive fuera de `raw/`). Parametros de costos de transporte de valores.
Reglas de negocio:
  - La ruta se resuelve via `conf/sources.yml` (C-12), NUNCA se hardcodea.
  - El libro trae 3 hojas de costos (`Fondos`, `Sucursales`, `ATM`) con un
    **encabezado de dos filas**: la primera agrupa por transportadora
    (`TRANSPORTADORA_00X`) y la segunda separa `Costo Fijo` / `Costo X10 Mil`
    (tarifa por cada 10.000 COP). Se despivota a largo:
    `(ambito, servicio, concepto, transportadora, costo_fijo, tarifa)`.
  - La hoja `Sucursales` trae dos bloques, `Tipo Costo (Provision)` y
    `Tipo Costo (Recolección)`, con los mismos conceptos: `servicio` dice de
    cual viene la fila (`provision`/`recoleccion`). En `ATM` y `Fondos` hay una
    sola tabla y `servicio` queda NULL (vale para cualquier servicio).
  - `No Disponible` -> NULL (concepto/transportadora sin tarifa publicada).
  - `$ -` (formato contable de cero; la tarifa variable de MF) -> 0.
  - Las notas (`*...`) y los encabezados repetidos no son conceptos: se descartan.

Alimenta el motor de costos `daas.costs.anexo_e` (costo = fijo + monto/10.000 x
tarifa), que es U6 (fuera del alcance U0); el lector solo normaliza la tabla.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Hojas de costos a leer (la hoja `Notas` se ignora).
_SHEETS = ("Fondos", "Sucursales", "ATM")
#: Literales que representan ausencia de dato.
_UNAVAILABLE = {"No Disponible", "ND", "N/A", "-"}
#: Cero en formato contable (Excel muestra `$ -` para 0).
_ACCOUNTING_ZERO = {"$ -", "$-"}
#: Inicio del encabezado de bloque (`Tipo Costo` o `Tipo Costo (Provision)`).
_HEADER = "tipo costo"
#: Servicio de un bloque segun su encabezado (sin acentos, minusculas).
_SERVICE_BY_BLOCK = {"provision": "provision", "recoleccion": "recoleccion"}


def _service_of_header(text: str) -> str | None:
    """Servicio (`provision`/`recoleccion`) que declara un encabezado de bloque.

    Args:
        text: Celda del encabezado, p.ej. `Tipo Costo (Recolección)`.

    Returns:
        str | None: El servicio, o ``None`` si el bloque no lo distingue.
    """
    flat = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    for key, service in _SERVICE_BY_BLOCK.items():
        if key in flat:
            return service
    return None


def _read_sheet(file_path, sheet: str) -> pd.DataFrame:
    """Lee y despivota una hoja de costos (encabezado de dos filas).

    Args:
        file_path: Ruta absoluta al archivo Anexo E.
        sheet: Nombre de la hoja (`Fondos`/`Sucursales`/`ATM`).

    Returns:
        pd.DataFrame: Columnas `ambito`, `servicio`, `concepto`,
        `transportadora`, `costo_fijo`, `tarifa`.
    """
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    # Fila 0: transportadora (merge -> rellenar hacia delante).
    # Fila 1: {Costo Fijo | Costo X10 Mil}. Datos desde fila 2.
    row_tdv = raw.iloc[0].ffill()
    row_kind = raw.iloc[1]
    data = raw.iloc[2:].reset_index(drop=True)

    concepts = data.iloc[:, 0].astype("string").str.strip()
    # Servicio de cada fila: el del ultimo encabezado de bloque visto.
    services: list[str | None] = []
    actual = _service_of_header(str(raw.iloc[0, 0]))
    for concept in concepts:
        if not pd.isna(concept) and str(concept).lower().startswith(_HEADER):
            actual = _service_of_header(str(concept))
        services.append(actual)
    records: list[dict] = []
    # Recorre pares de columnas (fijo, tarifa) por transportadora.
    for col in range(1, raw.shape[1]):
        tdv = row_tdv.iloc[col]
        kind = str(row_kind.iloc[col]).strip().lower()
        if pd.isna(tdv):
            continue
        tdv = str(tdv).strip().upper()
        if "fijo" in kind:
            col_fixed = col
            col_rate = col + 1 if col + 1 < raw.shape[1] else None
            series_fixed = data.iloc[:, col_fixed]
            series_rate = data.iloc[:, col_rate] if col_rate is not None else None
            for i, concept in enumerate(concepts):
                if pd.isna(concept) or concept == "":
                    continue
                if concept.startswith("*") or concept.lower().startswith(_HEADER):
                    continue
                records.append(
                    {
                        "ambito": sheet,
                        "servicio": services[i],
                        "concepto": concept,
                        "transportadora": tdv,
                        "costo_fijo": _num(series_fixed.iloc[i]),
                        "tarifa": _num(series_rate.iloc[i]) if series_rate is not None else None,
                    }
                )
    return pd.DataFrame.from_records(records)


def _num(value: object) -> float | None:
    """Coerciona un valor a float, mapeando `No Disponible` -> ``None``.

    Args:
        value: Celda cruda.

    Returns:
        float | None: Numero, o ``None`` si es un literal de no-disponible/vacio.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and value.strip() in _UNAVAILABLE:
        return None
    if isinstance(value, str) and value.strip() in _ACCOUNTING_ZERO:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read() -> pd.DataFrame:
    """Lee la fuente C-12 (`Anexo_E_Parametros costos.xlsx`).

    Ruta (con espacio, fuera de raw/) resuelta via `conf/sources.yml` (C-12).
    Despivota las 3 hojas de costos a formato largo.

    Returns:
        pd.DataFrame: Columnas canonicas `ambito` (str), `servicio` (str o
        NULL), `concepto` (str),
        `transportadora` (str), `costo_fijo` (float), `tarifa` (float).
    """
    spec = source_spec("C-12")
    file_path = spec.file_paths[0]
    marcos = [_read_sheet(file_path, sheet) for sheet in _SHEETS]
    df = pd.concat(marcos, ignore_index=True)

    df["ambito"] = df["ambito"].astype("string")
    df["servicio"] = df["servicio"].astype("string")
    df["concepto"] = df["concepto"].astype("string")
    df["transportadora"] = df["transportadora"].astype("string")
    df["costo_fijo"] = pd.to_numeric(df["costo_fijo"], errors="coerce")
    df["tarifa"] = pd.to_numeric(df["tarifa"], errors="coerce")
    return df.reset_index(drop=True)
