"""Lector del contrato C-09 `disponibles`.

Fuente real: union de 10 CSV `TRANSPORTADORA_00X_disponibles_{2024,2025,2026}.csv`
(sep `;`, fecha `yyyy-mm-dd`). Disponibilidad de efectivo por transportadora.
Reglas de negocio:

  - `TRANSPORTADORA_001_disponibles_2026.csv` trae BOM -> encoding `utf-8-sig`
    (override en `conf/sources.yml`).
  - `Denominacion` viene en TRES codificaciones: float (`100000.0`), entero
    (`100000`) y codigo-divisa de la 002 (`$100NF`, `$1000AF`...). Se coerciona
    a entero en pesos; las codificaciones `$XXXAF/NF` son MONEDA/divisa y se
    excluyen por el filtro de `Tipo_den`.
  - `Tipo_den`/`familia` se normalizan a mayusculas; se conserva solo `BILLETE`.
  - Se filtran ciudades fuera de alcance (BOGOTA/MEDELLIN/CARTAGENA/`'CARTAGENA '`
    con espacio -> trim/GIRARDOT), dejando {CALI, PASTO, IPIALES}.
  - Se excluye la denominacion 1000 y las monedas/divisa (M6: 100k..2k).

El lector deja las filas de `BILLETE` dentro de alcance con `denominacion`
numerica; la 004 solo aporta datos 2026 (natural, no se fuerza).
"""

from __future__ import annotations

import re

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Ciudades dentro del alcance de la PoC (tras trim + upper).
_CITIES_IN_SCOPE = {"CALI", "PASTO", "IPIALES"}
#: Denominaciones de billete obligatorias M6 (excluye 1000 y monedas/divisa).
_M6_DENOMINATIONS = {100000, 50000, 20000, 10000, 5000, 2000}

#: Mapeo nombre real -> canonico.
_RENAMES = {
    "Fecha": "fecha",
    "TDV": "transportadora",
    "Ciudad": "ciudad",
    "Denominacion": "denominacion",
    "Calidad": "calidad",
    "familia": "familia",
    "Tipo_den": "tipo_den",
    "valor": "valor",
}

#: Patron de codigo-divisa de la 002 (`$100NF`, `$1000AF`): numero en miles.
_CURRENCY_PATTERN = re.compile(r"^\$\s*(\d+)\s*(AF|NF)$", re.IGNORECASE)


def _coerce_denomination(value: object) -> int | None:
    """Coerciona una denominacion heterogenea a entero en pesos.

    Soporta float (`100000.0`), entero (`100000`), texto numerico (`'100000'`)
    y el codigo-divisa de la 002 (`$100NF` -> 100 miles = 100000). El codigo
    divisa igualmente cae por el filtro `Tipo_den != BILLETE`, pero se coerciona
    para que la fila sea consistente.

    Args:
        value: Valor crudo de la columna `Denominacion`.

    Returns:
        int | None: Denominacion en pesos, o ``None`` si no es interpretable.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, int | float):
        return int(round(float(value)))
    text = str(value).strip()
    if not text:
        return None
    currency = _CURRENCY_PATTERN.match(text)
    if currency:
        return int(currency.group(1)) * 1000
    try:
        return int(round(float(text.replace(",", "."))))
    except ValueError:
        return None


def read() -> pd.DataFrame:
    """Lee y concatena las 10 fuentes C-09 (`TRANSPORTADORA_*_disponibles_*.csv`).

    Aplica override de encoding `utf-8-sig` por archivo, coercion de
    `denominacion` (3 codificaciones), normalizacion de `tipo_den`/`familia`,
    filtro de ciudad {CALI,PASTO,IPIALES} y filtro M6 (solo BILLETE en
    {100k..2k}, excluye 1000 y monedas/divisa).

    Returns:
        pd.DataFrame: Columnas canonicas `transportadora` (str), `fecha` (date),
        `ciudad` (str), `denominacion` (int), `valor` (float), `tipo_den` (str),
        `familia` (str), `calidad` (str).
    """
    spec = source_spec("C-09")
    marcos: list[pd.DataFrame] = []
    for file_path in spec.file_paths:
        df = pd.read_csv(file_path, sep=spec.separator, encoding=spec.encoding_for(file_path))
        df = df.rename(columns=_RENAMES)
        marcos.append(df)
    df = pd.concat(marcos, ignore_index=True)

    df["transportadora"] = df["transportadora"].astype("string").str.strip().str.upper()
    df["ciudad"] = df["ciudad"].astype("string").str.strip().str.upper()
    df["tipo_den"] = df["tipo_den"].astype("string").str.strip().str.upper()
    if "familia" in df.columns:
        df["familia"] = df["familia"].astype("string").str.strip().str.upper()
    if "calidad" in df.columns:
        df["calidad"] = df["calidad"].astype("string")

    date = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.loc[date.notna()].copy()
    df["fecha"] = date.loc[date.notna()].dt.date

    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["denominacion"] = df["denominacion"].map(_coerce_denomination).astype("Int64")

    # Filtro de ciudad dentro de alcance.
    df = df.loc[df["ciudad"].isin(_CITIES_IN_SCOPE)]
    # Solo BILLETE (excluye MONEDA/divisa) y denominaciones M6 (excluye 1000).
    df = df.loc[df["tipo_den"] == "BILLETE"]
    df = df.loc[df["denominacion"].isin(_M6_DENOMINATIONS)]
    df["denominacion"] = df["denominacion"].astype("int64")

    cols = ["transportadora", "fecha", "ciudad", "denominacion", "valor", "tipo_den", "familia", "calidad"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].reset_index(drop=True)
