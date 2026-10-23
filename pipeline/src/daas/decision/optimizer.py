"""Optimizador PuLP del subpaquete `forecasting`, `decision` y `modules` (reuse-analysis.md).

Reuso portado de la demo de 1a ronda, adaptado. Calcula la caja optima y las
recomendaciones del modelo M6. Reglas de negocio (RN): respeta el cupo maximo
por fondo/sucursal, el margen operativo (8%) y la restriccion de saldo.

Caso especial `split_denominations` (M6): se reimplanta aislado del generador
sintetico de la demo (que NO se reutiliza); desglosa el monto en las 6
denominaciones obligatorias (100k, 50k, 20k, 10k, 5k, 2k) sin arrastrar RNG ni
parametros de simulacion.

Recomendacion M1 (`recommend_provision_m1`): regla determinista
sobre el saldo simulado que produce `fecha_sugerida_provision` y
`monto_para_completar` hasta el cupo operativo (sin PuLP; eleccion documentada).

Recomendaciones M2 y M3 (`recommend_actions_m2`, `recommend_actions_m3`): una fila por CADA
provision (manana) y CADA recoleccion (cierre) que la simulacion aplico en el horizonte (Anexo B
RN-21, RN-28). Con las dos el mismo dia salen separadas, en ese orden.

Toda recomendacion lleva el saldo simulado antes y despues de la accion y el cupo (RN-03): la
provision parte del saldo de apertura y suma el monto; la recoleccion parte del saldo al cierre,
antes de recoger, y resta el monto.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def recommend_provision_m1(balance_simulated: pd.DataFrame) -> pd.DataFrame:
    """Recomienda la provision M1 por cajero sobre el saldo simulado.

    Regla DETERMINISTA sobre la simulacion de saldo (no se usa PuLP: la decision
    es un recorrido directo del saldo diario, suficiente para la PoC y mas
    transparente que una optimizacion). Por cada cajero:

    - Una fila por CADA dia con provision endogena (`provision > 0`):
      `fecha_sugerida_provision` = dia de entrega, `monto_para_completar` = lo
      entregado. Sin columna `provision`, fallback al primer dia con
      `riesgo_agotamiento == True` con `monto = cupo_operativo - saldo_ese_dia`
      (recarga hasta el cupo operativo; nunca negativo).
    - Si el cajero no requiere provision en el horizonte, `requiere_provision=
      False` con `fecha_sugerida_provision=NaT` y `monto_para_completar=0.0`.

    Con el motor de saldo corregido la provision es ENDOGENA: cuando
    la columna `provision` esta presente, cada `monto_para_completar` es el
    monto que la simulacion ya aplico al saldo ese dia. Si no esta, se usa el
    fallback previo `cupo_operativo - saldo_ese_dia`.

    Args:
        balance_simulated: Salida de `modules.atm_m1_m2.balance.simular_saldo_m1`
            (concatenada por cajero) con columnas `cod_cajero`, `fecha`,
            `saldo`, `cupo_operativo`, `riesgo_agotamiento` (y opcionalmente
            `provision` endogena).

    Returns:
        pd.DataFrame: Una fila por provision (o una sola si el cajero no
        requiere) con columnas `cod_cajero`,
        `requiere_provision` (bool), `fecha_sugerida_provision` (date|NaT),
        `monto_para_completar` (float), `cupo_operativo` (float).

    Raises:
        KeyError: Si faltan columnas obligatorias en `saldo_simulado`.
    """
    required = {
        "cod_cajero",
        "fecha",
        "saldo",
        "cupo_operativo",
        "riesgo_agotamiento",
    }
    missing = required - set(balance_simulated.columns)
    if missing:
        raise KeyError(f"recomendar_provision_m1: faltan columnas {sorted(missing)}.")

    has_provision = "provision" in balance_simulated.columns
    recommendations: list[dict[str, Any]] = []
    for code, group in balance_simulated.groupby("cod_cajero", sort=True):
        g = group.sort_values("fecha").reset_index(drop=True)
        capacity_op = float(g["cupo_operativo"].iloc[0])
        # Provision endogena: si esta presente, el primer dia con
        # provision>0 marca la fecha/monto realimentados por la simulacion.
        provision_pos = (
            g[pd.to_numeric(g["provision"], errors="coerce").fillna(0.0) > 0.0] if has_provision else g.iloc[0:0]
        )
        in_risk = g[g["riesgo_agotamiento"].fillna(False).astype(bool)]
        if provision_pos.empty and in_risk.empty:
            recommendations.append(
                {
                    "cod_cajero": code,
                    "requiere_provision": False,
                    "fecha_sugerida_provision": pd.NaT,
                    "monto_para_completar": 0.0,
                    "cupo_operativo": capacity_op,
                    "saldo_antes": float("nan"),
                    "saldo_despues": float("nan"),
                }
            )
            continue
        if not provision_pos.empty:
            # Una fila por provision del horizonte: todas llegan a la
            # recomendacion y al costo, no solo la primera.
            for _, row in provision_pos.iterrows():
                amount = max(float(row["provision"]), 0.0)
                before = _balance_before_provision(row)
                recommendations.append(
                    {
                        "cod_cajero": code,
                        "requiere_provision": True,
                        "fecha_sugerida_provision": row["fecha"],
                        "monto_para_completar": amount,
                        "cupo_operativo": capacity_op,
                        "saldo_antes": before,
                        "saldo_despues": before + amount,
                    }
                )
            continue
        first = in_risk.iloc[0]
        recommendations.append(
            {
                "cod_cajero": code,
                "requiere_provision": True,
                "fecha_sugerida_provision": first["fecha"],
                "monto_para_completar": max(capacity_op - float(first["saldo"]), 0.0),
                "cupo_operativo": capacity_op,
                "saldo_antes": float(first["saldo"]),
                "saldo_despues": max(capacity_op, float(first["saldo"])),
            }
        )

    columns = [
        "cod_cajero",
        "requiere_provision",
        "fecha_sugerida_provision",
        "monto_para_completar",
        "cupo_operativo",
        "saldo_antes",
        "saldo_despues",
    ]
    return pd.DataFrame(recommendations, columns=columns)


#: Columnas de las recomendaciones M2/M3.
_ACTION_COLUMNS = [
    "cod_cajero",
    "accion",
    "momento",
    "fecha_sugerida",
    "monto",
    "cupo_operativo",
    "saldo_antes",
    "saldo_despues",
]


def _balance_before_provision(row: pd.Series) -> float:
    """Saldo de apertura del dia, antes de la provision (la provision llega en la manana)."""
    return float(row["saldo_inicial_dia"]) if "saldo_inicial_dia" in row.index else float("nan")


def _balance_before_collection(row: pd.Series) -> float:
    """Saldo al cierre antes de recoger (la recoleccion es lo ultimo del dia)."""
    if "saldo_antes_recoleccion" in row.index:
        return float(row["saldo_antes_recoleccion"])
    return float(row["saldo"]) + float(row["recoleccion"])


def _actions(balance_simulated: pd.DataFrame, name: str) -> pd.DataFrame:
    """Una fila por cada provision y cada recoleccion > 0 de la simulacion, con su saldo antes y despues.

    Args:
        balance_simulated: Simulacion concatenada por entidad (`cod_cajero`, `fecha`, `saldo`,
            `saldo_inicial_dia`, `cupo_operativo`, `provision`, `recoleccion`).
        name: Nombre de la funcion que llama (para el mensaje de error).

    Returns:
        pd.DataFrame: Columnas `_ACTION_COLUMNS`, por entidad, fecha y momento (manana antes que
        cierre). Vacio con ese esquema si no hay acciones.

    Raises:
        KeyError: Si faltan columnas obligatorias.
    """
    required = {
        "cod_cajero",
        "fecha",
        "saldo",
        "saldo_inicial_dia",
        "cupo_operativo",
        "provision",
        "recoleccion",
    }
    missing = required - set(balance_simulated.columns)
    if missing:
        raise KeyError(f"{name}: faltan columnas {sorted(missing)}.")

    actions: list[dict[str, Any]] = []
    for code, group in balance_simulated.groupby("cod_cajero", sort=True):
        g = group.sort_values("fecha").reset_index(drop=True)
        capacity_op = float(g["cupo_operativo"].iloc[0])
        provision = pd.to_numeric(g["provision"], errors="coerce").fillna(0.0)
        collection = pd.to_numeric(g["recoleccion"], errors="coerce").fillna(0.0)
        for k, row in g.iterrows():
            if provision[k] > 0.0:
                before = _balance_before_provision(row)
                actions.append(
                    {
                        "cod_cajero": code,
                        "accion": "provision",
                        "momento": "manana",
                        "fecha_sugerida": row["fecha"],
                        "monto": float(provision[k]),
                        "cupo_operativo": capacity_op,
                        "saldo_antes": before,
                        "saldo_despues": before + float(provision[k]),
                    }
                )
            if collection[k] > 0.0:
                before = _balance_before_collection(row)
                actions.append(
                    {
                        "cod_cajero": code,
                        "accion": "recoleccion",
                        "momento": "cierre",
                        "fecha_sugerida": row["fecha"],
                        "monto": float(collection[k]),
                        "cupo_operativo": capacity_op,
                        "saldo_antes": before,
                        "saldo_despues": before - float(collection[k]),
                    }
                )
    if not actions:
        return pd.DataFrame(columns=_ACTION_COLUMNS)
    return pd.DataFrame(actions, columns=_ACTION_COLUMNS)


def recommend_actions_m2(balance_simulated: pd.DataFrame) -> pd.DataFrame:
    """Recomienda TODAS las provisiones y recolecciones M2 del horizonte (Anexo B RN-21, RN-22, RN-28).

    Provision en la manana hasta el cupo (RN-19A); recoleccion al cierre de lo que pase del cupo
    (RN-22, RN-35). Con las dos el mismo dia salen como dos filas, provision primero.

    Args:
        balance_simulated: Salida de `modules.atm_m1_m2.balance.simular_saldo_m2`, concatenada por cajero.

    Returns:
        pd.DataFrame: Columnas `cod_cajero`, `accion`, `momento`, `fecha_sugerida`, `monto`,
        `cupo_operativo`, `saldo_antes`, `saldo_despues`.

    Raises:
        KeyError: Si faltan columnas obligatorias en `saldo_simulado`.
    """
    return _actions(balance_simulated, "recomendar_acciones_m2")


def recommend_actions_m3(balance_simulated: pd.DataFrame) -> pd.DataFrame:
    """Recomienda TODAS las provisiones y recolecciones M3 del horizonte (U3).

    Mismo recorrido que M2 sobre la simulacion de la boveda de sucursal. El id de entidad ya viene
    renombrado a `cod_cajero` por `run_u3` (id compartido enmascarado).

    Args:
        balance_simulated: Salida de `modules.branches_m3.balance.simular_saldo_m3`, concatenada por sucursal.

    Returns:
        pd.DataFrame: Columnas `cod_cajero`, `accion`, `momento`, `fecha_sugerida`, `monto`,
        `cupo_operativo`, `saldo_antes`, `saldo_despues`.

    Raises:
        KeyError: Si faltan columnas obligatorias en `saldo_simulado`.
    """
    return _actions(balance_simulated, "recomendar_acciones_m3")


def optimize(df: pd.DataFrame) -> pd.DataFrame:
    """Resuelve la caja optima / recomendaciones M6 con PuLP.

    Aplica las restricciones RN de cupo, margen 8% y saldo. STUB.
    """
    raise NotImplementedError("model.optimizer.optimize: pendiente de implementar (FEAT-003+). §8")


def split_denominations(amount: float) -> dict[int, int]:
    """Desglosa `monto` en las 6 denominaciones obligatorias (100k..2k).

    Reimplantado aislado del generador sintetico de la demo (sin RNG ni
    parametros de simulacion). STUB.
    """
    raise NotImplementedError("model.optimizer.split_denominations: pendiente de implementar (FEAT-003+). §8")
