"""Catalogo de validaciones de calidad V-01..V-12 del subpaquete `quality`.

`run_check(regla, df, **params)` despacha a la funcion de cada regla con la
**semantica del documento ** (no una numeracion previa). Cada check devuelve
`(df_conforme, df_rechazado)`, donde `df_rechazado` lleva las columnas de
cuarentena `__dq_rule`, `__dq_motivo`, `__dq_puerta` (accion). La compuerta
(quality/report.py) envia lo conforme a `processed/` y lo rechazado a
`daas://quality/rejected/<dataset>`.

Convenciones:
  - Acciones de ``cuarentena``/``fatal`` **separan** filas; ``marcar`` conserva
    todas las filas y a lo sumo anade una bandera (p.ej. holdout,
    missing_anexo_c, outlier marcado) devolviendo el rechazado vacio.
  - Reglas que no aplican a un DataFrame concreto (p.ej. V-07 sin columna de
    fecha) devuelven ``(df, vacio)`` sin error.
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Callable

import pandas as pd

from daas.fondo.build_fund import EXPECTED_FUND_COUNT, build_dim_fund

logger = logging.getLogger(__name__)

#: Columnas de metadata de cuarentena anadidas a las filas rechazadas.
_COL_RULE = "__dq_rule"
_COL_REASON = "__dq_motivo"
_COL_GATE = "__dq_puerta"


def _empty_as(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve un DataFrame vacio con las columnas de `df` + metadata DQ."""
    base = df.iloc[0:0].copy()
    base[_COL_RULE] = pd.Series(dtype="string")
    base[_COL_REASON] = pd.Series(dtype="string")
    base[_COL_GATE] = pd.Series(dtype="string")
    return base


def _mark_rejection(
    df: pd.DataFrame, mask: pd.Series, regla: str, motivo: str, puerta: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa `df` en (conforme, rechazado) segun `mask` (True = rechazado)."""
    rejected = df.loc[mask].copy()
    rejected[_COL_RULE] = regla
    rejected[_COL_REASON] = motivo
    rejected[_COL_GATE] = puerta
    compliant = df.loc[~mask].reset_index(drop=True)
    return compliant, rejected.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# V-01 Validez de esquema estructural                                         #
# --------------------------------------------------------------------------- #
def v01_esquema(df: pd.DataFrame, contrato: str | None = None, **_: object):
    """V-01: valida el esquema estructural del contrato (pandera).

    Delega en `quality.schemas.validar`. Si no se pasa `contrato`, no aplica.
    """
    if contrato is None:
        return df.reset_index(drop=True), _empty_as(df)
    from daas.quality.schemas import validate

    compliant, rejected = validate(df, contrato)
    if not rejected.empty:
        rejected[_COL_RULE] = "V-01"
        rejected[_COL_REASON] = rejected.get("__dq_motivo", "V-01: fallo de esquema")
        rejected[_COL_GATE] = "cuarentena"
    else:
        rejected = _empty_as(df)
    return compliant, rejected


# --------------------------------------------------------------------------- #
# V-02 Completitud de llaves/campos obligatorios                              #
# --------------------------------------------------------------------------- #
def v02_completitud(df: pd.DataFrame, llaves: list[str] | None = None, **_: object):
    """V-02: rechaza filas con nulos en las columnas llave/obligatorias."""
    llaves = [c for c in (llaves or []) if c in df.columns]
    if not llaves:
        return df.reset_index(drop=True), _empty_as(df)
    mask = df[llaves].isna().any(axis=1)
    return _mark_rejection(df, mask, "V-02", "V-02: nulo en llave/campo obligatorio", "cuarentena")


# --------------------------------------------------------------------------- #
# V-03 Unicidad de llave primaria                                             #
# --------------------------------------------------------------------------- #
def v03_unicidad(df: pd.DataFrame, llaves: list[str] | None = None, **_: object):
    """V-03: rechaza duplicados de la llave primaria (conserva la 1a aparicion)."""
    llaves = [c for c in (llaves or []) if c in df.columns]
    if not llaves:
        return df.reset_index(drop=True), _empty_as(df)
    mask = df.duplicated(subset=llaves, keep="first")
    return _mark_rejection(df, mask, "V-03", "V-03: llave primaria duplicada", "cuarentena")


# --------------------------------------------------------------------------- #
# V-04 Dominio valido de categoricas                                          #
# --------------------------------------------------------------------------- #
def v04_dominio(df: pd.DataFrame, columna: str | None = None, dominio: list | None = None, **_: object):
    """V-04: rechaza filas cuyo valor de `columna` no esta en `dominio`."""
    if columna is None or dominio is None or columna not in df.columns:
        return df.reset_index(drop=True), _empty_as(df)
    valid = set(dominio)
    mask = df[columna].notna() & ~df[columna].isin(valid)
    return _mark_rejection(df, mask, "V-04", f"V-04: valor fuera de dominio en {columna}", "cuarentena")


# --------------------------------------------------------------------------- #
# V-05 Rango numerico valido                                                  #
# --------------------------------------------------------------------------- #
def v05_rango(
    df: pd.DataFrame,
    columna: str | None = None,
    minimo: float | None = None,
    maximo: float | None = None,
    **_: object,
):
    """V-05: marca (no elimina) filas con `columna` fuera de [minimo, maximo].

    Accion ``marcar``: anade `__dq_outlier=True` y conserva todas las filas.
    """
    if columna is None or columna not in df.columns:
        return df.reset_index(drop=True), _empty_as(df)
    series = pd.to_numeric(df[columna], errors="coerce")
    outside = pd.Series(False, index=df.index)
    if minimo is not None:
        outside = outside | (series < minimo)
    if maximo is not None:
        outside = outside | (series > maximo)
    out = df.copy()
    out["__dq_outlier"] = outside.fillna(False)
    return out.reset_index(drop=True), _empty_as(df)


# --------------------------------------------------------------------------- #
# V-06 Integridad referencial (FK -> maestro/dim_fondo)                       #
# --------------------------------------------------------------------------- #
def v06_integridad(
    df: pd.DataFrame,
    columna: str | None = None,
    referencia: set | list | None = None,
    **_: object,
):
    """V-06: rechaza filas cuya FK `columna` no existe en `referencia`."""
    if columna is None or referencia is None or columna not in df.columns:
        return df.reset_index(drop=True), _empty_as(df)
    ref = set(referencia)
    mask = df[columna].notna() & ~df[columna].isin(ref)
    return _mark_rejection(df, mask, "V-06", f"V-06: FK sin referencia en {columna}", "cuarentena")


# --------------------------------------------------------------------------- #
# V-07 Corte temporal 31-ago-2026 -> holdout                                  #
# --------------------------------------------------------------------------- #
def v07_corte(
    df: pd.DataFrame,
    date_col: str = "fecha",
    corte: _dt.date | str = "2026-08-31",
    **_: object,
):
    """V-07: separa a holdout las filas con `date_col` posterior al corte.

    Accion ``marcar``: anade la bandera `__holdout=True` a las filas post-corte
    y las conserva (no van a cuarentena; se enrutan a `_holdout/` en curate).
    El rechazado se devuelve vacio.
    """
    if date_col not in df.columns:
        return df.reset_index(drop=True), _empty_as(df)
    if isinstance(corte, str):
        corte = _dt.date.fromisoformat(corte)
    dates = pd.to_datetime(df[date_col], errors="coerce").dt.date
    out = df.copy()
    out["__holdout"] = dates.map(lambda d: bool(d is not None and d > corte)).fillna(False)
    return out.reset_index(drop=True), _empty_as(df)


# --------------------------------------------------------------------------- #
# V-08 Anexo C: 27 dias NULL (nunca 0)                                        #
# --------------------------------------------------------------------------- #
def v08_anexo_c(
    df: pd.DataFrame,
    entity_col: str | None = None,
    date_col: str = "fecha",
    target_col: str = "valor",
    **_: object,
):
    """V-08: densifica el calendario y marca los 27 dias del Anexo C como NULL.

    Delega en `quality.anexo_c.mark_missing`. Accion ``marcar``: devuelve el
    DataFrame denso (con `missing_anexo_c`) como conforme y rechazado vacio.
    """
    if entity_col is None or entity_col not in df.columns or date_col not in df.columns:
        return df.reset_index(drop=True), _empty_as(df)
    from daas.quality.anexo_c import mark_missing

    dense = mark_missing(df, entity_col=entity_col, date_col=date_col, target_col=target_col)
    return dense.reset_index(drop=True), _empty_as(df)


# --------------------------------------------------------------------------- #
# V-09 Reconciliacion de desinstalados (RN-07)                                #
# --------------------------------------------------------------------------- #
def v09_desinstalados(
    df: pd.DataFrame,
    desinstalados: set | list | None = None,
    activos: set | list | None = None,
    columna: str = "cod_cajero",
    prioridad: str = "snapshot_vigente",
    **_: object,
):
    """V-09: reconcilia ATM desinstalados contra el snapshot vigente (RN-07).

    Default parametrizable (`prioridad='snapshot_vigente'`): un ATM activo
    (presente en `activos`) NO se excluye aunque figure en `desinstalados`; se
    **marca** el conflicto con `__rn07_conflicto=True` y se conserva. Solo si
    `prioridad='fecha_desinstalacion'` se enviarian a cuarentena (no es el
    default). Accion ``marcar``.
    """
    if columna not in df.columns or desinstalados is None:
        return df.reset_index(drop=True), _empty_as(df)
    uninstalled = set(desinstalados)
    act = set(activos) if activos is not None else set()
    out = df.copy()
    is_uninstalled = out[columna].isin(uninstalled)
    is_active = out[columna].isin(act)
    out["__rn07_conflicto"] = is_uninstalled & is_active
    if prioridad == "fecha_desinstalacion":
        # Variante no-default: excluir desinstalados que no estan activos.
        mask = is_uninstalled & ~is_active
        return _mark_rejection(out, mask, "V-09", "V-09: ATM desinstalado (RN-07)", "cuarentena")
    return out.reset_index(drop=True), _empty_as(df)


# --------------------------------------------------------------------------- #
# V-10 Cardinalidad de fondos (dim_fondo == 6) - fatal                        #
# --------------------------------------------------------------------------- #
def v10_cardinalidad_fondos(df: pd.DataFrame | None = None, **_: object):
    """V-10: verifica que `dim_fondo` tenga exactamente 6 fondos (fatal).

    Raises:
        ValueError: Si `dim_fondo` no tiene `EXPECTED_FUND_COUNT` filas.

    Returns:
        tuple: `(dim_fondo, vacio)` si cuadra.
    """
    dim = build_dim_fund()
    if len(dim) != EXPECTED_FUND_COUNT:
        raise ValueError(f"V-10 FATAL: dim_fondo tiene {len(dim)} fondos, se esperan " f"{EXPECTED_FUND_COUNT}.")
    return dim.reset_index(drop=True), _empty_as(dim)


# --------------------------------------------------------------------------- #
# V-11 Cobertura temporal / por modelo                                        #
# --------------------------------------------------------------------------- #
def v11_cobertura(
    df: pd.DataFrame,
    entity_col: str | None = None,
    esperado: int | None = None,
    **_: object,
):
    """V-11: marca si la cobertura de entidades alcanza lo esperado.

    Accion ``marcar``: no separa filas; expone el conteo observado como atributo
    del resultado via `attrs['cobertura']`. Devuelve rechazado vacio.
    """
    out = df.reset_index(drop=True)
    if entity_col is not None and entity_col in df.columns:
        obs = int(df[entity_col].nunique())
        out.attrs["cobertura_observada"] = obs
        out.attrs["cobertura_esperada"] = esperado
    return out, _empty_as(df)


# --------------------------------------------------------------------------- #
# V-12 Consistencia cruzada (p.ej. universo Clientes)                         #
# --------------------------------------------------------------------------- #
def v12_consistencia_cruzada(
    df: pd.DataFrame,
    entity_col: str | None = None,
    esperado: int | None = None,
    **_: object,
):
    """V-12: reporta discrepancias de universo (p.ej. Clientes 529 vs 344).

    Accion ``marcar``: no fuerza el conteo; expone observado/esperado en
    `attrs` para el reporte DQ. Devuelve rechazado vacio.
    """
    out = df.reset_index(drop=True)
    if entity_col is not None and entity_col in df.columns:
        obs = int(df[entity_col].nunique())
        out.attrs["universo_observado"] = obs
        out.attrs["universo_esperado"] = esperado
    return out, _empty_as(df)


# --------------------------------------------------------------------------- #
# Frescura y huecos de la red (aviso, no bloqueo)                             #
# --------------------------------------------------------------------------- #
def freshness_warning(
    df: pd.DataFrame,
    corte: _dt.date | str,
    date_col: str = "fecha",
    ventana_anexo_c: list | None = None,
) -> dict:
    """Aviso de frescura: dias entre la fecha maxima de los datos y el corte, y dias sin dato en toda la red.

    No bloquea la corrida: devuelve un dict para las notas del reporte DQ y avisa por log.
    Un "dia sin dato en toda la red" es un dia del calendario entre la fecha minima y la maxima sin ninguna
    fila en el dataset; `dias_sin_dato_fuera_anexo_c` descuenta los dias declarados de indisponibilidad (Anexo C).
    """
    if isinstance(corte, str):
        corte = _dt.date.fromisoformat(corte)
    if date_col not in df.columns or df.empty:
        return {"fecha_max": None, "dias_corte_vs_fecha_max": None, "dias_sin_dato_red": None}
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna().dt.normalize()
    if dates.empty:
        return {"fecha_max": None, "dias_corte_vs_fecha_max": None, "dias_sin_dato_red": None}
    date_max = dates.max().date()
    days_cutoff = (corte - date_max).days
    calendar = pd.date_range(dates.min(), dates.max(), freq="D")
    gaps = calendar.difference(pd.DatetimeIndex(dates.unique()))
    anexo_c = {pd.Timestamp(d) for d in (ventana_anexo_c or [])}
    outside = [d for d in gaps if d not in anexo_c]
    warning = {
        "fecha_max": date_max.isoformat(),
        "dias_corte_vs_fecha_max": int(days_cutoff),
        "dias_sin_dato_red": int(len(gaps)),
        "dias_sin_dato_fuera_anexo_c": int(len(outside)),
    }
    if days_cutoff != 0 or outside:
        logger.warning(
            "DQ frescura: fecha maxima %s (corte %s, diferencia %d dias); %d dias sin dato en toda la red "
            "(%d fuera de la ventana Anexo C).",
            date_max,
            corte,
            days_cutoff,
            len(gaps),
            len(outside),
        )
    return warning


#: Despachador de reglas V-xx -> funcion.
_DISPATCH: dict[str, Callable] = {
    "V-01": v01_esquema,
    "V-02": v02_completitud,
    "V-03": v03_unicidad,
    "V-04": v04_dominio,
    "V-05": v05_rango,
    "V-06": v06_integridad,
    "V-07": v07_corte,
    "V-08": v08_anexo_c,
    "V-09": v09_desinstalados,
    "V-10": v10_cardinalidad_fondos,
    "V-11": v11_cobertura,
    "V-12": v12_consistencia_cruzada,
}


def run_check(regla: str, df: pd.DataFrame, **params: object):
    """Ejecuta una validacion V-xx sobre un DataFrame.

    Args:
        regla: Codigo de la regla (`V-01`..`V-12`).
        df: DataFrame a validar.
        **params: Parametros especificos de la regla (llaves, dominio, corte...).

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: `(conforme, rechazado)`. El rechazado
        incluye `__dq_rule`, `__dq_motivo`, `__dq_puerta` cuando hay filas.

    Raises:
        KeyError: Si `regla` no esta registrada.
        ValueError: Si una regla fatal (V-10) no se cumple.
    """
    if regla not in _DISPATCH:
        raise KeyError(f"Regla DQ desconocida: {regla!r}. Validas: {sorted(_DISPATCH)}.")
    return _DISPATCH[regla](df, **params)
