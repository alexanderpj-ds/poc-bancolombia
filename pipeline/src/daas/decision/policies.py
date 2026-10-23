"""Politicas de provision de efectivo (comparadas en el lab: `lab/politicas.py`).

Contrato unico (el del lab, `lab/politicas.py`, que importa estas funciones):

    politica(d, posicion, yhat, cupo, lead_time) -> pedido (>= 0)

`d` es el indice del dia dentro del horizonte; `posicion` = saldo de apertura + pedidos en transito;
`yhat` es el pronostico (dias, o dias x entidades). Una politica nunca ve la demanda real. Sirve igual
para una entidad (escalares) que para muchas (vectores).

La politica es dato: cada unidad la elige por `familia` en su `conf/model_*.yml`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import partial
from typing import Any

import numpy as np


def threshold_to_capacity(d, position, yhat, capacity, lead_time, *, umbral: float) -> np.ndarray:
    """Regla original: si la posicion cae bajo `umbral x cupo`, pide hasta el cupo. No usa el pronostico."""
    return np.where(position < umbral * capacity, capacity - position, 0.0)


def forecast_threshold_to_capacity(
    d, position, yhat, capacity, lead_time, *, umbral: float, margen: float
) -> np.ndarray:
    """Regla del pliego (RN-11, RN-34) decidida con el pronostico.

    Pide hasta el cupo si la posicion, menos
    la demanda pronosticada de hoy ... hoy+lead_time con `margen`, cae bajo `umbral x cupo`.
    """
    projected = position - (1.0 + margen) * expected_demand(yhat, d, lead_time + 1)
    return np.where(projected < umbral * capacity, capacity - position, 0.0)


def expected_demand(yhat: np.ndarray, d: int, days: int) -> np.ndarray:
    """Suma del pronostico de los dias d ... d+dias-1; fuera del horizonte usa la media diaria pronosticada."""
    inside = yhat[d : d + days]
    return inside.sum(axis=0) + (days - len(inside)) * yhat.mean(axis=0)


def forecast_coverage(d, position, yhat, capacity, lead_time, *, margen: float, dias_objetivo: int) -> np.ndarray:
    """Punto de reorden atado a la demanda pronosticada, no al cupo.

    Lo pedido hoy llega en `lead_time` dias y el siguiente pedido, un dia despues: la posicion debe cubrir
    la demanda de hoy ... hoy+lead_time. Si no la cubre (con `margen` de seguridad), pide hasta cubrir
    `dias_objetivo` dias mas, sin pasar del cupo.
    """
    reorder = (1.0 + margen) * expected_demand(yhat, d, lead_time + 1)
    until = np.minimum(capacity, (1.0 + margen) * expected_demand(yhat, d, lead_time + dias_objetivo))
    return np.where(position < reorder, until - position, 0.0)


def quantile_coverage(d, position, yhat, capacity, lead_time, *, dias_objetivo: int, holgura: np.ndarray) -> np.ndarray:
    """Como `forecast_coverage`, con la holgura en pesos en vez de un margen sobre el pronostico.

    `holgura` (por dia) es el cuantil del error acumulado de (lead time + 1) dias por el nivel de la entidad.
    """
    reorder = expected_demand(yhat, d, lead_time + 1) + holgura[d]
    until = np.minimum(capacity, expected_demand(yhat, d, lead_time + dias_objetivo) + holgura[d])
    return np.where(position < reorder, until - position, 0.0)


#: Familias disponibles. Agregar una politica = agregar una entrada.
FAMILIES: dict[str, Callable[..., np.ndarray]] = {
    "umbral_a_cupo": threshold_to_capacity,
    "umbral_pronostico_a_cupo": forecast_threshold_to_capacity,
    "cobertura_pronostico": forecast_coverage,
    "cobertura_cuantil": quantile_coverage,
}


def build_policy(cfg: dict[str, Any], **by_default: Any) -> Callable[..., np.ndarray]:
    """Arma la politica desde su bloque de configuracion `{familia: ..., <parametros>}`.

    Args:
        cfg: Bloque `politica` de la configuracion de la unidad.
        **by_default: Parametros que pone la unidad (p.ej. `umbral`); solo se aplican si la familia
            los acepta y la configuracion no los fija.

    Returns:
        Callable: `politica(d, posicion, yhat, cupo, lead_time) -> pedido`.

    Raises:
        KeyError: Si la familia no existe.
    """
    params = dict(cfg)
    family = params.pop("familia")
    if family not in FAMILIES:
        raise KeyError(f"Politica de provision desconocida: '{family}'. Disponibles: {sorted(FAMILIES)}.")
    function = FAMILIES[family]
    accepted = inspect.signature(function).parameters
    return partial(function, **{**{k: v for k, v in by_default.items() if k in accepted}, **params})
