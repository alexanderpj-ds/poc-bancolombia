"""Orquestacion de las unidades U4 (M4 CBR) y U5 (M5 Clientes) del `pipeline`.

M4/M5 son los modelos MAS LIVIANOS de la PoC: solo pronostico de **ingreso de
efectivo por FONDO-dia** (`fondo_id = CIUDAD|TRANSPORTADORA`), horizonte 1-15 sep
2026. NO simulan saldo, NO recomiendan logistica y NO emiten alertas (son insumo
de M6). Por eso el orquestador escribe UNICAMENTE los contratos `predicciones` y
`metricas`; NO toca `recomendaciones` ni `alertas` (deja intactas las filas de
M1/M2/M3 en esos contratos).

Un solo orquestador parametrizado procesa AMBOS modelos (son gemelos: misma
logica; difieren en la fuente processed y el nombre del objetivo publicado). Por
cada modelo (`m4`, `m5`):

  1. CARGA   : `modules.funds_inflows_m4_m5.dataset.cargar_serie_fondo_dia(modelo)` lee el
               processed via `daas://`, deriva `fondo_id` (NO viene en el
               processed de C-07/C-08) y agrega `valor -> ingreso_efectivo` por
               `(fondo_id, fecha)`, densificando a dias calendario.
  2. FORECAST: pronostica `ingreso_efectivo` de todos los fondos a la vez con
               `forecasting.forecast.pronosticar` (horizonte 1-15 sep, backtest por
               ventana de fechas y banda), con la receta que elige
               `forecaster.modelo` en `conf/model_u4_u5.yml`.
  3. METRICAS: backtest interno -> WAPE/MAE/Bias; el holdout de sep se
               reporta con `n_obs=0` y nota (SUP-02, sin forzar). M4/M5 SIN
               exclusion RN-07 (RN-07 es de ATM; no aplica a puntos CBR/clientes).
  4. PUBLICA : UPSERT por modelo sobre `predicciones` y `metricas`: lee el
               contrato vigente (si existe), elimina las filas `modelo in {m4,
               m5}`, concatena los bloques frescos de m4 y m5 y re-publica con
               `publish.contracts.publish_contract` + `manifest.write_manifest`
               (NO toca `recomendaciones`/`alertas`; conserva M1/M2/M3).

ID STRATEGY (documentada): los contratos compartidos enmascaran el id de entidad
como `cod_cajero` (`publish/contracts.py::_COL_ID`). La entidad de M4/M5 es el
`fondo_id`; se renombra `fondo_id -> cod_cajero` en el bloque de predicciones
ANTES de publicar, de modo que `SCHEMAS['predicciones']` y el passthrough
existentes aplican SIN CAMBIOS (no se altera el esquema; M1/M2/M3 intactos).

Todo el I/O pasa por `daas.io.storage`; `run_id = manifest.new_run_id()`; no hay
rutas hardcodeadas.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from dataclasses import dataclass, field

import pandas as pd

from daas.forecasting import forecast as forecast_mod
from daas.forecasting import forecasters as forecasters
from daas.forecasting import laboratorio, metrics
from daas.io import storage
from daas.lineage import manifest
from daas.modules.funds_inflows_m4_m5.config import load_config
from daas.modules.funds_inflows_m4_m5.dataset import load_fund_day_series
from daas.publish import contracts as contracts_mod
from daas.publish import explainability as explainability
from daas.publish.contracts import publish_contract

logger = logging.getLogger(__name__)

#: Claves de los modelos que orquesta esta unidad.
_MODELS: tuple[str, ...] = ("m4", "m5")

#: Bloque de `metricas` con el sesgo del total de la red por ORIGEN (lo lee M6 para el
#: factor movil de `correccion_total`: razon real/pronostico de los origenes previos).
NETWORK_BIAS_BLOCK_ORIGIN = "sesgo_red_origen"

#: Bloque de `metricas` con el sesgo del total de la red (lo lee M6).
NETWORK_BIAS_BLOCK = "sesgo_red"

#: Contratos de salida que M4/M5 escriben (SIN recomendaciones ni alertas).
_CONTRACTS: tuple[str, ...] = ("predicciones", "metricas", "backtest")

#: Columna objetivo interna (agregada a fondo-dia por el loader).
_INTERNAL_TARGET = "ingreso_efectivo"


@dataclass
class ModelSummaryU4U5:
    """Resumen de la corrida de un modelo M4/M5.

    Attributes:
        modelo: Clave de modelo (`m4`/`m5`).
        objetivo: Nombre del objetivo publicado (p.ej. `ingreso_efectivo_cbr`).
        n_fondos: Nº de fondos con serie cargada.
        n_predicciones: Filas de pronostico (fondo-dia) del horizonte.
        wape: WAPE del backtest interno (NaN si sin denominador).
        mae: MAE del backtest interno.
        bias: Bias del backtest interno.
        n_obs_backtest: Nº de observaciones del backtest.
    """

    model: str
    target: str
    n_funds: int = 0
    n_predictions: int = 0
    wape: float = float("nan")
    mae: float = float("nan")
    bias: float = float("nan")
    n_obs_backtest: int = 0


@dataclass
class SummaryU4U5:
    """Resumen de una corrida completa de `run_u4_u5` (CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        modelos: Resumen por modelo (`m4`, `m5`).
        contratos: Ruta fisica escrita por contrato publicado.
        horizonte: Par `(inicio, fin)` del horizonte de pronostico (ISO).
    """

    run_id: str
    models: dict[str, ModelSummaryU4U5] = field(default_factory=dict)
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


def _network_bias_row(evaluations: pd.DataFrame | None, target: str) -> list[dict]:
    """Fila `sesgo_red`: sesgo del TOTAL de la red sobre todos los origenes fuera de muestra.

    M6 suma estos ingresos; el modelo que gana en WAPE apunta a la mediana y
    subestima el total. El sesgo se publica aqui, medido con
    pronosticos hechos con datos <= su origen, y M6 lo usa para corregir el
    total (`correccion_total` en `conf/model_u6.yml`). No se fuerza: sin
    observaciones no hay fila.
    """
    if evaluations is None or evaluations.empty:
        return []
    valid_ids = evaluations.dropna(subset=["y", "yhat"])
    if valid_ids.empty:
        return []
    n_origins = int(valid_ids["origen"].nunique())
    # Un sesgo por ORIGEN (columna extra `origen`, ISO): insumo del factor movil de M6,
    # que solo puede usar origenes ANTERIORES al de la corrida (sin fuga).
    by_origin = []
    for origin, g in valid_ids.groupby("origen", sort=True):
        by_origin.append(
            {
                "bloque": NETWORK_BIAS_BLOCK_ORIGIN,
                "objetivo": target,
                "wape": float("nan"),
                "mae": float("nan"),
                "bias": metrics.bias(g["y"], g["yhat"]),
                "n_obs": int(len(g)),
                "n_excluidas": 0,
                "nota": (
                    f"Sesgo del total de la red de '{target}' en el origen "
                    f"{pd.to_datetime(origin).date().isoformat()} (insumo del factor movil "
                    "de M6)."
                ),
                "origen": pd.to_datetime(origin).date().isoformat(),
            }
        )
    return by_origin + [
        {
            "bloque": NETWORK_BIAS_BLOCK,
            "objetivo": target,
            "wape": float("nan"),
            "mae": float("nan"),
            "bias": metrics.bias(valid_ids["y"], valid_ids["yhat"]),
            "n_obs": int(len(valid_ids)),
            "n_excluidas": 0,
            "nota": (
                f"Sesgo del total de la red de '{target}' sobre {n_origins} "
                "origen(es) fuera de muestra (ventanas de backtest y de "
                "calibracion). Insumo de la correccion del total en M6."
            ),
        }
    ]


def _metrics_block(
    backtests: list[pd.DataFrame],
    target: str,
    evaluations: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, int]:
    """Calcula las metricas del modelo (backtest interno + holdout sep).

    Patron EXACTO de `run_u3._bloque_metricas` para un unico objetivo: bloque
    `backtest` (WAPE/MAE/Bias sobre la ultima ventana del entrenamiento) +
    bloque `holdout_sep` con `n_obs=0` y nota (SUP-02, sin forzar). M4/M5 SIN
    exclusion RN-07 (no aplica a puntos CBR/clientes).

    Args:
        backtests: Lista de backtests por fondo (`fecha`, `y`, `yhat`).
        target: Nombre del objetivo publicado (para las notas).
        evaluations: Evaluaciones del pronostico; si se pasan, se agrega la fila de sesgo de red.

    Returns:
        tuple[pd.DataFrame, int]: `(metricas_df, n_obs_backtest)` con
        `metricas_df` de columnas `bloque`, `objetivo`, `wape`, `mae`, `bias`,
        `n_obs`, `n_excluidas`, `nota`.
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
        "origen",
    ]
    bt_all = pd.concat(backtests, ignore_index=True) if backtests else pd.DataFrame(columns=["fecha", "y", "yhat"])
    valid_ids = bt_all.dropna(subset=["y", "yhat"]) if not bt_all.empty else bt_all
    n_obs_bt = int(len(valid_ids))

    if n_obs_bt > 0:
        wape = metrics.wape_aggregate(  # ALX SUP-02: entidad con denominador cero fuera del WAPE agregado
            valid_ids["y"], valid_ids["yhat"], valid_ids.get("cod_sucursal", valid_ids.get("cod_cajero"))
        )
        mae = metrics.mae(valid_ids["y"], valid_ids["yhat"])
        bias = metrics.bias(valid_ids["y"], valid_ids["yhat"])
        note_bt = (
            f"Backtest interno de '{target}' (ultima ventana del "
            f"entrenamiento, D7); M4/M5 sin exclusion RN-07 (no aplica a "
            "puntos CBR/clientes)."
        )
    else:
        wape = mae = bias = float("nan")
        note_bt = (
            f"Backtest interno de '{target}' sin observaciones validas "
            "(serie insuficiente); metricas NaN (no se fuerza). M4/M5 sin "
            "exclusion RN-07."
        )

    rows = [
        {
            "bloque": "backtest",
            "objetivo": target,
            "wape": wape,
            "mae": mae,
            "bias": bias,
            "n_obs": n_obs_bt,
            "n_excluidas": 0,
            "nota": note_bt,
        },
        {
            "bloque": "holdout_sep",
            "objetivo": target,
            "wape": float("nan"),
            "mae": float("nan"),
            "bias": float("nan"),
            "n_obs": 0,
            "n_excluidas": 0,
            "nota": (
                f"Holdout 1-15 sep de '{target}' con 0 observaciones reales "
                "(los datos terminan el 31-ago); metricas no calculables, se "
                "reporta n_obs=0 (SUP-02, no se fuerza)."
            ),
        },
    ]
    rows += _network_bias_row(evaluations, target)
    return pd.DataFrame(rows, columns=columns), n_obs_bt


def _process_model(model: str, config: dict, dates: list[_dt.date]) -> tuple[ModelSummaryU4U5, dict[str, pd.DataFrame]]:
    """Procesa un modelo M4/M5 end-to-end y devuelve sus 2 bloques de salida.

    Args:
        model: Clave del modelo (`m4`/`m5`).
        config: Configuracion de `conf/model_u4_u5.yml` ya cargada.
        dates: Fechas del horizonte de pronostico (dias calendario).

    Returns:
        tuple[ResumenModeloU4U5, dict[str, pd.DataFrame]]: `(resumen, bloques)`
        donde `bloques` mapea `predicciones` y `metricas` a los DataFrames del
        modelo (con la columna `modelo` y el id de entidad ya renombrado a
        `cod_cajero` en predicciones).
    """
    min_obs = int(config["forecaster"]["min_obs"])
    backtest_days = int(config["backtest"]["dias"])
    target_published = str(config["modelos"][model]["objetivo"])

    data = load_fund_day_series(model)
    funds = sorted(data["fondo_id"].dropna().unique().tolist())

    predictions: list[pd.DataFrame] = []
    backtests: list[pd.DataFrame] = []
    summary = ModelSummaryU4U5(model=model, target=target_published, n_funds=int(len(funds)))

    # Pronostico de TODOS los fondos a la vez (camino unico: horizonte + backtest
    # por ventana de fechas + banda). La receta se elige por modelo en
    # `forecaster.modelo`.
    # ALX PARTE 7: champion `ml_laboratorio` con contexto V4 "as of" (no hace nada con la receta de Santiago).
    laboratorio.preparar(forecasters.resolve_model(config["forecaster"], model), data, "fondo_id", _INTERNAL_TARGET)
    forecast = forecast_mod.generate_forecast(
        data,
        "fondo_id",
        _INTERNAL_TARGET,
        dates,
        model=forecasters.resolve_model(config["forecaster"], model),
        min_obs=min_obs,
        backtest_days=backtest_days,
    )

    for fund in funds:
        fc, bt = forecast.of(fund)
        if not bt.empty:
            backtests.append(bt.assign(cod_cajero=fund))

        # ID STRATEGY: fondo_id -> cod_cajero ANTES de ensamblar el contrato.
        pred = fc.copy()
        pred.insert(0, "cod_cajero", fund)
        pred["objetivo"] = target_published
        predictions.append(pred)

    pred_df = (
        pd.concat(predictions, ignore_index=True)
        if predictions
        else pd.DataFrame(columns=["cod_cajero", "fecha", "yhat", "band_low", "band_high", "objetivo"])
    )
    metrics_df, n_obs = _metrics_block(backtests, target_published, forecast.evaluations)

    summary.n_predictions = int(len(pred_df))
    summary.n_obs_backtest = n_obs
    if not metrics_df.empty:
        bt_row = metrics_df[metrics_df["bloque"] == "backtest"]
        if not bt_row.empty:
            summary.wape = float(bt_row["wape"].iloc[0])
            summary.mae = float(bt_row["mae"].iloc[0])
            summary.bias = float(bt_row["bias"].iloc[0])

    blocks = {
        "predicciones": pred_df.assign(modelo=model),
        "metricas": metrics_df.assign(modelo=model),
        "backtest": contracts_mod.backtest_block(
            model,
            target_published,
            pd.concat(backtests, ignore_index=True).dropna(subset=["y", "yhat"])
            if backtests
            else pd.DataFrame(columns=["cod_cajero", "fecha", "y", "yhat"]),
        ),
        # Artefacto lateral (no es contrato): lo publica `run()`.
        "explicabilidad": explainability.block(model, {target_published: forecast.explanation}),
    }
    return summary, blocks


def _upsert_publish(
    blocks_by_model: dict[str, dict[str, pd.DataFrame]],
) -> dict[str, str]:
    """Publica `predicciones` y `metricas` como UPSERT por modelo (D-U45-8).

    Para cada contrato: si existe el parquet vigente lo lee, elimina las filas
    `modelo in {m4, m5}`, concatena los bloques frescos de m4 y m5 y re-publica
    el consolidado con `publish_contract`; si no existe, publica solo los
    bloques de M4/M5. NO toca `recomendaciones` ni `alertas` (conserva M1/M2/M3).
    Cada contrato lleva su `manifest`.

    Args:
        blocks_by_model: Mapa `modelo -> {contrato -> DataFrame}`.

    Returns:
        dict[str, str]: Ruta fisica escrita por contrato.
    """
    file_paths: dict[str, str] = {}
    for contract in _CONTRACTS:
        fresh = [
            blocks_by_model[m][contract]
            for m in _MODELS
            if m in blocks_by_model and not blocks_by_model[m][contract].empty
        ]
        block_fresco = pd.concat(fresh, ignore_index=True) if fresh else pd.DataFrame()

        uri = f"daas://output/api/{contract}"
        if storage.exists(uri):
            current = storage.read_table(uri)
            kept = current[~current["modelo"].isin(_MODELS)] if "modelo" in current.columns else current
            parts = [p for p in (kept, block_fresco) if not p.empty]
            consolidated = pd.concat(parts, ignore_index=True) if parts else block_fresco
        else:
            consolidated = block_fresco

        file_path = publish_contract(contract, consolidated)
        models = (
            sorted(consolidated["modelo"].dropna().unique().tolist())
            if "modelo" in consolidated.columns
            else list(_MODELS)
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


def run() -> SummaryU4U5:
    """Orquesta U4/U5: carga -> forecast -> metricas -> upsert (predicciones+metricas).

    Returns:
        ResumenU4U5: Resumen de la corrida (run_id, modelos, contratos,
        horizonte) para la CLI y la verificacion.
    """
    run_id = manifest.new_run_id()
    logger.info("U4/U5 (M4 CBR + M5 Clientes) run_id=%s", run_id)

    config = load_config()
    start = str(config["horizonte"]["inicio"])
    fin = str(config["horizonte"]["fin"])
    dates = _horizon_dates(start, fin)
    logger.info("Horizonte %s..%s (%d dias calendario).", start, fin, len(dates))

    summary = SummaryU4U5(run_id=run_id, horizon=(start, fin))
    blocks_by_model: dict[str, dict[str, pd.DataFrame]] = {}
    for model in _MODELS:
        res_model, blocks = _process_model(model, config, dates)
        summary.models[model] = res_model
        blocks_by_model[model] = blocks

    summary.contracts = _upsert_publish(blocks_by_model)
    explainability.upsert([b["explicabilidad"] for b in blocks_by_model.values()], list(_MODELS))
    return summary


def main() -> None:
    """Punto de entrada de consola para las unidades U4/U5 (M4 CBR + M5 Clientes).

    Ejecuta `run()` end-to-end y escribe un resumen por consola.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u4_u5",
        description=(
            "Orquesta U4/U5 (M4 CBR + M5 Clientes): carga->forecast->metricas->"
            "upsert de predicciones y metricas (sin saldo/alertas/recomendaciones, "
            "sin pisar M1/M2/M3)."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log a nivel INFO.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    summary = run()

    print(f"U4/U5 run_id={summary.run_id}")
    print(f"Horizonte: {summary.horizon[0]} .. {summary.horizon[1]}")
    for model in _MODELS:
        r = summary.models.get(model)
        if r is None:
            continue
        print(
            f"  {model} ({r.target}): fondos={r.n_funds} "
            f"predicciones={r.n_predictions} WAPE={r.wape} MAE={r.mae} "
            f"Bias={r.bias} n_obs_backtest={r.n_obs_backtest}"
        )
    print("Contratos publicados (output/api/):")
    for contract, file_path in summary.contracts.items():
        print(f"  {contract}: {file_path}")


if __name__ == "__main__":
    main()
