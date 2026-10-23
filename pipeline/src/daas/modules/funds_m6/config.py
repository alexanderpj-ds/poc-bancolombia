"""Carga de la configuracion M6 Fondos (`conf/model_u6.yml`) (U6).

Reutiliza el patron de localizacion de `conf/` de `daas.modules.branches_m3.config`: usa la
variable de entorno ``DAAS_CONF`` si esta definida y, en su defecto, cae a
``<raiz-del-paquete>/conf``. Si una clave falta en el archivo, se aplica el
default documentado en `DEFAULT_CONFIG` y se registra un ``logging.warning``
(NUNCA se inventa un dato que el banco no entrego; los defaults reproducen los
supuestos ya documentados SUP-07..SUP-14).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Nombre del archivo de configuracion dentro de ``conf/``.
_CONFIG_FILE = "model_u6.yml"

#: Configuracion por defecto documentada (SUP-07..SUP-14, D-* del diseno).
#: Se aplica clave a clave cuando el archivo no la provee.
DEFAULT_CONFIG: dict[str, Any] = {
    "horizonte": {"inicio": "2026-09-01", "fin": "2026-09-15"},
    "fuentes": {
        "disponibles": "processed/m6_fondos",
        "predicciones": "output/api/predicciones",
        "metricas": "output/api/metricas",
    },
    "denominaciones": [100000, 50000, 20000, 10000, 5000, 2000],
    "saldo_inicial": {"corte": "2026-08-31", "faltante_a_cero": True},
    "mezcla_denominacion": {
        "metodo": "historico_valor",
        "ventana_dias": 180,
        "fallback": "uniforme",
    },
    "efecto_m1_m5": {
        "ingresos": {
            "m2": ["cash_in"],
            "m3": ["entradas"],
            "m4": ["ingreso_efectivo_cbr"],
            "m5": ["ingreso_efectivo_clientes"],
        },
        "egresos": {
            "m1": ["pagado"],
            "m2": ["pagado"],
            "m3": ["salidas"],
        },
        "excluir_sin_fondo": True,
    },
    "correccion_total": {
        "activo": False,
        "metodo": "movil",
        "bloque": "sesgo_red",
        "bloque_origen": "sesgo_red_origen",
        "ventana_origenes": 3,
        "min_origenes": 1,
        "horizonte_evaluacion_dias": 15,
        "modelos": ["m5"],
        "factor_min": 0.67,
        "factor_max": 1.5,
    },
    "minmax": {
        "metodo": "percentiles",
        "p_min": 0.10,
        "p_max": 0.90,
        "ventana_dias": 180,
        "fallback_minimo": 0.0,
        "k_fallback_maximo": 3.0,
    },
    "operaciones": {
        "inferir_de": ["ventas", "intercambios", "banrep"],
        "banrep_desde_anexo_e": True,
        "traslado": {
            "mismo_ciudad_distinta_tdv_costo_cero": True,
            "preferir_costo_cero": True,
            "nan_al_final": True,
            "tarifa_por": "origen",
            "acotar_monto_a_excedente_origen": True,
            "permitir_parcial": True,
            "max_candidatos": 0,
        },
        "banrep": {"ciudades_habilitadas": ["CALI"]},
        "intercambio": {
            "emitir_recomendacion": True,
            "cambio_denominacion_hereda": True,
        },
    },
    "costos": {
        "ambito": "Fondos",
        "almacenamiento": {
            "habilitado": True,
            "concepto": "Costo almacenamiento por día (por cada 10Mil Millones)",
            "unidad_cop": 10_000_000_000,
        },
    },
    "decision": {
        "max_acciones_por_necesidad": 1,
        "redondeo": "denominacion",
        "traslado_mismo_dia": True,
        "dias_no_habiles_sin": [
            "banrep_consignacion",
            "banrep_retiro",
            "venta",
            "intercambio",
            "cambio_denominacion",
        ],
        "conservar_excedente": True,
        "venta": {"ventana_dias": 365, "tasa_por_monto": 10000},
        "riesgo_residual": {"alto_si_fraccion_minimo_menor": 0.5, "exceso": "medio"},
    },
    "forecaster": {"min_obs": 30, "fallback": "naive_estacional_7"},
}


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``).

    Este archivo esta en ``<raiz>/src/daas/modules/funds_m6/config.py``; la raiz del
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
                "model_u6.yml: falta la clave '%s'; se aplica el default %r.",
                file_path,
                value_default,
            )
            out[key] = value_default
        elif isinstance(value_default, dict) and isinstance(out[key], dict):
            out[key] = _combine_with_default(out[key], value_default, prefix=f"{file_path}.")
    return out


def load_config(conf_dir: Path | None = None) -> dict[str, Any]:
    """Carga ``conf/model_u6.yml`` aplicando defaults documentados.

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
