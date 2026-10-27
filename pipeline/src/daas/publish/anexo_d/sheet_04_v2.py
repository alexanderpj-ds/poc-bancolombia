"""Hoja `04_Descripcion_Solucion` v2 (interruptor `hoja04_v2` de conf/alx.yml).

Textos para el evaluador desde ``export_anexo_d.yml -> hoja_04_v2`` (sin identificadores internos, con tildes) y
cifras de las salidas de la corrida. Lo que describe un comportamiento detras de un interruptor usa la variante
`on`/`off` de ese interruptor (`variante`). El enfoque y las variables salen del modelo publicado de verdad: la receta
de cada fila se resuelve a su modelo (`_modelo_resuelto`) y sus grupos de variables se recorren por familia
(`grupos_modelo`); un modelo, grupo o familia sin texto da `KeyError` (nunca se publica un identificador).
La validacion de los textos (prohibidos, tildes, oraciones repetidas, SUP con titulo) la hace
`publish.validate_xlsx.validate_anexo_d`.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

import pandas as pd

from daas import alx
from daas.publish.anexo_d.constants import HEADERS, PROVIDER_ID

logger = logging.getLogger(__name__)

#: Orden de presentacion de los grupos de variables.
_GROUP_ORDER = (
    "base", "calendario", "pago", "dom_entidad", "pago_detalle", "festivo_detalle", "temporada", "rezagos", "anual",
    "perfil_entidad", "intermitencia", "contexto", "entidad_cat", "prophet_calendario", "perfil_dom",
)

#: Forma de incorporacion de cada grupo de calendario (RN-04).
_CALENDAR_INCORPORATION = {
    "calendario": "día del mes, días al fin de mes, festivo, víspera, día siguiente y día hábil",
    "pago": "días desde y hasta el pago",
    "pago_detalle": "día de pago, quincena o fin de mes y días hábiles desde y hasta el pago",
    "festivo_detalle": "puentes y largo del bloque no hábil",
    "prophet_calendario": "regresores de pago y festivos en el componente de series de tiempo",
}

#: Operacion del contrato M6 -> nombre de RN-84.
_RN84 = {
    "traslado": "traslado_fondos",
    "venta": "venta_efectivo",
    "banrep_consignacion": "consignacion_banrep",
    "banrep_retiro": "retiro_banrep",
    "cambio_denominacion": "cambio_denominacion",
    "intercambio": "intercambio_bancos",
}

_TARGET_LABEL = {"m1:pagado": "pagado de M1", "m2:pagado": "pagado de M2", "m2:cash_in": "cash-in de M2"}


def variante(block: dict[str, Any], switch: str) -> str:
    """Variante `on`/`off` del bloque segun el interruptor; falta la variante -> KeyError (configuracion incompleta)."""
    return str(block["encendido" if alx.interruptor(switch) else "apagado"])


def _dec(value: float, places: int) -> str:
    """Decimal con coma (``0,2490``)."""
    return f"{float(value):.{places}f}".replace(".", ",")


def _cop(value: float) -> str:
    """Pesos enteros con punto de miles (``1.360.258.526``)."""
    return f"{float(value):,.0f}".replace(",", ".")


def _pct(value: float, places: int = 0) -> str:
    """Porcentaje con coma (``8 %``, ``46,1 %``)."""
    return f"{100 * float(value):.{places}f}".replace(".", ",") + " %"


def _signed(value: float, places: int = 1) -> str:
    """Fraccion con signo como porcentaje (``-6,9 %``)."""
    text = f"{100 * float(value):+.{places}f}".replace(".", ",")
    return text.replace("-", "−") + " %"


def _recipes_yml() -> dict[str, Any]:
    from daas.forecasting import forecasters

    return forecasters.load_recipes().get("recetas") or {}


def _model_conf(model: str, recipes: dict[str, Any]) -> dict[str, Any]:
    """Configuracion de un modelo: la congelada del laboratorio (`ml.pronosticar._yml`) o la receta del pipeline."""
    try:
        from ml import pronosticar
    except ImportError as error:  # la familia ml_laboratorio lo usa en la misma corrida
        if model in recipes:
            return dict(recipes[model])
        raise RuntimeError(f"No se puede leer la configuracion de {model!r} (ml.pronosticar no disponible).") from error
    conf = pronosticar._yml(model)
    if conf is None:
        path = pronosticar.ENSAMBLES_CONF / f"{model}.yml"
        if path.exists():
            import yaml

            conf = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(conf or recipes.get(model) or {})


def modelo_resuelto(recipe: str, recipes: dict[str, Any]) -> str:
    """Id del modelo publicado detras de una receta (`campeon_m1` -> `ml_lgbm_v4_tw`; nativa -> ella misma)."""
    return str((recipes.get(recipe) or {}).get("modelo", recipe))


def _members(conf: dict[str, Any]) -> list[tuple[str, float]]:
    members = list(conf.get("miembros") or [])
    weights = conf.get("pesos")
    weights = [1.0] * len(members) if not weights else [float(w) for w in weights]
    return list(zip(members, weights, strict=True))


def grupos_modelo(model: str, recipes: dict[str, Any], h4: dict[str, Any]) -> list[str]:
    """Grupos de variables del modelo, recorriendo combinaciones (solo miembros con peso > 0) por familia."""
    from daas.forecasting import global_ml

    conf = _model_conf(model, recipes)
    family = conf.get("familia")
    if family == "combinacion":
        out: list[str] = []
        for member, weight in _members(conf):
            if weight > 0:
                out += grupos_modelo(member, recipes, h4)
        return list(dict.fromkeys(out))
    if family == "ml_global":
        return global_ml.resolver_grupos(
            conf.get("conjunto"), conf.get("grupos"), bool(conf.get("entidad_categorica", False))
        )
    if family == "gbm_global":
        return list(conf["grupos"])
    if family in (h4.get("grupos_modelos_base") or {}):
        return list(h4["grupos_modelos_base"][family])
    raise KeyError(f"Familia sin grupos de variables para la hoja 04: {family!r} ({model})")


def _approach(model: str, n_entities: int, recipes: dict[str, Any], h4: dict[str, Any]) -> str:
    """Texto de `algoritmo_o_enfoque` del modelo publicado (KeyError si no tiene entrada en `enfoques`)."""
    template = h4["enfoques"][model]
    conf = _model_conf(model, recipes)
    members = [(m, w) for m, w in _members(conf) if w > 0] if conf.get("familia") == "combinacion" else []
    names = h4["nombres_modelos"]
    if members and conf.get("pesos"):
        total = sum(w for _, w in members)
        ordered = sorted(members, key=lambda mw: -mw[1])
        listing = ", ".join(f"{names[m]} ({_pct(w / total, 1)})" for m, w in ordered)
    else:
        listing = ", ".join(names[m] for m, _ in members)
    return template.format(n_entidades=n_entities, n_miembros=len(members), miembros=listing)


def _variables(groups: list[str], h4: dict[str, Any]) -> str:
    """`variables_utilizadas`: frase de cada grupo del modelo y la definicion de calendario de RN-04."""
    phrases = h4["grupos"]
    ordered = [g for g in _GROUP_ORDER if g in groups] + [g for g in groups if g not in _GROUP_ORDER]
    text = h4["variables_prefijo"].format(grupos="; ".join(phrases[g] for g in ordered))
    incorporation = [_CALENDAR_INCORPORATION[g] for g in ordered if g in _CALENDAR_INCORPORATION]
    calendar = h4["bloques"]["calendario_rn04"].format(incorporacion="; ".join(incorporation))
    return f"{text} {calendar}"


def _importance_rows(importances: pd.DataFrame | None, mdl: str, target: str) -> pd.DataFrame:
    if importances is None or importances.empty:
        return pd.DataFrame(columns=["grupo", "valor", "receta"])
    return importances[
        (importances["modelo"].astype(str).str.upper() == mdl)
        & (importances["objetivo"].astype(str) == target)
        & (importances["tipo"] == "permutacion")
    ].sort_values("valor", ascending=False)


def _relevant(importances: pd.DataFrame | None, mdl: str, target: str, recipe: str, h4: dict[str, Any]) -> str:
    texts = h4["importancia"]
    d = _importance_rows(importances, mdl, target)
    d = d[d["valor"] > 0].head(3)
    if d.empty:
        return "Sin medición de importancia en esta corrida."
    parts = "; ".join(
        f"{texts['nombres'][str(g)]} ({_dec(100 * float(v), 1)})" for g, v in zip(d["grupo"], d["valor"], strict=False)
    )
    scope = texts["modelo_publicado"] if str(d["receta"].iloc[0]) == recipe else texts["componente"]
    return texts["texto"].format(grupos=parts, alcance=scope)


def _festivos_aporte(importances: pd.DataFrame | None, mdl: str, target: str) -> str:
    d = _importance_rows(importances, mdl, target)
    d = d[d["grupo"] == "festivos"]
    return _dec(100 * float(d["valor"].iloc[0]), 1) if not d.empty else "sin medición"


def _backtest_rows(met: pd.DataFrame, mdl: str, target: str, prefix: str) -> tuple[pd.Series | None, pd.Series | None]:
    """Filas `backtest` de `metricas` (lectura de entrenamiento, lectura RN-08) del modelo y objetivo."""
    sub = met[(met["modelo"] == mdl.lower()) & (met["bloque"] == "backtest")]
    if "objetivo" in sub.columns:
        sub = sub[sub["objetivo"].fillna(target).astype(str) == target]
    is_rn08 = sub["nota"].fillna("").astype(str).str.startswith(prefix)
    base, rn08 = sub[~is_rn08], sub[is_rn08]
    return (base.iloc[0] if not base.empty else None), (rn08.iloc[0] if not rn08.empty else None)


def wape_m3_lecturas(backtest: pd.DataFrame, target: str, published: float | None) -> tuple[float, float]:
    """WAPE de M3 con la formula literal del §8 (todas las sucursales) y con la exclusion de SUP-27.

    La segunda debe coincidir con la publicada en `metricas` (|dif| <= 1e-12); si no, ValueError.
    """
    bt = backtest[(backtest["modelo"] == "m3") & (backtest["objetivo"].astype(str) == target)].dropna(
        subset=["y", "yhat"]
    )
    err = (bt["y"] - bt["yhat"]).abs()
    literal = float(err.sum() / bt["y"].abs().sum())
    denominators = bt.assign(_a=bt["y"].abs()).groupby(bt["cod_cajero"].astype(str))["_a"].sum()
    keep = bt["cod_cajero"].astype(str).isin(denominators[denominators > 0].index)
    sup27 = float(err[keep].sum() / bt.loc[keep, "y"].abs().sum())
    if published is not None and abs(sup27 - float(published)) > 1e-12:
        raise ValueError(f"WAPE M3 {target}: {sup27} recalculado frente a {published} publicado (SUP-27).")
    return literal, sup27


def _periods_text(periods: dict[str, tuple[_dt.date, _dt.date]], mdl: str) -> dict[str, str]:
    since, until = periods.get(mdl.lower(), periods["m1"])
    return {"desde": since.strftime("%d-%m-%Y"), "hasta": until.strftime("%d-%m-%Y")}


def _anexo_c(h4: dict[str, Any], key: str) -> str | None:
    try:
        from daas.quality.anexo_c import anexo_c_window

        window = anexo_c_window()
    except Exception as error:  # noqa: BLE001  (sin ventana no se inventa el texto)
        logger.warning("No se pudo leer la ventana del Anexo C (%s).", error)
        return None
    if not window:
        return None
    from daas.publish.anexo_d.sheet_04_description import _contiguous_blocks

    blocks = _contiguous_blocks(window)
    names = "; ".join(
        b[0].strftime("%d-%m-%Y") if len(b) == 1 else f"{b[0].strftime('%d-%m-%Y')} a {b[-1].strftime('%d-%m-%Y')}"
        for b in blocks
    )
    b = h4["bloques"]
    base = b["anexo_c"].format(n_dias=len(window), bloques=f"{len(blocks)} bloques: {names}")
    return f"{base} {b['anexo_c_efecto'].format(**b['anexo_c_cifras'][key])}"


def _silent(mdl: str, contracts: dict[str, pd.DataFrame], h4: dict[str, Any]) -> str | None:
    sil = contracts.get("silenciosos")
    if sil is None:
        return None
    sub = sil[sil["modelo"].astype(str).str.lower() == mdl.lower()]
    codes = sorted(sub["cod_cajero"].astype(str).unique())
    if not codes:
        return None
    treatments = "; ".join(sorted(sub["tratamiento"].dropna().astype(str).unique())) or "sin tratamiento declarado"
    return h4["bloques"]["silenciosos"].format(n=len(codes), codigos=", ".join(codes), tratamientos=treatments)


def _m2_interurban_counts(contracts: dict[str, pd.DataFrame], cutoff: _dt.date) -> tuple[int, int]:
    from daas.costs.anexo_e import mf_es_interurbano
    from daas.publish.anexo_d import masters

    rec = contracts["recomendaciones"]
    rec = rec[(rec["modelo"] == "m2") & ~rec["sin_transportadora"].fillna(False).astype(bool)]
    attrs = masters.atm_attributes_m1_m2(cutoff).set_index("cod_cajero")
    hits = []
    for code in rec["cod_cajero"].astype(str):
        if code not in attrs.index:
            continue
        a = attrs.loc[code]
        if str(a["tipo_facturacion"]).strip().upper() == "MF" and mf_es_interurbano(a["municipio"], a["ciudad"]):
            hits.append(code)
    return len(hits), len(set(hits))


def _m3_scale_differences() -> int:
    from daas.io import storage

    offices = storage.read_table("daas://interim/oficinas")
    n = 0
    for location, scale in zip(offices["ubicacion"], offices["escalas"], strict=False):
        m = re.match(r"^INTERURBANO (\d+)$", " ".join(str(location).split()).upper())
        if m and pd.notna(scale) and float(scale).is_integer() and int(float(scale)) >= 1 and int(m.group(1)) != int(
            float(scale)
        ):
            n += 1
    return n


def _m3_policy(contracts: dict[str, pd.DataFrame], h4: dict[str, Any], start: _dt.date) -> str:
    from daas.modules.branches_m3.config import load_config as load_m3

    pol = load_m3().get("politica") or {}
    rec = contracts["recomendaciones"]
    rec = rec[(rec["modelo"] == "m3") & (rec["accion"] == "recoleccion")]
    day1 = rec[pd.to_datetime(rec["fecha_sugerida"]).dt.date == start]
    return h4["bloques"]["m3_politica"].format(
        reserva_max=_pct(float(pol["reserva_max"])),
        dias_cobertura=pol["dias_cobertura"],
        dias_techo=pol["dias_techo"],
        historia_dias=pol["historia_dias"],
        min_obs=pol["min_obs"],
        dia1_n=len(day1),
        dia1_monto=_cop(pd.to_numeric(day1["monto"], errors="coerce").sum()),
    )


def _m3_omissions(met: pd.DataFrame, h4: dict[str, Any]) -> str:
    block = h4["bloques"]["m3_omisiones"]
    if not alx.interruptor("monto_minimo_recoleccion"):
        return str(block["apagado"])
    row = met[(met["modelo"] == "m3") & (met["bloque"] == "recoleccion_omitida_monto")]
    if row.empty:
        raise ValueError("Falta la fila recoleccion_omitida_monto de M3 en metricas (monto_minimo_recoleccion).")
    n = int(row["n_obs"].iloc[0])
    return block["cero"] if n == 0 else block["encendido"].format(n=n, cop=_cop(float(row["valor"].iloc[0])))


def _m6_operations(contracts: dict[str, pd.DataFrame], h4: dict[str, Any]) -> str:
    b = h4["bloques"]
    rec = contracts["recomendaciones"]
    rec = rec[(rec["modelo"] == "m6") & rec["operacion"].notna()]
    rec = rec[rec["operacion"].astype(str) != "sin_accion"]
    counts = rec["operacion"].astype(str).value_counts().to_dict()
    used, unused = [], []
    for op in ("traslado", "venta", "banrep_consignacion", "banrep_retiro", "cambio_denominacion", "intercambio"):
        n = int(counts.get(op, 0))
        name = _RN84[op]
        if n and op == "traslado":
            pairs = int(rec.loc[rec["operacion"] == op, "id_par"].nunique()) if "id_par" in rec.columns else n // 2
            used.append(f"{name} ({n} filas: {pairs} traslados, cada uno con su fila de salida y de entrada)")
        elif n:
            used.append(f"{name} ({n} filas)")
        elif op in ("banrep_consignacion", "banrep_retiro"):
            unused.append(f"{name} ({b['m6_no_usada']['banrep']})")
        elif op == "cambio_denominacion":
            unused.append(f"{name} ({variante(b['m6_no_usada']['cambio_denominacion'], 'm6_operaciones_rn84')})")
        else:
            unused.append(f"{name} ({variante(b['m6_no_usada']['intercambio_bancos'], 'm6_operaciones_rn84')})")
    unused.append(f"otra_accion_justificada ({b['m6_no_usada']['otra_accion_justificada']})")
    return variante(b["m6_operaciones"], "m6_operaciones_rn84").format(
        usadas="; ".join(used) or "ninguna", no_usadas="; ".join(unused)
    )


#: Frase del simulador en los faltantes del mismo dia que no admiten traslado (SUP-52).
_SAME_DAY_NO_TRANSFER = "un faltante de hoy no se cubre con un traslado de hoy"


def _m6_transfer(contracts: dict[str, pd.DataFrame], h4: dict[str, Any]) -> str:
    """Bloque SUP-52 (interruptor `m6_traslado_t1`): regla de disponibilidad del traslado y sus cifras."""
    block = h4["bloques"]["m6_traslado"]
    if not alx.interruptor("m6_traslado_t1"):
        return str(block["apagado"])
    rec = contracts["recomendaciones"]
    rec = rec[rec["modelo"] == "m6"]
    pairs = int(rec.loc[rec["operacion"].astype(str) == "traslado", "id_par"].nunique())
    same = rec[rec["motivo"].astype(str).str.contains(_SAME_DAY_NO_TRANSFER, regex=False)]
    if same.empty:
        figures = block["sin_mismo_dia"].format(pares=pairs)
    else:
        groups = same.groupby([same["fecha_sugerida"].astype(str), same["operacion"].astype(str)]).size()
        detail = "; ".join(
            f"{n} el {pd.to_datetime(f):%d/%m/%Y} con {_RN84.get(op, op)}" for (f, op), n in sorted(groups.items())
        )
        figures = block["cifras"].format(pares=pairs, n=len(same), detalle=detail)
    return " ".join(str(block["encendido"]).format(cifras=figures).split())


def _m6_transfer_tariff(contracts: dict[str, pd.DataFrame], h4: dict[str, Any]) -> str:
    """Bloque SUP-53 (interruptor `m6_tarifa_traslado_declarada`): tarifa usada y alternativa, de `metricas`."""
    block = h4["bloques"]["m6_tarifa_traslado"]
    if not alx.interruptor("m6_tarifa_traslado_declarada"):
        return str(block["apagado"])
    met = contracts["metricas"]
    row = met[(met["modelo"] == "m6") & (met["bloque"] == "costo_traslado_tarifa_destino")]
    if row.empty:
        raise ValueError(
            "Falta la fila costo_traslado_tarifa_destino de M6 en metricas (m6_tarifa_traslado_declarada)."
        )
    rec = contracts["recomendaciones"]
    rec = rec[(rec["modelo"] == "m6") & (rec["operacion"].astype(str) == "traslado")]
    used = float(pd.to_numeric(rec["costo"], errors="coerce").fillna(0.0).sum())
    return block["encendido"].format(
        n=int(row["n_obs"].iloc[0]), usado=_cop(used), alterno=_cop(float(row["valor"].iloc[0]))
    )


def _m6_branch_atms(contracts: dict[str, pd.DataFrame], h4: dict[str, Any]) -> str:
    block = h4["bloques"]["m6_cajeros_sucursal"]
    if not alx.interruptor("m6_cajeros_sucursal"):
        return str(block["apagado"])
    met = contracts["metricas"]
    mapped = met[(met["modelo"] == "m6") & (met["bloque"] == "cajeros_sucursal_mapeados")]
    if mapped.empty:
        raise ValueError("Falta la fila cajeros_sucursal_mapeados de M6 en metricas (m6_cajeros_sucursal).")
    n_map, n_excl = int(mapped["n_obs"].iloc[0]), int(mapped["n_excluidas"].iloc[0])
    lost = met[(met["modelo"] == "m6") & (met["bloque"] == "flujo_sin_fondo")]
    excluded = block["sin_excluidos"]
    if not lost.empty:
        codes: list[str] = []
        for note in lost["nota"].astype(str):
            m = re.search(r"cajeros ([\d, ]+);", note)
            codes += [c.strip() for c in m.group(1).split(",")] if m else []
        detail = " y ".join(
            f"{_cop(v)} COP de {_TARGET_LABEL.get(str(t), str(t))}"
            for t, v in zip(lost["objetivo"], lost["valor"], strict=False)
        )
        unique = sorted(set(codes))
        excluded = block["excluidos"].format(n=len(unique), codigos=", ".join(unique), detalle=detail)
    case = ""
    pred = contracts["predicciones"]
    p2691 = pred[(pred["modelo"] == "m1") & (pred["cod_cajero"].astype(str) == "2691") & (pred["objetivo"] == "pagado")]
    if not p2691.empty:
        case = block["caso_2691"].format(cop=_cop(pd.to_numeric(p2691["yhat"], errors="coerce").sum()))
    return block["encendido"].format(mapeados=n_map, total=n_map + n_excl, excluidos=excluded, caso_2691=case).strip()


def _supuestos(codes: list[str], h4: dict[str, Any]) -> str:
    titles = h4["sup_titulos"]
    return "; ".join(f"SUP-{c} ({titles[c]})" for c in codes) + "."


def sheet_04_v2(
    contracts: dict[str, pd.DataFrame], cfg: dict[str, Any], ctx: dict[str, Any], rows_base: list[dict[str, Any]]
) -> pd.DataFrame:
    """Construye la hoja 04 v2 (8 filas, 13 columnas de la plantilla).

    Args:
        contracts: Contratos cargados (obligatorios: las cifras salen de ahi).
        cfg: Configuracion de ``export_anexo_d.yml`` (usa `hoja_04_v2`, `hoja_03`, `horizonte`).
        ctx: Contexto de `sheet_04_description._sheet_04_context` (recetas, importancias, m1).
        rows_base: Filas base de la hoja 04 (modelo y variable objetivo, en orden).
    """
    from daas.publish.anexo_d.cell_values import to_date_or_none
    from daas.publish.anexo_d.sheet_03_metrics import backtest_periods

    if not alx.interruptor("supuestos_alx"):
        raise ValueError("hoja04_v2 exige el interruptor supuestos_alx encendido (D-4).")
    h4 = cfg["hoja_04_v2"]
    b = h4["bloques"]
    recipes = _recipes_yml()
    met = contracts["metricas"]
    pred = contracts["predicciones"]
    cutoff = to_date_or_none(cfg.get("corte"))
    start = to_date_or_none(cfg["horizonte"]["inicio"])
    periods = backtest_periods(cutoff)
    prefix = cfg["hoja_03"]["lectura_rn08"]["prefijo_nota"]
    m1 = ctx["m1"]
    policy = m1.get("politica") or {}
    lead = int(m1.get("lead_time_dias", 0))
    out = []
    for base_row in rows_base:
        mdl, target = base_row["modelo"], base_row["variable_objetivo_evaluada"]
        key = f"{mdl}|{target}"
        row_cfg = h4["filas"][key]
        n_entities = int(pred.loc[pred["modelo"] == mdl.lower(), "cod_cajero"].astype(str).nunique())
        common = [b["procedencia"], b["entrega"]]
        if mdl == "M6":
            approach, variables, relevant = row_cfg["enfoque"], row_cfg["variables"], row_cfg["relevantes"]
            methodology = row_cfg["metodologia"]
            limits = [
                b["m6_base"],
                _m6_operations(contracts, h4),
                _m6_branch_atms(contracts, h4),
                _m6_transfer(contracts, h4),
                _m6_transfer_tariff(contracts, h4),
                b["m6_resto"],
            ]
        else:
            recipe = ctx["recetas"][(mdl, target)]
            model = modelo_resuelto(recipe, recipes)
            groups = grupos_modelo(model, recipes, h4)
            approach = _approach(model, n_entities, recipes, h4)
            variables = _variables(groups, h4)
            relevant = _relevant(ctx["importancias"], mdl, target, recipe, h4)
            base_bt, rn08_bt = _backtest_rows(met, mdl, target, prefix)
            pt = _periods_text(periods, mdl)
            if mdl in ("M1", "M2"):
                methodology = h4["metodologia"]["m1_m2"].format(
                    objetivo=target, rn08=_dec(rn08_bt["wape"], 4), base=_dec(base_bt["wape"], 4), **pt
                )
            elif mdl == "M3":
                literal, sup27 = wape_m3_lecturas(contracts["backtest"], target, float(base_bt["wape"]))
                methodology = h4["metodologia"]["m3"].format(
                    objetivo=target, lit=_dec(literal, 4), sup27=_dec(sup27, 4), **pt
                )
            else:
                methodology = h4["metodologia"]["m4_m5"].format(objetivo=target, base=_dec(base_bt["wape"], 4), **pt)
            limits = [b["base"]]
            if base_bt is not None and pd.notna(base_bt["wape"]):
                limits.append(
                    b["cifras_objetivo"].format(
                        objetivo=target,
                        wape=_dec(base_bt["wape"], 3),
                        sesgo=_signed(base_bt["bias"]),
                        n_obs=_cop(base_bt["n_obs"]),
                    )
                )
            if mdl in ("M1", "M2"):
                limits += [_anexo_c(h4, key), _silent(mdl, contracts, h4), b["lecturas_rn08_nota"]]
            if mdl == "M1":
                limits.append(b["decisiones_m1"].format(lead=lead))
            if mdl == "M3":
                limits += [_m3_policy(contracts, h4, start), _m3_omissions(met, h4)]
            if mdl == "M5" and base_bt is not None:
                limits.append(b["m5"].format(wape=_dec(base_bt["wape"], 2)))
            if mdl in ("M1", "M2", "M3"):
                limits.append(variante(b["nivel_riesgo"], "nivel_riesgo_previo"))
            if mdl == "M1":
                limits.append(b["costo_m1"])
            if mdl == "M2":
                n_act, n_eq = _m2_interurban_counts(contracts, cutoff)
                limits.append(variante(b["costo_m2"], "m2_tarifa_interurbana").format(n_acciones=n_act, n_equipos=n_eq))
            if mdl == "M3":
                limits.append(variante(b["costo_m3"], "m3_escala_anexo_a").format(n_distintas=_m3_scale_differences()))
            limits.append(b["historia_corta"])
            if mdl in ("M1", "M2") and target == "pagado":
                limits.append(b["demanda_censurada"])
            if {"temporada", "festivo_detalle"} & set(groups):
                limits.append(b["eventos"].format(aporte=_festivos_aporte(ctx["importancias"], mdl, target)))
            limits.append(b["laboratorio"])
        transformation = row_cfg["transformacion"]
        if mdl == "M1":
            transformation = transformation.format(
                umbral=_pct(float(m1.get("umbral_agotamiento", 0.0))),
                margen=_pct(float(policy.get("margen", 0.0))),
                lead=lead,
            )
        out.append(
            {
                "id_proveedor": PROVIDER_ID,
                "modelo": mdl,
                "variable_objetivo_evaluada": target,
                "definicion_variable_objetivo": row_cfg["definicion"],
                "algoritmo_o_enfoque": " ".join(str(approach).split()),
                "variables_utilizadas": " ".join(str(variables).split()),
                "variables_mas_relevantes": relevant,
                "horizonte_prediccion": h4["horizonte"],
                "metodologia_validacion": " ".join(str(methodology).split()),
                "transformacion_a_decision_operativa": " ".join(str(transformation).split()),
                "limitaciones_identificadas": " ".join(" ".join(str(t) for t in [*limits, *common] if t).split()),
                "dependencias_externas": row_cfg["dependencias"],
                "supuestos": _supuestos(
                    [str(c) for c in row_cfg["supuestos"]]
                    + [
                        str(c)
                        for switch, codes in (row_cfg.get("supuestos_interruptor") or {}).items()
                        if alx.interruptor(switch)
                        for c in codes
                    ],
                    h4,
                ),
            }
        )
    return pd.DataFrame(out, columns=HEADERS["04_Descripcion_Solucion"])
