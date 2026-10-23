"""Capa de almacenamiento FUNCIONAL del paquete `daas`.

Resuelve URIs abstractas de la forma ``daas://<capa>/<dataset>`` a un destino
fisico (``s3://...`` por defecto en AWS, ``file://...`` en el espejo local) a
partir de ``conf/paths.yml`` y realiza el round-trip de tablas parquet con
pyarrow.

Modo estricto: el esquema por defecto es ``local``. S3 se activa solo por
entorno (``DAAS_SCHEME=s3`` y ``DAAS_S3_BUCKET``; los nombres de las variables
estan en ``conf/paths.yml``). Si el esquema es ``s3`` y S3 falla (credenciales,
red, bucket sin definir), se lanza ``S3NoDisponible``: NO se cae a local en
silencio, porque se publicaria o leeria un dato distinto sin avisar.

Localizacion de ``conf/`` (en orden de prioridad):

1. El argumento ``paths_config`` (dict ya cargado), si se pasa.
2. La variable de entorno ``DAAS_CONF`` (ruta al directorio ``conf/``).
3. ``conf/`` relativo a la raiz del proyecto (dos niveles por encima de
   ``src/daas/``).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

#: Esquema de las URIs abstractas que maneja este modulo.
_SCHEME = "daas"
#: Nombre del archivo de configuracion de rutas dentro de ``conf/``.
_PATHS_FILE = "paths.yml"


class S3UnavailableError(RuntimeError):
    """El esquema es ``s3`` y el acceso a S3 fallo o esta mal configurado (modo estricto)."""


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``).

    Este archivo esta en ``<raiz>/src/daas/io/storage.py``; la raiz del paquete
    es, por tanto, tres niveles por encima del directorio de este modulo.

    Returns:
        Path: Ruta absoluta a la raiz del proyecto.
    """
    return Path(__file__).resolve().parents[3]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/``.

    Usa la variable de entorno ``DAAS_CONF`` si esta definida; en caso contrario
    cae a ``<raiz-del-paquete>/conf``.

    Returns:
        Path: Ruta al directorio ``conf/``.
    """
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def _load_paths_config() -> dict:
    """Carga ``conf/paths.yml`` como diccionario.

    Returns:
        dict: Contenido de ``paths.yml``.

    Raises:
        FileNotFoundError: Si no se encuentra el archivo de configuracion.
    """
    paths_file = _conf_dir() / _PATHS_FILE
    if not paths_file.is_file():
        raise FileNotFoundError(f"No se encontro {paths_file}. Defina DAAS_CONF o cree conf/paths.yml.")
    with paths_file.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_abstract_uri(uri: str) -> tuple[str, str]:
    """Descompone una URI abstracta ``daas://<capa>/<dataset>``.

    Args:
        uri: URI abstracta a parsear.

    Returns:
        tuple[str, str]: Par ``(capa, dataset)``.

    Raises:
        ValueError: Si la URI no usa el esquema ``daas://`` o le falta capa o
            dataset.
    """
    parsed = urlparse(uri)
    if parsed.scheme != _SCHEME:
        raise ValueError(f"URI no abstracta: {uri!r}. Se espera el esquema '{_SCHEME}://'.")
    layer = parsed.netloc
    dataset = parsed.path.lstrip("/")
    if not layer or not dataset:
        raise ValueError(f"URI abstracta malformada: {uri!r}. Formato: {_SCHEME}://<capa>/<dataset>.")
    return layer, dataset


def _local_path(layer: str, dataset: str, config: dict) -> str:
    """Construye la ruta fisica local (``file://``) de un dataset.

    La raiz local (``local.root``) se interpreta relativa a la raiz del paquete
    cuando es una ruta relativa.

    Args:
        layer: Capa medallion (raw, interim, processed, features, output, quality).
        dataset: Nombre del dataset.
        config: Configuracion cargada de ``paths.yml``.

    Returns:
        str: URI ``file://`` absoluta al archivo parquet.
    """
    root = str(config.get("local", {}).get("root", "./data"))
    root_path = Path(root)
    if not root_path.is_absolute():
        root_path = (_package_root() / root_path).resolve()
    target = root_path / layer / f"{dataset}.parquet"
    return target.as_uri()


def _s3_path(layer: str, dataset: str, config: dict) -> str:
    """Construye la ruta fisica S3 (``s3://``) de un dataset.

    Args:
        layer: Capa medallion.
        dataset: Nombre del dataset.
        config: Configuracion cargada de ``paths.yml``.

    Returns:
        str: URI ``s3://`` al archivo parquet.
    """
    s3_cfg = config.get("s3", {})
    env = s3_cfg.get("bucket_env")
    bucket = (os.environ.get(env) if env else None) or s3_cfg.get("bucket")
    if not bucket:
        raise S3UnavailableError(
            f"Esquema s3 sin bucket: defina la variable de entorno {env or 's3.bucket_env'} "
            "(o s3.bucket en conf/paths.yml)."
        )
    prefixes = s3_cfg.get("prefix_por_capa", {})
    prefix = prefixes.get(layer, layer)
    return f"s3://{bucket}/{prefix}/{dataset}.parquet"


def _schema(config: dict) -> str:
    """Esquema efectivo: la variable de entorno (``scheme_env``) manda sobre ``default_scheme``."""
    env = config.get("scheme_env")
    value = os.environ.get(env) if env else None
    return str(value or config.get("default_scheme", "local")).lower()


def resolve_uri(uri: str, paths_config: dict | None = None) -> str:
    """Resuelve una URI abstracta ``daas://`` a un destino fisico.

    Segun ``default_scheme`` de ``conf/paths.yml`` devuelve una ruta ``s3://``
    (modo AWS) o ``file://`` (modo local). Si ``default_scheme`` tiene un valor
    distinto de ``s3``/``local`` se asume ``local``.

    Args:
        uri: URI abstracta ``daas://<capa>/<dataset>``.
        paths_config: Configuracion de rutas ya cargada; si es ``None`` se lee
            de ``conf/paths.yml``.

    Returns:
        str: URI fisica (``s3://...`` o ``file://...``).

    Raises:
        ValueError: Si la URI abstracta es invalida.
    """
    config = paths_config if paths_config is not None else _load_paths_config()
    layer, dataset = _parse_abstract_uri(uri)
    if _schema(config) == "s3":
        return _s3_path(layer, dataset, config)
    return _local_path(layer, dataset, config)


def _resolve_for_io(uri: str) -> tuple[str, dict]:
    """Resuelve la URI. Con esquema s3 comprueba el acceso y, si falla, lanza ``S3NoDisponible``.

    Args:
        uri: URI abstracta ``daas://``.

    Returns:
        tuple[str, dict]: Par ``(uri_fisica, config)``.

    Raises:
        S3NoDisponible: Si el esquema es s3 y S3 no responde (sin degradar a local).
    """
    config = _load_paths_config()
    physical = resolve_uri(uri, config)
    if physical.startswith("s3://"):
        try:
            import s3fs

            s3fs.S3FileSystem().exists(physical)  # fuerza la resolucion de credenciales
        except Exception as error:  # noqa: BLE001
            raise S3UnavailableError(f"S3 no disponible para {uri} ({physical}): {error}") from error
    return physical, config


def _file_uri_to_path(uri_physical: str) -> Path:
    """Convierte una URI ``file://`` en un ``Path`` del sistema de archivos.

    Args:
        uri_physical: URI ``file://`` absoluta.

    Returns:
        Path: Ruta local correspondiente.
    """
    parsed = urlparse(uri_physical)
    # ``Path.as_uri`` codifica como ``%XX`` los caracteres no seguros (p.ej. el
    # espacio en "Proyectos Pragma"); hay que decodificar para obtener la ruta
    # real del sistema de archivos. ``unquote`` es no-op en rutas sin escapes.
    return Path(unquote(parsed.path))


def write_table(df: pd.DataFrame, uri: str) -> str:
    """Escribe ``df`` como parquet (pyarrow) en la URI abstracta ``daas://``.

    En modo local crea el directorio padre y escribe el archivo. En modo S3
    delega en pandas/s3fs; si S3 no esta disponible, lanza ``S3NoDisponible``.

    Args:
        df: DataFrame a persistir.
        uri: URI abstracta ``daas://<capa>/<dataset>``.

    Returns:
        str: Ruta fisica escrita (``s3://...`` o ``file://...``).
    """
    physical, _ = _resolve_for_io(uri)
    if physical.startswith("file://"):
        destination = _file_uri_to_path(physical)
        destination.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(destination, engine="pyarrow")
    else:
        df.to_parquet(physical, engine="pyarrow")
    return physical


def read_table(uri: str) -> pd.DataFrame:
    """Lee una tabla parquet (pyarrow) desde una URI abstracta ``daas://``.

    En modo S3 usa s3fs/pyarrow; si S3 falla, lanza ``S3NoDisponible``.

    Args:
        uri: URI abstracta ``daas://<capa>/<dataset>``.

    Returns:
        pd.DataFrame: Tabla leida.
    """
    physical, _ = _resolve_for_io(uri)
    if physical.startswith("file://"):
        origin = _file_uri_to_path(physical)
        return pd.read_parquet(origin, engine="pyarrow")
    return pd.read_parquet(physical, engine="pyarrow")


def exists(uri: str) -> bool:
    """Indica si el objeto/archivo resuelto desde la URI abstracta existe.

    En modo S3, si S3 no esta disponible, lanza ``S3NoDisponible``.

    Args:
        uri: URI abstracta ``daas://<capa>/<dataset>``.

    Returns:
        bool: ``True`` si el destino fisico existe.
    """
    physical, _ = _resolve_for_io(uri)
    if physical.startswith("file://"):
        return _file_uri_to_path(physical).is_file()
    # Modo S3 efectivo: `_resolve_for_io` ya verifico el acceso; un fallo aqui tampoco se oculta.
    try:
        import s3fs

        return bool(s3fs.S3FileSystem().exists(physical))
    except Exception as error:  # noqa: BLE001
        raise S3UnavailableError(f"S3 no disponible para {uri} ({physical}): {error}") from error
