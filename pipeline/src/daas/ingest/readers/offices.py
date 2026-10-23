"""Lector del contrato C-05 `oficinas`.

Fuente real: `raw/Oficinas.xlsm`, hoja `SUCURSALES` (44 filas). Reglas de
negocio:
  - Columnas reales `Código, Ubicación, TTADORA, Escalas, CIUDAD FONDO, Almacén`
    -> canonico `cod_sucursal, ubicacion, transportadora, escalas, ciudad,
    almacen`.
  - La llave del FONDO = `CIUDAD FONDO` + `TTADORA` (ciudad + transportadora).
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Mapeo nombre real -> canonico.
_RENAMES = {
    "Código": "cod_sucursal",
    "Ubicación": "ubicacion",
    "TTADORA": "transportadora",
    "Escalas": "escalas",
    "CIUDAD FONDO": "ciudad",
    "Almacén": "almacen",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-05 (`Oficinas.xlsm`, hoja `SUCURSALES`).

    Renombra a canonico y expone `ciudad`+`transportadora` para derivar el
    `fondo_id`. Ruta/hoja via `conf/sources.yml` (C-05).

    Returns:
        pd.DataFrame: Columnas canonicas `cod_sucursal` (str), `ubicacion`
        (str), `transportadora` (str), `ciudad` (str), `escalas` (float),
        `almacen` (str).
    """
    spec = source_spec("C-05")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    df = df.rename(columns=_RENAMES)

    df["cod_sucursal"] = df["cod_sucursal"].astype("string")
    for col in ("ubicacion", "transportadora", "ciudad", "almacen"):
        if col in df.columns:
            df[col] = df[col].astype("string")
    if "escalas" in df.columns:
        df["escalas"] = pd.to_numeric(df["escalas"], errors="coerce")

    cols = ["cod_sucursal", "ubicacion", "transportadora", "ciudad", "escalas", "almacen"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].reset_index(drop=True)
