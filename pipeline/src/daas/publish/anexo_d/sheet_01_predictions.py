"""Hoja `01_Predicciones`: una fila por entidad, dia y variable objetivo de M1 a M5."""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from daas.publish.anexo_d import masters
from daas.publish.anexo_d.cell_values import mark_formula, to_date_or_none, to_integer
from daas.publish.anexo_d.constants import HEADERS, PREDICTION_MODELS, PROVIDER_ID
from daas.publish.anexo_d.masters import capitalize_city, city_from_fund, city_map_m3


def sheet_01_predictions(contracts: dict[str, pd.DataFrame], cutoff: _dt.date) -> pd.DataFrame:
    """Construye `01_Predicciones` (solo M1-M5).

    Mapea `predicciones` -> encabezados oficiales: `ciudad` por maestro
    (cp_historico para m1/m2, oficinas/maestro para m3, fondo_id para m4/m5),
    `id_entidad=cod_cajero`, `variable_objetivo=objetivo`,
    `fecha_objetivo=fecha`, `valor_pronosticado_cop=yhat`,
    `horizonte_dias`=FORMULA, `nivel_agregacion` segun el modelo.

    Args:
        contracts: Contratos cargados.
        cutoff: Fecha de corte (para la vigencia de los maestros).

    Returns:
        pd.DataFrame: columnas = HEADERS['01_Predicciones'], en orden.
    """
    pred = contracts["predicciones"]
    pred = pred[pred["modelo"].isin(PREDICTION_MODELS)].copy()
    pred["cod_cajero"] = pred["cod_cajero"].astype(str)

    cp = masters.city_capacity_map_m1_m2(cutoff)[["cod_cajero", "ciudad"]]
    m3 = city_map_m3(cutoff)
    masters.load_dim_fund()

    map_m1m2 = dict(zip(cp["cod_cajero"], cp["ciudad"], strict=False))
    map_m3 = dict(zip(m3["cod_sucursal"], m3["ciudad"], strict=False))

    def _city(row: pd.Series) -> str | None:
        mdl, code = row["modelo"], row["cod_cajero"]
        if mdl in ("m1", "m2"):
            return capitalize_city(map_m1m2.get(code))
        if mdl == "m3":
            return capitalize_city(map_m3.get(code))
        # m4/m5: cod_cajero == fondo_id == CIUDAD|TRANSPORTADORA.
        return city_from_fund(code)

    # Nivel de agregacion: M4/M5 son fondo-dia (RN-48); M1-M3 entidad-dia.
    def _level(mdl: str) -> str:
        return "fondo-dia" if mdl in ("m4", "m5") else "entidad-dia"

    rows = []
    for _, row in pred.iterrows():
        rows.append(
            {
                "id_proveedor": PROVIDER_ID,
                "modelo": str(row["modelo"]).upper(),
                "ciudad": _city(row),
                "id_entidad": row["cod_cajero"],
                "variable_objetivo": row["objetivo"],
                "fecha_objetivo": to_date_or_none(row["fecha"]),
                "horizonte_dias": mark_formula("01_Predicciones", "horizonte_dias"),
                "valor_pronosticado_cop": to_integer(row["yhat"]),
                "nivel_agregacion": _level(str(row["modelo"])),
            }
        )
    out = pd.DataFrame(rows, columns=HEADERS["01_Predicciones"])
    return out.sort_values(["modelo", "id_entidad", "fecha_objetivo"]).reset_index(drop=True)
