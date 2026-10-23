"""Familia `ml_laboratorio`: los champions finales del laboratorio de ALX dentro del pipeline (PARTE 7, SUP-39).

Una receta `familia: ml_laboratorio` de `conf/pronosticadores.yml` (`modelo: <nombre del lab>`, `dataset: <ds>`)
pronostica con `ml.pronosticar.pronosticar`, la MISMA funcion que envuelve el modelo registrado
`models:/poc-daas-ml-<ds>@champion` (`ml.pronosticar.PronosticadorEscenario`, escenario S1) y que el arnes evaluo:
combinaciones y ensambles congelados miembro a miembro, ML globales con sus parametros de `lab/conf/experimentos`.

Contexto V4 "as of" (interruptor `contexto_asof`, SUP-28): si alguna hoja del champion usa el grupo `contexto`, la
unidad llama a `preparar(...)` antes de pronosticar. Se arman los insumos con
`imputacion.contexto_asof.construir_contexto_asof` (misma construccion que el arnes y el modelo registrado) a partir
de la raiz de datos de la corrida: snapshots de `raw/cp_historico.xlsx` (M1/M2), `processed/m3_sucursales` (M3) y la
matriz del objetivo hermano que arma el propio pipeline. En cada origen (horizonte, backtest y calibracion conformal)
los atributos son los del ultimo snapshot <= origen (`atributos_contexto`); nunca el maestro vigente del 8-sep.

Sin imputacion: la PARTE 5 no la adopto en ningun champion (SUP-36); esta familia no imputa ni recibe mascara.
Requiere la raiz de ALX en `sys.path` (paquetes `ml`, `lab`, `imputacion`); `corrida_entrega.sh` la agrega.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd

from daas import alx

logger = logging.getLogger(__name__)

FAMILY = "ml_laboratorio"

#: Insumos del contexto "as of" por dataset del laboratorio (`m1`, `m2_pagado`, ...), en memoria del proceso.
_INSUMOS: dict[str, dict | None] = {}
#: Snapshots del maestro leidos una vez por proceso (el xlsx pesa ~31 MB).
_SNAPSHOTS: dict[str, pd.DataFrame] = {}

_ATM = ("m1", "m2_pagado", "m2_cash_in")


def _pr():
    from ml import pronosticar  # noqa: PLC0415 (requiere la raiz de ALX en sys.path)

    return pronosticar


def necesita_contexto(modelo: str) -> bool:
    """True si alguna hoja del champion `modelo` usa el grupo `contexto` (V4)."""
    pr = _pr()
    return any(pr.usa_contexto(h) for h in pr.hojas(modelo))


def receta(nombre: str, conf: dict[str, Any]) -> dict[str, Any] | None:
    """Parametros de la receta si es de la familia `ml_laboratorio`; None si no."""
    rec = (conf.get("recetas") or {}).get(nombre) or {}
    return rec if rec.get("familia") == FAMILY else None


def snapshots_desde_excel(fuente: Any) -> pd.DataFrame:
    """Snapshots del maestro de cajeros desde `raw/cp_historico.xlsx` (bytes o ruta).

    Misma construccion que `imputacion.datos.cp_snapshots` (que lee el mismo objeto de S3): primera hoja,
    `daas.ingest.readers.cp_history._RENAMES`, `fecha_snapshot` con `ingestion_*`, `cod_cajero` como texto.
    """
    from daas.ingest.readers.cp_history import _RENAMES

    crudo = pd.read_excel(io.BytesIO(fuente) if isinstance(fuente, bytes) else fuente, sheet_name=0)
    presentes = {k: v for k, v in _RENAMES.items() if k in crudo.columns}
    df = crudo[list(presentes)].rename(columns=presentes)
    partes = {c: pd.to_numeric(df[f"ingestion_{c}"], errors="coerce") for c in ("year", "month", "day")}
    df["fecha_snapshot"] = pd.to_datetime(pd.DataFrame(partes))
    df["cod_cajero"] = df["cod_cajero"].astype(str)
    columnas = ["fecha_snapshot", "cod_cajero", "ciudad", "admon", "cupo", "disp_mf", "estado"]
    return df[columnas].sort_values(["cod_cajero", "fecha_snapshot"]).reset_index(drop=True)


def _ruta_raw(nombre: str) -> str:
    """Ruta fisica de `raw/<nombre>` en la raiz de datos de la corrida (mismo esquema que `daas.io.storage`)."""
    from daas.io import storage

    base = nombre.rsplit(".", 1)[0]
    fisica = storage.resolve_uri(f"daas://raw/{base}")
    fisica = fisica[: -len(".parquet")] + "." + nombre.rsplit(".", 1)[1]
    return storage._file_uri_to_path(fisica).as_posix() if fisica.startswith("file://") else fisica


def snapshots() -> pd.DataFrame:
    """Snapshots del maestro de la raiz de datos de la corrida (cacheados por proceso)."""
    if "cp" not in _SNAPSHOTS:
        ruta = _ruta_raw("cp_historico.xlsx")
        logger.info("Contexto as of: leyendo snapshots del maestro de %s", ruta)
        _SNAPSHOTS["cp"] = snapshots_desde_excel(ruta)
    return _SNAPSHOTS["cp"]


def preparar(
    nombre_receta: str,
    data: pd.DataFrame,
    entidad: str,
    objetivo: str,
    *,
    hermano: str | None = None,
    conf: dict[str, Any] | None = None,
) -> str | None:
    """Arma los insumos del contexto "as of" si `nombre_receta` es un champion `ml_laboratorio`.

    Args:
        nombre_receta: Receta resuelta para la unidad/objetivo.
        data: Serie larga de la unidad (la misma que recibe `generate_forecast`).
        entidad: Columna de la entidad.
        objetivo: Columna objetivo.
        hermano: Objetivo hermano (M2 pagado <-> cash_in, M3 entradas <-> salidas) para la matriz cruzada.
        conf: `pronosticadores.yml` cargado (se carga si es None).

    Returns:
        Dataset del laboratorio preparado, o None si la receta no es `ml_laboratorio`.

    Raises:
        ValueError: Si el champion usa V4 y el interruptor `contexto_asof` esta apagado (seria una variante no
            evaluada), o si el interruptor `imputacion` esta encendido (no hay imputacion adoptada).
    """
    from daas.forecasting import forecast as forecast_mod
    from daas.forecasting import forecasters

    conf = conf if conf is not None else forecasters.load_recipes()
    rec = receta(nombre_receta, conf)
    if rec is None:
        return None
    if alx.interruptor("imputacion"):
        raise ValueError("Interruptor `imputacion` encendido, pero la PARTE 5 no adopto imputacion (SUP-36).")
    dataset = str(rec["dataset"])
    modelo = str(rec["modelo"])
    if not necesita_contexto(modelo):
        _INSUMOS[dataset] = None
        return dataset
    if not alx.interruptor("contexto_asof"):
        raise ValueError(f"{modelo} usa el grupo contexto (V4): exige el interruptor `contexto_asof` (SUP-28).")
    from imputacion.contexto_asof import construir_contexto_asof

    wide = forecast_mod._matrix(data, entidad, objetivo)
    if entidad == "fondo_id":
        ciudad = pd.Series({c: str(c).split("|")[0] for c in wide.columns})
    elif "ciudad" in data.columns:
        ciudad = data.drop_duplicates(entidad).set_index(entidad)["ciudad"]
    else:
        ciudad = pd.Series(index=wide.columns, dtype=object)
    attrs = pd.DataFrame({"ciudad": ciudad.reindex(wide.columns).fillna("SIN_CIUDAD")})
    cruzada = forecast_mod._matrix(data, entidad, hermano) if hermano else None
    kwargs: dict[str, Any] = {}
    if dataset in _ATM:
        kwargs["snapshots"] = snapshots()
    elif dataset.startswith("m3_"):
        from daas.io import storage

        kwargs["tabla_m3"] = storage.read_table("daas://processed/m3_sucursales")
    _INSUMOS[dataset] = construir_contexto_asof(dataset, wide, attrs, {}, cruzada=cruzada, **kwargs)
    logger.info("Contexto as of preparado para %s (%s): %d entidades.", dataset, modelo, wide.shape[1])
    return dataset


def contexto_al(dataset: str, origen: pd.Timestamp, columnas: pd.Index) -> dict | None:
    """Contexto del champion al `origen` (atributos del ultimo snapshot <= origen y matriz cruzada)."""
    insumos = _INSUMOS.get(dataset)
    if insumos is None:
        return None
    from imputacion.contexto_asof import atributos_contexto

    return {"atributos": atributos_contexto(insumos, origen, columnas), "cruzada": insumos["cruzada"]}


def forecast_laboratorio(
    hist: pd.DataFrame, dates: pd.DatetimeIndex, *, modelo: str, dataset: str, explicar: str | None = None
) -> pd.DataFrame:
    """Pronostico del champion `modelo` con datos <= origen (`hist.index.max()`), como `PronosticadorEscenario`.

    `explicar` solo lo usa `forecasting.explain` (hoja ML que se explica); aqui se ignora.

    Raises:
        RuntimeError: Si el champion usa V4 y la unidad no llamo a `preparar` para `dataset`.
    """
    if dataset not in _INSUMOS and necesita_contexto(modelo):
        raise RuntimeError(f"{modelo} usa V4: la unidad debe llamar a laboratorio.preparar para {dataset}.")
    hist = hist.dropna(axis=1, how="all")
    origen = hist.index.max()
    if pd.Timestamp(dates[0]) != origen + pd.Timedelta(days=1):
        raise ValueError(f"Las fechas deben empezar el dia siguiente al origen {origen.date()}.")
    contexto = contexto_al(dataset, origen, hist.columns)
    return _pr().pronosticar(hist, dates, modelo=modelo, contexto=contexto).clip(lower=0.0)
