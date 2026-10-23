"""Lector del contrato C-02 `cp_historico`.

Fuente real: `raw/cp_historico.xlsx`, hoja `cp_historico_enmascarado` (26
columnas, snapshots `ingestion_year/month/day`). Reglas de negocio:
  - El **snapshot vigente** por `codigo_cajero` es el de mayor fecha de
    ingestion; derivarlo reproduce los 491 ATM activos. La derivacion de
    "vigente" la realiza `ingest.normalize` sobre el DataFrame crudo; el lector
    conserva todos los snapshots.
  - `#N/A` en `tipo_facturacion` -> nulo.
  - Proyecta el subconjunto canonico util para U0 (identidad, ubicacion, fondo,
    administrador/TDV y snapshot).
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Columnas reales a proyectar -> canonico. `fondo` real = ciudad.
_RENAMES = {
    "codigo_cajero": "cod_cajero",
    "disp_mf": "disp_mf",
    "admon": "admon",
    "codigo_sucursal": "cod_sucursal",
    "cupo": "cupo",
    "municipio": "municipio",
    "region": "region",
    "fondo": "ciudad",
    "estado": "estado",
    "tipo_facturacion": "tipo_facturacion",
    "ingestion_year": "ingestion_year",
    "ingestion_month": "ingestion_month",
    "ingestion_day": "ingestion_day",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-02 (`cp_historico.xlsx`, hoja `cp_historico_enmascarado`).

    Conserva todos los snapshots; `normalize` deriva el vigente por
    `cod_cajero`. Ruta/hoja via `conf/sources.yml` (C-02).

    Returns:
        pd.DataFrame: Subconjunto canonico con identidad, ubicacion (`ciudad`),
        `admon` (SUC|TRANSPORTADORA_00X) y columnas de snapshot `ingestion_*`.
    """
    spec = source_spec("C-02")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    present = {k: v for k, v in _RENAMES.items() if k in df.columns}
    df = df[list(present)].rename(columns=present)

    df["cod_cajero"] = df["cod_cajero"].astype("string")
    if "estado" in df.columns:
        df["estado"] = df["estado"].astype("string")
    if "tipo_facturacion" in df.columns:
        tf = df["tipo_facturacion"].astype("string").str.strip()
        df["tipo_facturacion"] = tf.replace({"#N/A": pd.NA})
    for col in ("ingestion_year", "ingestion_month", "ingestion_day"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("ciudad", "municipio", "region", "admon"):
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df.reset_index(drop=True)
