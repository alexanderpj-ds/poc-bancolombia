"""Contratos de salida del subpaquete `publish`.

Regla de negocio: escribe los artefactos de API en `output/api/<nombre>.parquet`
junto con su esquema versionado `output/api/_schemas/<nombre>.json`. En esta
PoC U1/U2 (ATM) se publican los 4 contratos de M1/M2:
`predicciones`, `recomendaciones`, `alertas` y `metricas`.

`publish_contract(nombre, df)`:

- Valida `df` contra un esquema tipado por contrato (columnas + dtypes
  esperados; ver `SCHEMAS`). Falla explicito si falta una columna obligatoria.
- Agrega la procedencia `origen_dato` de cada fila (`ORIGEN_DATO_POR_CONTRATO`, SUP-24..26; ALX): PROYECTADO
  para los pronosticos de M1-M5, SIMULADO para el balance de M6 y ESTIMADO para el resto. `REAL` nunca se
  publica (el horizonte es futuro); una etiqueta fuera del conjunto o distinta de la declarada falla.
- Serializa toda columna de fecha en ISO `yyyy-mm-dd` (hecho #3).
- Emite el id de entidad enmascarado PASSTHROUGH (`cod_cajero`) aplicando el
  mapeo `conf/entity_id_map.yml`; cuando el mapa esta vacio, el id sale
  tal cual (default accionable).
- Escribe el parquet via `storage.write_table(daas://output/api/<nombre>)` y el
  esquema JSON (`columnas` + `tipos` + `version`) via `storage`.
- Devuelve la ruta fisica escrita.

Todo el I/O pasa por `daas.io.storage` (URIs abstractas `daas://`); no hay rutas
hardcodeadas (el mismo codigo corre en S3 cambiando `default_scheme`).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from daas import alx
from daas.io import storage

logger = logging.getLogger(__name__)

#: Version del esquema de los contratos (la "API spec" de datos).
SCHEMA_VERSION = "1.0.0"

#: Nombre del archivo del mapa de ids de salida.
_ENTITY_ID_MAP_FILE = "entity_id_map.yml"

#: Vocabulario de la columna `lectura` del contrato `backtest`: el real tal cual (`base`) o rellenado segun RN-08.
BASE_READING = "base"
RN08_READING = "rn08"

#: Columna de id de entidad enmascarado (passthrough).
_COL_ID = "cod_cajero"

#: Esquema tipado por contrato: columna -> dtype logico esperado.
#: Los dtypes logicos son: 'str', 'date' (ISO yyyy-mm-dd), 'float', 'int',
#: 'bool'. Las columnas listadas son OBLIGATORIAS (orden del contrato); se
#: permiten columnas extra, que se conservan pero no se tipan estrictamente.
SCHEMAS: dict[str, dict[str, str]] = {
    "predicciones": {
        "modelo": "str",
        "cod_cajero": "str",
        "fecha": "date",
        "objetivo": "str",
        "yhat": "float",
        "band_low": "float",
        "band_high": "float",
    },
    "recomendaciones": {
        "modelo": "str",
        "cod_cajero": "str",
        "accion": "str",
        "momento": "str",
        "fecha_sugerida": "date",
        "monto": "float",
        "costo": "float",
        "sin_transportadora": "bool",
        "sin_tarifa": "bool",
        # RN-03: cupo aplicable y saldo simulado antes y despues de la accion (M1-M3; NaN en M6).
        "cupo": "float",
        "saldo_antes": "float",
        "saldo_despues": "float",
    },
    "alertas": {
        "modelo": "str",
        "cod_cajero": "str",
        "fecha": "date",
        "tipo": "str",
        "severidad": "str",
        "nivel": "float",
        "limite": "float",
    },
    # Informativo: entidades con dias de red sin dato al corte, desinstaladas o no (hoja 04 del Anexo D).
    "silenciosos": {
        "modelo": "str",
        "cod_cajero": "str",
        "ultimo_dato": "date",
        "dias_red_sin_dato": "int",
        "tratamiento": "str",
    },
    # Opcional: pares y/yhat del backtest que alimentan `metricas`, para el WAPE por segmento (hoja 03).
    "backtest": {
        "modelo": "str",
        "objetivo": "str",
        "cod_cajero": "str",
        "fecha": "date",
        "y": "float",
        "yhat": "float",
        "lectura": "str",
    },
    "metricas": {
        "modelo": "str",
        "bloque": "str",
        "wape": "float",
        "mae": "float",
        "bias": "float",
        "n_obs": "int",
        "n_excluidas": "int",
        "nota": "str",
    },
}


#: Procedencia de cada fila publicada (SUP-24, SUP-25, SUP-26 de `docs/supuestos.md`; PDF SUP-15/16/17). Conjunto
#: cerrado. `REAL` existe en el vocabulario (insumos del Anexo A) pero nunca se publica en `output/api/*`: el
#: horizonte 1-15 sep 2026 es futuro respecto del corte 31-ago-2026 (SUP-26).
ORIGENES_DATO: tuple[str, ...] = ("REAL", "PROYECTADO", "SIMULADO", "ESTIMADO")
ORIGEN_DATO_COL = "origen_dato"
ORIGEN_DATO_PROHIBIDO = "REAL"

#: Procedencia por contrato. `predicciones` depende del modelo: M1-M5 pronostican (PROYECTADO) y M6 simula el
#: balance (SIMULADO). Recomendaciones y alertas son reglas sobre lo proyectado o simulado (ESTIMADO, SUP-25);
#: metricas y backtest son estadisticos o pares del ejercicio de validacion (ESTIMADO, SUP-24; el `y` del backtest
#: es historico, pero la fila es un par de evaluacion, no un dato del horizonte); silenciosos es un diagnostico
#: derivado (ESTIMADO).
ORIGEN_DATO_POR_CONTRATO: dict[str, str | dict[str, str]] = {
    "predicciones": {"m1": "PROYECTADO", "m2": "PROYECTADO", "m3": "PROYECTADO", "m4": "PROYECTADO",
                     "m5": "PROYECTADO", "m6": "SIMULADO"},
    "recomendaciones": "ESTIMADO",
    "alertas": "ESTIMADO",
    "silenciosos": "ESTIMADO",
    "backtest": "ESTIMADO",
    "metricas": "ESTIMADO",
}

# `origen_dato` es la ultima columna obligatoria de cada contrato (la agrega `asignar_origen_dato` si falta).
for _schema in SCHEMAS.values():
    _schema[ORIGEN_DATO_COL] = "str"


def origen_dato_esperado(name: str, df: pd.DataFrame) -> pd.Series:
    """Procedencia que corresponde a cada fila del contrato segun `ORIGEN_DATO_POR_CONTRATO`.

    Args:
        name: Nombre del contrato.
        df: DataFrame del contrato (para `predicciones` usa la columna `modelo`).

    Returns:
        pd.Series: Etiqueta por fila (indice de `df`).

    Raises:
        KeyError: Si el contrato no tiene procedencia declarada.
        ValueError: Si un modelo de `predicciones` no tiene procedencia declarada.
    """
    if name not in ORIGEN_DATO_POR_CONTRATO:
        raise KeyError(f"Contrato {name!r} sin procedencia declarada en ORIGEN_DATO_POR_CONTRATO.")
    regla = ORIGEN_DATO_POR_CONTRATO[name]
    if isinstance(regla, str):
        return pd.Series(regla, index=df.index, dtype=object)
    modelos = df["modelo"].astype(str).str.lower()
    esperado = modelos.map(regla)
    if esperado.isna().any():
        raise ValueError(
            f"Contrato {name!r}: modelos sin procedencia declarada {sorted(modelos[esperado.isna()].unique())}."
        )
    return esperado.astype(object)


def asignar_origen_dato(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Agrega o completa `origen_dato` y valida la procedencia de cada fila (SUP-24..26).

    Si la columna falta se crea; si existe (p. ej. el UPSERT concatena lo ya publicado con un bloque nuevo) se
    completan los nulos. Toda fila debe quedar con la etiqueta que le corresponde por contrato y modelo.

    Args:
        name: Nombre del contrato.
        df: DataFrame a publicar.

    Returns:
        pd.DataFrame: Copia con `origen_dato` completo.

    Raises:
        ValueError: Si una etiqueta esta fuera de `ORIGENES_DATO`, si alguna fila es `REAL` (SUP-26) o si una
        etiqueta no coincide con la declarada para su contrato y modelo.
    """
    out = df.copy()
    esperado = origen_dato_esperado(name, out)
    if ORIGEN_DATO_COL not in out.columns:
        out[ORIGEN_DATO_COL] = esperado
    else:
        actual = out[ORIGEN_DATO_COL].astype(object)
        out[ORIGEN_DATO_COL] = actual.where(actual.notna(), esperado)
    valores = out[ORIGEN_DATO_COL].astype(str)
    fuera = sorted(set(valores) - set(ORIGENES_DATO))
    if fuera:
        raise ValueError(f"Contrato {name!r}: origen_dato fuera del conjunto {ORIGENES_DATO}: {fuera}.")
    if (valores == ORIGEN_DATO_PROHIBIDO).any():
        raise ValueError(f"Contrato {name!r}: origen_dato REAL no se publica en output/api/* (SUP-26).")
    distinto = valores != esperado.astype(str)
    if distinto.any():
        raise ValueError(
            f"Contrato {name!r}: {int(distinto.sum())} filas con origen_dato distinto del declarado "
            f"en ORIGEN_DATO_POR_CONTRATO."
        )
    return out


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (reutiliza el patron ``DAAS_CONF``).

    Returns:
        Path: Ruta al directorio ``conf/`` (``DAAS_CONF`` o raiz del paquete).
    """
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    # <raiz>/src/daas/publish/contracts.py -> raiz tres niveles arriba.
    return Path(__file__).resolve().parents[3] / "conf"


def _load_id_map(conf_dir: Path | None = None) -> dict[Any, Any]:
    """Carga el mapa de ids de salida `conf/entity_id_map.yml`.

    Args:
        conf_dir: Directorio ``conf/`` a usar; si es ``None`` se resuelve con
            ``DAAS_CONF`` o la raiz del paquete.

    Returns:
        dict: Mapeo ``origen -> id-oficial``. Vacio (``{}``) = passthrough.
    """
    directory = conf_dir if conf_dir is not None else _conf_dir()
    file_path = directory / _ENTITY_ID_MAP_FILE
    if not file_path.is_file():
        logger.warning("No se encontro %s; se usa passthrough de ids (OD-2 default).", file_path)
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    mapping = loaded.get("mapa") or {}
    if not isinstance(mapping, dict):
        logger.warning("entity_id_map.yml: 'mapa' no es un diccionario; se ignora " "(passthrough).")
        return {}
    return mapping


def _apply_id_map(series: pd.Series, mapping: dict[Any, Any]) -> pd.Series:
    """Traduce el id de entidad con el mapa (passthrough si no esta).

    Args:
        series: Columna de ids de origen (`cod_cajero` enmascarado).
        mapping: Mapeo ``origen -> id-oficial`` (vacio = passthrough).

    Returns:
        pd.Series: Ids de salida (traducidos los que esten en el mapa; el resto
        tal cual, passthrough).
    """
    if not mapping:
        return series
    return series.map(lambda v: mapping.get(v, v))


def _serialize_date(series: pd.Series) -> pd.Series:
    """Serializa una columna de fecha en ISO `yyyy-mm-dd` (hecho #3).

    Acepta `datetime.date`, `datetime`/`Timestamp` o texto; los NaT/None salen
    como ``None``.

    Args:
        series: Columna de fechas en cualquier representacion.

    Returns:
        pd.Series: Fechas como texto ISO `yyyy-mm-dd` (o ``None`` donde falte).
    """
    dates = pd.to_datetime(series, errors="coerce")
    return dates.dt.strftime("%Y-%m-%d").where(dates.notna(), None)


def _type_column(series: pd.Series, kind: str, name: str) -> pd.Series:
    """Castea una columna al dtype logico del contrato.

    Args:
        series: Columna a tipar.
        kind: Dtype logico (`str`/`date`/`float`/`int`/`bool`).
        name: Nombre de la columna (para mensajes de error).

    Returns:
        pd.Series: Columna tipada segun el contrato.

    Raises:
        ValueError: Si el dtype logico no esta soportado.
    """
    if kind == "date":
        return _serialize_date(series)
    if kind == "str":
        return series.where(series.notna(), None).map(
            lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
        )
    if kind == "float":
        return pd.to_numeric(series, errors="coerce").astype("float64")
    if kind == "int":
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    if kind == "bool":
        return series.astype("boolean")
    raise ValueError(f"Tipo logico no soportado para la columna {name!r}: {kind!r}.")


def _validate_and_type(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Valida `df` contra el esquema del contrato y lo tipa.

    Comprueba que estan todas las columnas obligatorias del contrato, aplica el
    cast de cada una y serializa las fechas en ISO. Conserva columnas extra al
    final sin tiparlas estrictamente.

    Args:
        name: Nombre del contrato (clave de `SCHEMAS`).
        df: DataFrame a validar y tipar.

    Returns:
        pd.DataFrame: DataFrame tipado con las columnas del contrato primero.

    Raises:
        KeyError: Si el contrato no esta definido en `SCHEMAS`.
        ValueError: Si faltan columnas obligatorias del contrato.
    """
    if name not in SCHEMAS:
        raise KeyError(f"Contrato desconocido: {name!r}. Validos: {sorted(SCHEMAS)}.")
    schema = SCHEMAS[name]
    with_origin = alx.interruptor("origen_dato")  # ALX PARTE 7: apagado = contratos de Santiago (sin la columna)
    if not with_origin:
        schema = {c: k for c, k in schema.items() if c != ORIGEN_DATO_COL}
    missing = [c for c in schema if c not in df.columns and c != ORIGEN_DATO_COL]
    if missing:
        raise ValueError(f"Contrato {name!r}: faltan columnas obligatorias {missing}.")

    # Procedencia de cada fila (SUP-24..26): se agrega o completa y se valida antes de tipar.
    if with_origin:
        out = asignar_origen_dato(name, df).reset_index(drop=True)
    else:
        out = df.drop(columns=[ORIGEN_DATO_COL], errors="ignore").reset_index(drop=True)
    for column, kind in schema.items():
        out[column] = _type_column(out[column], kind, column)

    # Orden: columnas del contrato primero, extras despues (conservadas).
    extras = [c for c in out.columns if c not in schema]
    return out[list(schema.keys()) + extras]


def _write_schema(name: str, df: pd.DataFrame) -> str:
    """Escribe el esquema JSON versionado del contrato via `storage`.

    El esquema recoge las columnas y sus tipos logicos (los del contrato + los
    de las columnas extra inferidos de los dtypes de pandas) y la version.

    Args:
        name: Nombre del contrato.
        df: DataFrame ya tipado que se va a publicar.

    Returns:
        str: Ruta fisica del JSON de esquema escrito.
    """
    schema = SCHEMAS[name]
    kinds: dict[str, str] = {}
    for column in df.columns:
        if column in schema:
            kinds[column] = schema[column]
        else:
            kinds[column] = str(df[column].dtype)

    meta = {
        "contrato": name,
        "version": SCHEMA_VERSION,
        "columnas": list(df.columns),
        "tipos": kinds,
    }
    # El esquema vive junto a los parquet en output/api/_schemas/<nombre>.json;
    # se resuelve su ruta fisica reutilizando storage (daas://) para no
    # hardcodear rutas, y se escribe el JSON en esa ubicacion (local o S3).
    uri_physical = storage.resolve_uri(f"daas://output/api/_schemas/{name}")
    content = json.dumps(meta, ensure_ascii=False, indent=2)
    destination = _write_json(uri_physical, content, suffix=".json")
    return destination


def _write_json(uri_physical: str, content: str, suffix: str) -> str:
    """Escribe `contenido` como JSON en la URI fisica (local `file://` o `s3://`).

    `storage.resolve_uri` devuelve una ruta terminada en `.parquet`; aqui se
    sustituye por `sufijo` (`.json`) y se escribe el texto. Soporta ambos
    esquemas: espejo local (`file://`) via sistema de archivos, y S3 (`s3://`)
    via s3fs, coherente con la degradacion/portabilidad de `storage`.

    Args:
        uri_physical: URI fisica resuelta por `storage` (`file://...` o `s3://...`).
        content: Texto JSON a escribir.
        suffix: Extension destino (`".json"`).

    Returns:
        str: Ruta fisica escrita (`file://...` path local o `s3://...`).
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri_physical)
    if parsed.scheme == "file":
        destination = Path(unquote(parsed.path)).with_suffix(suffix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return str(destination)
    if parsed.scheme == "s3":
        # Sustituye el sufijo .parquet por .json sobre la ruta s3:// y escribe
        # via s3fs (mismo backend que usan los parquet en storage).
        s3_uri = uri_physical
        if s3_uri.endswith(".parquet"):
            s3_uri = s3_uri[: -len(".parquet")] + suffix
        fs = __import__("s3fs").S3FileSystem()
        with fs.open(s3_uri, "w", encoding="utf-8") as handle:
            handle.write(content)
        return s3_uri
    raise RuntimeError(f"Esquema de URI no soportado para _schemas: {uri_physical!r}.")


def publish_contract(
    name: str,
    df: pd.DataFrame,
    conf_dir: Path | None = None,
) -> str:
    """Publica un contrato de salida `output/api/<nombre>.parquet` + `_schema`.

    Valida `df` contra el esquema tipado del contrato (`SCHEMAS`), serializa las
    fechas en ISO `yyyy-mm-dd`, aplica el id enmascarado passthrough
    (`conf/entity_id_map.yml`) y escribe el parquet
    (`storage.write_table(daas://output/api/<nombre>)`) y su esquema JSON
    (`output/api/_schemas/<nombre>.json`). Devuelve la ruta fisica del parquet.

    Args:
        name: Nombre del contrato (`predicciones`/`recomendaciones`/
            `alertas`/`metricas`).
        df: DataFrame a publicar (debe traer las columnas del contrato).
        conf_dir: Directorio ``conf/`` para el mapa de ids (opcional; util en
            tests). Si es ``None`` se resuelve con ``DAAS_CONF``/raiz.

    Returns:
        str: Ruta fisica del parquet escrito.

    Raises:
        KeyError: Si el contrato no esta definido.
        ValueError: Si faltan columnas obligatorias del contrato.
    """
    typed = _validate_and_type(name, df)

    # Id de entidad enmascarado passthrough cuando el contrato lo lleva.
    if _COL_ID in typed.columns:
        mapping = _load_id_map(conf_dir)
        typed[_COL_ID] = _apply_id_map(typed[_COL_ID], mapping)

    physical = storage.write_table(typed, f"daas://output/api/{name}")
    _write_schema(name, typed)
    logger.info("Contrato %s publicado en %s (%d filas).", name, physical, len(typed))
    return physical


def backtest_block(
    model: str, target: str, pairs: pd.DataFrame, reading: str = BASE_READING, col_id: str = _COL_ID
) -> pd.DataFrame:
    """Arma el bloque del contrato `backtest` desde los pares que ya puntuan en `metricas`.

    No recalcula nada: recibe los pares validos (con exclusiones aplicadas y sin faltantes en `y`/`yhat`).

    Args:
        model: Clave del modelo (`m1`..`m5`).
        target: Variable objetivo del backtest.
        pairs: DataFrame con `fecha`, `y`, `yhat` y la columna de id de la entidad.
        reading: `BASE_READING` o `RN08_READING`.
        col_id: Columna de `pares` con el id de la entidad.

    Returns:
        pd.DataFrame: Columnas `modelo, objetivo, cod_cajero, fecha, y, yhat, lectura`.
    """
    out = pd.DataFrame(
        {
            "modelo": model,
            "objetivo": target,
            "cod_cajero": pairs[col_id].astype(str).to_numpy(),
            "fecha": pairs["fecha"].to_numpy(),
            "y": pairs["y"].to_numpy(),
            "yhat": pairs["yhat"].to_numpy(),
            "lectura": reading,
        }
    )
    return out.reset_index(drop=True)
