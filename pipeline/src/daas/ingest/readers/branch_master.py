"""Lector del contrato C-06 `maestro_sucursales`.

Fuente real: `raw/maestro_sucursales_hist_enmascarado.xlsx`, hoja `Sheet1`
(19 columnas, snapshots `ingestion_year/month/day`). Reglas de negocio:
  - **No contiene `cupo_max_suc`** (ese vive en C-04 `txc_suc`).
  - El snapshot vigente por `cod_suc` lo deriva `ingest.normalize`; el lector
    conserva todos los snapshots.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Columnas reales a proyectar -> canonico.
_RENAMES = {
    "cod_suc": "cod_sucursal",
    "nombre_suc": "nombre",
    "formato": "formato",
    "tipo_suc": "tipo_suc",
    "region": "region",
    "dpto": "dpto",
    "ciudad": "ciudad",
    "ingestion_year": "ingestion_year",
    "ingestion_month": "ingestion_month",
    "ingestion_day": "ingestion_day",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-06 (`maestro_sucursales_hist_enmascarado.xlsx`, `Sheet1`).

    Conserva todos los snapshots; `normalize` deriva el vigente por
    `cod_sucursal`. Ruta/hoja via `conf/sources.yml` (C-06).

    Returns:
        pd.DataFrame: Subconjunto canonico con `cod_sucursal`, `ciudad`,
        atributos de sucursal y columnas de snapshot `ingestion_*`.
    """
    spec = source_spec("C-06")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    present = {k: v for k, v in _RENAMES.items() if k in df.columns}
    df = df[list(present)].rename(columns=present)

    df["cod_sucursal"] = df["cod_sucursal"].astype("string")
    for col in ("nombre", "formato", "tipo_suc", "region", "dpto", "ciudad"):
        if col in df.columns:
            df[col] = df[col].astype("string")
    for col in ("ingestion_year", "ingestion_month", "ingestion_day"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df.reset_index(drop=True)
