r"""Utilidades de MLflow 3.17.1 para el lab: experimentos, runs padre/hijo, metricas del arnes, datasets y modelos.

Store: metadatos en sqlite y artefactos en disco local, ambos FUERA de Google Drive (la carpeta ALX sincroniza):

- backend:    ``sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db``
- artefactos: ``file:///Users/alexanderpelaez/.mlflow/poc-daas/artifacts/<slug del experimento>``

Gotcha: con backend sqlite y sin ``artifact_location`` explicito, MLflow guarda los artefactos en ``./mlruns``
relativo al directorio de trabajo (caeria en Drive si se ejecuta desde ALX). Por eso `experimento` SIEMPRE crea
con ``artifact_location`` explicito y los scripts se ejecutan con ``cwd=/tmp`` y ``PYTHONDONTWRITEBYTECODE=1``.
El experimento ``Default`` (id 0) que MLflow crea solo no se usa nunca.

Uso tipico (p. ej. desde FEAT-004 para registrar SARIMA)::

    from lab.evaluation import harness
    from lab.tracking import mlflow_tracking as mt

    mt.configurar()
    mt.experimento("poc-daas/sarima-referencia", descripcion="SARIMA por serie como referencia")
    with mt.run_padre("sarima m1 seleccion", tags={"dataset": "m1", "modelo": "sarima", "particion": "seleccion"}):
        mt.registrar_dataset(wide, nombre="m1", contexto="training", fuente="s3://.../processed/m1_atm_dispensador")
        for origen in origenes:
            with mt.run_hijo(f"origen {origen.date()}", tags={"origen": str(origen.date())}):
                evaluado = ...  # mismo formato que harness.evaluate_origin
                mt.registrar_metricas_celdas(harness.cell_metrics(evaluado, conf))

Ver la UI (solo documentado; no se inicia ningun servidor desde el codigo)::

    mlflow ui --backend-store-uri sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db \
        --default-artifact-root file:///Users/alexanderpelaez/.mlflow/poc-daas/artifacts --port 5000

Escribir a sqlite solo desde un proceso (no desde workers de joblib): los workers devuelven resultados y el
proceso principal los registra.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.metadata
import math
import os
import re
import tempfile
import warnings
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import mlflow
import mlflow.data
import mlflow.pyfunc
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.entities import Metric, Param, RunTag
from mlflow.models import infer_signature

#: Backend de metadatos (sqlite local fuera de Drive).
TRACKING_URI_POR_DEFECTO = "sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db"
#: Raiz de artefactos; cada experimento usa ``RAIZ_ARTEFACTOS/<slug>``.
RAIZ_ARTEFACTOS = Path("/Users/alexanderpelaez/.mlflow/poc-daas/artifacts")
#: Contrato de evaluacion; su hash corto va en el tag ``conf_hash`` (mismo calculo que harness.py).
CONF_EVALUACION = Path(__file__).resolve().parents[1] / "conf" / "evaluacion.yml"
#: Origen del codigo que se registra en el tag ``fuente_codigo``.
FUENTE_CODIGO = "ALX (copia de repo-santiago 08a93bc)"
#: Paquetes cuyas versiones del venv se fijan en los modelos pyfunc.
PAQUETES_MODELO = ("mlflow", "cloudpickle", "pandas", "numpy", "scipy", "scikit-learn", "statsmodels", "pyyaml",
                   "holidays", "pyarrow")

_NO_PERMITIDO = re.compile(r"[^A-Za-z0-9_\-./ ]")
_MAX_METRICAS_LOTE = 1000
_MAX_PARAMS_TAGS_LOTE = 100
_MAX_PARAM = 6000
_MAX_TAG = 8000


# --------------------------------------------------------------------------- #
# Configuracion y experimentos                                                 #
# --------------------------------------------------------------------------- #
def configurar(uri: str | None = None) -> str:
    """Apunta tracking y registry al store local y crea la raiz de artefactos.

    Args:
        uri: URI del backend; por defecto `TRACKING_URI_POR_DEFECTO`. Tambien acepta un servidor
            (``http://...``) o el ARN de un tracking server de SageMaker (requiere el plugin ``sagemaker-mlflow``).

    Returns:
        La URI configurada.

    Example:
        >>> mt.configurar()
        'sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db'
    """
    uri = uri or TRACKING_URI_POR_DEFECTO
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    if uri.startswith("sqlite:///"):
        Path(uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    RAIZ_ARTEFACTOS.mkdir(parents=True, exist_ok=True)
    if "GoogleDrive" in str(Path.cwd()) or "CloudStorage" in str(Path.cwd()):
        warnings.warn(
            f"El directorio de trabajo ({Path.cwd()}) esta en Google Drive: ejecuta con cwd=/tmp para no crear "
            "mlruns/ ni caches dentro de la carpeta sincronizada.",
            stacklevel=2,
        )
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    return uri


def slug(nombre: str) -> str:
    """Nombre de carpeta seguro para un experimento (``poc-daas/x`` -> ``poc-daas-x``)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", nombre).strip("-").lower()


def experimento(nombre: str, descripcion: str = "", tags: dict[str, Any] | None = None) -> str:
    """Crea (con ``artifact_location`` explicito) o reutiliza un experimento y lo deja activo.

    Args:
        nombre: Nombre del experimento, p. ej. ``poc-daas/lab-santiago-historico``.
        descripcion: Texto de la nota del experimento (tag ``mlflow.note.content``).
        tags: Tags adicionales del experimento.

    Returns:
        El ``experiment_id``.

    Example:
        >>> eid = mt.experimento("poc-daas/demo", descripcion="prueba")
    """
    client = MlflowClient()
    existente = client.get_experiment_by_name(nombre)
    destino = (RAIZ_ARTEFACTOS / slug(nombre)).as_uri()
    if existente is None:
        experiment_id = client.create_experiment(nombre, artifact_location=destino)
    else:
        experiment_id = existente.experiment_id
        if existente.lifecycle_stage == "deleted":
            client.restore_experiment(experiment_id)
        if not existente.artifact_location.startswith(RAIZ_ARTEFACTOS.as_uri()):
            warnings.warn(
                f"El experimento {nombre!r} ya existia con artifact_location={existente.artifact_location}; "
                f"no es {destino}.",
                stacklevel=2,
            )
    mlflow.set_experiment(experiment_id=experiment_id)
    etiquetas = {"proyecto": "poc-daas", **(tags or {})}
    if descripcion:
        etiquetas["mlflow.note.content"] = descripcion
    mlflow.set_experiment_tags(etiquetas)
    return experiment_id


# --------------------------------------------------------------------------- #
# Runs                                                                         #
# --------------------------------------------------------------------------- #
def conf_hash(ruta: Path | None = None) -> str:
    """``sha256[:10]`` del contrato de evaluacion, igual que ``harness.run_evaluation`` (harness.py:247)."""
    return hashlib.sha256((ruta or CONF_EVALUACION).read_bytes()).hexdigest()[:10]


def tags_estandar(tags: dict[str, Any] | None = None) -> dict[str, str]:
    """Tags comunes de todo run: proyecto, conf_hash y fuente_codigo, mas los dados (dataset, modelo, ...).

    Las claves esperadas en `tags` son ``dataset``, ``modelo``, ``particion``, ``ciclo`` y ``datos``; las que
    vienen en None se omiten.
    """
    base = {"proyecto": "poc-daas", "conf_hash": conf_hash(), "fuente_codigo": FUENTE_CODIGO}
    base.update({k: v for k, v in (tags or {}).items() if v is not None})
    return {k: _texto(v, _MAX_TAG) for k, v in base.items()}


@contextlib.contextmanager
def run_padre(
    nombre: str, tags: dict[str, Any] | None = None, params: dict[str, Any] | None = None, **kwargs: Any
) -> Iterator[mlflow.ActiveRun]:
    """Run de primer nivel en el experimento activo, con los tags estandar y los `params` dados.

    Args:
        nombre: ``mlflow.runName``.
        tags: Tags del run (``dataset``, ``modelo``, ``particion``, ``ciclo``, ``datos``...).
        params: Parametros (se convierten a texto).
        **kwargs: Se pasan a ``mlflow.start_run`` (p. ej. ``log_system_metrics=True``, ``description``).

    Yields:
        El ``ActiveRun``.
    """
    with mlflow.start_run(run_name=nombre, tags=tags_estandar(tags), **kwargs) as run:
        if params:
            mlflow.log_params({k: _texto(v, _MAX_PARAM) for k, v in params.items()})
        yield run


@contextlib.contextmanager
def run_hijo(
    nombre: str, tags: dict[str, Any] | None = None, params: dict[str, Any] | None = None, **kwargs: Any
) -> Iterator[mlflow.ActiveRun]:
    """Run anidado (``nested=True``) bajo el run activo; MLflow pone el tag ``mlflow.parentRunId``.

    Args:
        nombre: ``mlflow.runName``.
        tags: Tags del run hijo (p. ej. ``origen``).
        params: Parametros del hijo.
        **kwargs: Se pasan a ``mlflow.start_run``.

    Yields:
        El ``ActiveRun`` hijo.
    """
    with mlflow.start_run(run_name=nombre, nested=True, tags=tags_estandar(tags), **kwargs) as run:
        if params:
            mlflow.log_params({k: _texto(v, _MAX_PARAM) for k, v in params.items()})
        yield run


# --------------------------------------------------------------------------- #
# Metricas                                                                     #
# --------------------------------------------------------------------------- #
def sanear(nombre: str) -> str:
    """Deja solo caracteres validos para claves de MLflow (``[A-Za-z0-9_.-/ ]``), maximo 250."""
    return _NO_PERMITIDO.sub("_", str(nombre))[:250]


def clave_metrica(fila: dict, metrica: str = "wape") -> str:
    """Clave de una celda de ``harness.cell_metrics``: ``<metrica>__<bloque>__<ciudad>__<universo>``.

    Example:
        >>> clave_metrica({"bloque": "total", "ciudad": "CALI", "universo": "principal"})
        'wape__total__CALI__principal'
    """
    return sanear(f"{metrica}__{fila['bloque']}__{fila['ciudad']}__{fila['universo']}")


def metricas_celdas(filas: Iterable[dict]) -> dict[str, float]:
    """Convierte filas de ``harness.cell_metrics`` en un dict ``clave -> valor`` (wape, mae, bias y n)."""
    salida = {}
    for fila in filas:
        for metrica in ("wape", "mae", "bias", "n"):
            if metrica in fila and fila[metrica] is not None:
                salida[clave_metrica(fila, metrica)] = float(fila[metrica])
    return salida


def registrar_lote(
    run_id: str,
    metricas: dict[str, float] | None = None,
    params: dict[str, Any] | None = None,
    tags: dict[str, Any] | None = None,
    step: int | None = None,
    timestamp: int | None = None,
    metricas_lista: Sequence[Metric] = (),
) -> int:
    """Registra metricas, params y tags con ``MlflowClient.log_batch`` respetando los limites por lote.

    Args:
        run_id: Run destino.
        metricas: ``clave -> valor`` (los None se omiten; NaN se conserva).
        params: Parametros (se convierten a texto).
        tags: Tags (se convierten a texto).
        step: Paso de las metricas (por defecto 0).
        timestamp: Milisegundos epoch de las metricas (por defecto ahora).
        metricas_lista: Metricas ya construidas (con su propio step/timestamp).

    Returns:
        Numero de metricas registradas.
    """
    ts = timestamp if timestamp is not None else _ahora_ms()
    lista = [
        Metric(sanear(k), float(v), ts, int(step or 0)) for k, v in (metricas or {}).items() if v is not None
    ] + list(metricas_lista)
    otros = [Param(sanear(k), _texto(v, _MAX_PARAM)) for k, v in (params or {}).items()]
    otros += [RunTag(k, _texto(v, _MAX_TAG)) for k, v in (tags or {}).items()]
    client = MlflowClient()
    for i in range(0, len(lista), _MAX_METRICAS_LOTE):
        client.log_batch(run_id, metrics=lista[i : i + _MAX_METRICAS_LOTE])
    for i in range(0, len(otros), _MAX_PARAMS_TAGS_LOTE):
        trozo = otros[i : i + _MAX_PARAMS_TAGS_LOTE]
        client.log_batch(
            run_id,
            params=[x for x in trozo if isinstance(x, Param)],
            tags=[x for x in trozo if isinstance(x, RunTag)],
        )
    return len(lista)


def registrar_metricas_celdas(
    filas: Iterable[dict], step: int | None = None, run_id: str | None = None, timestamp: int | None = None
) -> dict[str, float]:
    """Registra las celdas de ``harness.cell_metrics`` en un solo ``log_batch``.

    Args:
        filas: Filas con bloque, ciudad, universo, n, wape, mae y bias.
        step: Paso (p. ej. indice ordinal del origen); por defecto 0.
        run_id: Run destino; por defecto el run activo.
        timestamp: Milisegundos epoch (p. ej. la fecha del origen).

    Returns:
        El dict de metricas registrado.

    Example:
        >>> mt.registrar_metricas_celdas(harness.cell_metrics(evaluado, conf))
        {'wape__total__total__principal': 0.47, 'mae__total__total__principal': 4.1e7, ...}
    """
    metricas = metricas_celdas(filas)
    registrar_lote(run_id or _run_activo(), metricas, step=step, timestamp=timestamp)
    return metricas


# --------------------------------------------------------------------------- #
# Datasets y artefactos                                                        #
# --------------------------------------------------------------------------- #
def huella(df: pd.DataFrame) -> str:
    """Digest estable del contenido (indice incluido): ``sha256`` de ``pd.util.hash_pandas_object``, 16 hex."""
    hashes = pd.util.hash_pandas_object(df, index=True).to_numpy()
    columnas = "|".join(map(str, df.columns)).encode()
    return hashlib.sha256(hashes.tobytes() + columnas).hexdigest()[:16]


def resumen_matriz(wide: pd.DataFrame) -> pd.DataFrame:
    """Resumen por entidad de una matriz fecha x entidad (dias con dato, rango, total, media, fraccion NaN)."""
    con_dato = wide.notna()
    return pd.DataFrame(
        {
            "entidad": wide.columns.astype(str),
            "dias_con_dato": con_dato.sum().to_numpy(),
            "primera_fecha": [wide.index[c.to_numpy()].min() if c.any() else pd.NaT for _, c in con_dato.items()],
            "ultima_fecha": [wide.index[c.to_numpy()].max() if c.any() else pd.NaT for _, c in con_dato.items()],
            "total": wide.sum(min_count=1).to_numpy(dtype=float),
            "media": wide.mean().to_numpy(dtype=float),
            "frac_nan": (1.0 - con_dato.mean()).to_numpy(dtype=float),
        }
    )


def registrar_dataset(
    wide: pd.DataFrame,
    nombre: str,
    contexto: str = "training",
    fuente: str | None = None,
    max_columnas: int = 60,
) -> mlflow.data.pandas_dataset.PandasDataset:
    """Registra la matriz fecha x entidad como input del run activo (``mlflow.data.from_pandas`` + ``log_input``).

    Si la matriz tiene mas de `max_columnas` entidades se registra un resumen por entidad (`resumen_matriz`) para
    no inflar el esquema; el ``digest`` siempre es la `huella` de la matriz completa, asi dos runs con los mismos
    datos comparten digest.

    Args:
        wide: Matriz fecha x entidad (NaN = sin dato).
        nombre: Nombre del dataset (p. ej. ``m1``).
        contexto: ``training``, ``evaluation``...
        fuente: Origen de los datos (p. ej. ruta S3).
        max_columnas: Umbral para registrar la matriz o su resumen.

    Returns:
        El ``PandasDataset`` registrado.
    """
    if wide.shape[1] <= max_columnas:
        datos, forma = wide.rename_axis(index="fecha").reset_index(), "matriz"
        datos.columns = datos.columns.astype(str)
    else:
        datos, forma = resumen_matriz(wide), "resumen_por_entidad"
    dataset = mlflow.data.from_pandas(datos, source=fuente, name=nombre, digest=huella(wide))
    indice = pd.DatetimeIndex(wide.index)
    mlflow.log_input(
        dataset,
        context=contexto,
        tags={
            "forma": forma,
            "n_fechas": str(wide.shape[0]),
            "n_entidades": str(wide.shape[1]),
            "desde": str(indice.min().date()) if len(indice) else "",
            "hasta": str(indice.max().date()) if len(indice) else "",
        },
    )
    return dataset


def registrar_tabla(
    df: pd.DataFrame, nombre_archivo: str, run_id: str | None = None, artifact_path: str | None = None
) -> str:
    """Escribe `df` en un temporal FUERA de Drive (parquet o csv segun la extension) y lo sube como artefacto.

    Args:
        df: Tabla a guardar.
        nombre_archivo: ``*.parquet`` o ``*.csv``.
        run_id: Run destino; por defecto el run activo.
        artifact_path: Subcarpeta dentro de los artefactos del run.

    Returns:
        La ruta relativa del artefacto.
    """
    destino = run_id or _run_activo()
    with tempfile.TemporaryDirectory(prefix="poc-daas-mlflow-") as tmp:
        ruta = Path(tmp) / nombre_archivo
        if ruta.suffix == ".csv":
            df.to_csv(ruta, index=False)
        else:
            df.to_parquet(ruta, index=False)
        MlflowClient().log_artifact(destino, str(ruta), artifact_path)
    return f"{artifact_path}/{nombre_archivo}" if artifact_path else nombre_archivo


# --------------------------------------------------------------------------- #
# Modelo pyfunc de panel                                                       #
# --------------------------------------------------------------------------- #
def a_formato_largo(wide: pd.DataFrame) -> pd.DataFrame:
    """Matriz fecha x entidad -> formato largo ``fecha, entidad, y`` (conserva los NaN: rejilla densa)."""
    largo = wide.rename_axis(index="fecha", columns="entidad").stack(future_stack=True).rename("y").reset_index()
    largo["fecha"] = pd.to_datetime(largo["fecha"])
    largo["entidad"] = largo["entidad"].astype(str)
    largo["y"] = largo["y"].astype(float)
    return largo


def a_matriz(model_input: pd.DataFrame) -> pd.DataFrame:
    """Formato largo ``fecha, entidad, y`` -> matriz fecha x entidad diaria densa (dias faltantes = NaN)."""
    largo = model_input.assign(fecha=pd.to_datetime(model_input["fecha"]), entidad=model_input["entidad"].astype(str))
    # sum(min_count=1): una entidad-dia sin ningun valor queda NaN, nunca 0.
    wide = largo.groupby(["fecha", "entidad"])["y"].sum(min_count=1).unstack("entidad")
    wide = wide.asfreq("D")
    wide.columns = wide.columns.astype(str)
    wide.columns.name = None
    return wide.astype(float)


class PronosticadorPanel(mlflow.pyfunc.PythonModel):
    """Envuelve un pronosticador del lab (contrato ``forecast(history, dates)``) como modelo pyfunc.

    Formato elegido (la firma de MLflow exige columnas fijas y el numero de entidades varia):

    - entrada: DataFrame LARGO con columnas ``fecha`` (datetime), ``entidad`` (str), ``y`` (float, NaN = sin
      dato), es decir `a_formato_largo` de la matriz de historia (solo datos <= origen);
    - params: ``{"horizonte": 15}``;
    - salida: DataFrame ANCHO fecha x entidad con los ``horizonte`` dias siguientes al ultimo dia de la historia,
      recortado a >= 0 como el arnes (``harness.forecast_origin``).

    La funcion se guarda como texto ``modulo:funcion`` y se importa al cargar; los kwargs se guardan con el
    modelo. Para cargar en otro proceso, `lab` y `daas` deben ser importables (``code_paths``).
    """

    def __init__(self, funcion: str, kwargs: dict | None = None):
        """Guarda la referencia importable ``modulo:funcion`` y sus kwargs."""
        self.funcion = funcion
        self.kwargs = dict(kwargs or {})
        self._fn = None

    def _resolver(self):
        """Importa la funcion la primera vez."""
        if self._fn is None:
            modulo, nombre = self.funcion.split(":")
            self._fn = getattr(importlib.import_module(modulo), nombre)
        return self._fn

    def load_context(self, context):
        """Resuelve la funcion al cargar el modelo (falla pronto si el codigo no es importable)."""
        self._fn = None
        self._resolver()

    def __getstate__(self):
        """No serializa la funcion resuelta (solo su referencia)."""
        estado = self.__dict__.copy()
        estado["_fn"] = None
        return estado

    def predict(self, context, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Pronostico fecha x entidad para los ``params['horizonte']`` dias tras el ultimo dia de la historia."""
        horizonte = int((params or {}).get("horizonte", 15))
        historia = a_matriz(model_input) if {"fecha", "entidad", "y"} <= set(model_input.columns) else model_input
        historia = historia.dropna(axis=1, how="all")
        origen = historia.index.max()
        fechas = pd.date_range(origen + pd.Timedelta(days=1), periods=horizonte, freq="D")
        return self._resolver()(historia, fechas, **self.kwargs).clip(lower=0.0)


def requisitos_venv(paquetes: Iterable[str] = PAQUETES_MODELO) -> list[str]:
    """``paquete==version`` instalados en el venv (los ausentes se omiten)."""
    salida = []
    for paquete in paquetes:
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            salida.append(f"{paquete}=={importlib.metadata.version(paquete)}")
    return salida


def registrar_modelo_panel(
    funcion: str,
    kwargs: dict | None,
    nombre_registro: str,
    alias: str,
    ejemplo_historia: pd.DataFrame,
    code_paths: list[str] | None = None,
    horizonte: int = 15,
    clase: type[PronosticadorPanel] = PronosticadorPanel,
    artifacts: dict[str, str] | None = None,
    params_extra: dict[str, Any] | None = None,
) -> mlflow.models.model.ModelInfo:
    """Registra un pronosticador como pyfunc (LoggedModel), lo versiona en el Model Registry y le pone alias.

    Args:
        funcion: ``modulo:funcion`` importable, p. ej. ``lab.forecasting.registry:mean_by_weekday_4w``.
        kwargs: Argumentos fijos de la funcion.
        nombre_registro: Nombre del modelo registrado (p. ej. ``poc-daas-m1-referencia``).
        alias: Alias de la version (p. ej. ``referencia``, ``champion``, ``challenger``).
        ejemplo_historia: Matriz fecha x entidad pequena para la firma y el ``input_example``.
        code_paths: Carpetas a empaquetar para cargar en otro proceso, p. ej.
            ``[f"{ALX}/lab", f"{ALX}/pipeline/src/daas"]``. None = solo carga en este entorno.
        horizonte: Valor por defecto del parametro ``horizonte``.
        clase: Subclase de `PronosticadorPanel` a registrar (p. ej. una que lee artefactos en ``load_context``).
        artifacts: Archivos locales que viajan con el modelo (``context.artifacts`` al cargar).
        params_extra: Parametros adicionales de la firma con su valor por defecto.

    Returns:
        El ``ModelInfo`` (``registered_model_version`` y ``model_uri`` incluidos).

    Example:
        >>> info = mt.registrar_modelo_panel("lab.forecasting.registry:mean_by_weekday_4w", {}, "poc-daas-m1-ref",
        ...                                  "referencia", wide.iloc[-60:, :3])
        >>> modelo = mlflow.pyfunc.load_model("models:/poc-daas-m1-ref@referencia")
        >>> modelo.predict(mt.a_formato_largo(historia), params={"horizonte": 15})
    """
    modelo = clase(funcion, kwargs)
    if artifacts and hasattr(modelo, "cargar_contexto"):
        modelo.cargar_contexto(artifacts)  # para calcular la salida de la firma con los mismos datos
    entrada = a_formato_largo(ejemplo_historia)
    params_firma = {"horizonte": horizonte, **(params_extra or {})}
    salida = modelo.predict(None, entrada, params_firma)
    firma = infer_signature(entrada, salida.reset_index(drop=True), params=params_firma)
    info = mlflow.pyfunc.log_model(
        name=slug(nombre_registro),
        python_model=modelo,
        artifacts=artifacts,
        signature=firma,
        input_example=(entrada, params_firma),
        pip_requirements=requisitos_venv(),
        code_paths=code_paths,
        registered_model_name=nombre_registro,
        params={"funcion": funcion, **{k: _texto(v, _MAX_PARAM) for k, v in (kwargs or {}).items()}},
        tags={"proyecto": "poc-daas", "formato_entrada": "largo fecha,entidad,y", "formato_salida": "fecha x entidad"},
    )
    MlflowClient().set_registered_model_alias(nombre_registro, alias, str(info.registered_model_version))
    return info


# --------------------------------------------------------------------------- #
# Consulta                                                                     #
# --------------------------------------------------------------------------- #
def buscar_runs(nombre_experimento: str, filtro: str = "", **kwargs: Any) -> pd.DataFrame:
    """``mlflow.search_runs`` por nombre de experimento.

    Args:
        nombre_experimento: Nombre exacto del experimento.
        filtro: ``filter_string`` de MLflow, p. ej. ``"tags.dataset = 'm1' and metrics.wape__total__total__principal
            < 0.35"`` (sin OR; claves con caracteres especiales entre backticks).
        **kwargs: Se pasan a ``mlflow.search_runs`` (``order_by``, ``max_results``...).

    Returns:
        DataFrame con una fila por run (columnas ``metrics.*``, ``params.*``, ``tags.*``).
    """
    return mlflow.search_runs(experiment_names=[nombre_experimento], filter_string=filtro, **kwargs)


# --------------------------------------------------------------------------- #
# Internos                                                                     #
# --------------------------------------------------------------------------- #
def _texto(valor: Any, limite: int) -> str:
    """Valor como texto recortado al limite de MLflow."""
    if isinstance(valor, float) and math.isnan(valor):
        return "nan"
    if isinstance(valor, np.generic):
        valor = valor.item()
    return str(valor)[:limite]


def _ahora_ms() -> int:
    """Milisegundos epoch actuales."""
    return int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)


def ms_epoch(fecha: Any) -> int:
    """Milisegundos epoch de una fecha (medianoche UTC)."""
    return int(pd.Timestamp(fecha).tz_localize(None).normalize().value // 1_000_000)


def _run_activo() -> str:
    """``run_id`` del run activo o error claro."""
    run = mlflow.active_run()
    if run is None:
        raise RuntimeError("No hay run activo: usa run_padre/run_hijo o pasa run_id.")
    return run.info.run_id
