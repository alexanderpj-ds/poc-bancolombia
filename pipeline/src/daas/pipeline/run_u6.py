"""Orquestacion de la unidad U6 (Fondos de efectivo M6) del `pipeline`.

M6 es el modelo PRESCRIPTIVO de la PoC: NO entrena ni pronostica, sino que
SIMULA el balance de boveda por `fondo_id`+denominacion a partir de los
pronosticos ya publicados de M1-M5 y RECOMIENDA acciones logisticas costeadas.
Reutiliza la maquinaria congelada SIN tocarla (motor de costos extendido de
forma retrocompatible, contratos UPSERT por modelo, storage, manifest) y encadena:

  1. CARGA   : `modules.funds_m6.dataset.cargar_disponibles` (processed/m6_fondos) +
               `dim_fondo` + `intercambios` + `consolidado_ventas` + los
               pronosticos M1-M5 (`output/api/predicciones`).
  2. BALANCE : saldo inicial (SUP-07), mezcla por denominacion (SUP-09), efecto
               neto M1-M5 por fondo-dia (RN-70 / D-FLUJO-1) con el factor MOVIL de
               red de M5, distribucion por denominacion (ingresos y egresos por
               separado) y min/max operativos (SUP-10).
  3. ACCIONES: simulador secuencial (`modules.funds_m6.simulator`): dia a dia aplica
               el efecto, detecta faltantes/excedentes, elige UNA alternativa de bajo
               costo por necesidad (traslado/venta/BanRep/cambio de denominacion/
               conservar; costeadas con `compute_costs_m6`), la aplica al saldo y
               encadena saldos (RN-71/80/85). Traslados y cambios de denominacion en
               dos filas pareadas (RN-74); sin BanRep/venta/cambio en dias no habiles
               (RN-71A); BanRep solo en ciudades habilitadas (RN-75). Alertas
               (`classify_alerts_m6`) sobre el saldo ANTES de actuar.
  4. PUBLICA : UPSERT por `modelo=='m6'` sobre los 4 contratos output/api/*: lee
               el vigente, elimina las filas m6, concatena el bloque fresco y
               re-publica con `publish.contracts.publish_contract` + manifest
               (deja intactas las 9690 filas de M1-M5).

ID STRATEGY (documentada): los contratos compartidos enmascaran el id de entidad
como `cod_cajero`. La entidad de M6 es el `fondo_id`; se renombra
`fondo_id -> cod_cajero` en los bloques de salida ANTES de publicar, igual que
M4/M5, de modo que `SCHEMAS` y el passthrough existentes aplican SIN cambios.

COLUMNS EXTRA. M6 es el PRIMER modelo que anade columnas extra a los
contratos (hoy m1-m5 comparten exactamente las 7 columnas obligatorias de
`predicciones`, sin extras). El mecanismo es el verificado end-to-end: el UPSERT
concatena m1-m5 (sin extras -> NaN) + m6 (con extras); `_validate_and_type`
conserva las extras sin tiparlas; el schema JSON se regenera con las nuevas
columnas y su dtype. Para que la clave `(modelo, cod_cajero, fecha, objetivo)`
siga siendo UNICA en m6 (6 denominaciones por fondo-dia), el `objetivo` incluye
la denominacion: `objetivo = f'saldo_proyectado_{denominacion}'`. La columna
`denominacion` se castea a `Int64` (entero nullable) en el bloque m6 antes de
publicar, porque el `pd.concat` con m1-m5 (sin esa columna) la volveria float64.

Todo el I/O pasa por `daas.io.storage`; `run_id = manifest.new_run_id()`; no hay
rutas hardcodeadas. Implementacion y verificacion 100% LOCAL (no toca S3).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from dataclasses import dataclass, field

import pandas as pd

from daas.costs import anexo_e
from daas.decision import alerts as alerts_mod
from daas.features.calendar import build_calendar
from daas.io import storage
from daas.lineage import manifest
from daas.modules.funds_m6 import balance as balance_mod
from daas.modules.funds_m6 import dataset as dataset_mod
from daas.modules.funds_m6 import simulator as simulator_mod
from daas.modules.funds_m6.config import load_config
from daas.publish.contracts import publish_contract

logger = logging.getLogger(__name__)

#: Clave del modelo que orquesta esta unidad.
_MODEL = "m6"

#: Nombres de los 4 contratos de salida.
_CONTRACTS: tuple[str, ...] = (
    "predicciones",
    "recomendaciones",
    "alertas",
    "metricas",
)


@dataclass
class ModelSummaryM6:
    """Resumen de la corrida del modelo M6.

    Attributes:
        modelo: Clave de modelo (`m6`).
        n_fondos: Nº de fondos del universo (`dim_fondo`).
        n_denominaciones: Nº de denominaciones en alcance.
        n_predicciones: Filas de balance (fondo-denominacion-dia).
        n_alertas: Nº de alertas emitidas (deficit + exceso).
        n_recomendaciones: Nº de recomendaciones emitidas.
        recomendaciones_por_operacion: Mapa `operacion -> nº de recomendaciones`.
        n_cajeros_sin_fondo: Nº de ids de M1-M3 sin fondo mapeable (SUP-12).
    """

    model: str = _MODEL
    n_funds: int = 0
    n_denominations: int = 0
    n_predictions: int = 0
    n_alerts: int = 0
    n_recommendations: int = 0
    recommendations_by_operation: dict[str, int] = field(default_factory=dict)
    n_atms_without_fund: int = 0


@dataclass
class SummaryU6:
    """Resumen de una corrida completa de `run_u6` (CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        modelo: Resumen del modelo M6.
        contratos: Ruta fisica escrita por contrato publicado.
        horizonte: Par `(inicio, fin)` del horizonte (ISO).
    """

    run_id: str
    model: ModelSummaryM6 = field(default_factory=ModelSummaryM6)
    contracts: dict[str, str] = field(default_factory=dict)
    horizon: tuple[str, str] = ("", "")


def _horizon_dates(start: str, fin: str) -> list[_dt.date]:
    """Construye las fechas calendario del horizonte `[inicio, fin]` (dias corridos).

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


def _predictions_block(balance: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque `predicciones` m6 desde el balance simulado.

    Mapea el balance al contrato: `modelo='m6'`, `cod_cajero=fondo_id`,
    `yhat=saldo_proyectado` (SALDO DE CIERRE del dia, despues de las acciones y
    encadenado: es el saldo inicial del dia siguiente), `band_low=band_high=NaN` (M6
    no produce banda; es un balance determinista). Para preservar la unicidad de la
    clave `(modelo, cod_cajero, fecha, objetivo)` en m6, el `objetivo` incluye la
    denominacion: `saldo_proyectado_{denominacion}`. Columnas extra:
    `denominacion` (`Int64`), `saldo_proyectado`, `efecto_neto_den`, `deficit`,
    `minimo`, `maximo`, `saldo_inicial_dia`, `saldo_antes_acciones`,
    `ingresos_esperados`, `egresos_esperados`, `acciones_netas` y
    `nivel_riesgo` (residual, despues de actuar).

    Args:
        balance: Balance simulado (`simulador.simular(...).balance`).

    Returns:
        pd.DataFrame: Bloque `predicciones` m6 (con `cod_cajero` y `modelo`).
    """
    columns = [
        "modelo",
        "cod_cajero",
        "fecha",
        "objetivo",
        "yhat",
        "band_low",
        "band_high",
        "denominacion",
        "saldo_proyectado",
        "efecto_neto_den",
        "deficit",
        "minimo",
        "maximo",
        "saldo_inicial_dia",
        "saldo_antes_acciones",
        "ingresos_esperados",
        "egresos_esperados",
        "acciones_netas",
        "nivel_riesgo",
    ]
    if balance.empty:
        return pd.DataFrame(columns=columns)

    out = balance.copy()
    out["modelo"] = _MODEL
    out = out.rename(columns={"fondo_id": "cod_cajero"})
    out["objetivo"] = [f"saldo_proyectado_{int(d)}" for d in out["denominacion"]]
    out["yhat"] = out["saldo_proyectado"].astype(float)
    out["band_low"] = float("nan")
    out["band_high"] = float("nan")
    # denominacion como Int64 (tolera los NaN del concat con m1-m5).
    out["denominacion"] = pd.to_numeric(out["denominacion"], errors="coerce").astype("Int64")
    return out[columns]


def _cost_actions(actions: pd.DataFrame) -> pd.DataFrame:
    """Completa el costeo de las acciones simuladas con el motor del Anexo E.

    El simulador ya costeo cada alternativa para decidir; aqui se recalcula con el
    MISMO motor (`compute_costs_m6`) para poblar `concepto_costo`, `sin_tarifa` y
    `sin_transportadora` y se verifica que coincida con el costo usado al decidir.
    Reglas: el costo de un traslado o cambio de denominacion cae SOLO en
    la fila origen (la fila destino lleva 0 y `contraparte_sin_costo`); la venta no
    tiene tarifa en el Anexo E, asi que lleva costo 0 y el `beneficio` de referencia
    (tasa, RN-76) aparte, con `sin_tarifa=False` (no es una tarifa faltante); una
    `sin_accion` no lleva costo (el de almacenar va en `costo_almacenamiento`).

    Args:
        actions: `simulador.simular(...).acciones`.

    Returns:
        pd.DataFrame: `acciones` con `costo`, `sin_transportadora`, `sin_tarifa`,
        `concepto_costo` y `costo_regla` definitivos.
    """
    if actions.empty:
        return actions.assign(
            sin_transportadora=pd.Series(dtype=bool),
            sin_tarifa=pd.Series(dtype=bool),
            concepto_costo=pd.Series(dtype=object),
        )
    out = actions.copy().reset_index(drop=True)
    out["sin_transportadora"] = False
    out["sin_tarifa"] = False
    out["concepto_costo"] = None
    costable = out["operacion"].isin(["traslado", "banrep_consignacion", "banrep_retiro", "cambio_denominacion"]) & (
        out["rol"] != "destino"
    )
    if costable.any():
        base = out.loc[
            costable,
            [
                "operacion",
                "monto",
                "transportadora",
                "ciudad_origen",
                "ciudad_destino",
            ],
        ].copy()
        c = anexo_e.compute_costs_m6(base)
        for col in ("costo", "sin_transportadora", "sin_tarifa", "concepto_costo", "costo_regla"):
            out.loc[costable, col] = c[col].to_numpy()
        previous = actions.loc[costable, "costo"].astype(float).to_numpy()
        new = pd.to_numeric(c["costo"], errors="coerce").to_numpy()
        if not (abs(previous - new) < 1e-6).all():
            raise AssertionError("M6: el costo usado al decidir difiere del costo final")
    out.loc[out["operacion"] == "venta", "concepto_costo"] = (
        "Beneficio de referencia: tasa historica de consolidado_ventas (supuesto)"
    )
    return out


def _recommendations_block(rec: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque `recomendaciones` m6 (una fila por accion y fondo-den).

    Renombra `fondo_id -> cod_cajero`, anade `modelo='m6'` y `fecha_sugerida = fecha`.
    `momento='dia'` para todas: el traslado se aplica el mismo dia (el lag T+1 oficial
    no se modela; limitacion declarada). Columnas extra: `efecto`
    (entrada/salida/ninguno), `rol` (origen/destino), `id_par` (traslados y cambios de
    denominacion = 2 filas con el mismo id), `orden_aplicacion` (orden dentro del
    fondo-denominacion-dia), `criterio`, `beneficio`/`tasa_referencia` (venta),
    `costo_almacenamiento` (excedente conservado) y `necesidad_id`. `saldo_antes` /
    `saldo_despues` son los saldos REALES encadenados; `cupo` queda vacio (RN-03 es de
    M1-M3).

    Args:
        rec: Acciones ya costeadas (`_cost_actions`).

    Returns:
        pd.DataFrame: Bloque `recomendaciones` m6 (con `cod_cajero` y `modelo`).
    """
    columns = [
        "modelo",
        "cod_cajero",
        "accion",
        "momento",
        "fecha_sugerida",
        "monto",
        "costo",
        "sin_transportadora",
        "sin_tarifa",
        "denominacion",
        "denominacion_origen",
        "denominacion_destino",
        "fondo_contraparte",
        "ciudad_origen",
        "ciudad_destino",
        "operacion",
        "concepto_costo",
        "costo_regla",
        "motivo",
        "cupo",
        "saldo_antes",
        "saldo_despues",
        "efecto",
        "rol",
        "id_par",
        "orden_aplicacion",
        "criterio",
        "beneficio",
        "tasa_referencia",
        "costo_almacenamiento",
        "necesidad_id",
    ]
    if rec.empty:
        return pd.DataFrame(columns=columns)

    out = rec.copy()
    out["modelo"] = _MODEL
    out = out.rename(columns={"fondo_id": "cod_cajero"})
    out["fecha_sugerida"] = out["fecha"]
    out["momento"] = "dia"
    out["cupo"] = float("nan")
    for col in ("beneficio", "tasa_referencia", "costo_almacenamiento"):
        if col not in out.columns:
            out[col] = float("nan")
    # Denominaciones enteras extra como Int64 (tolera NaN del concat).
    for col in ("denominacion", "denominacion_origen", "denominacion_destino"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    return out[columns]


def _alerts_block(alerts: pd.DataFrame) -> pd.DataFrame:
    """Ensambla el bloque `alertas` m6 (deficit + exceso por denominacion).

    Renombra `fondo_id -> cod_cajero` y anade `modelo='m6'` (patron `run_u3`:
    `classify_alerts_m6` opera en el espacio `fondo_id` sin `modelo`). Son los riesgos
    detectados ANTES de actuar (saldo antes de las acciones del dia).

    Args:
        alerts: Salida de `alerts.classify_alerts_m6`.

    Returns:
        pd.DataFrame: Bloque `alertas` m6 (con `cod_cajero` y `modelo`).
    """
    columns = [
        "modelo",
        "cod_cajero",
        "fecha",
        "tipo",
        "severidad",
        "nivel",
        "limite",
        "denominacion",
    ]
    if alerts.empty:
        return pd.DataFrame(columns=columns)
    out = alerts.rename(columns={"fondo_id": "cod_cajero"}).copy()
    out["modelo"] = _MODEL
    out["denominacion"] = pd.to_numeric(out["denominacion"], errors="coerce").astype("Int64")
    return out[columns]


def _metric_row(
    block: str, note: str, n_obs: int = 0, n_excluded: int = 0, value: float = float("nan"), origin: str | None = None
) -> dict:
    """Fila de `metricas` m6 sin WAPE (M6 no es un forecaster; SUP-11)."""
    return {
        "modelo": _MODEL,
        "bloque": block,
        "wape": float("nan"),
        "mae": float("nan"),
        "bias": float("nan"),
        "n_obs": int(n_obs),
        "n_excluidas": int(n_excluded),
        "nota": note,
        "valor": float(value),
        "origen": origin,
    }


def _metrics_block(
    balance_initial: pd.DataFrame,
    balance: pd.DataFrame,
    needs: pd.DataFrame,
    actions: pd.DataFrame,
    detail_factor: dict[str, dict],
    storage_cost: float | None,
) -> pd.DataFrame:
    """Ensambla el bloque `metricas` m6 (SUP-11, WAPE no forzado).

    M6 no es un forecaster clasico: no hay objetivo observado comparable, asi que
    NO se fuerza un WAPE (`wape=mae=bias=NaN`). Reporta controles documentados; las
    cifras numericas van en la columna extra `valor`:

    - `completitud_saldo_inicial`: combinaciones con saldo inicial > 0 / a 0 (SUP-07).
    - `cobertura_recomendaciones`: necesidades (faltante/excedente) detectadas y cuantas
      quedaron sin resolver por completo (parciales o sin solucion). Las conservadas por
      costo cuentan como resueltas.
    - `saldo_red_inicial` / `saldo_red_dia_1` / `saldo_red_dia_N`: saldo agregado de la
      red al corte y al cierre del primer y ultimo dia del horizonte (RN-71: el saldo
      no sube sin explicacion; sube por el efecto M1-M5 y por las acciones).
    - `costo_almacenamiento_horizonte`: costo de guardar el saldo de cierre de todos los
      dias con la tarifa del Anexo E (RN-79); informativo, no entra al costo de acciones.
    - `factor_red_<modelo>` y `factor_red_origen_<modelo>`: factor movil aplicado y razon
      real/pronostico de cada origen usado.

    Args:
        balance_initial: Salida de `initial_balance_by_fund_denomination`.
        balance: Balance simulado.
        needs: Necesidades detectadas por el simulador.
        actions: Acciones costeadas.
        detail_factor: Salida de `dataset.detalle_correccion_total`.
        storage_cost: Costo de almacenar el horizonte (None si no hay tarifa).

    Returns:
        pd.DataFrame: Bloque `metricas` m6 (con `modelo`).
    """
    columns = [
        "modelo",
        "bloque",
        "wape",
        "mae",
        "bias",
        "n_obs",
        "n_excluidas",
        "nota",
        "valor",
        "origen",
    ]
    n_with_balance = int((balance_initial["saldo_inicial"] > 0.0).sum())
    n_without_balance = int((balance_initial["saldo_inicial"] <= 0.0).sum())
    rows = [
        _metric_row(
            "completitud_saldo_inicial",
            f"Cobertura del saldo inicial M6: {n_with_balance} combinaciones fondo x "
            f"denominacion con saldo > 0, {n_without_balance} a 0 por falta de registro <= corte "
            "(SUP-07). NO es un WAPE: comparar el saldo inicial contra su propia fuente "
            "daria 0 tautologico (SUP-11).",
            n_obs=n_with_balance,
            n_excluded=n_without_balance,
        )
    ]

    n_need = int(len(needs))
    if n_need:
        count = needs["resultado"].value_counts().to_dict()
        resolved = int(count.get("resuelta", 0))
        kept_count = int(count.get("conservar", 0))
        partial = int(count.get("parcial", 0))
        without_sol = int(count.get("sin_solucion", 0))
    else:
        resolved = kept_count = partial = without_sol = 0
    rows.append(
        _metric_row(
            "cobertura_recomendaciones",
            f"Necesidades de M6 (faltante o excedente por fondo, denominacion y dia): "
            f"{n_need}; resueltas por una accion {resolved}, conservadas por costo de "
            f"almacenamiento menor {kept_count}, cubiertas solo en parte {partial}, "
            f"sin alternativa viable {without_sol}. WAPE no aplica (SUP-11).",
            n_obs=n_need,
            n_excluded=partial + without_sol,
        )
    )

    if not balance.empty:
        dates = sorted(balance["fecha"].unique())
        initial = float(balance.loc[balance["fecha"] == dates[0], "saldo_inicial_dia"].sum())
        for block, date_k in (("saldo_red_dia_1", dates[0]), ("saldo_red_dia_N", dates[-1])):
            value = float(balance.loc[balance["fecha"] == date_k, "saldo_proyectado"].sum())
            rows.append(
                _metric_row(
                    block,
                    f"Saldo de cierre de la red (suma de fondos y denominaciones) el "
                    f"{pd.to_datetime(date_k).date().isoformat()}: {value:,.0f} COP.",
                    n_obs=int(balance["fondo_id"].nunique()),
                    value=value,
                    origin=pd.to_datetime(date_k).date().isoformat(),
                )
            )
        rows.append(
            _metric_row(
                "saldo_red_inicial",
                f"Saldo de la red al corte (insumo del dia 1): {initial:,.0f} COP.",
                value=initial,
            )
        )
    if storage_cost is not None:
        rows.append(
            _metric_row(
                "costo_almacenamiento_horizonte",
                "Costo de guardar el saldo de cierre de todos los dias del horizonte con la "
                "tarifa de almacenamiento del Anexo E por transportadora (RN-78/79). "
                "Informativo: no se suma al costo de las acciones.",
                value=storage_cost,
            )
        )
    for model, d in sorted(detail_factor.items()):
        rows.append(
            _metric_row(
                f"factor_red_{model}",
                f"Factor {d['metodo']} de red aplicado al total de {model} que consume M6: "
                f"{d['factor']:.4f} (crudo {d['crudo']:.4f}, acotado a [factor_min, "
                f"factor_max]); promedio de la razon real/pronostico de "
                f"{len(d['por_origen'])} origen(es) cerrados. El pronostico publicado de "
                f"{model} no se corrige.",
                n_obs=len(d["por_origen"]),
                value=d["factor"],
            )
        )
        for origin, ratio in sorted(d["por_origen"].items()):
            rows.append(
                _metric_row(
                    f"factor_red_origen_{model}",
                    f"Razon real/pronostico de la red de {model} en el origen {origin}.",
                    value=ratio,
                    origin=origin,
                )
            )
    return pd.DataFrame(rows, columns=columns)


def _process_m6(config: dict, dates: list[_dt.date]) -> tuple[ModelSummaryM6, dict[str, pd.DataFrame], pd.DataFrame]:
    """Procesa el modelo M6 end-to-end y devuelve sus 4 bloques de salida.

    Args:
        config: Configuracion de `conf/model_u6.yml` ya cargada.
        dates: Fechas del horizonte (dias calendario / corridos).

    Returns:
        tuple[ResumenModeloM6, dict[str, pd.DataFrame], pd.DataFrame]:
        `(resumen, bloques, recomendaciones_crudas)`. `bloques` mapea los 4
        contratos a los DataFrames del modelo (con `modelo` y `cod_cajero`);
        `recomendaciones_crudas` son las acciones ya costeadas en espacio `fondo_id`.
    """
    cutoff = pd.to_datetime(config["saldo_inicial"]["corte"]).date()
    denominations = [int(d) for d in config["denominaciones"]]

    available_cash = dataset_mod.load_available_cash(config)
    dim_fund = storage.read_table("daas://processed/_dim/dim_fondo")
    exchanges = storage.read_table("daas://interim/intercambios")
    sales = storage.read_table("daas://interim/consolidado_ventas")
    pred_m15 = storage.read_table(dataset_mod._uri(config["fuentes"]["predicciones"]))

    saldo0 = dataset_mod.initial_balance_by_fund_denomination(available_cash, cutoff, denominations, config)
    mix = dataset_mod.denomination_mix_by_fund(available_cash, cutoff, config)
    # Correccion del total de M5 por factor MOVIL de red: razon real/pronostico
    # de los ultimos origenes cerrados antes del corte, publicada por U4/U5 en `metricas`.
    # Si el contrato aun no existe o no hay origenes, no se corrige.
    uri_metrics = dataset_mod._uri(config["fuentes"]["metricas"])
    metrics_m15 = storage.read_table(uri_metrics) if storage.exists(uri_metrics) else None
    detail_factor = dataset_mod.total_correction_detail(metrics_m15, config, cutoff)
    factors = {m: d["factor"] for m, d in detail_factor.items()}
    if factors:
        logger.info("M6: correccion del total por factor de red %s.", factors)
    effect = dataset_mod.net_effect_m1_m5_by_fund_day(pred_m15, dates, config, factors)
    effect_d = dataset_mod.distribute_effect_by_denomination(effect, mix)
    minmax = balance_mod.operational_minmax(available_cash, saldo0, cutoff, config)
    matrix = dataset_mod.enabled_operations_matrix(exchanges, sales, available_cash, config)

    # Calendario CO (RN-71A): dias habiles del horizonte.
    cal = build_calendar(dates[0].isoformat(), dates[-1].isoformat())
    business = {pd.to_datetime(f).date(): bool(h) for f, h in zip(cal["fecha"], cal["es_habil"], strict=False)}
    rates = anexo_e._load_fund_rates()
    sale_rates = dataset_mod.sales_rate_by_fund(sales, cutoff, config)

    sim = simulator_mod.simulate(saldo0, effect_d, minmax, dates, dim_fund, matrix, rates, sale_rates, business, config)
    bal = sim.balance
    rec_cost = _cost_actions(sim.actions)

    # Alertas = riesgos detectados ANTES de actuar (saldo antes de las acciones del dia).
    bal_risk = bal.assign(saldo_proyectado=bal["saldo_antes_acciones"])
    alerts = alerts_mod.classify_alerts_m6(bal_risk)

    # Costo de almacenar el saldo de cierre (RN-79), informativo.
    storage_cost_total: float | None = None
    rate_storage = simulator_mod.storage_rate(rates, config)
    cfg_storage = config.get("costos", {}).get("almacenamiento", {})
    if cfg_storage.get("habilitado", True) and rate_storage:
        tdv = dict(zip(dim_fund["fondo_id"].astype(str), dim_fund["transportadora"].astype(str), strict=False))
        unit = float(cfg_storage.get("unidad_cop", 10_000_000_000))
        storage_cost_total = float(
            sum(
                s / unit * rate_storage.get(tdv.get(f, ""), 0.0)
                for f, s in zip(bal["fondo_id"].astype(str), bal["saldo_proyectado"], strict=False)
            )
        )

    pred_df = _predictions_block(bal)
    rec_df = _recommendations_block(rec_cost)
    alerts_df = _alerts_block(alerts)
    metrics_df = _metrics_block(saldo0, bal, sim.needs, rec_cost, detail_factor, storage_cost_total)

    summary = ModelSummaryM6(
        n_funds=int(dim_fund["fondo_id"].nunique()),
        n_denominations=len(denominations),
        n_predictions=int(len(pred_df)),
        n_alerts=int(len(alerts_df)),
        n_recommendations=int(len(rec_df)),
    )
    if not rec_cost.empty:
        summary.recommendations_by_operation = {
            str(op): int(n) for op, n in rec_cost["operacion"].value_counts().items()
        }

    blocks = {
        "predicciones": pred_df,
        "recomendaciones": rec_df,
        "alertas": alerts_df,
        "metricas": metrics_df,
    }
    return summary, blocks, rec_cost


def _upsert_publish(blocks: dict[str, pd.DataFrame]) -> dict[str, str]:
    """Publica los 4 contratos como UPSERT por modelo (no pisa m1..m5).

    Para cada contrato: si existe el parquet vigente lo lee, elimina las filas
    `modelo=='m6'`, concatena el bloque m6 fresco y re-publica el consolidado con
    `publish_contract`; si no existe, publica solo el bloque m6. Cada contrato
    lleva su `manifest`.

    Args:
        blocks: Mapa `contrato -> DataFrame m6` (con la columna `modelo`).

    Returns:
        dict[str, str]: Ruta fisica escrita por contrato.
    """
    file_paths: dict[str, str] = {}
    for contract in _CONTRACTS:
        block_m6 = blocks[contract]
        uri = f"daas://output/api/{contract}"
        if storage.exists(uri):
            current = storage.read_table(uri)
            kept = current[current["modelo"] != _MODEL] if "modelo" in current.columns else current
            parts = [p for p in (kept, block_m6) if not p.empty]
            consolidated = pd.concat(parts, ignore_index=True) if parts else block_m6
        else:
            consolidated = block_m6

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


def run() -> SummaryU6:
    """Orquesta U6: carga -> balance -> acciones -> metricas -> upsert.

    Returns:
        ResumenU6: Resumen de la corrida (run_id, modelo, contratos, horizonte)
        para la CLI y la verificacion.
    """
    run_id = manifest.new_run_id()
    logger.info("U6 (M6 fondos de efectivo) run_id=%s", run_id)

    config = load_config()
    start = str(config["horizonte"]["inicio"])
    fin = str(config["horizonte"]["fin"])
    dates = _horizon_dates(start, fin)
    logger.info("Horizonte %s..%s (%d dias corridos).", start, fin, len(dates))

    summary = SummaryU6(run_id=run_id, horizon=(start, fin))
    res_model, blocks, _ = _process_m6(config, dates)
    summary.model = res_model
    summary.contracts = _upsert_publish(blocks)
    return summary


def main() -> None:
    """Punto de entrada de consola para la unidad U6 (M6 fondos de efectivo).

    Ejecuta `run()` end-to-end y escribe un resumen por consola.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u6",
        description=(
            "Orquesta U6 (fondos M6): carga->balance->acciones->metricas->upsert "
            "de los 4 contratos output/api/* (sin pisar M1-M5). 100% LOCAL."
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
    print(f"U6 run_id={summary.run_id}")
    print(f"Horizonte: {summary.horizon[0]} .. {summary.horizon[1]}")
    print(
        f"  m6: fondos={r.n_funds} denominaciones={r.n_denominations} "
        f"predicciones={r.n_predictions} alertas={r.n_alerts} "
        f"recomendaciones={r.n_recommendations}"
    )
    if r.recommendations_by_operation:
        print("  recomendaciones por operacion:")
        for op, n in sorted(r.recommendations_by_operation.items()):
            print(f"    {op}: {n}")
    print("Contratos publicados (output/api/):")
    for contract, file_path in summary.contracts.items():
        print(f"  {contract}: {file_path}")


if __name__ == "__main__":
    main()
