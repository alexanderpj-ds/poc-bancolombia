"""Loader compartido de ``conf/sources.yml`` para los lectores.

Resuelve, para un contrato canonico (C-01..C-12), la especificacion de su(s)
fuente(s) real(es): archivo(s), hoja, encoding, separador y overrides. Las
rutas se interpretan **relativas a ``local.root``** de ``conf/paths.yml`` (misma
localizacion de ``conf/`` que usa ``daas.io.storage``: argumento explicito,
variable de entorno ``DAAS_CONF`` o ``conf/`` junto a la raiz del paquete).

Regla dura: **cero rutas hardcodeadas**. Todo lector obtiene su archivo aqui.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

#: Nombre del archivo de registro de fuentes dentro de ``conf/``.
_SOURCES_FILE = "sources.yml"
#: Nombre del archivo de rutas dentro de ``conf/``.
_PATHS_FILE = "paths.yml"


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``).

    Este archivo esta en ``<raiz>/src/daas/ingest/readers/_sources.py``; la raiz
    del paquete esta cuatro niveles por encima del directorio de este modulo.

    Returns:
        Path: Ruta absoluta a la raiz del proyecto.
    """
    return Path(__file__).resolve().parents[4]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (coherente con ``daas.io.storage``).

    Returns:
        Path: Ruta al directorio ``conf/`` (``DAAS_CONF`` o fallback).
    """
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def _load_yaml(name: str) -> dict:
    """Carga un YAML de ``conf/`` como diccionario.

    Args:
        name: Nombre del archivo dentro de ``conf/``.

    Returns:
        dict: Contenido del YAML (``{}`` si esta vacio).

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    file_path = _conf_dir() / name
    if not file_path.is_file():
        raise FileNotFoundError(f"No se encontro {file_path}. Defina DAAS_CONF o cree conf/{name}.")
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _local_root() -> Path:
    """Resuelve ``local.root`` de ``conf/paths.yml`` a una ruta absoluta.

    Una ``root`` relativa se interpreta contra la raiz del paquete (igual que
    ``daas.io.storage``).

    Returns:
        Path: Ruta absoluta a la raiz del espejo local de datos.
    """
    paths = _load_yaml(_PATHS_FILE)
    root = str(paths.get("local", {}).get("root", "./data"))
    root_path = Path(root)
    if not root_path.is_absolute():
        root_path = (_package_root() / root_path).resolve()
    return root_path


@dataclass(frozen=True)
class SourceSpec:
    """Especificacion resuelta de la(s) fuente(s) de un contrato.

    Attributes:
        contrato: Codigo canonico del contrato (C-01..C-12).
        dataset: Nombre canonico del dataset.
        lector: Tipo de lector (``csv`` o ``excel``).
        rutas: Rutas absolutas a el/los archivo(s) fuente, en orden.
        hoja: Nombre de hoja (solo Excel); ``None`` para CSV.
        separador: Separador de campos (solo CSV); ``None`` para Excel.
        encoding: Encoding por defecto (CSV).
        overrides_encoding: Encoding por archivo (clave = ruta relativa original).
    """

    contract: str
    dataset: str
    reader: str
    file_paths: list[Path]
    sheet: str | None = None
    separator: str | None = None
    encoding: str = "utf-8"
    overrides_encoding: dict[str, str] = field(default_factory=dict)

    def encoding_for(self, file_path: Path) -> str:
        """Devuelve el encoding aplicable a una ruta concreta.

        Resuelve el override por nombre de archivo (``overrides_encoding`` usa el
        valor relativo de ``sources.yml``, p.ej. ``raw/..._2026.csv`` con BOM).

        Args:
            file_path: Ruta absoluta del archivo a leer.

        Returns:
            str: Encoding a usar (override si aplica, si no el por defecto).
        """
        name = file_path.name
        for rel, header in self.overrides_encoding.items():
            if Path(rel).name == name:
                return header
        return self.encoding


def source_spec(contract: str) -> SourceSpec:
    """Resuelve la ``SourceSpec`` de un contrato desde ``conf/sources.yml``.

    Soporta tanto fuentes de un solo archivo (``archivo``) como la union de
    varios (``archivos``, p.ej. C-09). Las rutas se resuelven contra
    ``local.root``.

    Args:
        contract: Codigo canonico (C-01..C-12).

    Returns:
        SourceSpec: Especificacion con rutas absolutas y metadatos de lectura.

    Raises:
        KeyError: Si el contrato no esta registrado en ``sources.yml``.
    """
    sources = _load_yaml(_SOURCES_FILE)
    contracts = sources.get("contratos", {})
    if contract not in contracts:
        raise KeyError(f"Contrato {contract!r} no registrado en conf/sources.yml.")
    spec = contracts[contract]
    root = _local_root()

    relative: list[str]
    relative = list(spec["archivos"]) if "archivos" in spec else [spec["archivo"]]
    file_paths = [(root / rel).resolve() for rel in relative]

    return SourceSpec(
        contract=contract,
        dataset=str(spec.get("dataset", contract)),
        reader=str(spec.get("lector", "csv")),
        file_paths=file_paths,
        sheet=spec.get("hoja"),
        separator=spec.get("separador"),
        encoding=str(spec.get("encoding", "utf-8")),
        overrides_encoding=dict(spec.get("overrides_encoding", {})),
    )
