"""Localizacion y carga de la configuracion de exportacion (`conf/export_anexo_d.yml`) y de la plantilla."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

#: Nombre del archivo de configuracion de la exportacion dentro de `conf/`.
_EXPORT_FILE = "export_anexo_d.yml"


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o raiz del paquete).

    Returns:
        Path: Ruta al directorio ``conf/``.
    """
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    # <raiz>/src/daas/publish/anexo_d.py -> raiz tres niveles arriba.
    return Path(__file__).resolve().parents[4] / "conf"


def load_export_config(conf_dir: Path | None = None) -> dict[str, Any]:
    """Carga ``conf/export_anexo_d.yml`` (configuracion de la exportacion).

    Args:
        conf_dir: Directorio ``conf/`` a usar; si es ``None`` se resuelve con
            ``DAAS_CONF`` o la raiz del paquete.

    Returns:
        dict[str, Any]: Configuracion de la exportacion.

    Raises:
        FileNotFoundError: Si no existe ``conf/export_anexo_d.yml``.
    """
    directory = conf_dir if conf_dir is not None else _conf_dir()
    file_path = directory / _EXPORT_FILE
    if not file_path.is_file():
        raise FileNotFoundError(f"No se encontro {file_path}. Defina DAAS_CONF o cree {_EXPORT_FILE}.")
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _local_root(conf_dir: Path) -> Path:
    """Resuelve ``local.root`` de ``conf/paths.yml`` como ruta absoluta.

    La raiz local se interpreta relativa a la raiz del paquete cuando no es
    absoluta (mismo criterio que ``daas.io.storage``).

    Args:
        conf_dir: Directorio ``conf/``.

    Returns:
        Path: Ruta absoluta a la raiz del espejo local (``data/``).
    """
    paths = yaml.safe_load((conf_dir / "paths.yml").read_text(encoding="utf-8")) or {}
    root = str(paths.get("local", {}).get("root", "./data"))
    root_path = Path(root)
    if not root_path.is_absolute():
        # raiz del paquete = <conf_dir>/.. salvo que DAAS_CONF apunte a otro sitio;
        # para el conf del paquete, conf_dir.parent es la raiz.
        root_path = (conf_dir.parent / root_path).resolve()
    return root_path


def resolve_template_path(config: dict[str, Any], conf_dir: Path | None = None) -> Path:
    """Resuelve la ruta fisica de la plantilla oficial (sin hardcodear).

    Usa ``conf/export_anexo_d.yml::plantilla`` (ruta relativa a ``local.root``)
    o, en su defecto, ``conf/sources.yml::anexos_root`` +
    ``Anexo_D_Plantilla_entrega_proveedor_POC.xlsx``.

    Args:
        config: Configuracion de ``export_anexo_d.yml`` ya cargada.
        conf_dir: Directorio ``conf/``; si es ``None`` se resuelve por defecto.

    Returns:
        Path: Ruta absoluta a la plantilla ``.xlsx``.

    Raises:
        FileNotFoundError: Si la plantilla no existe en la ruta resuelta.
    """
    directory = conf_dir if conf_dir is not None else _conf_dir()
    root = _local_root(directory)
    rel = config.get("plantilla")
    if not rel:
        sources = yaml.safe_load((directory / "sources.yml").read_text(encoding="utf-8")) or {}
        anexos_root = str(sources.get("anexos_root", "anexos"))
        rel = f"{anexos_root}/Anexos/" "Anexo_D_Plantilla_entrega_proveedor_POC.xlsx"
    file_path = (root / rel).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(
            f"No se encontro la plantilla del Anexo D en {file_path}. "
            "Revise conf/export_anexo_d.yml::plantilla o conf/sources.yml."
        )
    return file_path


def resolve_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Configuracion de la exportacion: la recibida o la de ``conf/export_anexo_d.yml``."""
    return cfg if cfg is not None else load_export_config()
