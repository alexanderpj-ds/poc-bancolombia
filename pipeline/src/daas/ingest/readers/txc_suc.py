"""Lector del contrato C-04 `txc_suc`.

Fuente real: `raw/txc_suc_train.csv` (sep `,`, encoding utf-8, fecha
`dd/mm/yyyy`). Transacciones de sucursales. Reglas de negocio:
  - Columnas reales `f_trx, canal, cod_suc, cupo_max_suc, entradas, salidas`
    -> canonico `fecha, canal, cod_sucursal, cupo_max_suc, entradas, salidas`.
  - `cupo_max_suc` (cupo maximo por sucursal) vive **aqui**, no en el maestro
    C-06; es insumo de las restricciones del optimizador M6.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Mapeo nombre real -> canonico.
_RENAMES = {
    "f_trx": "fecha",
    "canal": "canal",
    "cod_suc": "cod_sucursal",
    "cupo_max_suc": "cupo_max_suc",
    "entradas": "entradas",
    "salidas": "salidas",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-04 (`txc_suc_train.csv`) y devuelve el DataFrame canonico.

    Parsea la fecha `dd/mm/yyyy` a `date` (filas con fecha invalida se
    descartan). Ruta/encoding/separador via `conf/sources.yml` (C-04).

    Returns:
        pd.DataFrame: Columnas canonicas `cod_sucursal` (str), `fecha` (date),
        `cupo_max_suc` (float), `entradas` (float), `salidas` (float),
        `canal` (str).
    """
    spec = source_spec("C-04")
    file_path = spec.file_paths[0]
    df = pd.read_csv(file_path, sep=spec.separator, encoding=spec.encoding_for(file_path))
    df = df.rename(columns=_RENAMES)

    date = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
    df = df.loc[date.notna()].copy()
    df["fecha"] = date.loc[date.notna()].dt.date

    df["cod_sucursal"] = df["cod_sucursal"].astype("string")
    df["canal"] = df["canal"].astype("string")
    for col in ("cupo_max_suc", "entradas", "salidas"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cols = ["cod_sucursal", "fecha", "cupo_max_suc", "entradas", "salidas", "canal"]
    return df[cols].reset_index(drop=True)
