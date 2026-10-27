"""Hoja `04_Descripcion_Solucion`: enfoque real, variables relevantes, limitaciones y SUP-xx por modelo."""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

from daas import alx
from daas.io import storage
from daas.publish.anexo_d.cell_values import to_date_or_none
from daas.publish.anexo_d.config import resolve_config
from daas.publish.anexo_d.constants import HEADERS, METHODOLOGY, PROVIDER_ID
from daas.publish.anexo_d.sheet_03_metrics import rn08_text

logger = logging.getLogger(__name__)

#: Enfoque de respaldo cuando el modelo/objetivo no declara receta (`forecaster.modelo`): Prophet por
#: serie + fallback naive_estacional_7. Lo que corrio de verdad sale de `descripciones` (pronosticadores.yml).
_PROPHET_APPROACH = (
    "Prophet por serie (una por entidad) con fallback naive_estacional_7 cuando "
    "la serie no es modelable (pocos datos)."
)


_HORIZON_TEXT = "1 a 15 dias desde el corte (1-15 sep 2026)"


#: ALX (oct-2026): SUP agregados por fila (modelo, objetivo) de `docs/supuestos.md` (SUP-24 a SUP-40).
#: Procedencia (24-26) y anexos de la corrida (40) en todos; decisiones del laboratorio de ML en M1-M5 (27, 30, 31,
#: 33, 38), imputacion no adoptada (36) y champions finales en el pipeline (39); maestro "as of" (28) donde el champion
#: usa V4 (M1, M2 pagado, M5) o hay maestro (M2 cash_in, M3); correccion de datos (35) en M1-M3; pesos congelados (32)
#: donde el champion es un ponderado (M2, M3 entradas); demanda censurada (34) en `pagado` de M1/M2; ceros dudosos de
#: agosto (37) en M3; disponibles corregidos (29) en M6.
_ALX_SUP: dict[tuple[str, str], list[str]] = {
    ("M1", "pagado"): ["24", "25", "26", "27", "28", "30", "31", "33", "34", "35", "36", "38", "39", "40"],
    ("M2", "pagado"): ["24", "25", "26", "27", "28", "30", "31", "32", "33", "34", "35", "36", "38", "39", "40"],
    ("M2", "cash_in"): ["24", "25", "26", "27", "28", "30", "31", "32", "33", "35", "36", "38", "39", "40"],
    ("M3", "entradas"): ["24", "25", "26", "27", "28", "30", "31", "32", "33", "35", "36", "37", "38", "39", "40"],
    ("M3", "salidas"): ["24", "25", "26", "27", "28", "30", "31", "33", "35", "36", "37", "38", "39", "40"],
    ("M4", "ingreso_efectivo_cbr"): ["24", "25", "26", "27", "30", "31", "33", "36", "38", "39", "40"],
    ("M5", "ingreso_efectivo_clientes"): ["24", "25", "26", "27", "28", "30", "31", "33", "36", "38", "39", "40"],
    ("M6", "saldo_proyectado"): ["24", "25", "26", "29", "40"],
}


def _with_alx_sup(supuestos: str, mdl: str, target: str) -> str:
    """Agrega al texto de `supuestos` los SUP de ALX de la fila (`_ALX_SUP`)."""
    codes = _ALX_SUP.get((mdl, target))
    if not codes:
        return supuestos
    return f"{supuestos.rstrip().rstrip('.')}. ALX: " + ", ".join(f"SUP-{c}" for c in codes) + "."


_COMMON_LIMITATIONS = (
    "Holdout 1-15 sep con 0 observaciones reales (datos hasta 31-ago): la " "validacion es backtest interno (SUP-02)."
)


#: Filas de la hoja 04 (una por modelo x variable_objetivo), textos honestos con
#: los SUP-xx aplicables por modelo. 8 filas en total.
_SHEET_04_ROWS: list[dict[str, Any]] = [
    {
        "modelo": "M1",
        "variable_objetivo_evaluada": "pagado",
        "definicion_variable_objetivo": ("Efectivo entregado por el ATM dispensador en el dia (cdgtrn 220, 420, 520)."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": (
            "Observadas: pagado, cupo, admon, estado (maestro CP y desinstalados). "
            "Derivadas: rezagos (pagado t-7). Calendario CO (RN-04): festivos, "
            "quincenas y fin de mes."
        ),
        "variables_mas_relevantes": "Pagado t-7, dia de semana, quincena",
        "transformacion_a_decision_operativa": (
            "Trayectoria desde el cupo operativo (RN-09, RN-11); provision antes del "
            "pagado hasta el cupo el dia en que el saldo proyectado bajaria del 8% (RN-34)."
        ),
        "dependencias_externas": "Calendario oficial de Colombia (libreria holidays).",
        "supuestos": "SUP-01, SUP-02, SUP-03, SUP-04, SUP-06, SUP-16, SUP-19.",
    },
    {
        "modelo": "M2",
        "variable_objetivo_evaluada": "pagado",
        "definicion_variable_objetivo": ("Efectivo entregado por el multifuncional en el dia."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": (
            "Observadas: pagado, cupo, segmentacion. Derivadas: rezagos. " "Calendario CO (RN-04)."
        ),
        "variables_mas_relevantes": "Pagado t-7, dia de semana",
        "transformacion_a_decision_operativa": (
            "Saldo neto con cash_in (RN-19, RN-30); provision hasta el cupo el dia en "
            "que el saldo proyectado bajaria del 8% (RN-19A, RN-21)."
        ),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-01, SUP-02, SUP-03, SUP-06.",
    },
    {
        "modelo": "M2",
        "variable_objetivo_evaluada": "cash_in",
        "definicion_variable_objetivo": ("Efectivo recibido (depositos) por el multifuncional en el dia."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": ("Observadas: cash_in, cupo. Derivadas: rezagos. Calendario CO."),
        "variables_mas_relevantes": "Cash_in t-7, dia de semana",
        "transformacion_a_decision_operativa": (
            "Saldo neto (RN-30): el cash_in se recicla; recoleccion al cierre de lo "
            "que pase del cupo (RN-22, RN-35)."
        ),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-01, SUP-02, SUP-03, SUP-06.",
    },
    {
        "modelo": "M3",
        "variable_objetivo_evaluada": "entradas",
        "definicion_variable_objetivo": ("Efectivo que entra a la boveda de la sucursal fisica en el dia."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": ("Observadas: entradas, salidas, cupo_max_suc. Derivadas: rezagos. " "Calendario CO."),
        "variables_mas_relevantes": "Entradas t-7, dia de semana",
        "transformacion_a_decision_operativa": (
            "Simulacion del saldo en [0, cupo_max_suc]; recoleccion del excedente " "sobre el cupo (SUP-M3-01)."
        ),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-03, SUP-M3-01, SUP-M3-02.",
    },
    {
        "modelo": "M3",
        "variable_objetivo_evaluada": "salidas",
        "definicion_variable_objetivo": ("Efectivo que sale de la boveda de la sucursal fisica en el dia."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": ("Observadas: entradas, salidas, cupo_max_suc. Derivadas: rezagos. " "Calendario CO."),
        "variables_mas_relevantes": "Salidas t-7, dia de semana",
        "transformacion_a_decision_operativa": (
            "Simulacion del saldo en [0, cupo_max_suc]; provision ante riesgo de " "agotamiento (SUP-M3-01)."
        ),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-03, SUP-M3-01, SUP-M3-02.",
    },
    {
        "modelo": "M4",
        "variable_objetivo_evaluada": "ingreso_efectivo_cbr",
        "definicion_variable_objetivo": ("Ingreso de efectivo por puntos CBR agregado a nivel fondo-dia (RN-48)."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": ("Observadas: ingreso por punto CBR. Derivadas: rezagos. Calendario CO."),
        "variables_mas_relevantes": "Ingreso t-7, dia de semana",
        "transformacion_a_decision_operativa": ("Insumo de ingreso del balance de fondos M6 (RN-70)."),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-02 (holdout 0 obs); insumo de M6.",
    },
    {
        "modelo": "M5",
        "variable_objetivo_evaluada": "ingreso_efectivo_clientes",
        "definicion_variable_objetivo": ("Ingreso de efectivo por clientes agregado a nivel fondo-dia (RN-48)."),
        "algoritmo_o_enfoque": _PROPHET_APPROACH,
        "variables_utilizadas": ("Observadas: ingreso por cliente. Derivadas: rezagos. Calendario CO."),
        "variables_mas_relevantes": "Ingreso t-7, dia de semana",
        "transformacion_a_decision_operativa": ("Insumo de ingreso del balance de fondos M6 (RN-70)."),
        "dependencias_externas": "Calendario oficial de Colombia.",
        "supuestos": "SUP-02, SUP-20; insumo de M6. El WAPE medido esta en 03_Metricas_Desarrollo.",
    },
    {
        "modelo": "M6",
        "variable_objetivo_evaluada": "saldo_proyectado",
        "definicion_variable_objetivo": (
            "Saldo proyectado de la boveda por fondo+denominacion (balance " "determinista derivado de M1-M5)."
        ),
        "algoritmo_o_enfoque": (
            "Balance determinista por fondo+denominacion derivado de M1-M5 + "
            "recomendador prescriptivo costeado (Anexo E). NO entrena ni "
            "pronostica: simula el balance dia a dia y recomienda acciones "
            "logisticas (traslado, venta, BanRep, intercambio y cambio de denominacion)."
        ),
        "variables_utilizadas": (
            "Pronosticos M1-M5, saldo inicial por denominacion (SUP-07), mezcla "
            "historica por denominacion (SUP-09), min/max operativos (SUP-10), "
            "tarifas del Anexo E."
        ),
        "variables_mas_relevantes": ("Efecto neto M1-M5, mezcla por denominacion, min/max operativos"),
        "transformacion_a_decision_operativa": (
            "Recomendaciones costeadas por fondo+denominacion+dia (RN-72..85) con " "min/max objetivo (SUP-10)."
        ),
        "dependencias_externas": ("Anexo E (tarifas), calendario oficial de Colombia."),
        "supuestos": ("SUP-07, SUP-08, SUP-09, SUP-10, SUP-11, SUP-12, SUP-13, SUP-14, SUP-20, SUP-23."),
    },
]


def _sheet_04_context() -> dict[str, Any]:
    """Lee de la configuracion y de los artefactos lo que la hoja 04 declara.

    La hoja describe lo que el pipeline corrio de verdad: la receta de cada
    modelo/objetivo sale de `forecaster.modelo` de su unidad, sus textos de
    `descripciones` en `pronosticadores.yml`, las variables mas relevantes del
    artefacto de explicabilidad (si existe) y la decision de M1 de `m1.policy`.

    Returns:
        dict[str, Any]: `recetas` {(MODELO, objetivo): nombre}, `descripciones`,
        `importancias` (DataFrame o `None`), `m1` (config de M1).
    """
    from daas.forecasting import forecasters as forecasters
    from daas.modules.atm_m1_m2.config import load_config as load_u12
    from daas.modules.branches_m3.config import load_config as load_m3
    from daas.modules.funds_inflows_m4_m5.config import load_config as load_u45
    from daas.modules.funds_m6.config import load_config as load_u6
    from daas.publish import explainability as explainability

    u12, m3, u45 = load_u12(), load_m3(), load_u45()
    recipes: dict[tuple[str, str], str] = {}
    for base in _SHEET_04_ROWS:
        mdl, obj = base["modelo"], base["variable_objetivo_evaluada"]
        if mdl in {"M1", "M2"}:
            recipes[(mdl, obj)] = forecasters.resolve_model(u12["forecaster"], mdl.lower(), obj)
        elif mdl == "M3":
            recipes[(mdl, obj)] = forecasters.resolve_model(m3["forecaster"], obj)
        elif mdl in {"M4", "M5"}:
            recipes[(mdl, obj)] = forecasters.resolve_model(u45["forecaster"], mdl.lower())
    correction = load_u6().get("correccion_total") or {}
    importances = storage.read_table(explainability.URI) if storage.exists(explainability.URI) else None
    return {
        "recetas": recipes,
        "descripciones": forecasters.load_recipes().get("descripciones") or {},
        "importancias": importances,
        "m1": u12.get("m1", {}),
        "corregidos": {str(m).upper() for m in correction.get("modelos", [])} if correction.get("activo") else set(),
    }


def _relevant_variables(
    importances: pd.DataFrame | None, mdl: str, target: str, adopted: str | None, h4: dict[str, Any]
) -> str | None:
    """Texto de `variables_mas_relevantes` desde la explicabilidad medida; `None` si no hay.

    El alcance distingue si la receta medida es el modelo publicado o un componente del promedio.
    """
    if importances is None or importances.empty:
        return None
    d = importances[
        (importances["modelo"].astype(str).str.upper() == mdl)
        & (importances["objetivo"].astype(str) == target)
        & (importances["tipo"] == "permutacion")
    ].sort_values("valor", ascending=False)
    d = d[d["valor"] > 0].head(3)
    if d.empty:
        return None
    parts = "; ".join(
        f"{str(g).replace('_', ' ')} ({100 * float(v):.1f})" for g, v in zip(d["grupo"], d["valor"], strict=False)
    )
    texts = h4["importancia"]
    scope = texts["modelo_publicado"] if str(d["receta"].iloc[0]) == adopted else texts["componente"]
    return texts["texto"].format(grupos=parts, alcance=scope)


def _contiguous_blocks(dates: list[_dt.date]) -> list[list[_dt.date]]:
    """Agrupa fechas ordenadas en bloques de dias consecutivos."""
    blocks: list[list[_dt.date]] = []
    for f in sorted(dates):
        if blocks and (f - blocks[-1][-1]).days == 1:
            blocks[-1].append(f)
        else:
            blocks.append([f])
    return blocks


def _anexo_c_text(h4: dict[str, Any]) -> str | None:
    """Tratamiento del Anexo C (dias sin dato en toda la red), calculado de la ventana configurada.

    Returns:
        str | None: Texto con el numero de dias, los bloques y el mas largo; ``None`` si la
        ventana no se puede leer (la hoja no inventa).
    """
    try:
        from daas.quality.anexo_c import anexo_c_window

        window = anexo_c_window()
    except Exception as error:  # noqa: BLE001  (sin ventana -> sin texto, no se inventa)
        logger.warning("No se pudo leer la ventana del Anexo C (%s); la hoja 04 no la describe.", error)
        return None
    if not window:
        return None
    blocks = _contiguous_blocks(window)
    names = "; ".join(
        f"{b[0].isoformat()}" if len(b) == 1 else f"{b[0].isoformat()} a {b[-1].isoformat()}" for b in blocks
    )
    key = "anexo_c_alx" if alx.interruptor("supuestos_alx") else "anexo_c"  # ALX PARTE 7: apagado = Santiago
    return h4["limitaciones_adicionales"][key].format(
        n_dias=len(window), bloques=f"{len(blocks)} bloques: {names}", bloque_max=max(len(b) for b in blocks)
    )


def _silent_text(mdl: str, contracts: dict[str, pd.DataFrame] | None, h4: dict[str, Any]) -> str | None:
    """Equipos sin dato reciente de M1/M2 (contrato informativo `silenciosos`): conteo y codigos."""
    if mdl not in ("M1", "M2"):
        return None
    texts = h4["limitaciones_adicionales"]
    sil = (contracts or {}).get("silenciosos")
    if sil is None:
        return texts["silenciosos_ausentes"]
    sub = sil[sil["modelo"].astype(str).str.lower() == mdl.lower()]
    codes = sorted(sub["cod_cajero"].astype(str).unique())
    cap = int(h4["max_codigos"])
    listing = ", ".join(codes[:cap]) + (f" y {len(codes) - cap} mas" if len(codes) > cap else "")
    treatments = " | ".join(sorted(sub["tratamiento"].dropna().astype(str).unique())) or "sin tratamiento declarado"
    return texts[mdl.lower()].format(
        **{
            f"n_silenciosos_{mdl.lower()}": len(codes),
            f"codigos_{mdl.lower()}": listing or "ninguno",
            "tratamientos": treatments,
        }
    )


def _m3_text(contracts: dict[str, pd.DataFrame] | None, h4: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """Politica de M3 y el efecto del primer dia, con cifras de la configuracion y de las salidas."""
    from daas.modules.branches_m3.config import load_config as load_m3

    policy = load_m3().get("politica") or {}
    if not policy.get("activa"):
        return None
    dia1_n, dia1_amount = 0, 0
    if contracts is not None:
        rec = contracts["recomendaciones"]
        rec = rec[(rec["modelo"] == "m3") & (rec["accion"] == "recoleccion")]
        start = to_date_or_none(cfg["horizonte"]["inicio"])
        dia1 = rec[pd.to_datetime(rec["fecha_sugerida"]).dt.date == start]
        dia1_n, dia1_amount = len(dia1), int(round(float(pd.to_numeric(dia1["monto"], errors="coerce").sum())))
    return h4["limitaciones_adicionales"]["m3"].format(
        reserva_max=float(policy["reserva_max"]),
        dias_cobertura=policy["dias_cobertura"],
        dias_techo=policy["dias_techo"],
        historia_dias=policy["historia_dias"],
        min_obs=policy["min_obs"],
        dia1_n=dia1_n,
        dia1_monto=f"{dia1_amount:,}".replace(",", "."),
    )


def _target_error_text(
    mdl: str, target: str, contracts: dict[str, pd.DataFrame] | None, cfg: dict[str, Any]
) -> str | None:
    """Error de backtest de la variable objetivo de la fila (lectura de entrenamiento); ``None`` sin cifra."""
    if contracts is None:
        return None
    met = contracts["metricas"]
    prefix = cfg["hoja_03"]["lectura_rn08"]["prefijo_nota"]
    sub = met[
        (met["modelo"] == mdl.lower())
        & (met["bloque"] == "backtest")
        & (met["objetivo"] == target)
        & ~met["nota"].fillna("").astype(str).str.startswith(prefix)
    ]
    if sub.empty or pd.isna(sub["wape"].iloc[0]):
        return None
    row = sub.iloc[0]
    return cfg["hoja_04"]["limitaciones_adicionales"]["cifras_objetivo"].format(
        objetivo=target, wape=float(row["wape"]), sesgo=float(row["bias"]), n_obs=int(row["n_obs"])
    )


def sheet_04_description(
    contracts: dict[str, pd.DataFrame] | None = None, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Construye `04_Descripcion_Solucion` (8 filas, una por modelo x objetivo).

    Textos honestos con los SUP-xx por modelo. El enfoque, las
    variables y las limitaciones salen de la receta que corrio
    (`_sheet_04_context`); sin receta declarada se usan los textos de Prophet +
    fallback. `variables_mas_relevantes` usa la explicabilidad medida cuando
    existe. M6 conserva su matiz (sin WAPE, SUP-11).

    Las limitaciones se completan con textos de ``export_anexo_d.yml::hoja_04`` y cifras de las
    salidas: tratamiento del Anexo C (M1/M2), equipos silenciosos (contrato `silenciosos`, si existe),
    politica de M3 y su primer dia, limitaciones de M6 y sus decisiones. La decision de
    M1 describe la familia de politica vigente (`m1.policy`), sin cifras escritas a mano.

    Args:
        contracts: Contratos cargados (``None``: sin cifras de las salidas).
        cfg: Configuracion de ``export_anexo_d.yml`` (``None`` la carga).

    Returns:
        pd.DataFrame: columnas = HEADERS['04_Descripcion_Solucion'], en orden.
    """
    cfg = resolve_config(cfg)
    h4 = cfg["hoja_04"]
    rows = []
    ctx = _sheet_04_context()
    if alx.interruptor("hoja04_v2"):  # correcciones v2: textos para el evaluador (sheet_04_v2)
        if contracts is None:
            raise ValueError("hoja04_v2 necesita los contratos de la corrida (cifras de la hoja 04).")
        from daas.publish.anexo_d.sheet_04_v2 import sheet_04_v2

        return sheet_04_v2(contracts, cfg, ctx, _SHEET_04_ROWS)
    wape_m5 = None
    if contracts is not None:
        met = contracts["metricas"]
        sub = met[(met["modelo"] == "m5") & (met["bloque"] == "backtest")]
        if not sub.empty and pd.notna(sub["wape"].iloc[0]):
            wape_m5 = float(sub["wape"].iloc[0])
    text_c = _anexo_c_text(h4)
    for base in _SHEET_04_ROWS:
        mdl = base["modelo"]
        target = base["variable_objetivo_evaluada"]
        base = dict(base)
        desc = ctx["descripciones"].get(ctx["recetas"].get((mdl, target)))
        if desc:
            base["algoritmo_o_enfoque"] = desc["enfoque"]
            base["variables_utilizadas"] = desc["variables"]
        relevant = _relevant_variables(ctx["importancias"], mdl, target, ctx["recetas"].get((mdl, target)), h4)
        if relevant:
            base["variables_mas_relevantes"] = relevant
        policy = ctx["m1"].get("politica") or {}
        lead = int(ctx["m1"].get("lead_time_dias", 0))
        if mdl == "M1":
            template = h4["decision_m1"].get(policy.get("familia"))
            base["transformacion_a_decision_operativa"] = (
                template.format(
                    politica=policy.get("familia"),
                    margen=float(policy.get("margen", 0.0)),
                    lead=lead,
                    umbral=float(ctx["m1"].get("umbral_agotamiento", 0.0)),
                )
                if template
                else h4["decision_m1_general"]
            )
        if mdl == "M3":
            base["transformacion_a_decision_operativa"] = h4["decision_m3"]
        if mdl in ctx["corregidos"]:
            base["supuestos"] = "SUP-02; insumo de M6, que corrige su total (SUP-20)."
        if desc:
            limitations, methodology = desc["limitaciones"], METHODOLOGY
        elif mdl == "M6":
            limitations = (
                "Balance determinista sin WAPE sobre el saldo (SUP-11): la "
                "validacion es completitud + cobertura. Habilitacion de "
                "operaciones inferida del historico (SUP-08/SUP-13); min/max y "
                "mezcla por denominacion son supuestos de Pragma (SUP-09/SUP-10)."
            )
            methodology = "Completitud del saldo inicial + cobertura de recomendaciones " "(sin WAPE, SUP-11)."
        elif mdl == "M5":
            limitations = _COMMON_LIMITATIONS + (
                f" M5 muestra un WAPE alto ({wape_m5:.2f}) y subestima el total: serie de ingreso por "
                "clientes ruidosa, con picos sin patron de calendario; se publica sin corregir y M6 corrige su "
                "total con un factor de red (SUP-20)."
                if wape_m5 is not None
                else " M5 es una serie de ingreso por clientes ruidosa, con picos sin patron de calendario; se "
                "publica sin corregir y M6 corrige su total con un factor de red (SUP-20)."
            )
            methodology = METHODOLOGY
        else:
            limitations = _COMMON_LIMITATIONS
            methodology = METHODOLOGY
        additional = [_target_error_text(mdl, target, contracts, cfg)]
        if mdl in ("M1", "M2"):
            additional += [text_c, _silent_text(mdl, contracts, h4), rn08_text(mdl, target, contracts, cfg)]
        if mdl == "M1":
            additional.append(h4["decisiones_pragma"].format(lead=lead))
        if mdl == "M3":
            additional.append(_m3_text(contracts, h4, cfg))
        if mdl in ("M1", "M2", "M3"):
            additional.append(h4["limitaciones_adicionales"]["nivel_riesgo"])
        if mdl == "M6":
            m6_key = "m6_alx" if alx.interruptor("supuestos_alx") else "m6"  # ALX PARTE 7: apagado = Santiago
            additional.append(h4["limitaciones_adicionales"][m6_key])
        # ALX (oct-2026): decisiones del laboratorio de ML, demanda censurada y procedencia (SUP-24 a SUP-35, SUP-38).
        alx_on = alx.interruptor("supuestos_alx")  # ALX PARTE 7: apagado = textos de Santiago
        if alx_on and mdl != "M6":
            additional.append(h4["limitaciones_adicionales"].get("laboratorio_ml"))
        if alx_on and mdl in ("M1", "M2") and target == "pagado":
            additional.append(h4["limitaciones_adicionales"].get("demanda_censurada"))
        if alx_on:
            additional.append(h4.get("procedencia"))
            additional.append(h4.get("entrega_alx"))
        limitations = " ".join([limitations, *[t for t in additional if t]])
        rows.append(
            {
                "id_proveedor": PROVIDER_ID,
                "modelo": mdl,
                "variable_objetivo_evaluada": base["variable_objetivo_evaluada"],
                "definicion_variable_objetivo": base["definicion_variable_objetivo"],
                "algoritmo_o_enfoque": base["algoritmo_o_enfoque"],
                "variables_utilizadas": base["variables_utilizadas"],
                "variables_mas_relevantes": base["variables_mas_relevantes"],
                "horizonte_prediccion": _HORIZON_TEXT,
                "metodologia_validacion": methodology,
                "transformacion_a_decision_operativa": base["transformacion_a_decision_operativa"],
                "limitaciones_identificadas": limitations,
                "dependencias_externas": base["dependencias_externas"],
                "supuestos": _with_alx_sup(base["supuestos"], mdl, target) if alx_on else base["supuestos"],
            }
        )
    return pd.DataFrame(rows, columns=HEADERS["04_Descripcion_Solucion"])
