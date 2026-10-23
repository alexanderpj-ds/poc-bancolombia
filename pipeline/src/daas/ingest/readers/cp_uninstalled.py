"""Lector del contrato C-03 `cp_desinstalados` (RN-07).

Fuente real: `raw/cp_desinstalados_enmascarados.xlsx`, hoja `Hoja1`
(3 columnas: `FECHA DE DESCONEXION, COD, OBSERVACIONES`). Reglas de negocio:
  - La **llave real es `COD`** (no `codigo_cajero`) -> canonico `cod_cajero`.
  - `FECHA DE DESCONEXION` admite nulos (desconexion sin fecha); se parsea a
    `date`.
  - RN-07: la lista se reconcilia contra el snapshot vigente de C-02; esa regla
    (parametrizable) vive en `quality.checks` V-09, no aqui.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Mapeo nombre real -> canonico. Llave real `COD`.
_RENAMES = {
    "COD": "cod_cajero",
    "FECHA DE DESCONEXION": "fecha_desinstalacion",
    "OBSERVACIONES": "observaciones",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-03 (`cp_desinstalados_enmascarados.xlsx`, hoja `Hoja1`).

    Renombra la llave real `COD` a `cod_cajero` y parsea
    `FECHA DE DESCONEXION` a `date` (nulos permitidos). Ruta/hoja via
    `conf/sources.yml` (C-03) / RN-07.

    Returns:
        pd.DataFrame: Columnas canonicas `cod_cajero` (str),
        `fecha_desinstalacion` (date, nullable) y `observaciones` (str).
    """
    spec = source_spec("C-03")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    df = df.rename(columns=_RENAMES)

    df["cod_cajero"] = df["cod_cajero"].astype("string")
    date = pd.to_datetime(df["fecha_desinstalacion"], errors="coerce")
    df["fecha_desinstalacion"] = date.dt.date
    if "observaciones" in df.columns:
        df["observaciones"] = df["observaciones"].astype("string")

    cols = ["cod_cajero", "fecha_desinstalacion", "observaciones"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].reset_index(drop=True)
