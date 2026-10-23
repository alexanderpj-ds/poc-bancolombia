"""Carga de la configuracion M3 Sucursales (`conf/model_m3.yml`) (U3).

Reutiliza el patron de localizacion de `conf/` de `daas.modules.atm_m1_m2.config`:
usa la variable de entorno ``DAAS_CONF`` si esta definida y, en su defecto, cae
a ``<raiz-del-paquete>/conf``. Si una clave falta en el archivo, se aplica el
default documentado en `DEFAULT_CONFIG` y se registra un ``logging.warning``
(NUNCA se inventa un dato que el banco no entrego; los defaults reproducen los
supuestos ya documentados en SUP-M3-01 / SUP-M3-02).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Nombre del archivo de configuracion dentro de ``conf/``.
_CONFIG_FILE = "model_m3.yml"

#: Configuracion por defecto documentada (SUP-M3-01 / SUP-M3-02).
#: Se aplica clave a clave cuando el archivo no la provee.
DEFAULT_CONFIG: dict[str, Any] = {
    "horizonte": {"inicio": "2026-09-01", "fin": "2026-09-15"},
    "backtest": {"dias": 15},
    "objetivos": ["entradas", "salidas"],
    "m3": {"umbral_agotamiento": 0.08},
    # Politica diferenciada por sucursal (V3 `dif_ocioso`); ver `modules.branches_m3.policy`.
    "politica": {
        "activa": True,
        "historia_dias": 180,
        "min_obs": 30,
        "reserva_max": 0.5,
        "k_reserva": 1.0,
        "dias_cobertura": 3,
        "dias_techo": 6,
        "usa_pronostico": True,
        "historia_corta_regla_vigente": True,
    },
    "saldo": {"cap_superior": "cupo_max_suc"},
    "forecaster": {"min_obs": 30, "fallback": "naive_estacional_7"},
}


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``).

    Este archivo esta en ``<raiz>/src/daas/modules/branches_m3/config.py``; la raiz del
    paquete es cuatro niveles por encima del directorio de este modulo.

    Returns:
        Path: Ruta absoluta a la raiz del proyecto.
    """
    return Path(__file__).resolve().parents[4]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o fallback).

    Returns:
        Path: Ruta al directorio ``conf/``.
    """
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def _combine_with_default(loaded: dict, default: dict, prefix: str = "") -> dict:
    """Rellena recursivamente las claves ausentes de ``cargada`` con ``defecto``.

    Para cada clave del default que no exista en lo cargado se aplica el valor
    por defecto y se registra un ``warning``. Las sub-dicts se combinan de forma
    recursiva; los valores presentes en ``cargada`` siempre prevalecen.

    Args:
        loaded: Configuracion leida del archivo (puede estar incompleta).
        default: Configuracion por defecto documentada.
        prefix: Prefijo de la clave para el mensaje de log (uso interno).

    Returns:
        dict: Configuracion combinada (defaults aplicados donde faltaba).
    """
    out = dict(loaded)
    for key, value_default in default.items():
        file_path = f"{prefix}{key}"
        if key not in out:
            logger.warning(
                "model_m3.yml: falta la clave '%s'; se aplica el default %r.",
                file_path,
                value_default,
            )
            out[key] = value_default
        elif isinstance(value_default, dict) and isinstance(out[key], dict):
            out[key] = _combine_with_default(out[key], value_default, prefix=f"{file_path}.")
    return out


def load_config(conf_dir: Path | None = None) -> dict[str, Any]:
    """Carga ``conf/model_m3.yml`` aplicando defaults documentados.

    Si el archivo no existe se usa integramente ``DEFAULT_CONFIG`` (con
    ``warning``); si existe pero le faltan claves, cada clave ausente toma su
    default y se anota.

    Args:
        conf_dir: Directorio ``conf/`` a usar; si es ``None`` se resuelve con
            ``DAAS_CONF`` o la raiz del paquete.

    Returns:
        dict[str, Any]: Configuracion completa (archivo + defaults).
    """
    directory = conf_dir if conf_dir is not None else _conf_dir()
    file_path = directory / _CONFIG_FILE
    if not file_path.is_file():
        logger.warning("No se encontro %s; se usa la configuracion por defecto completa.", file_path)
        return _combine_with_default({}, DEFAULT_CONFIG)
    with file_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return _combine_with_default(loaded, DEFAULT_CONFIG)
