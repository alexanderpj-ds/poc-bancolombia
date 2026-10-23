"""Curado interim -> processed del subpaquete `curate`.

Regla de negocio: construye las tablas processed por modelo (m1..m6), aplica el
corte de entrenamiento (validacion V-07, corte 2026-08-31) y separa el holdout
de evaluacion (2026-09-01..2026-09-15) en tablas `_holdout`. processed es el
SSOT que consumen features y modelos.

Diseno Decisiones de diseno:
  - El corte se lee de `conf/dq_rules.yml::training_cutoff` (default
    2026-08-31). Las filas con `fecha <= corte` forman el set de entrenamiento;
    las filas con `fecha > corte` que caen en la ventana de evaluacion
    (1-15 sep) van al holdout; las filas posteriores a la ventana (p.ej.
    16-29 sep de Clientes) quedan fuera de ambos (ni entrenan ni evaluan).
  - `build_processed(modelo, df)` devuelve SOLO el set de entrenamiento (lo que
    va a `processed/<modelo>/`). Para obtener ambos lados a la vez, usar
    `split_cutoff(df)` -> `(entrenamiento, holdout)`, que es lo que consume el
    pipeline para escribir `processed/<modelo>/` y `processed/_holdout/<modelo>/`.
  - El curado NO re-filtra calidad: recibe interim ya conforme (lo rechazado
    quedo en cuarentena aguas arriba); aqui solo aplica el corte temporal.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

import pandas as pd
import yaml

#: Modelos de la PoC -> nombre de carpeta processed.
MODELS = {
    "m1": "m1_atm_dispensador",
    "m2": "m2_atm_multifuncional",
    "m3": "m3_sucursales",
    "m4": "m4_cbr",
    "m5": "m5_clientes",
    "m6": "m6_fondos",
}

#: Corte de entrenamiento por defecto (V-07).
_DEFAULT_CUTOFF = _dt.date(2026, 8, 31)
#: Ventana de evaluacion (holdout) por defecto.
_EVAL_DEFAULT = (_dt.date(2026, 9, 1), _dt.date(2026, 9, 15))


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``)."""
    return Path(__file__).resolve().parents[3]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o fallback)."""
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def _to_date(value: object) -> _dt.date:
    """Coerciona un valor (str ISO o date) a `datetime.date`."""
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value))


def _cutoff_params() -> tuple[_dt.date, tuple[_dt.date, _dt.date]]:
    """Lee corte + ventana de evaluacion de `conf/dq_rules.yml`.

    Returns:
        tuple: `(corte, (eval_inicio, eval_fin))` con defaults documentados.
    """
    file_path = _conf_dir() / "dq_rules.yml"
    cutoff = _DEFAULT_CUTOFF
    start, fin = _EVAL_DEFAULT
    if file_path.is_file():
        with file_path.open("r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        if cfg.get("corte_entrenamiento"):
            cutoff = _to_date(cfg["corte_entrenamiento"])
        window = cfg.get("ventana_evaluacion", {}) or {}
        if window.get("inicio"):
            start = _to_date(window["inicio"])
        if window.get("fin"):
            fin = _to_date(window["fin"])
    return cutoff, (start, fin)


def split_cutoff(df: pd.DataFrame, date_col: str = "fecha") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa `df` en (entrenamiento, holdout) segun el corte V-07.

    - Entrenamiento: `fecha <= corte` (2026-08-31).
    - Holdout: `corte < fecha <= fin de ventana de evaluacion` (1-15 sep).
    - Las filas posteriores a la ventana de evaluacion se descartan de ambos
      (no entrenan ni evaluan; se registran como "fuera de ventana").

    Si `df` no tiene columna de fecha, se devuelve `(df, vacio)` (p.ej. tablas
    maestras/costos sin dimension temporal).

    Args:
        df: DataFrame interim conforme (curado) del modelo.
        date_col: Columna de fecha (`datetime.date`).

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: `(entrenamiento, holdout)`.
    """
    if date_col not in df.columns:
        return df.reset_index(drop=True), df.iloc[0:0].reset_index(drop=True)

    cutoff, (eval_start, eval_fin) = _cutoff_params()
    dates = pd.to_datetime(df[date_col], errors="coerce").dt.date

    is_training = dates.map(lambda d: bool(d is not None and d <= cutoff)).fillna(False)
    is_holdout = dates.map(lambda d: bool(d is not None and cutoff < d <= eval_fin and d >= eval_start)).fillna(False)

    training = df.loc[is_training].reset_index(drop=True)
    holdout = df.loc[is_holdout].reset_index(drop=True)
    return training, holdout


def build_processed(model: str, df: pd.DataFrame) -> pd.DataFrame:
    """Construye la tabla processed (entrenamiento) de un modelo.

    Aplica el corte V-07 y devuelve SOLO el set de entrenamiento
    (`fecha <= corte`). El holdout (1-15 sep) se obtiene con `split_cutoff`; el
    pipeline lo escribe por separado en `processed/_holdout/<modelo>/`.

    Args:
        model: Clave de modelo (`m1`..`m6`).
        df: DataFrame interim conforme del modelo.

    Returns:
        pd.DataFrame: Tabla processed de entrenamiento del modelo.

    Raises:
        KeyError: Si `modelo` no es `m1`..`m6`.
    """
    if model not in MODELS:
        raise KeyError(f"Modelo desconocido: {model!r}. Validos: {sorted(MODELS)}.")
    training, _ = split_cutoff(df)
    return training
