"""Hoja `05_M6_Fondos`: balance por fondo, denominacion y dia con una accion recomendada por fila."""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

from daas import alx
from daas.publish.anexo_d import masters
from daas.publish.anexo_d.cell_values import mark_formula, to_date_or_none, to_integer
from daas.publish.anexo_d.config import resolve_config
from daas.publish.anexo_d.constants import HEADERS, PROVIDER_ID
from daas.publish.anexo_d.masters import capitalize_city, city_from_fund

logger = logging.getLogger(__name__)

#: Mapa operacion del contrato -> accion_sugerida de la plantilla (vocabulario
#: oficial de la hoja 05, RN-84). El cambio de denominacion usa `cambio_denominacion`
#: (`intercambio_denominacion` no existe en el vocabulario oficial).
_ACTION_M6 = {
    "traslado": "traslado_fondos",
    "venta": "venta_efectivo",
    "banrep_consignacion": "consignacion_banrep",
    "banrep_retiro": "retiro_banrep",
    "cambio_denominacion": "cambio_denominacion",
    "sin_accion": "sin_accion",
}


#: SUP-xx aplicable por operacion M6 (supuesto_utilizado).
_SUP_BY_OP = {
    "traslado": "SUP-08, SUP-10",
    "venta": "SUP-08, SUP-10, SUP-23",
    "banrep_consignacion": "SUP-10, SUP-13",
    "banrep_retiro": "SUP-10, SUP-13",
    "cambio_denominacion": "SUP-09, SUP-14",
    "sin_accion": "SUP-07, SUP-10",
    None: "SUP-07, SUP-10",
}


def origin_destination_m6(reco: pd.Series, fund: str) -> tuple[str | None, str | None]:
    """Deriva `(fondo_origen, fondo_destino)` de la accion M6 desde el contrato.

    Usa `efecto` y `fondo_contraparte` del contrato (ya no se parsea el `motivo`):
    traslado salida -> (fondo, contraparte); traslado entrada -> (contraparte, fondo);
    venta -> (fondo, vacio); BanRep -> BANREP en el lado correspondiente; cambio de
    denominacion -> (fondo, fondo). Valores reales del contrato (no inventados).

    Args:
        reco: Fila de recomendacion m6 (una accion de un fondo-denominacion).
        fund: fondo_id de la fila del balance.

    Returns:
        tuple[str | None, str | None]: ``(fondo_origen, fondo_destino)``.
    """
    operation = str(reco.get("operacion"))
    effect = str(reco.get("efecto"))
    counterpart = reco.get("fondo_contraparte")
    counterpart = None if (counterpart is None or pd.isna(counterpart)) else str(counterpart)
    if operation == "traslado":
        return (counterpart, fund) if effect == "entrada" else (fund, counterpart)
    if operation == "venta":
        return fund, None
    if operation == "banrep_consignacion":
        return fund, "BANREP"
    if operation == "banrep_retiro":
        return "BANREP", fund
    if operation == "cambio_denominacion":
        return fund, fund
    return fund, counterpart


def sheet_05_m6_funds(
    contracts: dict[str, pd.DataFrame], cutoff: _dt.date, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Construye `05_M6_Fondos` (31 cols): una fila por ACCION y fondo-den-dia.

    Grano: cada accion del contrato `recomendaciones` m6 es una fila (los
    traslados y cambios de denominacion tienen dos filas, una por fondo/denominacion
    afectado, con el mismo monto) y cada fondo-denominacion-dia sin accion es una fila
    `sin_accion`. Las acciones de un mismo fondo-denominacion-dia van en orden de
    aplicacion: la primera lleva la disponibilidad inicial y los ingresos/salidas del
    dia; las siguientes parten del saldo que dejo la anterior (ingresos y salidas 0),
    de modo que las formulas de la plantilla (`saldo_antes = disponibilidad + ingresos -
    salidas`, `saldo_despues` segun el efecto) reproducen el saldo encadenado del
    contrato. `nivel_riesgo` es el RESIDUAL despues de actuar (contrato predicciones);
    la direccion y las contrapartes salen de `efecto`/`fondo_contraparte` del contrato.

    Si un egreso esperado supera el saldo disponible (deficit por falta de efectivo), las
    `salidas_proyectadas_cop` muestran lo ATENDIDO y la explicacion lo declara.

    Args:
        contracts: Contratos cargados.
        cutoff: Fecha de corte (SUP-07).
        cfg: Configuracion de exportacion; si es None se carga la de `conf/`.

    Returns:
        pd.DataFrame: columnas = HEADERS['05_M6_Fondos'], en orden.
    """
    cfg = resolve_config(cfg)
    pred = contracts["predicciones"]
    bal = pred[pred["modelo"] == "m6"].copy()
    bal["cod_cajero"] = bal["cod_cajero"].astype(str)
    bal["denominacion"] = pd.to_numeric(bal["denominacion"], errors="coerce")

    dim = masters.load_dim_fund()
    map_city = dict(zip(dim["fondo_id"].astype(str), dim["ciudad"].astype(str), strict=False))
    map_tdv = dict(zip(dim["fondo_id"].astype(str), dim["transportadora"].astype(str), strict=False))

    # dia_habil via el calendario oficial CO.
    business = business_day_map(bal["fecha"], cfg["vocabulario"]["dia_habil"])

    # Acciones m6 indexadas por (fondo, den, fecha), en orden de aplicacion.
    rec = contracts["recomendaciones"]
    rec6 = rec[rec["modelo"] == "m6"].copy()
    rec6["cod_cajero"] = rec6["cod_cajero"].astype(str)
    rec6["denominacion"] = pd.to_numeric(rec6["denominacion"], errors="coerce")
    rec6["fecha_sugerida"] = rec6["fecha_sugerida"].astype(str)
    if "orden_aplicacion" not in rec6.columns:
        rec6["orden_aplicacion"] = 1
    recs_by_key: dict[tuple[str, int, str], list[pd.Series]] = {}
    if not rec6.empty:
        rec6 = rec6.sort_values(["fecha_sugerida", "orden_aplicacion"], kind="stable")
        for _, r in rec6.iterrows():
            if pd.isna(r["denominacion"]):
                continue
            k = (str(r["cod_cajero"]), int(r["denominacion"]), str(r["fecha_sugerida"]))
            recs_by_key.setdefault(k, []).append(r)

    def _num(v: object) -> float | None:
        return None if v is None or pd.isna(v) else float(v)

    # SUP-12 determina los ingresos y salidas de todas las filas cuando M6 integra los cajeros de sucursal (RN-73).
    sup12 = alx.interruptor("m6_cajeros_sucursal")
    sup52 = alx.interruptor("m6_traslado_t1")
    sup53 = alx.interruptor("m6_tarifa_traslado_declarada")

    rows = []
    for _, row in bal.iterrows():
        fund = row["cod_cajero"]
        denom = row["denominacion"]
        date_iso = str(row["fecha"])
        denom_int = int(denom) if pd.notna(denom) else None
        city = capitalize_city(map_city.get(fund)) or city_from_fund(fund)
        carrier = map_tdv.get(fund)
        if carrier is None and "|" in fund:
            carrier = fund.split("|")[1]

        level = str(row.get("nivel_riesgo") or "bajo")
        balance_start = _num(row.get("saldo_inicial_dia"))
        inflow = _num(row.get("ingresos_esperados"))
        outflow = _num(row.get("egresos_esperados"))
        deficit = _num(row.get("deficit")) or 0.0
        if balance_start is None:  # contrato antiguo sin esos campos: se deduce como antes.
            net = _num(row.get("efecto_neto_den"))
            sp = _num(row.get("saldo_proyectado"))
            if net is not None and sp is not None:
                balance_start = sp - net
                inflow, outflow = max(net, 0.0), max(-net, 0.0)
        served = None if outflow is None else max(outflow - deficit, 0.0)

        key = (fund, denom_int, date_iso) if denom_int is not None else None
        actions = recs_by_key.get(key, []) if key else []
        actions = actions or [None]
        balance_prev = balance_start
        for k, reco in enumerate(actions):
            first = k == 0
            if reco is not None and str(reco.get("operacion")) != "sin_accion":
                operation = str(reco.get("operacion"))
                action = _ACTION_M6.get(operation, operation)
                effect = str(reco.get("efecto"))
                if effect not in ("entrada", "salida"):
                    effect = "ninguno"
                amount = to_integer(reco.get("monto"))
                fund_origin, fund_destination = origin_destination_m6(reco, fund)
                cost = to_integer(reco.get("costo"))  # NaN -> None (no se inventa)
                criterion = reco.get("criterio") or reco.get("costo_regla")
                assumption = _SUP_BY_OP.get(operation, _SUP_BY_OP[None])
                explanation = reco.get("motivo")
            elif reco is not None:  # sin_accion con necesidad (conservar / sin solucion)
                action, effect, amount = "sin_accion", "ninguno", 0
                fund_origin = fund_destination = None
                cost = 0
                criterion = reco.get("criterio")
                assumption = _SUP_BY_OP["sin_accion"]
                explanation = reco.get("motivo")
            else:
                action, effect, amount = "sin_accion", "ninguno", 0
                fund_origin = fund_destination = None
                cost = 0
                criterion = "RN-85: dentro de niveles objetivo (sin_accion)"
                assumption = _SUP_BY_OP["sin_accion"]
                explanation = "Saldo dentro del rango objetivo; sin accion."
            if first and deficit > 0:
                explanation = (
                    f"{explanation or ''} Egresos esperados {outflow:,.0f}: se atienden "
                    f"{served:,.0f} por falta de saldo (deficit {deficit:,.0f})."
                ).strip()
            if sup12:
                assumption = f"{assumption}, SUP-12"
            if action == "traslado_fondos":
                # SUP-52: disponible en el destino al dia siguiente; SUP-53: tarifa del traslado entre ciudades.
                if sup52:
                    assumption = f"{assumption}, SUP-52"
                if sup53 and city_from_fund(str(fund_origin)) != city_from_fund(str(fund_destination)):
                    assumption = f"{assumption}, SUP-53"
            rows.append(
                {
                    "id_proveedor": PROVIDER_ID,
                    "fondo_id": fund,
                    "ciudad": city,
                    "transportadora": carrier,
                    "fecha_corte": cutoff,
                    "fecha_objetivo": to_date_or_none(row["fecha"]),
                    "dia_habil": business.get(date_iso),
                    "denominacion_cop": denom_int,
                    "disponibilidad_inicial_cop": to_integer(balance_start if first else balance_prev),
                    "ingresos_proyectados_cop": to_integer(inflow) if first else 0,
                    "salidas_proyectadas_cop": to_integer(served) if first else 0,
                    "presion_neta_canales_cop": mark_formula("05_M6_Fondos", "presion_neta_canales_cop"),
                    "saldo_antes_accion_cop": mark_formula("05_M6_Fondos", "saldo_antes_accion_cop"),
                    "nivel_objetivo_min_cop": to_integer(row.get("minimo")),
                    "nivel_objetivo_max_cop": to_integer(row.get("maximo")),
                    "faltante_potencial_cop": mark_formula("05_M6_Fondos", "faltante_potencial_cop"),
                    "excedente_potencial_cop": mark_formula("05_M6_Fondos", "excedente_potencial_cop"),
                    "nivel_riesgo": level,
                    "accion_sugerida": action,
                    "efecto_en_fondo": effect,
                    "monto_sugerido_cop": amount,
                    "fondo_origen": fund_origin,
                    "fondo_destino": fund_destination,
                    "saldo_despues_accion_cop": mark_formula("05_M6_Fondos", "saldo_despues_accion_cop"),
                    "costo_estimado_cop": cost,
                    "criterio_aplicado": criterion,
                    "supuesto_utilizado": assumption,
                    "explicacion_funcional": explanation,
                    "origen_disponibilidad": (
                        "Ultimo disponible al 31/08/2026 (SUP-07)"
                        if k == 0 and date_iso == str(bal["fecha"].min())
                        else "Cierre del dia anterior (saldo encadenado, RN-71)"
                    ),
                    "origen_presion": cfg["vocabulario"]["origen_presion"],
                    "metodo_distribucion_denominacion": ("Participacion historica por denominacion (SUP-09)"),
                }
            )
            if reco is not None and str(reco.get("operacion")) != "sin_accion":
                if effect == "entrada" and balance_prev is not None:
                    balance_prev = (balance_prev if not first else (balance_start + (inflow or 0) - (served or 0))) + (
                        amount or 0
                    )
                elif effect == "salida" and balance_prev is not None:
                    balance_prev = (balance_prev if not first else (balance_start + (inflow or 0) - (served or 0))) - (
                        amount or 0
                    )
            elif first and balance_start is not None:
                balance_prev = balance_start + (inflow or 0) - (served or 0)
    out = pd.DataFrame(rows, columns=HEADERS["05_M6_Fondos"])
    return out.reset_index(drop=True)


def business_day_map(dates: pd.Series, vocabulary: dict[str, str] | None = None) -> dict[str, str]:
    """Mapa ``fecha ISO -> 'Sí'/'No'`` segun el calendario oficial CO (RN-71A).

    Args:
        dates: Serie de fechas ISO del balance m6.
        vocabulary: ``vocabulario.dia_habil`` de la configuracion (``{habil, no_habil}``).

    Returns:
        dict[str, str]: ``{fecha_iso: 'Sí'|'No'}``. Si el calendario no se puede
        construir, devuelve ``{}`` (la celda queda vacia, NO se inventa).
    """
    try:
        from daas.features.calendar import build_calendar

        dates_norm = pd.to_datetime(dates, errors="coerce").dropna()
        if dates_norm.empty:
            return {}
        start = dates_norm.min().date().isoformat()
        fin = dates_norm.max().date().isoformat()
        cal = build_calendar(start, fin)
        col_date = "fecha" if "fecha" in cal.columns else cal.columns[0]
        voc = vocabulary or resolve_config(None)["vocabulario"]["dia_habil"]
        out: dict[str, str] = {}
        for _, row in cal.iterrows():
            iso = pd.to_datetime(row[col_date]).date().isoformat()
            out[iso] = voc["habil"] if bool(row["es_habil"]) else voc["no_habil"]
        return out
    except Exception as error:  # noqa: BLE001  (sin calendario -> celda vacia)
        logger.warning(
            "No se pudo construir el calendario CO para dia_habil (%s); " "la columna queda vacia (NO se inventa).",
            error,
        )
        return {}
