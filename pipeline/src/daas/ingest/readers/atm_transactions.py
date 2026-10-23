"""Lector del contrato C-01 `txn_cajeros`.

Fuente real: `raw/txn_cajeros_train.csv` (sep `,`, encoding utf-8, fecha
`dd/mm/yyyy`). Transacciones de cajeros automaticos (ATM). Reglas de negocio:
  - Fecha `dd/mm/yyyy` -> `date`; la fila con fecha invalida `35/06/2026` se
    **descarta** (no se infiere 30/06, que ademas cae en dia ausente del Anexo C).
  - Columnas reales `fecha, cdgtrn, codigo_cajero, total_vlrtran, nro_txn,
    dispensador_multifuncional` -> canonico
    `fecha, cdgtrn, cod_cajero, monto, num_transacciones, disp_mf`.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Mapeo nombre real -> canonico.
_RENAMES = {
    "fecha": "fecha",
    "cdgtrn": "cdgtrn",
    "codigo_cajero": "cod_cajero",
    "total_vlrtran": "monto",
    "nro_txn": "num_transacciones",
    "dispensador_multifuncional": "disp_mf",
}


def read() -> pd.DataFrame:
    """Lee la fuente C-01 (`txn_cajeros_train.csv`) y devuelve el DataFrame canonico.

    Parsea la fecha `dd/mm/yyyy` a `date` y descarta las filas con fecha
    invalida (p.ej. `35/06/2026`). Ruta/encoding/separador via
    `conf/sources.yml` (C-01).

    Returns:
        pd.DataFrame: Columnas canonicas `cod_cajero` (str), `fecha` (date),
        `monto` (float), `num_transacciones` (int), `cdgtrn` (int),
        `disp_mf` (str).
    """
    spec = source_spec("C-01")
    file_path = spec.file_paths[0]
    df = pd.read_csv(file_path, sep=spec.separator, encoding=spec.encoding_for(file_path), low_memory=False)
    df = df.rename(columns=_RENAMES)

    # Parseo estricto dd/mm/yyyy; las fechas invalidas quedan NaT y se descartan.
    date = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
    df = df.loc[date.notna()].copy()
    df["fecha"] = date.loc[date.notna()].dt.date

    df["cod_cajero"] = df["cod_cajero"].astype("string")
    df["monto"] = pd.to_numeric(df["monto"], errors="coerce")
    df["num_transacciones"] = pd.to_numeric(df["num_transacciones"], errors="coerce").astype("Int64")
    df["cdgtrn"] = pd.to_numeric(df["cdgtrn"], errors="coerce").astype("Int64")
    df["disp_mf"] = df["disp_mf"].astype("string").str.upper()

    cols = ["cod_cajero", "fecha", "monto", "num_transacciones", "cdgtrn", "disp_mf"]
    return df[cols].reset_index(drop=True)
