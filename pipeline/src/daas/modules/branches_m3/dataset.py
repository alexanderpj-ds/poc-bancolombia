"""Loader y densificacion de series M3 Sucursales (U3).

Lee `processed/m3_sucursales` via `daas.io.storage` (daas://), conserva las
columnas canonicas de la sucursal (C-04: `cod_sucursal`, `fecha`,
`cupo_max_suc`, `entradas`, `salidas`, `canal`), valida el invariante de canal
unico (solo `'SUCURSAL FISICA'`, nada de TDV/logistica), densifica a dias
calendario los DOS objetivos (`entradas`, `salidas`) reutilizando
`quality.anexo_c.mark_missing` y deriva el `cupo_max_suc` vigente por sucursal
(ultimo valor con `fecha <= corte` 2026-08-31; best-effort + WARNING si falta,
SUP-M3-02).

A diferencia de los ATM (M1/M2) la sucursal NO deriva objetivos desde `cdgtrn`:
`entradas` y `salidas` vienen ya materializadas en la tabla processed.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

from daas import alx
from daas.io import storage
from daas.quality.anexo_c import mark_missing

logger = logging.getLogger(__name__)

#: URI del dataset processed de sucursales (daas://processed/m3_sucursales).
_URI_PROCESSED = "daas://processed/m3_sucursales"

#: Canal unico admitido para M3 (nada de TDV/logistica).
_SINGLE_CHANNEL = "SUCURSAL FISICA"

#: Fecha de corte para el `cupo_max_suc` vigente por sucursal (SUP-M3-02).
_CURRENT_CUTOFF = _dt.date(2026, 8, 31)

#: Objetivos del modelo de sucursales (doble forecaster).
_TARGETS = ("entradas", "salidas")


def _densify(target: pd.DataFrame, name: str) -> pd.DataFrame:
    """Densifica un objetivo a dias calendario por sucursal (reutiliza mark_missing).

    Usa `quality.anexo_c.mark_missing` para construir la rejilla densa
    `(cod_sucursal x calendario)` del minimo al maximo observado y marcar los
    dias `missing_anexo_c` (target NULL, nunca 0).

    Args:
        target: DataFrame largo `(cod_sucursal, fecha, <nombre>)`.
        name: Nombre de la columna objetivo (`entradas`/`salidas`).

    Returns:
        pd.DataFrame: `(cod_sucursal, fecha, <nombre>, missing_anexo_c,
        anexo_c_con_dato)` denso por dia calendario.
    """
    return mark_missing(
        target,
        entity_col="cod_sucursal",
        date_col="fecha",
        target_col=name,
    )


def _current_capacity_by_branch(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva el `cupo_max_suc` vigente por sucursal (SUP-M3-02, best-effort).

    El cupo vigente es el ultimo valor observado con `fecha <= corte`
    (2026-08-31). Si una sucursal no tiene ningun `cupo_max_suc` con `fecha <=
    corte`, se cae a su maximo observado (best-effort) con un ``logging.warning``
    (SUP-M3-02, NUNCA se inventa un cupo arbitrario).

    Args:
        df: Tabla processed con `cod_sucursal`, `fecha`, `cupo_max_suc`.

    Returns:
        pd.DataFrame: Columnas `cod_sucursal`, `cupo_max_suc` (un valor vigente
        por sucursal).
    """
    work = df[["cod_sucursal", "fecha", "cupo_max_suc"]].copy()
    work["cupo_max_suc"] = pd.to_numeric(work["cupo_max_suc"], errors="coerce")

    current: list[dict[str, Any]] = []
    for code, group in work.groupby("cod_sucursal", sort=True):
        until_cutoff = group[(group["fecha"] <= _CURRENT_CUTOFF) & group["cupo_max_suc"].notna()].sort_values("fecha")
        if not until_cutoff.empty:
            capacity = float(until_cutoff["cupo_max_suc"].iloc[-1])
        else:
            # Fallback best-effort (SUP-M3-02): maximo observado + WARNING.
            observed = group["cupo_max_suc"].dropna()
            capacity = float(observed.max()) if not observed.empty else float("nan")
            logger.warning(
                "Sucursal %s sin cupo_max_suc vigente (fecha <= %s); se usa el "
                "maximo observado %s best-effort con WARNING (SUP-M3-02, no se "
                "inventa cupo).",
                code,
                _CURRENT_CUTOFF.isoformat(),
                capacity,
            )
        current.append({"cod_sucursal": code, "cupo_max_suc": capacity})

    return pd.DataFrame(current, columns=["cod_sucursal", "cupo_max_suc"])


def load_series_m3(conf_dir: Any | None = None) -> pd.DataFrame:
    """Carga la serie diaria densa de sucursales con ambos objetivos (U3).

    Lee `processed/m3_sucursales` via `daas://`, valida el canal unico
    (`'SUCURSAL FISICA'`), densifica a dias calendario los objetivos `entradas`
    y `salidas` (uno a uno con `mark_missing`, merge outer sobre
    `cod_sucursal + fecha` como hace el loader de M2) y joina el `cupo_max_suc`
    vigente por sucursal (SUP-M3-02).

    Args:
        conf_dir: Parametro de simetria con el loader de M1/M2 (no usado aqui:
            M3 no deriva objetivos desde una config de `cdgtrn`). Se mantiene en
            la firma para homogeneidad con `daas.modules.atm_m1_m2.dataset`.

    Returns:
        pd.DataFrame: DataFrame largo con columnas `cod_sucursal`, `fecha`,
        `entradas`, `salidas`, `cupo_max_suc`, `missing_anexo_c`.

    Raises:
        ValueError: Si alguna fila trae un `canal` distinto de
            `'SUCURSAL FISICA'` (no TDV/logistica).
    """
    df = storage.read_table(_URI_PROCESSED)
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    # Invariante de canal unico: nada de TDV/logistica en M3.
    if "canal" in df.columns:
        channels = set(df["canal"].dropna().astype(str).unique().tolist())
        no_physical = {c for c in channels if c != _SINGLE_CHANNEL}
        if no_physical:
            raise ValueError(
                f"processed/m3_sucursales trae canales no fisicos {sorted(no_physical)}; "
                f"M3 solo admite '{_SINGLE_CHANNEL}' (D9: sin TDV/logistica)."
            )

    # ALX PARTE 7 (SUP-35, interruptor `correcciones_datos`): filas duplicadas EXACTAS (13-may-2026: 44 sucursales
    # x 2) se deduplican, igual que `imputacion.datos.matriz_corregida`. Si quedan llaves (sucursal, fecha)
    # repetidas con valores distintos no es un duplicado de carga y se aborta (no se corrige sin evidencia).
    if alx.interruptor("correcciones_datos"):
        n_before = len(df)
        df = df.drop_duplicates().reset_index(drop=True)
        repeated = int(df.duplicated(["cod_sucursal", "fecha"]).sum())
        if repeated:
            raise ValueError(f"m3: {repeated} llaves (sucursal, fecha) repetidas con valores distintos; no se corrige.")
        if len(df) < n_before:
            logger.info("SUP-35: %d filas duplicadas exactas de sucursales deduplicadas.", n_before - len(df))

    # Densificacion de los DOS objetivos (uno por target) y merge outer.
    inflows = _densify(df[["cod_sucursal", "fecha", "entradas"]], "entradas")
    outflows = _densify(df[["cod_sucursal", "fecha", "salidas"]], "salidas")
    base = inflows[["cod_sucursal", "fecha", "entradas", "missing_anexo_c"]].merge(
        outflows[["cod_sucursal", "fecha", "salidas"]],
        on=["cod_sucursal", "fecha"],
        how="outer",
    )
    base["missing_anexo_c"] = base["missing_anexo_c"].fillna(True)

    # Join del cupo_max_suc vigente por sucursal (SUP-M3-02).
    capacity = _current_capacity_by_branch(df)
    base = base.merge(capacity, on="cod_sucursal", how="left")

    columns = [
        "cod_sucursal",
        "fecha",
        "entradas",
        "salidas",
        "cupo_max_suc",
        "missing_anexo_c",
    ]
    base = base[columns].sort_values(["cod_sucursal", "fecha"]).reset_index(drop=True)
    return base
