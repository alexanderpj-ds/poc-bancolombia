"""Loader y densificacion de series FONDO-dia de M4 (CBR) / M5 (Clientes) (U4/U5).

Lee `processed/<m4_cbr|m5_clientes>` via `daas.io.storage` (daas://) y construye
la serie-objetivo a nivel FONDO-dia (`fondo_id = CIUDAD|TRANSPORTADORA`), que es
el nivel de entrega de la PoC (D-U45-1).

Hallazgo clave (D-U45-2, verificado en `daas.ingest.normalize`): C-07 (CBR) y
C-08 (Clientes) NO reciben `fondo_id` en `normalize` (`_WITH_FUND` solo cubre
C-09/C-10/C-11). Por eso el processed de M4/M5 trae
`cod_punto, fecha, ciudad, transportadora, valor, ...` pero **NO** `fondo_id`.
Este loader lo deriva con `daas.fondo.build_fund.build_fund_id(ciudad,
transportadora)` por fila (descartando las que quedan fuera de dominio ->
`fondo_id is None`, con WARNING y conteo), agrega `sum(valor)` por `(fondo_id,
fecha)` a la columna `ingreso_efectivo` y densifica a dias calendario por
`fondo_id` reutilizando `daas.quality.anexo_c.mark_missing` (los dias faltantes
quedan NULL, nunca 0).

Si un futuro U0 llegara a materializar `fondo_id` en el processed, se prefiere
el existente y solo se deriva donde falte (defensivo).

Todo el I/O pasa por `daas.io.storage`; CERO rutas hardcodeadas.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from daas.fondo.build_fund import build_fund_id
from daas.io import storage
from daas.modules.funds_inflows_m4_m5.config import load_config
from daas.quality.anexo_c import mark_missing

logger = logging.getLogger(__name__)

#: Nombre de la columna objetivo agregada a nivel fondo-dia.
_TARGET = "ingreso_efectivo"


def _derive_fund_id(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva `fondo_id` por fila y descarta las fuera de dominio (D-U45-2).

    Si el processed YA trae `fondo_id` (defensivo), se prefiere el existente y
    solo se deriva donde falte. Las filas cuyo `(ciudad, transportadora)` queda
    fuera de dominio (`build_fund_id -> None`) se descartan con un
    ``logging.warning`` que reporta el conteo (no se inventan fondos).

    Args:
        df: Tabla processed con `ciudad`, `transportadora` (y opcionalmente
            `fondo_id`).

    Returns:
        pd.DataFrame: Copia con la columna `fondo_id` poblada y sin las filas
        fuera de dominio.
    """
    work = df.copy()
    derived = [
        build_fund_id(city, carrier) for city, carrier in zip(work["ciudad"], work["transportadora"], strict=False)
    ]
    if "fondo_id" in work.columns:
        # Preferir el fondo_id existente; derivar solo donde falte (defensivo).
        work["fondo_id"] = work["fondo_id"].where(work["fondo_id"].notna(), pd.Series(derived, index=work.index))
    else:
        work["fondo_id"] = derived

    n_total = len(work)
    valid_rows = work[work["fondo_id"].notna()].copy()
    n_discarded = n_total - len(valid_rows)
    if n_discarded:
        logger.warning(
            "Se descartan %d/%d filas con (ciudad, transportadora) fuera de "
            "dominio (fondo_id is None); no se inventan fondos (D-U45-2).",
            n_discarded,
            n_total,
        )
    return valid_rows


def load_fund_day_series(model: str, conf_dir: Any | None = None) -> pd.DataFrame:
    """Carga la serie diaria densa de ingreso de efectivo por fondo (U4/U5).

    Resuelve el dataset processed del `modelo` ('m4'/'m5') desde
    `conf/model_u4_u5.yml`, lo lee via `daas://`, deriva `fondo_id` (no presente
    en el processed de C-07/C-08), agrega `valor` a `ingreso_efectivo` por
    `(fondo_id, fecha)` y densifica a dias calendario con `mark_missing` (los
    dias faltantes quedan `missing_anexo_c=True` con `ingreso_efectivo` NULL,
    nunca 0).

    Args:
        model: Clave del modelo ('m4' o 'm5').
        conf_dir: Directorio ``conf/`` a usar; si es ``None`` se resuelve con
            ``DAAS_CONF`` o la raiz del paquete.

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `fecha` (date), `ingreso_efectivo`,
        `missing_anexo_c`, densa por dia calendario y ordenada por
        `(fondo_id, fecha)`.

    Raises:
        KeyError: Si `modelo` no esta definido en la config.
    """
    config = load_config(conf_dir)
    models = config["modelos"]
    if model not in models:
        raise KeyError(f"Modelo desconocido: {model!r}. Validos: {sorted(models)}.")
    name_processed = str(models[model]["processed"])

    df = storage.read_table(f"daas://processed/{name_processed}")
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    # Derivar fondo_id por fila y descartar fuera de dominio (D-U45-2).
    df = _derive_fund_id(df)

    # Agregar valor -> ingreso_efectivo por (fondo_id, fecha).
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    aggregated = (
        df.groupby(["fondo_id", "fecha"], as_index=False)["valor"].sum(min_count=1).rename(columns={"valor": _TARGET})
    )

    # Densificar a dias calendario por fondo_id (dias faltantes NULL, no 0).
    dense = mark_missing(
        aggregated,
        entity_col="fondo_id",
        date_col="fecha",
        target_col=_TARGET,
    )

    columns = ["fondo_id", "fecha", _TARGET, "missing_anexo_c"]
    base = dense[columns].sort_values(["fondo_id", "fecha"]).reset_index(drop=True)
    return base
