"""Orquestacion de las unidades U1/U2 (ATM M1/M2) del subpaquete `pipeline`.

Regla de negocio (imitando el patron de `run_u0.py`): `run_u1_u2`
encadena, para M1 (dispensador) y M2 (multifuncional):

  1. CARGA   : `modules.atm_m1_m2.dataset.cargar_series(modelo)` lee `processed/` +
               `interim/cp_historico` via `daas://` y deriva los objetivos.
  2. FORECAST: entrena un modelo por serie (`cod_cajero`, SUP-06) y pronostica el
               horizonte 1-15 sep (dias calendario, SUP-03); M2 pronostica
               `pagado` y `cash_in`.
  3. SALDO   : simula el saldo operativo (M1: `simulate_balance_m1`; M2:
               `simulate_balance_m2` con orden manana/cierre, hecho #5).
  4. ACCIONES: recomendaciones + alertas + costo (Anexo E, concepto por
               tipologia y dia; `admon='SUC'` -> costo NULL +
               `sin_transportadora`, presente).
  5. METRICAS: backtest interno -> WAPE/MAE/Bias con exclusion RN-07 por
               cajero (SUP-01); el holdout de sep se reporta con `n_obs=0` y
               nota, sin forzar un numero (SUP-02).
  6. PUBLICA : ensambla los 4 contratos (predicciones, recomendaciones, alertas,
               metricas) FILTRADOS a `modelo in {m1,m2}` y los publica con
               `publish.contracts.publish_contract` (esquema tipado + `_schemas`,
               id enmascarado passthrough, fechas ISO).

Todo el I/O pasa por `daas.io.storage`; `run_id = manifest.new_run_id()`; cada
artefacto de salida lleva su `.meta.json` (patron). No hay rutas hardcodeadas.
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
from daas.modules.atm_m1_m2 import balance as balance_mod
from daas.modules.atm_m1_m2 import inactivity as inactivity
from daas.modules.atm_m1_m2.config import load_config
from daas.modules.atm_m1_m2.dataset import actual_with_rn08_reading, exclude_rn07_by_atm, load_series
from daas.publish import contracts as contracts_mod
from daas.publish import explainability as explainability
from daas.publish.contracts import publish_contract

logger = logging.getLogger(__name__)

#: Modelos ATM que orquesta esta unidad (M1 dispensador, M2 multifuncional).
_MODELS: tuple[str, ...] = ("m1", "m2")

#: Maestro CP (`tipo_facturacion` de cada cajero, para el concepto del costo).
_URI_CP_HISTORY = "daas://interim/cp_historico"

#: Nombres de los contratos de salida (filtrados a M1/M2); `backtest` es opcional (WAPE por segmento, hoja 03).
_CONTRACTS: tuple[str, ...] = (
    "predicciones",
    "recomendaciones",
    "alertas",
    "metricas",
    "backtest",
)


@dataclass
class ModelSummary:
    """Resumen de la corrida de un modelo (M1 o M2).

    Attributes:
        modelo: Clave de modelo (`m1`/`m2`).
        n_cajeros: Nº de cajeros con serie cargada.
        n_predicciones: Filas de pronostico (cajero-dia-objetivo) del horizonte.
        n_alertas: Nº de alertas emitidas (agotamiento + recoleccion).
        n_recomendaciones: Nº de recomendaciones emitidas (provision/recoleccion).
        n_excluidas: Nº de cajeros excluidos de las metricas por RN-07 (SUP-01).
        wape: WAPE del backtest interno (NaN si no hay denominador).
        mae: MAE del backtest interno.
        bias: Bias del backtest interno.
        n_obs_backtest: Nº de observaciones usadas en el backtest (post-exclusion).
        n_inactivas_rn07: Nº de equipos desmontados (pronostico cero, sin provisiones).
        n_inactivas_rn08: Nº de equipos sin dato reciente con la red operando (igual trato).
    """

    model: str
    n_atms: int = 0
    n_predictions: int = 0
    n_alerts: int = 0
    n_recommendations: int = 0
    n_excluded: int = 0
    wape: float = float("nan")
    mae: float = float("nan")
    bias: float = float("nan")
    n_obs_backtest: int = 0
    n_inactive_rn07: int = 0
    n_inactive_rn08: int = 0


@dataclass
class SummaryU1U2:
    """Resumen de una corrida completa de `run_u1_u2` (CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        por_modelo: Resumen por modelo (`m1`/`m2`).
        contratos: Ruta fisica escrita por contrato publicado.
        horizonte: Par `(inicio, fin)` del horizonte de pronostico (ISO).
    """

    run_id: str
    by_model: dict[str, ModelSummary] = field(default_factory=dict)
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


def _carrier_of_admin(admin: object) -> object:
    """Deriva la transportadora de costeo desde `admon` (admon=SUC -> NA).

    Un cajero administrado por sucursal (`admon='SUC'`) no tiene transportadora;
    el costo quedara NULL + `sin_transportadora` (hecho confirmado), pero la
    accion/alerta sigue presente.

    Args:
        admin: Valor de `admon` del maestro CP (transportadora o `'SUC'`).

    Returns:
        object: La transportadora, o `pd.NA` si `admon='SUC'`/faltante.
    """
    if admin is None or (isinstance(admin, float) and pd.isna(admin)):
        return pd.NA
    if isinstance(admin, str) and admin.strip().upper() == "SUC":
        return pd.NA
    return admin


def _read_uninstalled(params: dict) -> pd.DataFrame:
    """Maestro de desinstalados (`cod_cajero`, fecha de baja); vacio, con aviso, si no existe en la capa."""
    uri = str(params["desinstalados"])
    if not storage.exists(uri):
        logger.warning("No existe %s; RN-07 no se aplica por desinstalados.", uri)
        return pd.DataFrame(columns=["cod_cajero", params["col_fecha"]])
    return storage.read_table(uri)


def _process_model(model: str, config: dict, dates: list[_dt.date]) -> tuple[ModelSummary, dict[str, pd.DataFrame]]:
    """Procesa un modelo ATM end-to-end y devuelve sus 4 bloques de salida.

    Args:
        model: `'m1'` (dispensador) o `'m2'` (multifuncional).
        config: Configuracion de `conf/model_u1_u2.yml` ya cargada.
        dates: Fechas del horizonte de pronostico (dias calendario).

    Returns:
        tuple[ResumenModelo, dict[str, pd.DataFrame]]: `(resumen, bloques)` donde
        `bloques` mapea `{'predicciones','recomendaciones','alertas','metricas'}`
        a los DataFrames del modelo (ya con la columna `modelo`).
    """
    is_m2 = model == "m2"
    min_obs = int(config["forecaster"]["min_obs"])
    backtest_days = int(config["backtest"]["dias"])
    targets = ["pagado", "cash_in"] if is_m2 else ["pagado"]

    data = load_series(model)
    # Mapa cajero -> (cupo, admon) y bandera RN-07 por cajero.
    by_atm = (
        data.groupby("cod_cajero")
        .agg(
            cupo=("cupo", "first"),
            admon=("admon", "first"),
            __rn07_conflicto=("__rn07_conflicto", "max"),
        )
        .reset_index()
    )

    predictions: list[pd.DataFrame] = []
    balances_simulated: list[pd.DataFrame] = []
    backtests: dict[str, list[pd.DataFrame]] = {obj: [] for obj in targets}
    summary = ModelSummary(model=model, n_atms=int(len(by_atm)))

    # Pronostico por objetivo para TODOS los cajeros a la vez (camino unico:
    # horizonte + backtest por ventana de fechas + banda). La receta se elige
    # por modelo y objetivo en `forecaster.modelo`. Los cajeros en conflicto
    # RN-07 no calibran la banda, igual que no entran a las metricas (SUP-01).
    exclude_rn07 = bool(config["metricas"]["excluir_rn07_por_cajero"])
    in_conflict = by_atm.loc[by_atm["__rn07_conflicto"].astype(bool), "cod_cajero"].tolist() if exclude_rn07 else []
    # ALX PARTE 7: champions `ml_laboratorio` con contexto V4 "as of" (no hace nada con la receta de Santiago).
    for obj in targets:
        laboratorio.preparar(
            forecasters.resolve_model(config["forecaster"], model, obj), data, "cod_cajero", obj,
            hermano=next((t for t in targets if t != obj), None),
        )
    model_forecasts = {
        obj: forecast_mod.generate_forecast(
            data,
            "cod_cajero",
            obj,
            dates,
            model=forecasters.resolve_model(config["forecaster"], model, obj),
            min_obs=min_obs,
            backtest_days=backtest_days,
            exclude_calibration=in_conflict,
        )
        for obj in targets
    }

    # RN-07/RN-08: equipos desmontados o inactivos -> pronostico y banda cero, sin saldo ni provisiones.
    inactive = inactivity.inactive_entities(
        data, _read_uninstalled(config["inactividad"]), config["inactividad"], targets
    )
    codes_inactive = set(inactive["cod_cajero"])
    summary.n_inactive_rn07 = int((inactive["regla"] == "RN-07").sum())
    summary.n_inactive_rn08 = int((inactive["regla"] == "RN-08").sum())
    if len(inactive):
        logger.info(
            "%s: %d equipos con pronostico cero (RN-07: %d, RN-08: %d).",
            model,
            len(inactive),
            summary.n_inactive_rn07,
            summary.n_inactive_rn08,
        )

    for _, info in by_atm.iterrows():
        code = info["cod_cajero"]
        is_inactive = code in codes_inactive

        forecasts: dict[str, pd.DataFrame] = {}
        for obj in targets:
            fc, bt = model_forecasts[obj].of(code)
            if is_inactive:
                fc = inactivity.apply_zero(fc)
            forecasts[obj] = fc
            if not bt.empty:
                bt = bt.copy()
                bt["cod_cajero"] = code
                bt["__rn07_conflicto"] = bool(info["__rn07_conflicto"])
                backtests[obj].append(bt)

            # Bloque de predicciones (cajero-dia-objetivo con banda).
            pred = fc.copy()
            pred.insert(0, "cod_cajero", code)
            pred["objetivo"] = obj
            predictions.append(pred)

        if is_inactive:
            continue  # sin saldo simulado: no genera alertas ni provisiones (RN-07 / RN-15)

        # Serie del horizonte para la simulacion de saldo (yhat de pagado,
        # cash_in para M2). La provision/recoleccion son ENDOGENAS:
        # la simulacion las decide y realimenta el saldo (ya no se fija 0 ni se
        # hace una segunda pasada); las recomendaciones consumen esos montos.
        horizon_df = pd.DataFrame({"fecha": dates})
        horizon_df["yhat"] = forecasts["pagado"]["yhat"].to_numpy()
        if is_m2:
            horizon_df["cash_in"] = forecasts["cash_in"]["yhat"].to_numpy()

        if is_m2:
            sim = balance_mod.simulate_balance_m2(horizon_df, capacity=info["cupo"], params=config, code_atm=code)
        else:
            sim = balance_mod.simulate_balance_m1(horizon_df, capacity=info["cupo"], params=config, code_atm=code)
        sim["admon"] = info["admon"]
        balances_simulated.append(sim)

    pred_df = (
        pd.concat(predictions, ignore_index=True)
        if predictions
        else pd.DataFrame(columns=["cod_cajero", "fecha", "yhat", "band_low", "band_high", "objetivo"])
    )
    balance_df = pd.concat(balances_simulated, ignore_index=True) if balances_simulated else pd.DataFrame()

    alerts_df = _alerts_block(model, balance_df)
    recommendations_df = _recommendations_block(model, balance_df)
    metrics_df, n_excluded, n_obs_bt = _metrics_block(model, backtests["pagado"], config, data)
    for obj in targets[1:]:  # objetivos adicionales (M2 cash_in): solo filas `backtest`, mismas formulas y exclusiones
        extra, _, _ = _metrics_block(model, backtests[obj], config, data, target=obj)
        metrics_df = pd.concat([metrics_df, extra[extra["bloque"] == "backtest"]], ignore_index=True)

    summary.n_predictions = int(len(pred_df))
    summary.n_alerts = int(len(alerts_df))
    summary.n_recommendations = int(len(recommendations_df))
    summary.n_excluded = int(n_excluded)
    summary.n_obs_backtest = int(n_obs_bt)
    if not metrics_df.empty:
        row_bt = metrics_df[metrics_df["bloque"] == "backtest"]
        if not row_bt.empty:
            summary.wape = float(row_bt["wape"].iloc[0])
            summary.mae = float(row_bt["mae"].iloc[0])
            summary.bias = float(row_bt["bias"].iloc[0])

    blocks = {
        "predicciones": pred_df.assign(modelo=model),
        "recomendaciones": recommendations_df.assign(modelo=model),
        "alertas": alerts_df.assign(modelo=model),
        "metricas": metrics_df.assign(modelo=model),
        "backtest": pd.concat(
            [_backtest_block(model, backtests[obj], config, data, obj) for obj in targets], ignore_index=True
        ),
        "silenciosos": inactivity.silent_entities(model, data, inactive, config["inactividad"], targets),
        # Artefacto lateral (no es contrato): lo publica `run()`.
        "explicabilidad": explainability.block(model, {obj: p.explanation for obj, p in model_forecasts.items()}),
    }
    return summary, blocks


def _alerts_block(model: str, balance_df: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque de alertas unificado (tipo/severidad/nivel/limite).

    M1 solo tiene agotamiento; M2 tiene la doble alerta (agotamiento +
    recoleccion). Se normaliza al esquema unificado de M2
    (`cod_cajero,fecha,tipo,severidad,nivel,limite`).

    Args:
        model: `'m1'`/`'m2'`.
        balance_df: Saldo simulado concatenado del modelo.

    Returns:
        pd.DataFrame: Alertas con `cod_cajero`, `fecha`, `tipo`, `severidad`,
        `nivel`, `limite`.
    """
    columns = ["cod_cajero", "fecha", "tipo", "severidad", "nivel", "limite"]
    if balance_df.empty:
        return pd.DataFrame(columns=columns)
    if model == "m2":
        return alerts_mod.classify_alerts_m2(balance_df)
    # M1: agotamiento sobre el saldo sin provision (RN-34); se normaliza (saldo->nivel, umbral->limite).
    depletion = alerts_mod.classify_alerts(balance_df, col_balance="saldo_sin_provision")
    depletion = depletion.rename(columns={"saldo": "nivel", "umbral": "limite"})
    return depletion[columns] if not depletion.empty else pd.DataFrame(columns=columns)


def _recommendations_block(model: str, balance_df: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque de recomendaciones con costo (Anexo E, hoja `ATM`).

    M1: provision. M2: provision (manana) + recoleccion (cierre). Cada accion con
    `monto>0` se costea con el concepto de su tipologia (`tipo_facturacion` del
    maestro CP) y del dia de la accion; `admon='SUC'` -> costo
    NULL + `sin_transportadora` con la accion PRESENTE.

    Args:
        model: `'m1'`/`'m2'`.
        balance_df: Saldo simulado concatenado del modelo (con columna `admon`).

    Returns:
        pd.DataFrame: Recomendaciones con `cod_cajero`, `accion`, `momento`,
        `fecha_sugerida`, `monto`, `costo`, `sin_transportadora`, `sin_tarifa`.
    """
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
    ]
    if balance_df.empty:
        return pd.DataFrame(columns=columns)

    if model == "m2":
        rec = optimizer.recommend_actions_m2(balance_df)
    else:
        base = optimizer.recommend_provision_m1(balance_df)
        base = base[base["requiere_provision"]].copy()
        rec = base.rename(
            columns={
                "fecha_sugerida_provision": "fecha_sugerida",
                "monto_para_completar": "monto",
            }
        )
        rec["accion"] = "provision"
        rec["momento"] = "manana"
        rec = rec[
            [
                "cod_cajero",
                "accion",
                "momento",
                "fecha_sugerida",
                "monto",
                "cupo_operativo",
                "saldo_antes",
                "saldo_despues",
            ]
        ]

    if rec.empty:
        return pd.DataFrame(columns=columns)
    # RN-03: el cupo aplicable es el operativo (en M1, el de RN-09).
    rec = rec.rename(columns={"cupo_operativo": "cupo"})

    # Costear via Anexo E: derivar la transportadora desde `admon` del maestro.
    admin_by_atm = (
        balance_df.groupby("cod_cajero")["admon"].first() if "admon" in balance_df.columns else pd.Series(dtype=object)
    )
    rec = rec.copy()
    rec["transportadora"] = rec["cod_cajero"].map(lambda c: _carrier_of_admin(admin_by_atm.get(c)))
    cp = storage.read_table(_URI_CP_HISTORY)
    typology = (
        cp.drop_duplicates(subset=["cod_cajero"]).set_index("cod_cajero")["tipo_facturacion"]
        if "tipo_facturacion" in cp.columns
        else pd.Series(dtype=object)
    )
    rec["tipo_facturacion"] = rec["cod_cajero"].map(typology)
    if model == "m2" and alx.interruptor("m2_tarifa_interurbana"):
        rec["tipo_facturacion"] = _m2_interurban_typology(rec, cp)
    rec["concepto"] = anexo_e.atm_concepts(rec)
    costed = anexo_e.compute_costs(rec)
    return costed[columns]


def _m2_interurban_typology(rec: pd.DataFrame, cp: pd.DataFrame) -> pd.Series:
    """Tipologia de costeo de M2 con RN-04A (interruptor `m2_tarifa_interurbana`, SUP-21).

    RN-04A: "Urbano cuando el municipio del equipo coincide con la ciudad del fondo; interurbano en los demas
    casos." Un MF de TDV (tipologia `MF`) con `municipio` distinto de la ciudad del fondo (`ciudad` del CP) pasa a
    `MF INTERURBANO`; si falta alguno de los dos se queda urbano con WARNING (no se inventa). Los MF de sucursal no
    tienen transportadora y siguen con costo 0 declarado.
    """
    base = cp.drop_duplicates(subset=["cod_cajero"]).set_index("cod_cajero")
    out = rec["tipo_facturacion"].copy()
    missing = 0
    for idx, code, kind, carrier in zip(
        rec.index, rec["cod_cajero"], rec["tipo_facturacion"], rec["transportadora"], strict=False
    ):
        if not (isinstance(kind, str) and kind.strip().upper() == "MF") or anexo_e._is_empty(carrier):
            continue
        municipio = base["municipio"].get(code) if "municipio" in base.columns else None
        city = base["ciudad"].get(code) if "ciudad" in base.columns else None
        inter = anexo_e.mf_es_interurbano(municipio, city)
        if inter is None:
            missing += 1
            logger.warning("M2 cajero %s sin municipio o ciudad del fondo: se costea como MF urbano (SUP-21).", code)
        elif inter:
            out.loc[idx] = "MF INTERURBANO"
    n_inter = int((out == "MF INTERURBANO").sum())
    logger.info("M2: %d acciones con tarifa MF interurbano (RN-04A); %d sin municipio/ciudad.", n_inter, missing)
    return out


def _metrics_block(
    model: str,
    backtests: list[pd.DataFrame],
    config: dict,
    data: pd.DataFrame | None = None,
    target: str = "pagado",
) -> tuple[pd.DataFrame, int, int]:
    """Calcula las metricas por modelo/bloque (backtest interno + holdout sep).

    Backtest interno: WAPE/MAE/Bias sobre la ultima ventana del
    entrenamiento, excluyendo los cajeros en conflicto RN-07 (SUP-01). El holdout
    1-15 sep se reporta con `n_obs=0` y una nota, sin forzar un numero (SUP-02).

    Args:
        model: `'m1'`/`'m2'`.
        backtests: Lista de backtests por cajero (`fecha`,`y`,`yhat`,
            `cod_cajero`,`__rn07_conflicto`).
        config: Configuracion ya cargada (para `metricas.excluir_rn07_por_cajero` y `metricas.lectura_rn08`).
        target: Objetivo del backtest (`'pagado'` o `'cash_in'`).
        data: Serie de `load_series`; con `metricas.lectura_rn08` activa se agrega una segunda fila `backtest`
            con el real leido segun RN-08 (nota `RN-08: ...`).

    Returns:
        tuple[pd.DataFrame, int, int]: `(metricas_df, n_excluidas, n_obs_bt)` con
        `metricas_df` de columnas `bloque`, `wape`, `mae`, `bias`, `n_obs`,
        `n_excluidas`, `nota`.
    """
    active = bool(config["metricas"]["excluir_rn07_por_cajero"])
    columns = ["bloque", "objetivo", "wape", "mae", "bias", "n_obs", "n_excluidas", "nota"]

    if backtests:
        bt_all = pd.concat(backtests, ignore_index=True)
    else:
        bt_all = pd.DataFrame(columns=["fecha", "y", "yhat", "cod_cajero", "__rn07_conflicto"])

    bt_metrics, n_excluded = exclude_rn07_by_atm(bt_all, active=active)
    # Solo pares con observacion real entran a las metricas (SUP-02).
    valid_ids = bt_metrics.dropna(subset=["y", "yhat"]) if not bt_metrics.empty else bt_metrics
    n_obs_bt = int(len(valid_ids))

    if n_obs_bt > 0:
        wape = metrics.wape_aggregate(valid_ids["y"], valid_ids["yhat"], valid_ids["cod_cajero"])  # ALX SUP-02
        mae = metrics.mae(valid_ids["y"], valid_ids["yhat"])
        bias = metrics.bias(valid_ids["y"], valid_ids["yhat"])
        note_bt = (
            f"Backtest interno (ultima ventana del entrenamiento, D7); " f"exclusion RN-07 por cajero activa={active}."
        )
    else:
        wape = mae = bias = float("nan")
        note_bt = "Backtest interno sin observaciones validas (serie insuficiente); " "metricas NaN (no se fuerza)."

    rows = [
        {
            "bloque": "backtest",
            "objetivo": target,
            "wape": wape,
            "mae": mae,
            "bias": bias,
            "n_obs": n_obs_bt,
            "n_excluidas": int(n_excluded),
            "nota": note_bt,
        },
        {
            # Holdout 1-15 sep: 0 obs reales (los datos terminan el 31-ago,
            # SUP-02/). Se reporta con n_obs=0 y nota, sin forzar un numero.
            "bloque": "holdout_sep",
            "objetivo": target,
            "wape": float("nan"),
            "mae": float("nan"),
            "bias": float("nan"),
            "n_obs": 0,
            "n_excluidas": int(n_excluded),
            "nota": (
                "Holdout 1-15 sep con 0 observaciones reales (los datos "
                "terminan el 31-ago); metricas no calculables, se reporta "
                "n_obs=0 (SUP-02, no se fuerza)."
            ),
        },
    ]
    if bool(config["metricas"]["lectura_rn08"]) and data is not None and n_obs_bt > 0:
        # Segunda lectura (RN-08): mismo backtest, real rellenado en 0 donde la red opera. Las formulas no cambian.
        bt08, _ = exclude_rn07_by_atm(actual_with_rn08_reading(bt_all, data, target), active=active)
        v08 = bt08.dropna(subset=["y", "yhat"])
        rows.insert(
            1,
            {
                "bloque": "backtest",
                "objetivo": target,
                "wape": metrics.wape_aggregate(v08["y"], v08["yhat"], v08["cod_cajero"]),  # ALX SUP-02
                "mae": metrics.mae(v08["y"], v08["yhat"]),
                "bias": metrics.bias(v08["y"], v08["yhat"]),
                "n_obs": int(len(v08)),
                "n_excluidas": int(n_excluded),
                "nota": str(config["metricas"]["nota_rn08"]),
            },
        )
    return pd.DataFrame(rows, columns=columns), int(n_excluded), n_obs_bt


def _backtest_block(
    model: str, backtests: list[pd.DataFrame], config: dict, data: pd.DataFrame, target: str = "pagado"
) -> pd.DataFrame:
    """Pares y/yhat del backtest que puntuan en `metricas` (misma exclusion RN-07, Anexo C y pares observados).

    Incluye la lectura base y, si `metricas.lectura_rn08` esta activa, la lectura RN-08
    (mismo backtest, real rellenado).
    """
    if not backtests:
        return contracts_mod.backtest_block(model, target, pd.DataFrame(columns=["cod_cajero", "fecha", "y", "yhat"]))
    active = bool(config["metricas"]["excluir_rn07_por_cajero"])
    bt_all = pd.concat(backtests, ignore_index=True)
    base, _ = exclude_rn07_by_atm(bt_all, active=active)
    parts = [contracts_mod.backtest_block(model, target, base.dropna(subset=["y", "yhat"]))]
    if bool(config["metricas"]["lectura_rn08"]) and len(parts[0]):
        bt08, _ = exclude_rn07_by_atm(actual_with_rn08_reading(bt_all, data, target), active=active)
        parts.append(
            contracts_mod.backtest_block(model, target, bt08.dropna(subset=["y", "yhat"]), contracts_mod.RN08_READING)
        )
    return pd.concat(parts, ignore_index=True)


def _publish(blocks_by_model: dict[str, dict[str, pd.DataFrame]]) -> dict[str, str]:
    """Ensambla los 4 contratos (filtrados a M1/M2) y los publica con linaje.

    Args:
        blocks_by_model: Mapa `modelo -> {contrato -> DataFrame}`.

    Returns:
        dict[str, str]: Ruta fisica escrita por contrato.
    """
    file_paths: dict[str, str] = {}
    for contract in _CONTRACTS:
        parts = [
            blocks_by_model[m][contract]
            for m in _MODELS
            if m in blocks_by_model and not blocks_by_model[m][contract].empty
        ]
        if parts:
            consolidated = pd.concat(parts, ignore_index=True)
        else:
            # Mantener el contrato con su esquema aunque no haya filas.
            consolidated = pd.concat(
                [blocks_by_model[m][contract] for m in _MODELS if m in blocks_by_model],
                ignore_index=True,
            )
        # Filtrado a M1/M2 (defensa explicita).
        if "modelo" in consolidated.columns:
            consolidated = consolidated[consolidated["modelo"].isin(_MODELS)]
        file_path = publish_contract(contract, consolidated)
        manifest.write_manifest(
            file_path,
            {
                "capa": "output",
                "dataset": f"api/{contract}",
                "contrato": contract,
                "filas": int(len(consolidated)),
                "columnas": list(consolidated.columns),
                "modelos": list(_MODELS),
            },
        )
        file_paths[contract] = file_path
    return file_paths


def _publish_silent(blocks_by_model: dict[str, dict[str, pd.DataFrame]]) -> str:
    """Publica la lista informativa `output/api/silenciosos` (M1 y M2) con linaje; no es parte de los 4 contratos."""
    consolidated = pd.concat(
        [blocks_by_model[m]["silenciosos"] for m in _MODELS if m in blocks_by_model], ignore_index=True
    )
    file_path = publish_contract("silenciosos", consolidated)
    manifest.write_manifest(
        file_path,
        {
            "capa": "output",
            "dataset": "api/silenciosos",
            "contrato": "silenciosos",
            "filas": int(len(consolidated)),
            "columnas": list(consolidated.columns),
            "modelos": list(_MODELS),
        },
    )
    return file_path


def run() -> SummaryU1U2:
    """Orquesta U1/U2: carga -> forecast -> saldo -> acciones -> metricas -> publica.

    Returns:
        ResumenU1U2: Resumen de la corrida (run_id, por modelo, contratos,
        horizonte) para la CLI y la verificacion.
    """
    run_id = manifest.new_run_id()
    logger.info("U1/U2 run_id=%s", run_id)

    config = load_config()
    start = str(config["horizonte"]["inicio"])
    fin = str(config["horizonte"]["fin"])
    dates = _horizon_dates(start, fin)
    logger.info("Horizonte %s..%s (%d dias calendario).", start, fin, len(dates))

    summary = SummaryU1U2(run_id=run_id, horizon=(start, fin))
    blocks_by_model: dict[str, dict[str, pd.DataFrame]] = {}
    for model in _MODELS:
        logger.info("Procesando modelo %s.", model)
        res_model, blocks = _process_model(model, config, dates)
        summary.by_model[model] = res_model
        blocks_by_model[model] = blocks

    summary.contracts = _publish(blocks_by_model)
    summary.contracts["silenciosos"] = _publish_silent(blocks_by_model)
    explainability.upsert([b["explicabilidad"] for b in blocks_by_model.values()], list(_MODELS))
    return summary


def main() -> None:
    """Punto de entrada de consola para las unidades U1/U2.

    Ejecuta `run()` end-to-end y escribe un resumen por consola.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u1_u2",
        description=(
            "Orquesta U1/U2 (ATM M1/M2): carga->forecast->saldo->acciones->"
            "metricas->publica los 4 contratos output/api/*."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log a nivel INFO.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    summary = run()

    print(f"U1/U2 run_id={summary.run_id}")
    print(f"Horizonte: {summary.horizon[0]} .. {summary.horizon[1]}")
    print("Por modelo:")
    for model, r in summary.by_model.items():
        print(
            f"  {model}: cajeros={r.n_atms} predicciones={r.n_predictions} "
            f"alertas={r.n_alerts} recomendaciones={r.n_recommendations} "
            f"n_excluidas={r.n_excluded} n_obs_backtest={r.n_obs_backtest} "
            f"inactivas_rn07={r.n_inactive_rn07} inactivas_rn08={r.n_inactive_rn08} "
            f"WAPE={r.wape} MAE={r.mae} Bias={r.bias}"
        )
    print("Contratos publicados (output/api/):")
    for contract, file_path in summary.contracts.items():
        print(f"  {contract}: {file_path}")


if __name__ == "__main__":
    main()
