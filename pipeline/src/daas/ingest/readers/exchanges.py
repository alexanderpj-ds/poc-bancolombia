"""Lector del contrato C-10 `intercambios`.

Fuente real: `raw/Historico_Intercambios.xlsx`, hoja `Sheet1` (formato ancho,
una columna por denominacion). Reglas de negocio:
  - Despivotar de ancho a largo (`denominacion` -> filas).
  - La columna `1000` aparece **duplicada** (pandas la renombra `1000.1`): se
    **suman ambas** bajo la denominacion 1000 para no perder aporte ni doblar
    columnas, y se registra en el log.
  - Direccion por `CLIENTE ORIGEN`/`CLIENTE DESTINO`.
"""

from __future__ import annotations

import logging

import pandas as pd

from daas.ingest.readers._sources import source_spec

logger = logging.getLogger(__name__)

#: Columnas identificadoras (no-denominacion) real -> canonico.
_RENAMES_ID = {
    "FECHA": "fecha",
    "CLIENTE ORIGEN": "cliente_origen",
    "CLIENTE DESTINO": "cliente_destino",
    "CIUDAD": "ciudad",
    "TRANSPORTADORA": "transportadora",
    "CALIDAD": "calidad",
}
#: Columnas de totales / metadatos que NO son denominaciones a despivotar.
_NO_DENOMINATION = {"AÑO", "MES", "TOTAL"}


def read() -> pd.DataFrame:
    """Lee la fuente C-10 (`Historico_Intercambios.xlsx`, hoja `Sheet1`).

    Consolida la columna `1000` duplicada (suma) y despivota ancho->largo.
    Ruta/hoja via `conf/sources.yml` (C-10).

    Returns:
        pd.DataFrame: Columnas canonicas `fecha` (date), `ciudad` (str),
        `transportadora` (str), `cliente_origen`/`cliente_destino` (str),
        `calidad` (str), `denominacion` (int), `cantidad` (float).
    """
    spec = source_spec("C-10")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)

    # Consolidar la columna 1000 duplicada (pandas la renombra "1000.1").
    if "1000.1" in [str(c) for c in df.columns]:
        c1000 = [c for c in df.columns if str(c) == "1000"]
        c1000_1 = [c for c in df.columns if str(c) == "1000.1"]
        if c1000 and c1000_1:
            base = pd.to_numeric(df[c1000[0]], errors="coerce").fillna(0)
            extra = pd.to_numeric(df[c1000_1[0]], errors="coerce").fillna(0)
            df[c1000[0]] = base + extra
            df = df.drop(columns=c1000_1)
            logger.info("C-10 intercambios: columna '1000' duplicada consolidada (suma).")

    df = df.rename(columns=_RENAMES_ID)

    id_cols = [v for v in _RENAMES_ID.values() if v in df.columns]
    denom_cols = [c for c in df.columns if c not in id_cols and str(c) not in _NO_DENOMINATION]

    long = df.melt(
        id_vars=id_cols,
        value_vars=denom_cols,
        var_name="denominacion",
        value_name="cantidad",
    )
    long["denominacion"] = pd.to_numeric(long["denominacion"], errors="coerce").astype("Int64")
    long["cantidad"] = pd.to_numeric(long["cantidad"], errors="coerce")
    long = long.loc[long["cantidad"].notna() & (long["cantidad"] != 0)]

    if "fecha" in long.columns:
        date = pd.to_datetime(long["fecha"], errors="coerce")
        long = long.loc[date.notna()].copy()
        long["fecha"] = date.loc[date.notna()].dt.date
    for col in ("ciudad", "transportadora", "cliente_origen", "cliente_destino", "calidad"):
        if col in long.columns:
            long[col] = long[col].astype("string")
            if col in ("ciudad", "transportadora"):
                long[col] = long[col].str.strip().str.upper()

    cols = [
        "fecha",
        "ciudad",
        "transportadora",
        "cliente_origen",
        "cliente_destino",
        "calidad",
        "denominacion",
        "cantidad",
    ]
    cols = [c for c in cols if c in long.columns]
    return long[cols].reset_index(drop=True)
