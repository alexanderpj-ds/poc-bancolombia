"""Linaje y manifiestos del subpaquete `lineage`.

Regla de negocio: cada corrida genera un `run_id =
'<YYYYMMDDTHHMMSS>_<short_git_sha>'`, calcula hashes sha256 de los inputs,
escribe un manifiesto `.meta.json` junto a cada artefacto y mantiene un
`model_registry.json`. Esto hace cada artefacto trazable y reproducible.

Diseno Decisiones de diseno:
  - `new_run_id()` compone el timestamp local con el git sha corto del worktree
    (fallback `"nogit"` si no hay repositorio git disponible).
  - `sha256_of(path)` calcula el hash de un archivo en bloques (estable e
    independiente de la memoria disponible).
  - `write_manifest(artifact_path, meta)` escribe `<artefacto>.meta.json` junto
    al parquet, anadiendo `run_id`/timestamp/versiones si no vienen en `meta`.
Los manifiestos NO contienen datos (solo hashes, conteos y rutas), por lo que
son git-safe; aqui no se escriben a git, pero el formato lo permite.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

#: Tamano de bloque para el hash incremental (64 KiB).
_BLOCK = 65536


def _path_of(path: str) -> Path:
    """Convierte una ruta ``file://`` (o del sistema) en ``Path`` real.

    Decodifica el percent-encoding (p.ej. ``%20`` por el espacio en
    "Proyectos Pragma") que introduce ``Path.as_uri`` en ``daas.io.storage``;
    ``unquote`` es no-op en rutas sin escapes.

    Args:
        path: Ruta ``file://...`` o del sistema.

    Returns:
        Path: Ruta del sistema de archivos.
    """
    if str(path).startswith("file://"):
        return Path(unquote(str(path).replace("file://", "", 1)))
    return Path(path)


#: Valor de git sha cuando no hay repositorio disponible.
_SHA_FALLBACK = "nogit"


def _package_root() -> Path:
    """Devuelve la raiz del proyecto.

    Este archivo esta en ``<raiz>/src/daas/lineage/manifest.py``; la raiz esta
    tres niveles por encima del directorio de este modulo.

    Returns:
        Path: Ruta absoluta a la raiz del proyecto.
    """
    return Path(__file__).resolve().parents[3]


def short_git_sha() -> str:
    """Obtiene el git sha corto del repositorio del paquete.

    Usa ``git -C <raiz> rev-parse --short HEAD``. Si git no esta disponible o el
    directorio no es un repositorio, devuelve ``"nogit"`` (fallback documentado).

    Returns:
        str: Sha corto (p.ej. ``"cc0151b"``) o ``"nogit"``.
    """
    try:
        output = subprocess.run(
            ["git", "-C", str(_package_root()), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _SHA_FALLBACK
    sha = output.stdout.strip()
    return sha if (output.returncode == 0 and sha) else _SHA_FALLBACK


def new_run_id() -> str:
    """Genera `run_id = '<YYYYMMDDTHHMMSS>_<short_git_sha>'`.

    Returns:
        str: Identificador de corrida con timestamp local y git sha corto.
    """
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{ts}_{short_git_sha()}"


def sha256_of(path: str) -> str:
    """Calcula el hash sha256 de un archivo input.

    Lee el archivo en bloques para no cargarlo entero en memoria (relevante con
    `txn_cajeros` ~37 MB).

    Args:
        path: Ruta al archivo (admite ``file://`` o ruta del sistema).

    Returns:
        str: Hash sha256 en hexadecimal.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    file_path = _path_of(path)
    h = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def _library_versions() -> dict[str, str]:
    """Reune las versiones de las librerias clave del pipeline.

    Returns:
        dict[str, str]: Mapa ``libreria -> version`` (solo las instaladas).
    """
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for lib in ("pandas", "pyarrow", "pandera", "holidays", "numpy"):
        try:
            modulo = __import__(lib)
            versions[lib] = getattr(modulo, "__version__", "desconocida")
        except Exception:  # noqa: BLE001  (libreria opcional ausente)
            continue
    return versions


def write_manifest(artifact_path: str, meta: dict[str, Any]) -> str:
    """Escribe el manifiesto `.meta.json` junto a un artefacto.

    El manifiesto se escribe en ``<artefacto-sin-extension>.meta.json`` (p.ej.
    ``processed/m1_atm_dispensador.parquet`` ->
    ``processed/m1_atm_dispensador.meta.json``). Si ``meta`` no trae ``run_id``,
    ``timestamp`` o ``versiones``, se completan aqui.

    Args:
        artifact_path: Ruta fisica del artefacto (``file://...`` o del sistema).
        meta: Metadatos del artefacto (fuentes+hash+conteos+run_id+versiones).

    Returns:
        str: Ruta del archivo ``.meta.json`` escrito.
    """
    base = str(_path_of(artifact_path))
    destination = Path(base).with_suffix(".meta.json")
    destination.parent.mkdir(parents=True, exist_ok=True)

    complete = dict(meta)
    complete.setdefault("run_id", new_run_id())
    complete.setdefault("timestamp", _dt.datetime.now().isoformat(timespec="seconds"))
    complete.setdefault("versiones", _library_versions())
    complete.setdefault("artifact", str(Path(base).name))

    destination.write_text(
        json.dumps(complete, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(destination)
