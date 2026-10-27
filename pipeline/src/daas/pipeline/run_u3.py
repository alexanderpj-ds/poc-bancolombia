"""Orquestacion de la unidad U3 (Sucursales M3) del subpaquete `pipeline`.

Reutiliza la maquinaria compartida de M1/M2 SIN tocar el motor congelado
(`daas.modules.atm_m1_m2`) ni `run_u1_u2`. `run_u3` encadena, para el modelo M3
(sucursal fisica):

  1. CARGA   : `modules.branches_m3.dataset.cargar_series_m3()` lee `processed/m3_sucursales`
               via `daas://`, valida el canal unico y densifica entradas/salidas.
  2. FORECAST: entrena un modelo por serie-objetivo (una serie = `cod_sucursal`)
               para `entradas` Y `salidas`, y pronostica el horizonte 1-15 sep
               (dias calendario) con la misma mecanica que `run_u1_u2`.
  3. SALDO   : simula la boveda (`modules.branches_m3.balance.simular_saldo_m3`) con cap duro
               en `cupo_max_suc` (SUP-M3-01), provision/recoleccion endogenas.
  4. ACCIONES: recomendaciones (`optimizer.recomendar_acciones_m3`) costeadas con
               Anexo E (`compute_costs`; concepto por `ubicacion` de la
               sucursal y tabla de provision o recoleccion) + alertas
               (`alerts.classify_alerts_m3`: agotamiento + excedente).
  5. METRICAS: backtest interno -> WAPE/MAE/Bias por variable (entradas,
               salidas); el holdout de sep se reporta con `n_obs=0` y nota, sin
               forzar un numero (SUP-02). SIN exclusion RN-07 (no aplica a M3).
  6. PUBLICA : UPSERT por modelo sobre los 4 contratos output/api/*: lee el
               contrato vigente (si existe), elimina las filas `modelo=='m3'`,
               concatena el bloque m3 fresco y re-publica con
               `publish.contracts.publish_contract` (deja intactas las filas
               M1/M2). Cada contrato lleva su `.meta.json` (patron).

ID STRATEGY (documentada): los contratos compartidos enmascaran el id de entidad
como `cod_cajero` (`publish/contracts.py::_COL_ID`). La entidad de M3 es
`cod_sucursal`; se renombra `cod_sucursal -> cod_cajero` en los bloques de salida
ANTES de publicar, de modo que las SCHEMAS y el passthrough existentes
aplican SIN CAMBIOS (no se altera el esquema; M1/M2 intactos).

Todo el I/O pasa por `daas.io.storage`; `run_id = manifest.new_run_id()`; no hay
rutas hardcodeadas.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from dataclasses import dataclass, field

import pandas as pd

from daas import alx
from daas.costs import anexo_e
from daas.decision import alerts as alerts_mod
from daas.decision import optimizer
from daas.forecasting import forecast as forecast_mod
from daas.forecasting import forecasters as forecasters
from daas.forecasting import laboratorio, metrics
from daas.io import storage
from daas.lineage import manifest
from daas.modules.branches_m3.balance import simulate_balance_m3
from daas.modules.branches_m3.config import load_config
from daas.modules.branches_m3.dataset import load_series_m3
from daas.modules.branches_m3.policy import explain_action, load_policy, min_collection_factor, policy_params
from daas.publish import contracts as contracts_mod
from daas.publish import explainability as explainability
from daas.publish.contracts import publish_contract

logger = logging.getLogger(__name__)

#: Clave del modelo que orquesta esta unidad.
_MODEL = "m3"
#: Maestro de oficinas (transportadora y `ubicacion` de cada sucursal, para el costo).
_URI_OFFICES = "daas://interim/oficinas"

#: Nombres de los 4 contratos de salida.
_CONTRACTS: tuple[str, ...] = (
    "predicciones",
    "recomendaciones",
    "alertas",
    "metricas",
    "backtest",  # opcional: pares y/yhat del backtest para el WAPE por segmento (hoja 03)
)


@dataclass
class ModelSummaryM3:
    """Resumen de la corrida del modelo M3.

    Attributes:
        modelo: Clave de modelo (`m3`).
        n_sucursales: Nº de sucursales con serie cargada.
        n_predicciones: Filas de pronostico (sucursal-dia-objetivo) del horizonte.
        n_alertas: Nº de alertas emitidas (agotamiento + excedente).
        n_recomendaciones: Nº de recomendaciones (provision/recoleccion).
        wape: dict objetivo -> WAPE del backtest interno (NaN si sin denominador).
        mae: dict objetivo -> MAE del backtest interno.
        bias: dict objetivo -> Bias del backtest interno.
        n_obs_backtest: dict objetivo -> nº de observaciones del backtest.
    """

    model: str = _MODEL
    n_branches: int = 0
    n_predictions: int = 0
    n_alerts: int = 0
    n_recommendations: int = 0
    wape: dict[str, float] = field(default_factory=dict)
    mae: dict[str, float] = field(default_factory=dict)
    bias: dict[str, float] = field(default_factory=dict)
    n_obs_backtest: dict[str, int] = field(default_factory=dict)


@dataclass
class SummaryU3:
    """Resumen de una corrida completa de `run_u3` (CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        modelo: Resumen del modelo M3.
        contratos: Ruta fisica escrita por contrato publicado.
        horizonte: Par `(inicio, fin)` del horizonte de pronostico (ISO).
    """

    run_id: str
    model: ModelSummaryM3 = field(default_factory=ModelSummaryM3)
    contracts: dict[str, str] = field(default_factory=dict)
    horizon: tuple[str, str] = ("", "")


def _horizon_dates(start: str, fin: str) -> list[_dt.date]:
    """Construye las fechas calendario del horizonte `[inicio, fin]` (SUP-03).

    Args:
        start: Fecha inicial ISO `yyyy-mm-dd`.
        fin: Fecha final ISO `yyyy-mm-dd` (inclusive).

    Returns:
        list[datetime.date]: Dias calendario consecutivos de inicio a fin.
    """
    d0 = pd.to_datetime(start).date()
    d1 = pd.to_datetime(fin).date()
    days = (d1 - d0).days
    return [d0 + _dt.timedelta(days=k) for k in range(days + 1)]


def _metrics_block(
    backtests_by_target: dict[str, list[pd.DataFrame]],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Calcula las metricas por objetivo (backtest interno + holdout sep).

    Backtest interno: WAPE/MAE/Bias sobre la ultima ventana del
    entrenamiento, por variable (`entradas`, `salidas`). SIN exclusion RN-07 (
    no aplica a M3). El holdout 1-15 sep se reporta con `n_obs=0` y una nota, sin
    forzar un numero (SUP-02).

    Args:
        backtests_by_target: Mapa `objetivo -> lista de backtests por sucursal`
            (`fecha`, `y`, `yhat`).

    Returns:
        tuple[pd.DataFrame, dict[str, int]]: `(metricas_df, n_obs_por_objetivo)`
        con `metricas_df` de columnas `bloque`, `objetivo`, `wape`, `mae`,
        `bias`, `n_obs`, `n_excluidas`, `nota`.
    """
    columns = [
        "bloque",
        "objetivo",
        "wape",
        "mae",
        "bias",
        "n_obs",
        "n_excluidas",
        "nota",
    ]
    rows: list[dict] = []
    n_obs_by_target: dict[str, int] = {}

    for target, backtests in backtests_by_target.items():
        bt_all = pd.concat(backtests, ignore_index=True) if backtests else pd.DataFrame(columns=["fecha", "y", "yhat"])
        valid_ids = bt_all.dropna(subset=["y", "yhat"]) if not bt_all.empty else bt_all
        n_obs_bt = int(len(valid_ids))
        n_obs_by_target[target] = n_obs_bt

        if n_obs_bt > 0:
            wape = metrics.wape_aggregate(  # ALX SUP-02: entidad con denominador cero fuera del WAPE agregado
                valid_ids["y"], valid_ids["yhat"], valid_ids.get("cod_sucursal", valid_ids.get("cod_cajero"))
            )
            mae = metrics.mae(valid_ids["y"], valid_ids["yhat"])
            bias = metrics.bias(valid_ids["y"], valid_ids["yhat"])
            note_bt = (
                f"Backtest interno de '{target}' (ultima ventana del "
                f"entrenamiento, D7); M3 sin exclusion RN-07 (D8)."
            )
            note_bt += metrics.sup02_note(valid_ids["y"], valid_ids["cod_cajero"])  # ALX SUP-02 ("" si no aplica)
        else:
            wape = mae = bias = float("nan")
            note_bt = (
                f"Backtest interno de '{target}' sin observaciones validas "
                "(serie insuficiente); metricas NaN (no se fuerza)."
            )

        rows.append(
            {
                "bloque": "backtest",
                "objetivo": target,
                "wape": wape,
                "mae": mae,
                "bias": bias,
                "n_obs": n_obs_bt,
                "n_excluidas": 0,
                "nota": note_bt,
            }
        )
        rows.append(
            {
                "bloque": "holdout_sep",
                "objetivo": target,
                "wape": float("nan"),
                "mae": float("nan"),
                "bias": float("nan"),
                "n_obs": 0,
                "n_excluidas": 0,
                "nota": (
                    f"Holdout 1-15 sep de '{target}' con 0 observaciones "
                    "reales (los datos terminan el 31-ago); metricas no "
                    "calculables, se reporta n_obs=0 (SUP-02, no se fuerza)."
                ),
            }
        )

    return pd.DataFrame(rows, columns=columns), n_obs_by_target


def min_collection_amount(fixed: float | None, rate_10k: float | None, factor: float) -> float | None:
    """Monto minimo de recoleccion: solucion de `monto <= factor x (fijo + monto/10.000 x tarifa)` (SUP-43).

    Devuelve el mayor monto cuya recoleccion no supera `factor` veces su costo del Anexo E:
    `factor x fijo / (1 - factor x tarifa / 10.000)`. Sin costo (sin transportadora o sin tarifa) -> None (la
    sucursal no omite nada). `factor x tarifa >= 10.000` -> ValueError (todo monto seria antieconomico).
    """
    if fixed is None or rate_10k is None or pd.isna(fixed) or pd.isna(rate_10k):
        return None
    if factor * float(rate_10k) >= 10000.0:
        raise ValueError(f"monto_minimo_recoleccion: factor x tarifa >= 10.000 ({factor} x {rate_10k}).")
    return factor * float(fixed) / (1.0 - factor * float(rate_10k) / 10000.0)


def _min_collection_by_branch(branches: list, factor: float) -> dict[str, float | None]:
    """Monto minimo de recoleccion por sucursal con su tarifa de recoleccion del Anexo E (SUP-43)."""
    offices = storage.read_table(_URI_OFFICES).drop_duplicates(subset=["cod_sucursal"])
    offices = offices.set_index(offices["cod_sucursal"].astype(str))
    tar = pd.DataFrame({"cod_cajero": [str(b) for b in branches]})
    tar["transportadora"] = tar["cod_cajero"].map(offices["transportadora"])
    tar["ubicacion"] = tar["cod_cajero"].map(offices["ubicacion"])
    if alx.interruptor("m3_escala_anexo_a") and "escalas" in offices.columns:
        tar["escalas"] = tar["cod_cajero"].map(offices["escalas"])
    tar["concepto"] = anexo_e.branch_concepts(tar)
    tar["accion"] = "recoleccion"
    c0 = anexo_e.compute_costs(tar.assign(monto=0.0))["costo"]
    c1 = anexo_e.compute_costs(tar.assign(monto=10000.0))["costo"]
    out: dict[str, float | None] = {}
    for code, fixed, high in zip(tar["cod_cajero"], c0, c1, strict=False):
        rate = None if pd.isna(fixed) or pd.isna(high) else float(high) - float(fixed)
        value = min_collection_amount(None if pd.isna(fixed) else float(fixed), rate, factor)
        if value is None:
            logger.warning("Sucursal %s sin costo de recoleccion en el Anexo E: no se omite ninguna (SUP-43).", code)
        out[code] = value
    return out


def _omitted_metric_row(balance_df: pd.DataFrame) -> dict:
    """Fila informativa `recoleccion_omitida_monto` de M3 (SUP-43); se emite tambien con 0 omisiones."""
    omitted = (
        balance_df[balance_df["recoleccion_omitida"] > 0]
        if "recoleccion_omitida" in balance_df.columns
        else balance_df.iloc[0:0]
    )
    id_col = "cod_cajero" if "cod_cajero" in omitted.columns else "cod_sucursal"
    branches = sorted({str(c) for c in omitted[id_col]}) if not omitted.empty else []
    total = float(omitted["recoleccion_omitida"].sum()) if not omitted.empty else 0.0
    return {
        "bloque": "recoleccion_omitida_monto",
        "objetivo": None,
        "wape": float("nan"),
        "mae": float("nan"),
        "bias": float("nan"),
        "n_obs": int(len(omitted)),
        "n_excluidas": int(len(branches)),
        "nota": (
            f"Recolecciones de efectivo ocioso omitidas porque el monto no superaba el costo de la visita: "
            f"{len(omitted)} por {total:,.0f} COP en {len(branches)} sucursal(es)"
            + (f" ({', '.join(branches)})" if branches else "")
            + "; el efectivo queda en la bóveda dentro del cupo (SUP-43)."
        ),
        "origen": None,  # mismo orden de columnas que el contrato v1 (origen antes de valor)
        "valor": total,
    }


def _process_m3(config: dict, dates: list[_dt.date]) -> tuple[ModelSummaryM3, dict[str, pd.DataFrame]]:
    """Procesa el modelo M3 end-to-end y devuelve sus 4 bloques de salida.

    Args:
        config: Configuracion de `conf/model_m3.yml` ya cargada.
        dates: Fechas del horizonte de pronostico (dias calendario).

    Returns:
        tuple[ResumenModeloM3, dict[str, pd.DataFrame]]: `(resumen, bloques)`
        donde `bloques` mapea los 4 contratos a los DataFrames del modelo (con la
        columna `modelo` y el id de entidad ya renombrado a `cod_cajero`).
    """
    min_obs = int(config["forecaster"]["min_obs"])
    backtest_days = int(config["backtest"]["dias"])
    targets = list(config["objetivos"])

    data = load_series_m3()
    capacities = data.groupby("cod_sucursal")["cupo_max_suc"].first().to_dict()
    branches = sorted(data["cod_sucursal"].dropna().unique().tolist())

    # Politica diferenciada: parametros por sucursal con la historia <= corte (dia previo al horizonte).
    pol = load_policy(config)
    threshold = float(config["m3"]["umbral_agotamiento"])
    params = None
    if pol["activa"]:
        cutoff = dates[0] - _dt.timedelta(days=1)
        hist = data[data["fecha"] <= cutoff]
        params = policy_params(
            hist.pivot(index="fecha", columns="cod_sucursal", values="entradas").sort_index(),
            hist.pivot(index="fecha", columns="cod_sucursal", values="salidas").sort_index(),
            pd.Series(capacities).reindex(branches).rename_axis("cod_sucursal"),
            threshold,
            pol,
        )

    predictions: list[pd.DataFrame] = []
    balances_simulated: list[pd.DataFrame] = []
    backtests_by_target: dict[str, list[pd.DataFrame]] = {obj: [] for obj in targets}
    summary = ModelSummaryM3(n_branches=int(len(branches)))
    # SUP-43: monto minimo de recoleccion por sucursal (solo con el interruptor; si no, sin minimo = v1).
    min_by_branch: dict[str, float | None] = {}
    with_min = alx.interruptor("monto_minimo_recoleccion")
    if with_min:
        min_by_branch = _min_collection_by_branch(branches, min_collection_factor(pol))

    # Pronostico por objetivo para TODAS las sucursales a la vez (camino unico:
    # horizonte + backtest por ventana de fechas + banda). La receta se elige
    # por objetivo en `forecaster.modelo`.
    # ALX PARTE 7: champions `ml_laboratorio` con contexto V4 "as of" (no hace nada con la receta de Santiago).
    for obj in targets:
        laboratorio.preparar(
            forecasters.resolve_model(config["forecaster"], obj), data, "cod_sucursal", obj,
            hermano=next((t for t in targets if t != obj), None),
        )
    model_forecasts = {
        obj: forecast_mod.generate_forecast(
            data,
            "cod_sucursal",
            obj,
            dates,
            model=forecasters.resolve_model(config["forecaster"], obj),
            min_obs=min_obs,
            backtest_days=backtest_days,
        )
        for obj in targets
    }

    for code in branches:
        forecasts: dict[str, pd.DataFrame] = {}
        for obj in targets:
            fc, bt = model_forecasts[obj].of(code)
            forecasts[obj] = fc
            if not bt.empty:
                backtests_by_target[obj].append(bt.assign(cod_cajero=code))

            # Bloque de predicciones (sucursal-dia-objetivo con banda).
            pred = fc.copy()
            pred.insert(0, "cod_sucursal", code)
            pred["objetivo"] = obj
            predictions.append(pred)

        # Serie del horizonte para la simulacion de saldo (entradas + salidas).
        horizon_df = pd.DataFrame({"fecha": dates})
        horizon_df["entradas"] = forecasts["entradas"]["yhat"].to_numpy()
        horizon_df["salidas"] = forecasts["salidas"]["yhat"].to_numpy()

        pair = None
        if params is not None and pd.notna(params.loc[code, "reserva"]):
            pair = {
                "reserva": params.loc[code, "reserva"],
                "objetivo": params.loc[code, "objetivo"],
                "techo": params.loc[code, "techo"],
                "usa_pronostico": bool(params.loc[code, "usa_pronostico"]),
            }
            if with_min:
                pair["monto_min_recoleccion"] = min_by_branch.get(str(code))
        sim = simulate_balance_m3(
            horizon_df,
            branch_max_capacity=float(capacities.get(code, float("nan"))),
            params=config,
            code_branch=code,
            policy=pair,
        )
        if params is not None:
            for col in ("perfil", "mu_salidas", "mu_entradas", "sigma_neto", "reserva_frac"):
                sim[col] = params.loc[code, col]
        else:  # politica inactiva: regla anterior, sin historia usada
            sim["perfil"], sim["reserva_frac"] = "sin_historia", threshold
            sim["mu_salidas"] = sim["mu_entradas"] = sim["sigma_neto"] = float("nan")
        balances_simulated.append(sim)

    pred_df = (
        pd.concat(predictions, ignore_index=True)
        if predictions
        else pd.DataFrame(columns=["cod_sucursal", "fecha", "yhat", "band_low", "band_high", "objetivo"])
    )
    balance_df = pd.concat(balances_simulated, ignore_index=True) if balances_simulated else pd.DataFrame()

    # ID STRATEGY: renombrar cod_sucursal -> cod_cajero (id compartido
    # enmascarado) ANTES de ensamblar los contratos; asi las SCHEMAS y el
    # passthrough existentes aplican sin cambios.
    pred_df = pred_df.rename(columns={"cod_sucursal": "cod_cajero"})
    if not balance_df.empty:
        balance_df = balance_df.rename(columns={"cod_sucursal": "cod_cajero"})

    alerts_df = _alerts_block(balance_df)
    recommendations_df = _recommendations_block(balance_df, pol)
    metrics_df, n_obs = _metrics_block(backtests_by_target)
    if with_min:
        metrics_df = pd.concat([metrics_df, pd.DataFrame([_omitted_metric_row(balance_df)])], ignore_index=True)

    summary.n_predictions = int(len(pred_df))
    summary.n_alerts = int(len(alerts_df))
    summary.n_recommendations = int(len(recommendations_df))
    summary.n_obs_backtest = n_obs
    if not metrics_df.empty:
        bt_rows = metrics_df[metrics_df["bloque"] == "backtest"]
        for _, row in bt_rows.iterrows():
            obj = row["objetivo"]
            summary.wape[obj] = float(row["wape"])
            summary.mae[obj] = float(row["mae"])
            summary.bias[obj] = float(row["bias"])

    blocks = {
        "predicciones": pred_df.assign(modelo=_MODEL),
        "recomendaciones": recommendations_df.assign(modelo=_MODEL),
        "alertas": alerts_df.assign(modelo=_MODEL),
        "metricas": metrics_df.assign(modelo=_MODEL),
        "backtest": _backtest_block(backtests_by_target),
        # Artefacto lateral (no es contrato): lo publica `run()`.
        "explicabilidad": explainability.block(_MODEL, {obj: p.explanation for obj, p in model_forecasts.items()}),
    }
    return summary, blocks


def _backtest_block(backtests_by_target: dict[str, list[pd.DataFrame]]) -> pd.DataFrame:
    """Pares y/yhat del backtest que puntuan en `metricas` (mismos pares observados, sin exclusion RN-07)."""
    parts = [
        contracts_mod.backtest_block(_MODEL, obj, pd.concat(bts, ignore_index=True).dropna(subset=["y", "yhat"]))
        for obj, bts in backtests_by_target.items()
        if bts
    ]
    if not parts:
        return contracts_mod.backtest_block(_MODEL, "", pd.DataFrame(columns=["cod_cajero", "fecha", "y", "yhat"]))
    return pd.concat(parts, ignore_index=True)


def _alerts_block(balance_df: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque de alertas M3 (agotamiento + excedente).

    Args:
        balance_df: Saldo simulado concatenado (con `cod_cajero`).

    Returns:
        pd.DataFrame: Alertas con `cod_cajero`, `fecha`, `tipo`, `severidad`,
        `nivel`, `limite`.
    """
    columns = ["cod_cajero", "fecha", "tipo", "severidad", "nivel", "limite"]
    if balance_df.empty:
        return pd.DataFrame(columns=columns)
    return alerts_mod.classify_alerts_m3(balance_df)


def _recommendations_block(balance_df: pd.DataFrame, pol: dict | None = None) -> pd.DataFrame:
    """Ensambla el bloque de recomendaciones M3 con costo (Anexo E).

    Provision (manana) + recoleccion (cierre). Cada accion se costea con la
    transportadora y la `ubicacion` de la sucursal (maestro de oficinas) y con la
    tabla de su accion. Sin transportadora -> costo NULL +
    `sin_transportadora`; sin concepto o tarifa -> costo NULL + `sin_tarifa`;
    la accion sigue PRESENTE.

    Cada accion lleva ademas la regla que la dispara (`regla`, RN-40) y una
    explicacion funcional por sucursal (`explicacion`, RN-40/41) construida con
    sus numeros (mu de salidas, sigma, perfil, reserva, techo y tarifa).

    Args:
        balance_df: Saldo simulado concatenado (con `cod_cajero`).
        pol: Politica efectiva (`modules.branches_m3.policy.cargar_politica`).

    Returns:
        pd.DataFrame: Recomendaciones con `cod_cajero`, `accion`, `momento`,
        `fecha_sugerida`, `monto`, `costo`, `sin_transportadora`, `sin_tarifa`,
        `cupo`, `saldo_antes`, `saldo_despues`, `regla`, `explicacion`.
    """
    pol = pol or load_policy({})
    columns = [
        "cod_cajero",
        "accion",
        "momento",
        "fecha_sugerida",
        "monto",
        "costo",
        "sin_transportadora",
        "sin_tarifa",
        "cupo",
        "saldo_antes",
        "saldo_despues",
        "regla",
        "explicacion",
    ]
    if balance_df.empty:
        return pd.DataFrame(columns=columns)

    rec = optimizer.recommend_actions_m3(balance_df)
    if rec.empty:
        return pd.DataFrame(columns=columns)
    rec = rec.rename(columns={"cupo_operativo": "cupo"})  # RN-03: cupo aplicable

    offices = storage.read_table(_URI_OFFICES).drop_duplicates(subset=["cod_sucursal"])
    offices = offices.set_index(offices["cod_sucursal"].astype(str))
    rec = rec.copy()
    key = rec["cod_cajero"].astype(str)
    rec["transportadora"] = key.map(offices["transportadora"])
    rec["ubicacion"] = key.map(offices["ubicacion"])
    if alx.interruptor("m3_escala_anexo_a") and "escalas" in offices.columns:
        rec["escalas"] = key.map(offices["escalas"])  # SUP-22: escala desde `Escalas` de Oficinas
    rec["concepto"] = anexo_e.branch_concepts(rec)
    costed = anexo_e.compute_costs(rec)

    # Regla que dispara y datos de la sucursal para la explicacion.
    extras = balance_df.copy()
    extras["cod_cajero"] = extras["cod_cajero"].astype(str)
    extras["fecha"] = pd.to_datetime(extras["fecha"])
    base = extras.drop(columns=[c for c in ("regla_provision", "regla_recoleccion")])
    cols_pair = [
        c
        for c in (
            "reserva",
            "objetivo",
            "techo",
            "perfil",
            "mu_salidas",
            "mu_entradas",
            "sigma_neto",
            "reserva_frac",
            "saldo_previsto",
            "entradas",
            "salidas",
        )
        if c in base.columns
    ]
    by_day = base.set_index(["cod_cajero", "fecha"])[cols_pair]
    rules = (
        pd.concat(
            [
                extras.assign(accion="provision", regla=extras["regla_provision"]),
                extras.assign(accion="recoleccion", regla=extras["regla_recoleccion"]),
            ]
        )
        .dropna(subset=["regla"])
        .set_index(["cod_cajero", "fecha", "accion"])["regla"]
    )
    key_f = pd.to_datetime(costed["fecha_sugerida"])
    idx = pd.MultiIndex.from_arrays([costed["cod_cajero"].astype(str), key_f])
    costed["regla"] = rules.reindex(
        pd.MultiIndex.from_arrays([costed["cod_cajero"].astype(str), key_f, costed["accion"]])
    ).to_numpy()
    detail = by_day.reindex(idx).reset_index(drop=True)
    for c in detail.columns:
        costed[c] = detail[c].to_numpy()

    # Tarifa del Anexo E por sucursal: fijo (monto 0) y variable por cada $10.000 (monto 10.000 - fijo).
    c0 = anexo_e.compute_costs(costed[["accion", "transportadora", "concepto"]].assign(monto=0.0))["costo"]
    c1 = anexo_e.compute_costs(costed[["accion", "transportadora", "concepto"]].assign(monto=10000.0))["costo"]
    costed["costo_fijo"] = c0.to_numpy()
    costed["tarifa_10k"] = (c1 - c0).to_numpy()
    costed["explicacion"] = [explain_action(row, pol) for row in costed.to_dict("records")]
    if alx.interruptor("monto_minimo_recoleccion"):
        costed["explicacion"] = _min_collection_texts(costed, extras, pol)
    return costed[columns]


def _min_collection_texts(costed: pd.DataFrame, balance: pd.DataFrame, pol: dict) -> list[str]:
    """Frases de SUP-43 en las explicaciones de M3 (interruptor `monto_minimo_recoleccion`).

    - Recoleccion que incluye efectivo de recolecciones omitidas desde la anterior: monto y fechas omitidas.
    - Recoleccion de exceso sobre el cupo cuyo monto no supera `factor x costo`: se mantiene por RN-38.
    """
    cfg = pol.get("monto_minimo_recoleccion") or {}
    texts = cfg.get("textos") or {}
    factor = min_collection_factor(pol)
    has_omitted = "recoleccion_omitida" in balance.columns
    omitted = balance[["cod_cajero", "fecha", "recoleccion_omitida"]] if has_omitted else None
    out: list[str] = []
    last_collection: dict[str, pd.Timestamp] = {}
    order = costed.assign(_f=pd.to_datetime(costed["fecha_sugerida"])).sort_values("_f", kind="stable")
    extra: dict[int, str] = {}
    for idx, row in order.iterrows():
        if row["accion"] != "recoleccion":
            continue
        code, date = str(row["cod_cajero"]), row["_f"]
        parts = []
        if omitted is not None:
            prev = last_collection.get(code)
            win = omitted[(omitted["cod_cajero"].astype(str) == code) & (omitted["fecha"] < date)]
            if prev is not None:
                win = win[win["fecha"] > prev]
            win = win[win["recoleccion_omitida"] > 0]
            if not win.empty:
                dates_txt = ", ".join(pd.Timestamp(f).strftime("%d-%m-%Y") for f in win["fecha"])
                amount = "$" + f"{float(win['recoleccion_omitida'].sum()):,.0f}".replace(",", ".")
                parts.append(str(texts.get("omitidas_previas", "")).format(monto=amount, fechas=dates_txt))
        last_collection[code] = date
        cost = row.get("costo")
        if row.get("regla") == "exceso_sobre_cupo" and pd.notna(cost) and float(row["monto"]) <= factor * float(cost):
            parts.append(str(texts.get("exceso_antieconomica", "")))
        parts = [p for p in parts if p]
        if parts:
            extra[idx] = " " + " ".join(parts)
    for idx, text in zip(costed.index, costed["explicacion"], strict=False):
        out.append(f"{text}{extra.get(idx, '')}")
    return out


def _upsert_publish(
    blocks: dict[str, pd.DataFrame],
) -> dict[str, str]:
    """Publica los 4 contratos como UPSERT por modelo (no pisa M1/M2).

    Para cada contrato: si existe el parquet vigente lo lee, elimina las filas
    `modelo=='m3'`, concatena el bloque m3 fresco y re-publica el consolidado
    con `publish_contract`; si no existe, publica solo el bloque m3. Cada
    contrato lleva su `.meta.json`.

    Args:
        blocks: Mapa `contrato -> DataFrame m3` (con la columna `modelo`).

    Returns:
        dict[str, str]: Ruta fisica escrita por contrato.
    """
    file_paths: dict[str, str] = {}
    for contract in _CONTRACTS:
        block_m3 = blocks[contract]
        uri = f"daas://output/api/{contract}"
        if storage.exists(uri):
            current = storage.read_table(uri)
            kept = current[current["modelo"] != _MODEL] if "modelo" in current.columns else current
            parts = [p for p in (kept, block_m3) if not p.empty]
            consolidated = pd.concat(parts, ignore_index=True) if parts else block_m3
        else:
            consolidated = block_m3

        file_path = publish_contract(contract, consolidated)
        models = (
            sorted(consolidated["modelo"].dropna().unique().tolist()) if "modelo" in consolidated.columns else [_MODEL]
        )
        manifest.write_manifest(
            file_path,
            {
                "capa": "output",
                "dataset": f"api/{contract}",
                "contrato": contract,
                "filas": int(len(consolidated)),
                "columnas": list(consolidated.columns),
                "modelos": models,
            },
        )
        file_paths[contract] = file_path
    return file_paths


def run() -> SummaryU3:
    """Orquesta U3: carga -> forecast -> saldo -> acciones -> metricas -> upsert.

    Returns:
        ResumenU3: Resumen de la corrida (run_id, modelo, contratos, horizonte)
        para la CLI y la verificacion.
    """
    run_id = manifest.new_run_id()
    logger.info("U3 (M3 sucursales) run_id=%s", run_id)

    config = load_config()
    start = str(config["horizonte"]["inicio"])
    fin = str(config["horizonte"]["fin"])
    dates = _horizon_dates(start, fin)
    logger.info("Horizonte %s..%s (%d dias calendario).", start, fin, len(dates))

    summary = SummaryU3(run_id=run_id, horizon=(start, fin))
    res_model, blocks = _process_m3(config, dates)
    summary.model = res_model
    summary.contracts = _upsert_publish(blocks)
    explainability.upsert([blocks["explicabilidad"]], [_MODEL])
    return summary


def main() -> None:
    """Punto de entrada de consola para la unidad U3 (M3 sucursales).

    Ejecuta `run()` end-to-end y escribe un resumen por consola.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u3",
        description=(
            "Orquesta U3 (sucursales M3): carga->forecast->saldo->acciones->"
            "metricas->upsert de los 4 contratos output/api/* (sin pisar M1/M2)."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log a nivel INFO.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    summary = run()

    r = summary.model
    print(f"U3 run_id={summary.run_id}")
    print(f"Horizonte: {summary.horizon[0]} .. {summary.horizon[1]}")
    print(
        f"  m3: sucursales={r.n_branches} predicciones={r.n_predictions} "
        f"alertas={r.n_alerts} recomendaciones={r.n_recommendations}"
    )
    for obj in r.wape:
        print(
            f"    {obj}: WAPE={r.wape.get(obj)} MAE={r.mae.get(obj)} "
            f"Bias={r.bias.get(obj)} n_obs_backtest={r.n_obs_backtest.get(obj)}"
        )
    print("Contratos publicados (output/api/):")
    for contract, file_path in summary.contracts.items():
        print(f"  {contract}: {file_path}")


if __name__ == "__main__":
    main()
