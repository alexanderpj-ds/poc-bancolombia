"""Orquestacion del Anexo D: construye las 5 hojas y las escribe sobre la plantilla oficial."""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd

from daas.io import storage
from daas.publish.anexo_d.cell_values import to_date_or_none
from daas.publish.anexo_d.config import load_export_config, resolve_config, resolve_template_path
from daas.publish.anexo_d.constants import HEADERS, REQUIRED_SHEETS
from daas.publish.anexo_d.masters import load_contracts
from daas.publish.anexo_d.sheet_01_predictions import sheet_01_predictions
from daas.publish.anexo_d.sheet_02_operational_plan import sheet_02_operational_plan
from daas.publish.anexo_d.sheet_03_metrics import sheet_03_metrics
from daas.publish.anexo_d.sheet_04_description import sheet_04_description
from daas.publish.anexo_d.sheet_05_m6_funds import sheet_05_m6_funds
from daas.publish.anexo_d.workbook import (
    apply_formats,
    apply_unit_formats,
    column_formats,
    delete_example_rows,
    embed_cached_values,
    extend_validations,
    validate_headers,
    write_sheet,
)

logger = logging.getLogger(__name__)


def _file_uri_to_path(uri_physical: str) -> Path:
    """Convierte una URI ``file://`` en ``Path`` (decodifica ``%20``).

    Args:
        uri_physical: URI ``file://`` o ``s3://``.

    Returns:
        Path: Ruta del sistema (solo para ``file://``).

    Raises:
        RuntimeError: Si la URI no es ``file://`` (U7 es 100% local).
    """
    parsed = urlparse(uri_physical)
    if parsed.scheme != "file":
        raise RuntimeError(f"La generacion del Anexo D es local; URI no soportada: {uri_physical!r}.")
    return Path(unquote(parsed.path))


def build_sheets(
    contracts: dict[str, pd.DataFrame], cutoff: _dt.date, cfg: dict[str, Any] | None = None
) -> dict[str, pd.DataFrame]:
    """Construye los 5 DataFrames de hoja (orden/encabezados oficiales).

    Args:
        contracts: Contratos cargados.
        cutoff: Fecha de corte (``2026-08-31``).
        cfg: Configuracion de exportacion; si es None se carga la de `conf/`.

    Returns:
        dict[str, pd.DataFrame]: ``{nombre_hoja: df}`` para las 5 obligatorias.
    """
    cfg = resolve_config(cfg)
    return {
        "01_Predicciones": sheet_01_predictions(contracts, cutoff),
        "02_Plan_Operativo": sheet_02_operational_plan(contracts, cutoff, cfg),
        "03_Metricas_Desarrollo": sheet_03_metrics(contracts, cutoff, cfg),
        "04_Descripcion_Solucion": sheet_04_description(contracts, cfg),
        "05_M6_Fondos": sheet_05_m6_funds(contracts, cutoff, cfg),
    }


def generate_anexo_d(
    config: dict[str, Any] | None = None,
    output: str | None = None,
    conf_dir: Path | None = None,
) -> str:
    """Genera el Excel del Anexo D (5 hojas obligatorias) desde la plantilla.

    Lee los contratos `output/api/*` via `storage`, abre la plantilla oficial con
    openpyxl (preservando formato), borra las filas de ejemplo `PROVEEDOR_DEMO`,
    valida los encabezados oficiales, escribe las 5 hojas obligatorias con los
    datos reales (`id_proveedor='PRAGMA'`), conserva `06_Diccionario_Campos` y
    guarda el `.xlsx` en la ruta de salida. Devuelve la ruta fisica del archivo.

    Args:
        config: Configuracion de `export_anexo_d.yml`; si es ``None`` se carga.
        output: URI/ruta de salida; si es ``None`` se toma de la config.
        conf_dir: Directorio ``conf/`` (opcional; util en tests).

    Returns:
        str: Ruta fisica del `.xlsx` generado.
    """
    import openpyxl

    cfg = config if config is not None else load_export_config(conf_dir)
    cutoff = to_date_or_none(cfg.get("corte", "2026-08-31"))
    output_uri = output or cfg.get("salida", "daas://output/anexo_d/POC_Efectivo_PRAGMA.xlsx")

    contracts = load_contracts()
    sheets = build_sheets(contracts, cutoff, cfg)

    template = resolve_template_path(cfg, conf_dir)
    wb = openpyxl.load_workbook(template, data_only=False)

    # Comprobacion de hojas: deben estar las 5 obligatorias + diccionario.
    missing = [h for h in REQUIRED_SHEETS if h not in wb.sheetnames]
    if missing:
        raise ValueError(
            f"La plantilla no contiene las hojas obligatorias {missing}. " f"Hojas presentes: {wb.sheetnames}."
        )

    cached: dict[str, dict[str, Any]] = {}
    for sheet in REQUIRED_SHEETS:
        ws = wb[sheet]
        validate_headers(ws, sheet)
        n_cols = len(HEADERS[sheet])
        formats = column_formats(ws, n_cols)
        delete_example_rows(ws)
        df = sheets[sheet]
        cached[sheet] = write_sheet(ws, df)
        apply_formats(ws, formats, len(df))
        if sheet == "03_Metricas_Desarrollo" and cfg["hoja_03"].get("formato_valor"):
            apply_unit_formats(ws, df, "valor_metrica", "unidad", cfg["hoja_03"]["formato_valor"])
        extend_validations(ws, 2 + len(df))

    # 06_Diccionario_Campos NO se toca (se conserva intacta).

    # Resolver la ruta fisica de salida y guardar. Si es una URI daas:// el entregable se escribe SIEMPRE en
    # el espejo local (`_xlsx_output_path` fuerza `default_scheme=local`; U7 es local y no toca S3).
    destination = _xlsx_output_path(output_uri) if output_uri.startswith("daas://") else Path(output_uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destination)
    embed_cached_values(destination, cached)
    logger.info("Anexo D generado en %s (%d hojas obligatorias).", destination, len(REQUIRED_SHEETS))
    return str(destination)


def _xlsx_output_path(output_uri: str) -> Path:
    """Resuelve la ruta fisica LOCAL ``.xlsx`` de ``daas://output/anexo_d/...``.

    El Anexo D es un entregable LOCAL para inspeccion manual (U7 no toca S3), asi
    que la salida se escribe SIEMPRE en el espejo local (`conf/paths.yml::
    local.root`), independientemente de `default_scheme`. Se fuerza la resolucion
    local pasando una copia de la config de rutas con `default_scheme='local'`,
    y se conserva el nombre real del archivo (`POC_Efectivo_PRAGMA.xlsx`), ya que
    `storage` normaliza el dataset a `.parquet`.

    Args:
        output_uri: URI abstracta ``daas://<capa>/<dataset>`` (dataset con `.xlsx`).

    Returns:
        Path: Ruta fisica local del ``.xlsx``.
    """
    config = dict(storage._load_paths_config())
    config["default_scheme"] = "local"
    physical = storage.resolve_uri(output_uri, config)
    base = _file_uri_to_path(physical)
    # base termina en '<...>.parquet' porque storage anade .parquet al dataset.
    # El dataset real ya trae '.xlsx'; se recompone quitando el .parquet extra.
    name = base.name
    if name.endswith(".xlsx.parquet"):
        name = name[: -len(".parquet")]
    elif name.endswith(".parquet"):
        name = name[: -len(".parquet")] + ".xlsx"
    return base.with_name(name)
