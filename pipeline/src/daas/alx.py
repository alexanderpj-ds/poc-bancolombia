"""Interruptores de la copia de trabajo ALX (`conf/alx.yml`).

Cada cambio de ALX sobre el pipeline de Santiago se consulta con `interruptor(nombre)`. Sin el archivo, o con la
clave ausente o en false, el comportamiento es el de Santiago. Busca primero en ``DAAS_CONF`` y luego en el
``conf/`` del paquete (igual que `forecasting.forecasters.load_recipes`).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_FILE = "alx.yml"


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ruta() -> Path | None:
    """Archivo `alx.yml` que manda (None si no hay ninguno)."""
    candidates = []
    if os.environ.get("DAAS_CONF"):
        candidates.append(Path(os.environ["DAAS_CONF"]).expanduser().resolve())
    candidates.append(_package_root() / "conf")
    for directory in candidates:
        if (directory / _FILE).is_file():
            return directory / _FILE
    return None


def interruptores() -> dict[str, bool]:
    """Todos los interruptores declarados (vacio = Santiago)."""
    path = ruta()
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): bool(v) for k, v in (data.get("interruptores") or {}).items()}


def interruptor(nombre: str) -> bool:
    """True si el interruptor `nombre` esta encendido en `conf/alx.yml`."""
    return interruptores().get(nombre, False)
