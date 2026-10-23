"""Lectura compartida de las hojas `CBR` y `Clientes` de `CLIENTES_Y_CBR.xlsx`.

Ambos contratos (C-07 CBR, C-08 Clientes) comparten el **mismo esquema** de 11
columnas. Reglas de negocio comunes:
  - Usar `Formato Fecha` (datetime real) como fecha canonica, **NO** `FECHAEFC`
    (entero `YYYYMMDD` mal formado).
  - `FONDO` es la ciudad (CALI/PASTO/IPIALES); `CIUPUNTO` el codigo
    {60->CALI, 74->PASTO, 888->IPIALES}.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Mapeo nombre real -> canonico comun a CBR/Clientes.
_RENAMES = {
    "cod_punto": "cod_punto",
    "CIUPUNTO": "ciupunto",
    "FONPUNTO": "fonpunto",
    "FONDO": "ciudad",
    "VALOR": "valor",
    "TRANSPORTADORA": "transportadora",
    "Formato Fecha": "fecha",
}


def read_points(contract: str) -> pd.DataFrame:
    """Lee una hoja de `CLIENTES_Y_CBR.xlsx` al esquema canonico de puntos.

    Args:
        contract: `C-07` (hoja CBR) o `C-08` (hoja Clientes).

    Returns:
        pd.DataFrame: Columnas canonicas `cod_punto` (str), `ciudad` (str),
        `transportadora` (str), `fecha` (date), `valor` (float),
        `ciupunto`/`fonpunto` auxiliares.
    """
    spec = source_spec(contract)
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    present = {k: v for k, v in _RENAMES.items() if k in df.columns}
    df = df[list(present)].rename(columns=present)

    df["cod_punto"] = df["cod_punto"].astype("string")
    for col in ("ciudad", "transportadora"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip().str.upper()
    if "fonpunto" in df.columns:
        df["fonpunto"] = df["fonpunto"].astype("string")
    if "ciupunto" in df.columns:
        df["ciupunto"] = pd.to_numeric(df["ciupunto"], errors="coerce").astype("Int64")
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    date = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.loc[date.notna()].copy()
    df["fecha"] = date.loc[date.notna()].dt.date

    cols = ["cod_punto", "fecha", "ciudad", "transportadora", "valor", "ciupunto", "fonpunto"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].reset_index(drop=True)
