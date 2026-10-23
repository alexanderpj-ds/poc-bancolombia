"""Normalizacion raw -> interim del subpaquete `ingest`.

Convierte las tablas de los lectores (C-01..C-12) al formato interim: tipos
canonicos finales, fechas en ISO 8601 (`datetime.date`), derivacion del
`fondo_id` (CIUDAD|TRANSPORTADORA) cuando la tabla porta ciudad +
transportadora, y resolucion del **snapshot vigente** para los maestros con
`ingestion_year/month/day` (C-02 cp_historico, C-06 maestro_sucursales).

Regla de negocio: `normalize` concentra las reglas transversales; los lectores
solo hacen E/S + mapeo de nombres + coerciones intrinsecas al formato.
`normalize(df, contrato)` despacha por contrato y es idempotente.
"""

from __future__ import annotations

import pandas as pd

from daas.fondo.build_fund import build_fund_id

#: Columnas de snapshot usadas para derivar el "vigente" de los maestros.
_SNAPSHOT_COLS = ["ingestion_year", "ingestion_month", "ingestion_day"]

#: Contratos cuyo "vigente" se resuelve por ultimo snapshot y su llave.
_CURRENT_MASTERS = {
    "C-02": "cod_cajero",
    "C-06": "cod_sucursal",
}

#: Contratos que portan (ciudad, transportadora) y admiten `fondo_id`.
_WITH_FUND = {"C-09", "C-10", "C-11"}


def _current_snapshot(df: pd.DataFrame, key_column: str) -> pd.DataFrame:
    """Devuelve el ultimo snapshot por `llave` segun `ingestion_year/month/day`.

    Si faltan las columnas de snapshot, devuelve el DataFrame sin cambios
    (deduplicado por llave quedandose con la ultima aparicion).

    Args:
        df: DataFrame del maestro con snapshots.
        key_column: Columna llave de la entidad (p.ej. `cod_cajero`).

    Returns:
        pd.DataFrame: Una fila por entidad (snapshot vigente).
    """
    if not all(c in df.columns for c in _SNAPSHOT_COLS):
        return df.drop_duplicates(subset=[key_column], keep="last").reset_index(drop=True)
    ordered = df.sort_values(_SNAPSHOT_COLS)
    current = ordered.drop_duplicates(subset=[key_column], keep="last")
    return current.reset_index(drop=True)


def _add_fund_id(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva `fondo_id` desde `ciudad` + `transportadora`.

    Las filas cuyo `(ciudad, transportadora)` esta fuera de dominio quedan con
    `fondo_id = <NA>` (candidatas a cuarentena en quality V-07); no se eliminan
    aqui.

    Args:
        df: DataFrame con columnas `ciudad` y `transportadora`.

    Returns:
        pd.DataFrame: Copia con la columna `fondo_id` (nullable string).
    """
    if not {"ciudad", "transportadora"}.issubset(df.columns):
        return df
    out = df.copy()
    out["fondo_id"] = [build_fund_id(c, t) for c, t in zip(out["ciudad"], out["transportadora"], strict=False)]
    out["fondo_id"] = out["fondo_id"].astype("string")
    return out


def normalize(df: pd.DataFrame, contract: str) -> pd.DataFrame:
    """Normaliza una tabla raw de un contrato dado al formato interim.

    Aplica (segun el contrato): resolucion de snapshot vigente para maestros
    (C-02, C-06) y derivacion de `fondo_id` para las fuentes que portan ciudad +
    transportadora (C-09, C-10, C-11). Los tipos y fechas ya vienen canonicos de
    los lectores; `normalize` es idempotente.

    Args:
        df: DataFrame canonico producido por el lector del contrato.
        contract: Codigo canonico (C-01..C-12).

    Returns:
        pd.DataFrame: Tabla interim normalizada.
    """
    out = df

    if contract in _CURRENT_MASTERS:
        out = _current_snapshot(out, _CURRENT_MASTERS[contract])

    if contract in _WITH_FUND:
        out = _add_fund_id(out)

    return out.reset_index(drop=True)
