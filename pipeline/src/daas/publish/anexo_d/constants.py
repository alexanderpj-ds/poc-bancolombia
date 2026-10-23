"""Constantes del Anexo D: proveedor, hojas obligatorias, encabezados oficiales y formulas."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from typing import Any

#: id del proveedor (constante en TODAS las filas de las 5 hojas obligatorias).
PROVIDER_ID = "PRAGMA"


#: Modelos que van en `01_Predicciones` (M6 queda fuera por la).
PREDICTION_MODELS = ("m1", "m2", "m3", "m4", "m5")


#: Nombres de las 5 hojas obligatorias (y la informativa que no se toca).
REQUIRED_SHEETS: tuple[str, ...] = (
    "01_Predicciones",
    "02_Plan_Operativo",
    "03_Metricas_Desarrollo",
    "04_Descripcion_Solucion",
    "05_M6_Fondos",
)


DICTIONARY_SHEET = "06_Diccionario_Campos"


#: Encabezados oficiales EXACTOS (fila 2) de cada hoja obligatoria. Se validan
#: contra la plantilla real antes de escribir (si difieren, se aborta: protege
#: el formato oficial).
HEADERS: dict[str, list[str]] = {
    "01_Predicciones": [
        "id_proveedor",
        "modelo",
        "ciudad",
        "id_entidad",
        "variable_objetivo",
        "fecha_objetivo",
        "horizonte_dias",
        "valor_pronosticado_cop",
        "nivel_agregacion",
    ],
    "02_Plan_Operativo": [
        "id_proveedor",
        "modelo",
        "ciudad",
        "id_entidad",
        "tipo_administracion",
        "fecha_accion_sugerida",
        "accion_sugerida",
        "monto_sugerido_cop",
        "nivel_riesgo",
        "regla_aplicada",
        "explicacion_funcional",
        "cupo_entidad_cop",
        "saldo_antes_accion_cop",
        "porcentaje_ocupacion_antes",
        "saldo_despues_accion_cop",
        "costo_estimado_cop",
    ],
    "03_Metricas_Desarrollo": [
        "id_proveedor",
        "modelo",
        "variable_o_kpi_evaluado",
        "tipo_metrica",
        "metrica",
        "valor_metrica",
        "unidad",
        "segmento",
        "periodo_desde",
        "periodo_hasta",
        "metodologia_validacion",
        "comentarios",
    ],
    "04_Descripcion_Solucion": [
        "id_proveedor",
        "modelo",
        "variable_objetivo_evaluada",
        "definicion_variable_objetivo",
        "algoritmo_o_enfoque",
        "variables_utilizadas",
        "variables_mas_relevantes",
        "horizonte_prediccion",
        "metodologia_validacion",
        "transformacion_a_decision_operativa",
        "limitaciones_identificadas",
        "dependencias_externas",
        "supuestos",
    ],
    "05_M6_Fondos": [
        "id_proveedor",
        "fondo_id",
        "ciudad",
        "transportadora",
        "fecha_corte",
        "fecha_objetivo",
        "dia_habil",
        "denominacion_cop",
        "disponibilidad_inicial_cop",
        "ingresos_proyectados_cop",
        "salidas_proyectadas_cop",
        "presion_neta_canales_cop",
        "saldo_antes_accion_cop",
        "nivel_objetivo_min_cop",
        "nivel_objetivo_max_cop",
        "faltante_potencial_cop",
        "excedente_potencial_cop",
        "nivel_riesgo",
        "accion_sugerida",
        "efecto_en_fondo",
        "monto_sugerido_cop",
        "fondo_origen",
        "fondo_destino",
        "saldo_despues_accion_cop",
        "costo_estimado_cop",
        "criterio_aplicado",
        "supuesto_utilizado",
        "explicacion_funcional",
        "origen_disponibilidad",
        "origen_presion",
        "metodo_distribucion_denominacion",
    ],
}


#: Marcador de celda que debe escribirse como FORMULA Excel (no como valor). El
#: valor es la plantilla de la formula con `{r}` por el numero de fila real.
FORMULA_PREFIX = "__FORMULA__:"


#: Fecha base de `horizonte_dias` en la formula de la plantilla.
HORIZON_BASE_DATE = _dt.date(2026, 8, 31)

#: Formulas Excel por (hoja, columna) replicadas de la plantilla.
FORMULAS: dict[str, dict[str, str]] = {
    "01_Predicciones": {
        "horizonte_dias": (
            f"=F{{r}}-DATE({HORIZON_BASE_DATE.year},{HORIZON_BASE_DATE.month},{HORIZON_BASE_DATE.day})"
        ),
    },
    "02_Plan_Operativo": {
        "porcentaje_ocupacion_antes": '=IF(ISNUMBER(M{r}),M{r}/L{r},"No aplica")',
        "saldo_despues_accion_cop": ('=IF(G{r}="provision",M{r}+H{r},' 'IF(G{r}="recoleccion",M{r}-H{r},"No aplica"))'),
    },
    "05_M6_Fondos": {
        "presion_neta_canales_cop": "=J{r}-K{r}",
        "saldo_antes_accion_cop": "=I{r}+L{r}",
        "faltante_potencial_cop": "=MAX(0,N{r}-M{r})",
        "excedente_potencial_cop": "=MAX(0,M{r}-O{r})",
        "saldo_despues_accion_cop": ('=IF(T{r}="entrada",M{r}+U{r},IF(T{r}="salida",M{r}-U{r},M{r}))'),
    },
}



def _number(value: Any) -> float | None:
    """Valor numerico de una celda como lo ve ISNUMBER; ``None`` si no es numero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _operand(value: Any) -> float:
    """Operando aritmetico de Excel: vacio cuenta 0; texto es error (``ValueError``)."""
    if value is None or (isinstance(value, float) and value != value):
        return 0.0
    number = _number(value)
    if number is None:
        raise ValueError(value)
    return number


def _days_from_base(value: Any) -> int:
    day = value.date() if isinstance(value, _dt.datetime) else value
    if not isinstance(day, _dt.date):
        raise ValueError(value)
    return (day - HORIZON_BASE_DATE).days


def _occupancy(c: dict[str, Any]) -> float | str:
    if _number(c["M"]) is None:
        return "No aplica"
    return _operand(c["M"]) / _operand(c["L"])


def _balance_after_02(c: dict[str, Any]) -> float | str:
    if c["G"] == "provision":
        return _operand(c["M"]) + _operand(c["H"])
    if c["G"] == "recoleccion":
        return _operand(c["M"]) - _operand(c["H"])
    return "No aplica"


def _balance_after_05(c: dict[str, Any]) -> float:
    if c["T"] == "entrada":
        return _operand(c["M"]) + _operand(c["U"])
    if c["T"] == "salida":
        return _operand(c["M"]) - _operand(c["U"])
    return _operand(c["M"])


#: Equivalente en Python de cada formula de `FORMULAS`, sobre las celdas de la fila por letra de columna.
#: Da el valor que se guarda en cache para que el libro se lea sin recalcular; un error de Excel se
#: representa con una excepcion y la celda queda sin cache.
FORMULA_VALUES: dict[str, dict[str, Callable[[dict[str, Any]], Any]]] = {
    "01_Predicciones": {
        "horizonte_dias": lambda c: _days_from_base(c["F"]),
    },
    "02_Plan_Operativo": {
        "porcentaje_ocupacion_antes": _occupancy,
        "saldo_despues_accion_cop": _balance_after_02,
    },
    "05_M6_Fondos": {
        "presion_neta_canales_cop": lambda c: _operand(c["J"]) - _operand(c["K"]),
        "saldo_antes_accion_cop": lambda c: _operand(c["I"]) + _operand(c["L"]),
        "faltante_potencial_cop": lambda c: max(0.0, _operand(c["N"]) - _operand(c["M"])),
        "excedente_potencial_cop": lambda c: max(0.0, _operand(c["M"]) - _operand(c["O"])),
        "saldo_despues_accion_cop": _balance_after_05,
    },
}

METHODOLOGY = "Backtesting temporal, ventanas de 15 dias"
