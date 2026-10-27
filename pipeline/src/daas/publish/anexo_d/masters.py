"""Lectura de contratos y dimensiones (maestros, capacidades, fondos) que alimentan las hojas del Anexo D."""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from daas.io import storage


def load_contracts() -> dict[str, pd.DataFrame]:
    """Lee los 4 contratos ``output/api/*`` via ``storage`` (``daas://``).

    Returns:
        dict[str, pd.DataFrame]: ``{predicciones, recomendaciones, alertas,
        metricas}``.
    """
    contracts = {
        name: storage.read_table(f"daas://output/api/{name}")
        for name in ("predicciones", "recomendaciones", "alertas", "metricas")
    }
    # Contratos OPCIONALES: si el modelo aun no los publica, las hojas lo dicen y no fallan.
    for name in _OPTIONAL_CONTRACTS:
        uri = f"daas://output/api/{name}"
        if storage.exists(uri):
            contracts[name] = storage.read_table(uri)
    return contracts


#: Contratos que U7 usa si existen: `backtest` (y, yhat por cajero y dia, para el WAPE por segmento) y
#: `silenciosos` (equipos sin dato reciente que U1/U2 informa; es informativo).
_OPTIONAL_CONTRACTS = ("backtest", "silenciosos")


def _last_by_cutoff(df: pd.DataFrame, key_column: str, value_cols: list[str], cutoff: _dt.date) -> pd.DataFrame:
    """Devuelve, por ``llave``, la ultima fila con ingestion <= corte (best-effort).

    Como los maestros ``interim/*`` traen snapshots con ``ingestion_*``, se usa
    la ultima ingesta disponible por llave (no se filtra por fecha estricta: el
    maestro vigente es el ultimo snapshot). Si no hay columnas de ingesta, se
    conserva la ultima aparicion.

    Args:
        df: Maestro con snapshots.
        key_column: Columna llave (``cod_cajero`` / ``cod_sucursal``).
        value_cols: Columnas a conservar.
        cutoff: Fecha de corte (informativa; los maestros no traen fecha diaria).

    Returns:
        pd.DataFrame: Una fila por ``llave`` con ``valor_cols``.
    """
    cols_order = [c for c in ("ingestion_year", "ingestion_month", "ingestion_day") if c in df.columns]
    work = df.copy()
    work[key_column] = work[key_column].astype(str)
    if cols_order:
        work = work.sort_values(cols_order)
    work = work.drop_duplicates(subset=[key_column], keep="last")
    present = [c for c in value_cols if c in work.columns]
    return work[[key_column, *present]].reset_index(drop=True)


def city_capacity_map_m1_m2(cutoff: _dt.date) -> pd.DataFrame:
    """Mapa ``cod_cajero -> (ciudad, admon, cupo)`` para M1/M2 (cp_historico).

    Args:
        cutoff: Fecha de corte (SUP-07/vigencia del maestro).

    Returns:
        pd.DataFrame: columnas ``cod_cajero, ciudad, admon, cupo``.
    """
    cp = storage.read_table("daas://interim/cp_historico")
    return _last_by_cutoff(cp, "cod_cajero", ["ciudad", "admon", "cupo"], cutoff)


def atm_attributes_m1_m2(cutoff: _dt.date) -> pd.DataFrame:
    """Mapa ``cod_cajero -> (municipio, ciudad, tipo_facturacion, admon)`` (RN-04A; textos de la hoja 02 v2).

    Args:
        cutoff: Fecha de corte (vigencia del maestro).

    Returns:
        pd.DataFrame: columnas ``cod_cajero, municipio, ciudad, tipo_facturacion, admon``.
    """
    cp = storage.read_table("daas://interim/cp_historico")
    return _last_by_cutoff(cp, "cod_cajero", ["municipio", "ciudad", "tipo_facturacion", "admon"], cutoff)


def city_map_m3(cutoff: _dt.date) -> pd.DataFrame:
    """Mapa ``cod_sucursal -> ciudad`` para M3 (oficinas U maestro_sucursales).

    Args:
        cutoff: Fecha de corte (vigencia del maestro).

    Returns:
        pd.DataFrame: columnas ``cod_sucursal, ciudad``.
    """
    offices = storage.read_table("daas://interim/oficinas")
    master = storage.read_table("daas://interim/maestro_sucursales")
    of = _last_by_cutoff(offices, "cod_sucursal", ["ciudad"], cutoff)
    ms = _last_by_cutoff(master, "cod_sucursal", ["ciudad"], cutoff)
    # Union: prioriza oficinas; completa con maestro_sucursales.
    combined = pd.concat([of, ms], ignore_index=True)
    combined["cod_sucursal"] = combined["cod_sucursal"].astype(str)
    return combined.drop_duplicates(subset=["cod_sucursal"], keep="first")


def capacity_m3(cutoff: _dt.date) -> pd.DataFrame:
    """Cupo vigente por sucursal M3 (``cupo_max_suc`` <= corte, SUP-M3-02).

    Args:
        cutoff: Fecha de corte.

    Returns:
        pd.DataFrame: columnas ``cod_sucursal, cupo``.
    """
    m3 = storage.read_table("daas://processed/m3_sucursales")
    work = m3.copy()
    work["cod_sucursal"] = work["cod_sucursal"].astype(str)
    work["fecha"] = pd.to_datetime(work["fecha"], errors="coerce").dt.date
    work = work[work["fecha"] <= cutoff]
    work = work.sort_values("fecha").drop_duplicates(subset=["cod_sucursal"], keep="last")
    out = work[["cod_sucursal", "cupo_max_suc"]].rename(columns={"cupo_max_suc": "cupo"})
    return out.reset_index(drop=True)


def load_dim_fund() -> pd.DataFrame:
    """Carga ``processed/_dim/dim_fondo`` (fuente de ciudad/TDV de M4/M5/M6).

    Returns:
        pd.DataFrame: columnas ``fondo_id, ciudad, transportadora``.
    """
    return storage.read_table("daas://processed/_dim/dim_fondo")


def capitalize_city(city: object) -> str | None:
    """Normaliza el nombre de ciudad a Capitalizado (``CALI`` -> ``Cali``).

    Args:
        city: Nombre de ciudad en cualquier caja (o nulo).

    Returns:
        str | None: Ciudad capitalizada, o ``None`` si falta.
    """
    if city is None or (isinstance(city, float) and pd.isna(city)):
        return None
    text = str(city).strip()
    return text.capitalize() if text else None


def city_from_fund(fund_id: object) -> str | None:
    """Ciudad desde ``fondo_id = CIUDAD|TRANSPORTADORA`` (M4/M5/M6), capitalizada.

    Args:
        fund_id: Identificador del fondo.

    Returns:
        str | None: Ciudad capitalizada (``Cali``, ``Pasto``, ``Ipiales``).
    """
    if fund_id is None or (isinstance(fund_id, float) and pd.isna(fund_id)):
        return None
    text = str(fund_id)
    return capitalize_city(text.split("|")[0]) if "|" in text else None


def cap_m1() -> float | None:
    """`m1.tope_saldo_inicial` (RN-09) de ``conf/model_u1_u2.yml``; ``None`` si no se declara."""
    from daas.modules.atm_m1_m2.config import load_config as load_u12

    cap = (load_u12().get("m1") or {}).get("tope_saldo_inicial")
    return None if cap is None else float(cap)
