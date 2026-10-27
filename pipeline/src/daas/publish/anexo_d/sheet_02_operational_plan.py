"""Hoja `02_Plan_Operativo`: acciones y reglas aplicadas, con nivel de riesgo y explicacion."""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import numpy as np
import pandas as pd

from daas import alx
from daas.costs.anexo_e import mf_es_interurbano
from daas.publish.anexo_d import masters
from daas.publish.anexo_d.cell_values import mark_formula, to_date_or_none, to_integer
from daas.publish.anexo_d.config import resolve_config
from daas.publish.anexo_d.constants import HEADERS, PROVIDER_ID
from daas.publish.anexo_d.masters import cap_m1, capacity_m3, capitalize_city, city_map_m3

logger = logging.getLogger(__name__)

#: Niveles admitidos por la plantilla (diccionario 06).
_LEVELS = ("alto", "medio", "bajo")

#: Mapa accion del contrato (M1-M3) -> regla aplicada (Anexo B). provision via
#: RN-11 (simulacion/provision hasta cupo); recoleccion via la regla de
#: recoleccion del modelo. Son reglas documentadas (RN-11/RN-34 en el repo); el
#: texto completo del criterio se toma del contrato donde exista.
_RULE_BY_ACTION = {
    ("m1", "provision"): "RN-11 y RN-34: provision hasta el cupo operativo antes de bajar del 8 %",
    ("m2", "provision"): "RN-19A y RN-21: provision hasta el cupo antes de bajar del 8 %",
    ("m2", "recoleccion"): "RN-22 y RN-35: recoleccion al cierre de lo que pasa del cupo",
    ("m3", "provision"): "SUP-M3-01: provision hasta el cupo de la boveda bajo el 8 %",
    ("m3", "recoleccion"): "SUP-M3-01: recoleccion al cierre de lo que pasa del cupo de la boveda",
}


def administration_type(admin: object) -> str | None:
    """Deriva `tipo_administracion` de `admon` del maestro CP (RN-08A).

    Args:
        admin: Valor de ``admon`` (nombre de TDV o ``'SUC'``).

    Returns:
        str | None: ``'TDV'`` si es una transportadora, ``'Sucursal'`` si
        ``'SUC'``, ``None`` si falta.
    """
    if admin is None or (isinstance(admin, float) and pd.isna(admin)):
        return None
    text = str(admin).strip().upper()
    if not text:
        return None
    return "Sucursal" if text == "SUC" else "TDV"


def level_by_occupancy(balance: float | None, capacity: float | None, cfg_level: dict[str, Any]) -> str | None:
    """Nivel de riesgo segun la ocupacion (saldo / cupo) y las bandas de `nivel_riesgo.bandas`.

    Args:
        balance: Saldo despues de la accion (COP) o ``None``.
        capacity: Cupo de la entidad (COP) o ``None``.
        cfg_level: Bloque `nivel_riesgo` de ``export_anexo_d.yml``.

    Returns:
        str | None: Nivel de la primera banda que cumple (o `por_defecto`); ``None`` si no hay
        saldo o cupo para calcular la ocupacion.
    """
    if balance is None or capacity is None or capacity <= 0:
        return None
    occupancy = balance / capacity
    for band in cfg_level["bandas"]:
        smaller = band.get("ocupacion_menor_que")
        greater = band.get("ocupacion_mayor_que")
        if (smaller is not None and occupancy < float(smaller)) or (greater is not None and occupancy > float(greater)):
            return str(band["nivel"])
    return str(cfg_level["por_defecto"])


def _rule_label(mdl: str, action: object, rule: object, cfg: dict[str, Any]) -> str | None:
    """`regla_aplicada`: la etiqueta de la regla del contrato (M3) o la del mapa por accion."""
    if rule is not None and not (isinstance(rule, float) and pd.isna(rule)):
        return cfg.get("regla_m3", {}).get(str(rule), str(rule))
    return _RULE_BY_ACTION.get((mdl, str(action)))


def sheet_02_operational_plan(
    contracts: dict[str, pd.DataFrame], cutoff: _dt.date, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Construye `02_Plan_Operativo` (16 cols) desde `recomendaciones` M1/M2/M3.

    Mapea: `accion_sugerida=accion`, `fecha_accion_sugerida=fecha_sugerida`,
    `monto_sugerido_cop=monto`, `costo_estimado_cop=costo`,
    `tipo_administracion` del maestro (M3: "No aplica"), `cupo_entidad_cop` del `cupo` de la fila
    (respaldo: maestro), `saldo_antes_accion_cop` del `saldo_antes` de la fila (RN-03),
    `regla_aplicada` y `explicacion_funcional` del contrato cuando lo trae (M3) y, si no, por accion;
    y columnas de formula (N/O) marcadas.

    `nivel_riesgo` se mide sobre el saldo DESPUES de la accion: ocupacion = saldo despues / cupo
    contra las bandas de `nivel_riesgo` de la configuracion (decision de Pragma; el pliego no fija bandas). Sin
    saldo o cupo se usa la peor severidad de `alertas` (que mira el saldo SIN actuar).

    Toda entidad de M1-M3 con pronostico y sin accion en el horizonte sale con una fila `sin_accion`
    en la fecha de inicio del horizonte (RN-02): monto 0 y "No aplica" en saldo y costo.

    Los equipos con `admon = SUC` no tienen tarifa TDV: su costo sale 0 declarado en la explicacion.

    Args:
        contracts: Contratos cargados.
        cutoff: Fecha de corte (vigencia de maestros).
        cfg: Configuracion de ``export_anexo_d.yml`` (``None`` la carga).

    Returns:
        pd.DataFrame: columnas = HEADERS['02_Plan_Operativo'], en orden.
    """
    cfg = resolve_config(cfg)
    na = cfg["vocabulario"]["no_aplica"]
    rec = contracts["recomendaciones"]
    rec = rec[rec["modelo"].isin(("m1", "m2", "m3"))].copy()
    rec["cod_cajero"] = rec["cod_cajero"].astype(str)

    cp = masters.city_capacity_map_m1_m2(cutoff)
    m3_city = city_map_m3(cutoff)
    m3_capacity = capacity_m3(cutoff)
    map_cp_city = dict(zip(cp["cod_cajero"], cp["ciudad"], strict=False))
    map_cp_admin = dict(zip(cp["cod_cajero"], cp["admon"], strict=False))
    map_cp_capacity = dict(zip(cp["cod_cajero"], cp["cupo"], strict=False))
    map_m3_city = dict(zip(m3_city["cod_sucursal"], m3_city["ciudad"], strict=False))
    map_m3_capacity = dict(zip(m3_capacity["cod_sucursal"], m3_capacity["cupo"], strict=False))
    cap = cap_m1()

    alerts = contracts["alertas"]
    level_alert = _risk_level_map(alerts, ("m1", "m2", "m3"))
    zero = cfg["costo_cero_sucursal"]

    # Correcciones v2 (cada una detras de su interruptor de conf/alx.yml; apagadas = comportamiento previo).
    with_level = alx.interruptor("nivel_riesgo_previo")
    with_interurban = alx.interruptor("m2_tarifa_interurbana")
    with_min_collection = alx.interruptor("monto_minimo_recoleccion")
    texts_v2 = cfg.get("textos_v2") or {}
    attrs = masters.atm_attributes_m1_m2(cutoff) if (with_interurban or with_min_collection) else None
    map_attrs = attrs.set_index("cod_cajero").to_dict("index") if attrs is not None else {}
    factor_collection = None
    if with_min_collection:
        from daas.modules.branches_m3.config import load_config as load_m3
        from daas.modules.branches_m3.policy import load_policy, min_collection_factor

        factor_collection = min_collection_factor(load_policy(load_m3()))
    flows_day: dict[tuple[str, str, str], tuple[float, float]] = {}
    insufficient: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    fallback_level = 0
    if with_level:
        flows_day = _daily_flows(contracts["predicciones"])

    def _context(mdl: str, code: str) -> tuple[str | None, str | None, Any]:
        if mdl in ("m1", "m2"):
            capacity_m = map_cp_capacity.get(code)
            if mdl == "m1" and cap is not None and capacity_m is not None and pd.notna(capacity_m):
                capacity_m = min(float(capacity_m), cap)  # RN-09: cupo operativo de M1
            return (
                capitalize_city(map_cp_city.get(code)),
                administration_type(map_cp_admin.get(code)),
                capacity_m,
            )
        return capitalize_city(map_m3_city.get(code)), na, map_m3_capacity.get(code)

    if with_level:
        entity_keys = {(m, c) for m, c, _ in flows_day}
        capacities = {}
        for m, c in entity_keys:
            value = _context(m, c)[2]
            capacities[(m, c)] = None if value is None or pd.isna(value) else float(value)
        insufficient = entidades_cupo_insuficiente(flows_day, capacities)

    rows = []
    for _, row in rec.iterrows():
        mdl, code = str(row["modelo"]), row["cod_cajero"]
        action = row.get("accion")
        city, kind_admin, capacity_master = _context(mdl, code)
        capacity = to_integer(row.get("cupo")) if pd.notna(row.get("cupo")) else to_integer(capacity_master)
        amount = to_integer(row.get("monto"))
        before = to_integer(row.get("saldo_antes"))
        after = to_integer(row.get("saldo_despues"))
        if after is None and before is not None and amount is not None:
            after = before + amount if str(action) == "provision" else before - amount
        level = level_by_occupancy(after, capacity, cfg["nivel_riesgo"]) or _alerts_level(
            level_alert.get((mdl, code)), cfg
        )
        explanation = row.get("explicacion")
        if explanation is None or (isinstance(explanation, float) and pd.isna(explanation)):
            explanation = _explanation_m1_m3(row, kind_admin if mdl != "m3" else None)
        cost = to_integer(row.get("costo"))
        if cost is None and mdl in ("m1", "m2"):
            if str(map_cp_admin.get(code)).strip().upper() == str(zero["admon"]).upper():
                cost = 0  # RN-04A: sin tarifa TDV, costo 0 declarado
                explanation = f"{explanation or ''} {zero['texto']}".strip()
            else:
                explanation = f"{explanation or ''} {zero['texto_tdv_sin_tarifa']}".strip()
        extra: list[str] = []
        info = map_attrs.get(code, {}) if mdl == "m2" else {}
        is_tdv_mf = kind_admin == "TDV" and str(info.get("tipo_facturacion", "")).strip().upper() == "MF"
        if with_interurban and is_tdv_mf and mf_es_interurbano(info.get("municipio"), info.get("ciudad")):
            extra.append(
                texts_v2["mf_interurbano"].format(
                    municipio=capitalize_city(info.get("municipio")), ciudad=capitalize_city(info.get("ciudad"))
                )
            )
        if (
            with_min_collection
            and mdl == "m2"
            and str(action) == "recoleccion"
            and kind_admin == "TDV"
            and pd.notna(row.get("costo"))
            and float(row.get("monto")) <= factor_collection * float(row.get("costo"))
        ):
            extra.append(texts_v2["m2_antieconomica"])
        if with_level:
            previous = nivel_riesgo_previo(
                {**row.to_dict(), "modelo": mdl},
                flows_day.get((mdl, code, str(pd.Timestamp(row.get("fecha_sugerida")).date()))),
                None if capacity is None else float(capacity),
                cfg["nivel_riesgo_previo"],
            )
            if previous is None:
                fallback_level += 1
                level = _alerts_level(level_alert.get((mdl, code)), cfg)
            else:
                level = previous[0]
                extra.append(texts_v2["motivo_riesgo"][previous[1]])
            if (mdl, code) in insufficient:
                level = "alto"
                extra.append(_insufficient_text(insufficient[(mdl, code)], mdl, kind_admin, cfg))
            if level not in _LEVELS:
                raise ValueError(f"nivel_riesgo fuera de {_LEVELS}: {level!r} ({mdl} {code})")
        if extra:
            explanation = f"{explanation or ''} {' '.join(extra)}".strip()
        rows.append(
            {
                "id_proveedor": PROVIDER_ID,
                "modelo": mdl.upper(),
                "ciudad": city,
                "id_entidad": code,
                "tipo_administracion": kind_admin,
                "fecha_accion_sugerida": to_date_or_none(row.get("fecha_sugerida")),
                "accion_sugerida": action,
                "monto_sugerido_cop": amount,
                "nivel_riesgo": level,
                "regla_aplicada": _rule_label(mdl, action, row.get("regla"), cfg),
                "explicacion_funcional": explanation,
                # RN-03: cupo aplicable (el operativo de la simulacion; en M1, el de RN-09) y saldo
                # simulado antes de la accion. La plantilla calcula el saldo despues y la ocupacion.
                "cupo_entidad_cop": capacity,
                "saldo_antes_accion_cop": before,
                "porcentaje_ocupacion_antes": mark_formula("02_Plan_Operativo", "porcentaje_ocupacion_antes"),
                "saldo_despues_accion_cop": mark_formula("02_Plan_Operativo", "saldo_despues_accion_cop"),
                "costo_estimado_cop": cost,
            }
        )

    # RN-02: toda entidad M1-M3 con pronostico y sin accion tiene su fila `sin_accion`.
    pred = contracts["predicciones"]
    pred = pred[pred["modelo"].isin(("m1", "m2", "m3"))]
    with_action = {(str(m), str(c)) for m, c in zip(rec["modelo"], rec["cod_cajero"], strict=False)}
    entities = (
        pred.assign(cod_cajero=pred["cod_cajero"].astype(str))[["modelo", "cod_cajero"]]
        .drop_duplicates()
        .sort_values(["modelo", "cod_cajero"])
    )
    start = to_date_or_none(cfg["horizonte"]["inicio"])
    sa = cfg["sin_accion"]
    for mdl, code in zip(entities["modelo"], entities["cod_cajero"], strict=False):
        if (str(mdl), code) in with_action:
            continue
        city, kind_admin, capacity_master = _context(str(mdl), code)
        capacity = to_integer(capacity_master)
        worst = level_alert.get((str(mdl), code))
        severity = {v: k for k, v in cfg["nivel_riesgo"]["respaldo_alertas"].items()}.get(worst)
        explanation_sa = (
            sa["explicacion_con_alerta"].format(severidad=severity) if worst else sa["explicacion_sin_alerta"]
        )
        level_sa = worst or cfg["nivel_riesgo"]["por_defecto"]
        if with_level and (str(mdl), code) in insufficient:  # SUP-44: el cupo insuficiente prevalece
            level_sa = "alto"
            explanation_sa = (
                f"{explanation_sa} "
                f"{_insufficient_text(insufficient[(str(mdl), code)], str(mdl), kind_admin, cfg)}"
            )
        rows.append(
            {
                "id_proveedor": PROVIDER_ID,
                "modelo": str(mdl).upper(),
                "ciudad": city,
                "id_entidad": code,
                "tipo_administracion": kind_admin,
                "fecha_accion_sugerida": start,
                "accion_sugerida": "sin_accion",
                "monto_sugerido_cop": 0,
                "nivel_riesgo": level_sa,
                "regla_aplicada": sa["regla"],
                "explicacion_funcional": explanation_sa,
                "cupo_entidad_cop": capacity,
                "saldo_antes_accion_cop": na,
                "porcentaje_ocupacion_antes": mark_formula("02_Plan_Operativo", "porcentaje_ocupacion_antes"),
                "saldo_despues_accion_cop": mark_formula("02_Plan_Operativo", "saldo_despues_accion_cop"),
                "costo_estimado_cop": na,
            }
        )
    if fallback_level:
        logger.warning("nivel_riesgo_previo: %d acciones sin pronostico o cupo; nivel por alertas.", fallback_level)
    out = pd.DataFrame(rows, columns=HEADERS["02_Plan_Operativo"])
    return out.sort_values(["modelo", "id_entidad", "fecha_accion_sugerida"]).reset_index(drop=True)


def _cop(value: float) -> str:
    """Pesos enteros con separador de miles colombiano."""
    return f"{float(value):,.0f}".replace(",", ".")


def nivel_riesgo_previo(
    row: dict[str, Any], flows: tuple[float, float] | None, capacity: float | None, cfg: dict[str, Any]
) -> tuple[str, str] | None:
    """Nivel de riesgo ANTES de la accion (SUP-42; interruptor `nivel_riesgo_previo`).

    Provision: `sin = saldo_antes + entradas - salidas` del dia (sin la provision). M1/M2: `sin <= 0` -> alto
    (agotamiento; RN-12, RN-21, RN-38); `0 < sin < umbral x cupo` -> medio (RN-34; el borde exacto del 8 % queda
    fuera, igual que las alertas); resto -> bajo (provision preventiva). M3: `sin <= 0` -> alto; resto -> medio
    (toda provision de M3 nace de un saldo previsto bajo la reserva preventiva; RN-40, RN-44); nunca bajo.
    Recoleccion M2: medio (saldo al cierre sobre el cupo, RN-35). Recoleccion M3: alto si el saldo al cierre supera
    el cupo (regla `exceso_sobre_cupo`, RN-38); si no, bajo (efectivo ocioso, RN-40).

    Args:
        row: Accion con `modelo`, `accion`, `saldo_antes` y `regla` (M3).
        flows: `(entradas, salidas)` del dia redondeadas al peso, o None si no hay pronostico del dia.
        capacity: Cupo aplicable.
        cfg: Bloque `nivel_riesgo_previo` de la configuracion (`umbral`).

    Returns:
        tuple[str, str] | None: `(nivel, motivo)`, o None si faltan datos (el llamador usa el respaldo).
    """
    mdl, action = str(row.get("modelo")), str(row.get("accion"))
    threshold = float(cfg.get("umbral", 0.08))
    if action == "recoleccion":
        if mdl == "m2":
            return "medio", "sobre_cupo"
        if mdl == "m3":
            return ("alto", "exceso_cupo") if str(row.get("regla")) == "exceso_sobre_cupo" else ("bajo", "ocioso")
        return None
    if action != "provision" or flows is None or capacity is None or not capacity > 0:
        return None
    before = row.get("saldo_antes")
    if before is None or pd.isna(before):
        return None
    without = float(before) + float(flows[0]) - float(flows[1])
    if without <= 0:
        return "alto", "agotamiento"
    if without < threshold * float(capacity):
        return "medio", "bajo_umbral"
    if mdl == "m3":
        return "medio", "bajo_reserva"
    return "bajo", "preventiva"


def _daily_flows(pred: pd.DataFrame) -> dict[tuple[str, str, str], tuple[float, float]]:
    """`(modelo, entidad, fecha ISO) -> (entradas, salidas)` del pronostico, redondeadas al peso como la simulacion."""
    sub = pred[pred["modelo"].isin(("m1", "m2", "m3"))].copy()
    sub["cod_cajero"] = sub["cod_cajero"].astype(str)
    sub["fecha"] = pd.to_datetime(sub["fecha"]).dt.date.astype(str)
    sub["yhat"] = np.round(pd.to_numeric(sub["yhat"], errors="coerce").fillna(0.0))
    wide = sub.pivot_table(index=["modelo", "cod_cajero", "fecha"], columns="objetivo", values="yhat", aggfunc="sum")
    out: dict[tuple[str, str, str], tuple[float, float]] = {}
    for (mdl, code, date), values in wide.iterrows():
        if mdl == "m1":
            flows = (0.0, float(values.get("pagado", 0.0) or 0.0))
        elif mdl == "m2":
            flows = (float(values.get("cash_in", 0.0) or 0.0), float(values.get("pagado", 0.0) or 0.0))
        else:
            flows = (float(values.get("entradas", 0.0) or 0.0), float(values.get("salidas", 0.0) or 0.0))
        out[(str(mdl), str(code), str(date))] = tuple(0.0 if pd.isna(v) else v for v in flows)
    return out


def entidades_cupo_insuficiente(
    flows: dict[tuple[str, str, str], tuple[float, float]], capacities: dict[tuple[str, str], float | None]
) -> dict[tuple[str, str], list[tuple[str, float, float]]]:
    """Entidades cuyo flujo neto de salida pronosticado supera su cupo en algun dia (SUP-44; RN-18, RN-21).

    Neto = salidas - entradas del dia (M1 pagado; M2 pagado - cash_in; M3 salidas - entradas) frente al cupo
    aplicable (M1 operativo de RN-09; M2 cupo; M3 `cupo_max_suc`).

    Returns:
        dict: `(modelo, entidad) -> [(fecha ISO, neto, cupo), ...]` solo con los dias en que neto > cupo.
    """
    out: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    for (mdl, code, date), (inflow, outflow) in sorted(flows.items()):
        capacity = capacities.get((mdl, code))
        if capacity is None or pd.isna(capacity) or not float(capacity) > 0:
            continue
        net = float(outflow) - float(inflow)
        if net > float(capacity):
            out.setdefault((mdl, code), []).append((date, net, float(capacity)))
    return out


def _insufficient_text(days: list[tuple[str, float, float]], mdl: str, kind_admin: str | None, cfg: dict) -> str:
    """Frase de cupo insuficiente (SUP-44) con los dias, el neto maximo, el cupo y la demanda no atendida minima."""
    texts = cfg["textos_v2"]["cupo_insuficiente"]
    template = texts["m2_sucursal"] if mdl == "m2" and kind_admin == "Sucursal" else texts["general"]
    dates = ", ".join(pd.Timestamp(d).strftime("%d-%m-%Y") for d, _, _ in days)
    return template.format(
        n=len(days),
        fechas=dates,
        max_neto=_cop(max(n for _, n, _ in days)),
        cupo=_cop(days[0][2]),
        exceso=_cop(sum(n - c for _, n, c in days)),
    )


def _alerts_level(worst: str | None, cfg: dict[str, Any]) -> str:
    """Respaldo del nivel de riesgo: la peor severidad de `alertas`, o el nivel por defecto."""
    return worst or str(cfg["nivel_riesgo"]["por_defecto"])


def _explanation_m1_m3(row: pd.Series, kind_admin: str | None = None) -> str | None:
    """Explicacion funcional de la accion M1-M3 con las cifras de la simulacion (RN-03, RN-29).

    Args:
        row: Fila de `recomendaciones` (M1-M3), con `saldo_antes`, `saldo_despues` y `cupo`.
        kind_admin: Tipo de administracion ya derivado (TDV o sucursal), para RN-29.

    Returns:
        str | None: Explicacion funcional, o ``None`` si no hay accion.
    """
    action = row.get("accion")
    if action is None or (isinstance(action, float) and pd.isna(action)):
        return None
    before, after, capacity = (to_integer(row.get(c)) for c in ("saldo_antes", "saldo_despues", "cupo"))
    who = f" Equipo administrado por {kind_admin}." if kind_admin else ""
    if None in (before, after, capacity):
        return f"Accion '{action}' sugerida por la simulacion de saldo.{who}"
    before, after, capacity = (f"{v:,}".replace(",", ".") for v in (before, after, capacity))
    if str(action) == "provision":
        return (
            f"Provision en la manana, antes del pagado: con el pronostico, sin provision el saldo bajaria del "
            f"8 % del cupo ese dia. Lleva el saldo de {before} a {after} COP (cupo {capacity}).{who}"
        )
    if str(action) == "recoleccion":
        return (
            f"Recoleccion al cierre: con el pronostico, el saldo cerraria en {before} COP, sobre el cupo de "
            f"{capacity}. Se recoge el excedente y el saldo queda en {after} COP.{who}"
        )
    return f"Accion '{action}' sugerida por la simulacion de saldo.{who}"


def _risk_level_map(alerts: pd.DataFrame, models: tuple[str, ...]) -> dict[tuple[str, str], str]:
    """Mapa ``(modelo, cod_cajero) -> nivel_riesgo`` desde la peor severidad.

    `critico` -> 'alto', `alerta` -> 'medio'. Sin alerta -> no entra (se trata
    como 'bajo' en la hoja).

    Args:
        alerts: Contrato de alertas.
        models: Modelos a considerar.

    Returns:
        dict[tuple[str, str], str]: nivel_riesgo por (modelo, entidad).
    """
    severity_to_level = {"critico": "alto", "alerta": "medio"}
    order = {"alto": 2, "medio": 1}
    out: dict[tuple[str, str], str] = {}
    sub = alerts[alerts["modelo"].isin(models)]
    for _, row in sub.iterrows():
        key = (str(row["modelo"]), str(row["cod_cajero"]))
        level = severity_to_level.get(str(row["severidad"]))
        if level is None:
            continue
        if key not in out or order[level] > order[out[key]]:
            out[key] = level
    return out
