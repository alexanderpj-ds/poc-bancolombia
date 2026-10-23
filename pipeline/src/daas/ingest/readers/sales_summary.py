"""Lector del contrato C-11 `consolidado_ventas`.

Fuente real: `raw/Consolidado_ventas.xlsx`, hoja `Consolidado_ciudades`.
Consolidado de ventas por ciudad. Reglas de negocio:
  - `TASA` es una comision "por 10.000 COP" (esperado 0-10); trae outliers
    10M-200M que se **limpian a NULL** (no se eliminan filas). El umbral es
    `_OUTLIER_RATE_THRESHOLD` (supuesto documentado: una tasa valida no supera
    unas pocas decenas; se marca como outlier por encima de 1.000).
  - El literal `'$ -'` (cero contable de Excel) en columnas `DEN $ ...` se
    coerciona a 0 numerico.
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._sources import source_spec

#: Umbral de outlier para `TASA` (supuesto documentado).
#: Una tasa valida es ~0-10; por seguridad se marca outlier por encima de 1000.
_OUTLIER_RATE_THRESHOLD = 1000.0

#: Columnas identificadoras real -> canonico.
_RENAMES_ID = {
    "FECHA": "fecha",
    "CIUDAD": "ciudad",
    "TDV": "transportadora",
    "RAZÓN SOCIAL": "razon_social",
    "TASA": "tasa",
    "TOTAL VENTA": "total_venta",
    "TOTAL COMISIÓN": "total_comision",
    "TOTAL IVA": "total_iva",
    "TOTAL NETO": "total_neto",
}

#: Columnas de denominacion `DEN $ ...` -> denominacion entera.
_DENOM_COLS = {
    "DEN $ 100.000": 100000,
    "DEN $ 50.000": 50000,
    "DEN $ 20.000": 20000,
    "DEN $ 10.000": 10000,
    "DEN $ 5.000": 5000,
    "DEN $ 2.000": 2000,
}


def _coerce_denom(series: pd.Series) -> pd.Series:
    """Coerciona una columna `DEN $ ...` a numerico, con `'$ -'` -> 0.

    Args:
        series: Columna cruda de denominacion (puede ser texto por `'$ -'`).

    Returns:
        pd.Series: Serie numerica (float) con `'$ -'`/vacios -> 0.
    """
    text = series.astype("string").str.strip()
    text = text.replace({"$ -": "0", "-": "0", "": "0"})
    return pd.to_numeric(text, errors="coerce").fillna(0.0)


def read() -> pd.DataFrame:
    """Lee la fuente C-11 (`Consolidado_ventas.xlsx`, hoja `Consolidado_ciudades`).

    Despivota las columnas `DEN $ ...` a largo, coerciona `'$ -'`->0 y limpia los
    outliers de `TASA` (>`_OUTLIER_RATE_THRESHOLD` -> NULL). Ruta/hoja via
    `conf/sources.yml` (C-11).

    Returns:
        pd.DataFrame: Columnas canonicas `fecha` (date), `ciudad` (str),
        `transportadora` (str), `denominacion` (int), `cantidad` (float),
        `tasa` (float, outliers->NaN) y totales de venta/comision.
    """
    spec = source_spec("C-11")
    df = pd.read_excel(spec.file_paths[0], sheet_name=spec.sheet)
    df = df.rename(columns=_RENAMES_ID)

    for col in ("ciudad", "transportadora", "razon_social"):
        if col in df.columns:
            df[col] = df[col].astype("string")
            if col in ("ciudad", "transportadora"):
                df[col] = df[col].str.strip().str.upper()
    if "fecha" in df.columns:
        date = pd.to_datetime(df["fecha"], errors="coerce")
        df = df.loc[date.notna()].copy()
        df["fecha"] = date.loc[date.notna()].dt.date

    # Limpiar outliers de TASA (no eliminar filas: marcar NULL).
    if "tasa" in df.columns:
        sale_rate = pd.to_numeric(df["tasa"], errors="coerce")
        df["tasa"] = sale_rate.where(sale_rate <= _OUTLIER_RATE_THRESHOLD)
    for col in ("total_venta", "total_comision", "total_iva", "total_neto"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Coercionar y despivotar las columnas DEN $ ... a largo.
    denom_present = {k: v for k, v in _DENOM_COLS.items() if k in df.columns}
    for real in denom_present:
        df[real] = _coerce_denom(df[real])
    id_cols = [c for c in df.columns if c not in denom_present]
    long = df.melt(
        id_vars=id_cols,
        value_vars=list(denom_present),
        var_name="_den_col",
        value_name="cantidad",
    )
    long["denominacion"] = long["_den_col"].map(denom_present).astype("int64")
    long = long.drop(columns=["_den_col"])
    long = long.loc[long["cantidad"].fillna(0) != 0]

    cols = [
        "fecha",
        "ciudad",
        "transportadora",
        "denominacion",
        "cantidad",
        "tasa",
        "total_venta",
        "total_comision",
        "total_iva",
        "total_neto",
    ]
    cols = [c for c in cols if c in long.columns]
    return long[cols].reset_index(drop=True)
