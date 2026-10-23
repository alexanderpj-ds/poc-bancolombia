"""Orquestacion de la unidad U0 del subpaquete `pipeline`.

Regla de negocio: `run_u0` encadena las etapas de U0 en orden:
ingest (lectores C-01..C-12) -> quality (validaciones V-xx + Anexo C) ->
fondo (dim_fondo) -> curate (processed por modelo) -> features
(calendario + ts_features). Es la compuerta de datos de la PoC.

Flujo (medallion, unidireccional):
  1. INGEST  : cada lector C-01..C-12 -> normalize -> `interim/<dataset>`.
  2. FONDO   : `dim_fondo` autoritativo (V-10 fatal si != 6) -> `processed/_dim/`.
  3. QUALITY : por dataset, validaciones V-xx; compuerta conforme/cuarentena y
               reporte DQ cuadrado.
  4. CURATE  : por modelo m1..m6, deriva la base, aplica el corte V-07 y separa
               el holdout 1-15 sep -> `processed/<modelo>` y
               `processed/_holdout/<modelo>`.
  5. FEATURES: `dim_calendario` (holidays CO) -> `features/dim_calendario`;
               `add_ts_features` por modelo -> `features/ts_features_<modelo>`.
  Cada artefacto escrito lleva su manifiesto `.meta.json`.

Todo el I/O pasa por `daas.io.storage` (URIs abstractas `daas://`), de modo que
corre identico en S3 y en el espejo local. No hay rutas hardcodeadas.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from daas.curate.build_processed import MODELS, split_cutoff
from daas.features.calendar import build_calendar
from daas.features.ts_features import add_ts_features
from daas.fondo.build_fund import build_dim_fund
from daas.ingest import normalize
from daas.ingest.readers import anexo_e_costs as anexo_e_costs
from daas.ingest.readers import atm_transactions as atm_transactions
from daas.ingest.readers import available_cash as available_cash
from daas.ingest.readers import branch_master as branch_master
from daas.ingest.readers import cbr, txc_suc
from daas.ingest.readers import cp_history as cp_history
from daas.ingest.readers import cp_uninstalled as cp_uninstalled
from daas.ingest.readers import customers as customers
from daas.ingest.readers import exchanges as exchanges
from daas.ingest.readers import offices as offices
from daas.ingest.readers import sales_summary as sales_summary
from daas.io import storage
from daas.lineage import manifest
from daas.quality import anexo_c, checks
from daas.quality.anexo_c import mark_missing
from daas.quality.report import DatasetResult, generate_report

logger = logging.getLogger(__name__)

#: Lectores por contrato canonico (C-01..C-12).
_READERS: dict[str, Callable[[], pd.DataFrame]] = {
    "C-01": atm_transactions.read,
    "C-02": cp_history.read,
    "C-03": cp_uninstalled.read,
    "C-04": txc_suc.read,
    "C-05": offices.read,
    "C-06": branch_master.read,
    "C-07": cbr.read,
    "C-08": customers.read,
    "C-09": available_cash.read,
    "C-10": exchanges.read,
    "C-11": sales_summary.read,
    "C-12": anexo_e_costs.read,
}

#: Contrato -> nombre de dataset interim (coherente con).
_DATASET = {
    "C-01": "txn_cajeros",
    "C-02": "cp_historico",
    "C-03": "cp_desinstalados",
    "C-04": "txc_suc",
    "C-05": "oficinas",
    "C-06": "maestro_sucursales",
    "C-07": "cbr",
    "C-08": "clientes",
    "C-09": "disponibles",
    "C-10": "intercambios",
    "C-11": "consolidado_ventas",
    "C-12": "costos_anexo_e",
}


@dataclass
class ModelSpec:
    """Especificacion de curado/features de un modelo (mapeo modelo->fuente).

    Attributes:
        clave: Clave de modelo (`m1`..`m6`).
        contrato: Contrato canonico fuente (C-01..C-11).
        entidad: Columna de entidad para densificar/features.
        objetivo: Columna objetivo (serie a pronosticar).
        filtro: Filtro opcional sobre el interim (p.ej. disp_mf==DISPENSADOR).
    """

    key: str
    contract: str
    entity: str
    target: str
    row_filter: Callable[[pd.DataFrame], pd.Series] | None = field(default=None)


#: Mapeo modelo -> fuente/entidad/objetivo (: C-01 M1+M2, C-04 M3, C-07 M4,
#: C-08 M5, C-09 M6).
_MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "m1",
        "C-01",
        "cod_cajero",
        "monto",
        row_filter=lambda d: d["disp_mf"] == "DISPENSADOR",
    ),
    ModelSpec(
        "m2",
        "C-01",
        "cod_cajero",
        "monto",
        row_filter=lambda d: d["disp_mf"] == "MULTIFUNCIONAL",
    ),
    ModelSpec("m3", "C-04", "cod_sucursal", "salidas"),
    ModelSpec("m4", "C-07", "cod_punto", "valor"),
    ModelSpec("m5", "C-08", "cod_punto", "valor"),
    ModelSpec("m6", "C-09", "fondo_id", "valor"),
)


@dataclass
class SummaryU0:
    """Resumen de una corrida de `run_u0` (para CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        conteos_interim: Filas por dataset interim.
        conteos_entidades: Entidades unicas por dataset clave.
        dq: Resumen del reporte DQ (`cuadra_global`, por dataset).
        processed: Filas de entrenamiento + holdout por modelo.
    """

    run_id: str
    counts_interim: dict[str, int] = field(default_factory=dict)
    counts_entities: dict[str, int] = field(default_factory=dict)
    dq: dict = field(default_factory=dict)
    processed: dict[str, dict[str, int]] = field(default_factory=dict)


def _ingest() -> dict[str, pd.DataFrame]:
    """Lee y normaliza los 12 contratos, escribe `interim/` y devuelve el mapa.

    Returns:
        dict[str, pd.DataFrame]: `contrato -> interim normalizado`.
    """
    interim: dict[str, pd.DataFrame] = {}
    for contract, read in _READERS.items():
        logger.info("INGEST %s (%s)", contract, _DATASET[contract])
        df = normalize.normalize(read(), contract)
        interim[contract] = df
        physical = storage.write_table(df, f"daas://interim/{_DATASET[contract]}")
        manifest.write_manifest(
            physical,
            {
                "capa": "interim",
                "contrato": contract,
                "dataset": _DATASET[contract],
                "filas": int(len(df)),
                "columnas": list(df.columns),
            },
        )
    return interim


def _quality(interim: dict[str, pd.DataFrame], run_id: str) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Aplica la compuerta de calidad por dataset y genera el reporte DQ.

    Para cada dataset se aplican las validaciones aplicables (dominio de ciudad,
    corte V-07, Anexo C en las fuentes diarias, cobertura/universo). V-10 (fatal)
    verifica `dim_fondo == 6` antes de curar.

    La compuerta NO es solo-reporte: los DataFrames **conformes** (con las marcas
    V-04/V-09/V-12 ya aplicadas) se devuelven para que `curate` consuma solo lo
    que paso la compuerta (los rechazos ya fueron a cuarentena). Los contratos
    sin validacion explicita se propagan tal cual desde `interim`.

    Args:
        interim: Mapa `contrato -> interim`.
        run_id: Identificador de corrida.

    Returns:
        tuple[dict, dict[str, pd.DataFrame]]: `(reporte_dq, conformes)` donde
        `reporte_dq` incluye `cuadra_global` y `conformes` mapea
        `contrato -> DataFrame conforme` para alimentar el curado.
    """
    # V-10 fatal: dim_fondo == 6 (aborta la corrida si difiere).
    checks.run_check("V-10", None)

    results: list[DatasetResult] = []
    # Arranca con el interim crudo; cada validacion reemplaza su contrato por el
    # DataFrame conforme (lo rechazado sale a cuarentena en generate_report).
    compliant_frames: dict[str, pd.DataFrame] = dict(interim)

    # C-09 disponibles: dominio de ciudad (ya filtrado por el lector; cuadra).
    dispenser = interim["C-09"]
    conf, rejected_rows = checks.run_check("V-04", dispenser, columna="ciudad", dominio=["CALI", "PASTO", "IPIALES"])
    compliant_frames["C-09"] = conf
    results.append(
        DatasetResult(
            "disponibles",
            total_inflow=len(dispenser),
            compliant=conf,
            rejected=rejected_rows,
            notes={"entidades_fondo": int(conf["fondo_id"].nunique())} if "fondo_id" in conf.columns else {},
        )
    )

    # Clientes (C-08): universo observado vs esperado (P24, V-12; no fuerza).
    customer = interim["C-08"]
    conf_customer, rejected_customer = checks.run_check("V-12", customer, entity_col="cod_punto", esperado=344)
    compliant_frames["C-08"] = conf_customer
    results.append(
        DatasetResult(
            "clientes",
            total_inflow=len(customer),
            compliant=conf_customer,
            rejected=rejected_customer,
            notes={
                "universo_observado": int(conf_customer.attrs.get("universo_observado", 0)),
                "universo_esperado": conf_customer.attrs.get("universo_esperado"),
            },
        )
    )

    # CBR (C-07) y sucursales (C-04): cobertura de entidades (informativo).
    cbr_df = interim["C-07"]
    conf_cbr, rejected_cbr = checks.run_check("V-11", cbr_df, entity_col="cod_punto")
    compliant_frames["C-07"] = conf_cbr
    results.append(
        DatasetResult(
            "cbr",
            total_inflow=len(cbr_df),
            compliant=conf_cbr,
            rejected=rejected_cbr,
            notes={"entidades": int(cbr_df["cod_punto"].nunique())},
        )
    )
    branch = interim["C-04"]
    conf_branch, rejected_branch = checks.run_check("V-11", branch, entity_col="cod_sucursal")
    compliant_frames["C-04"] = conf_branch
    results.append(
        DatasetResult(
            "txc_suc",
            total_inflow=len(branch),
            compliant=conf_branch,
            rejected=rejected_branch,
            notes={"entidades": int(branch["cod_sucursal"].nunique())},
        )
    )

    # ATM (C-01): reconciliacion RN-07 (V-09) marca conflictos activo/desinstalado.
    atm = interim["C-01"]
    uninstalled = set(interim["C-03"]["cod_cajero"].dropna().unique().tolist())
    active = set(atm["cod_cajero"].dropna().unique().tolist())
    conf_atm, rejected_atm = checks.run_check(
        "V-09", atm, desinstalados=uninstalled, activos=active, columna="cod_cajero"
    )
    compliant_frames["C-01"] = conf_atm
    conflicts = int(conf_atm["__rn07_conflicto"].sum()) if "__rn07_conflicto" in conf_atm.columns else 0
    results.append(
        DatasetResult(
            "txn_cajeros",
            total_inflow=len(atm),
            compliant=conf_atm,
            rejected=rejected_atm,
            notes={
                "entidades": int(atm["cod_cajero"].nunique()),
                "rn07_conflictos": conflicts,
                # Aviso (no bloqueo) de frescura frente al corte y de huecos en toda la red.
                "frescura": checks.freshness_warning(
                    atm, corte=anexo_c.training_cutoff(), ventana_anexo_c=anexo_c.anexo_c_window()
                ),
            },
        )
    )

    report = generate_report(results, ts=run_id.split("_")[0])
    return report, compliant_frames


def _curate_features(compliant_frames: dict[str, pd.DataFrame], run_id: str) -> dict:
    """Cura por modelo (corte V-07 + holdout) y construye features.

    Consume los DataFrames **conformes** que entrego la compuerta de calidad
    (`_quality`), no el interim crudo: curate solo propaga dato que paso la
    compuerta. Antes de `add_ts_features`, cada set de entrenamiento se densifica
    por entidad via `anexo_c.mark_missing` (V-08) para que (a) los 27 dias del
    Anexo C queden NULL (nunca 0) y (b) los lags/rolling signifiquen "k dias
    naturales" sobre una serie densa, no "k observaciones".

    Args:
        compliant_frames: Mapa `contrato -> DataFrame conforme` (salida de `_quality`).
        run_id: Identificador de corrida.

    Returns:
        dict: Conteos por modelo `{clave: {entrenamiento, holdout}}`.
    """
    interim = compliant_frames
    # dim_fondo autoritativo -> processed/_dim.
    dim = build_dim_fund()
    physical_dim = storage.write_table(dim, "daas://processed/_dim/dim_fondo")
    manifest.write_manifest(
        physical_dim, {"capa": "processed", "dataset": "_dim/dim_fondo", "filas": int(len(dim)), "run_id": run_id}
    )

    # Rango del calendario: del minimo historico al fin de la ventana de eval.
    dates_all: list[_dt.date] = []
    for contract in ("C-01", "C-04", "C-07", "C-08", "C-09"):
        df = interim.get(contract)
        if df is not None and "fecha" in df.columns and not df.empty:
            series = pd.to_datetime(df["fecha"], errors="coerce").dropna()
            if not series.empty:
                dates_all.append(series.min().date())
                dates_all.append(series.max().date())
    start = min(dates_all) if dates_all else _dt.date(2024, 1, 1)
    fin = max(dates_all + [_dt.date(2026, 9, 15)])

    calendar = build_calendar(start.isoformat(), fin.isoformat())
    physical_cal = storage.write_table(calendar, "daas://features/dim_calendario")
    manifest.write_manifest(
        physical_cal,
        {"capa": "features", "dataset": "dim_calendario", "filas": int(len(calendar)), "run_id": run_id},
    )

    counts: dict[str, dict[str, int]] = {}

    for spec in _MODEL_SPECS:
        base = interim[spec.contract].copy()
        if spec.row_filter is not None:
            base = base.loc[spec.row_filter(base)].reset_index(drop=True)

        training, holdout = split_cutoff(base)
        folder = MODELS[spec.key]

        physical_tr = storage.write_table(training, f"daas://processed/{folder}")
        manifest.write_manifest(
            physical_tr,
            {
                "capa": "processed",
                "modelo": spec.key,
                "dataset": folder,
                "contrato": spec.contract,
                "filas": int(len(training)),
                "entidad": spec.entity,
                "objetivo": spec.target,
                "run_id": run_id,
            },
        )
        physical_ho = storage.write_table(holdout, f"daas://processed/_holdout/{folder}")
        manifest.write_manifest(
            physical_ho,
            {
                "capa": "processed",
                "modelo": spec.key,
                "dataset": f"_holdout/{folder}",
                "filas": int(len(holdout)),
                "run_id": run_id,
            },
        )

        # Features de serie temporal sobre el set de entrenamiento (sin fuga).
        has_cols = spec.entity in training.columns and spec.target in training.columns and "fecha" in training.columns
        if has_cols and not training.empty:
            # Densificar por entidad (V-08): calendario diario completo con los
            # 27 dias del Anexo C en NULL (missing_anexo_c=True). Esto es lo que
            # habilita que add_ts_features (a) excluya el Anexo C del rolling y
            # (b) interprete los lags como dias naturales, no observaciones.
            dense = mark_missing(
                training,
                entity_col=spec.entity,
                date_col="fecha",
                target_col=spec.target,
            )
            feats = add_ts_features(dense, entity_col=spec.entity, target=spec.target)
            physical_ft = storage.write_table(feats, f"daas://features/ts_features_{spec.key}")
            manifest.write_manifest(
                physical_ft,
                {
                    "capa": "features",
                    "modelo": spec.key,
                    "dataset": f"ts_features_{spec.key}",
                    "filas": int(len(feats)),
                    "run_id": run_id,
                },
            )

        counts[spec.key] = {
            "entrenamiento": int(len(training)),
            "holdout": int(len(holdout)),
            "entidades": int(training[spec.entity].nunique()) if spec.entity in training.columns else 0,
        }

    return counts


def run() -> SummaryU0:
    """Orquesta U0: ingest -> quality -> fondo -> curate -> features.

    Returns:
        ResumenU0: Resumen de la corrida (run_id, conteos, DQ, processed) para
        la CLI y la verificacion.
    """
    run_id = manifest.new_run_id()
    logger.info("U0 run_id=%s", run_id)

    interim = _ingest()
    summary = SummaryU0(run_id=run_id)
    summary.counts_interim = {_DATASET[c]: int(len(df)) for c, df in interim.items()}
    summary.counts_entities = {
        "atm_cod_cajero": int(interim["C-01"]["cod_cajero"].nunique()),
        "sucursales_cod_sucursal": int(interim["C-04"]["cod_sucursal"].nunique()),
        "cbr_cod_punto": int(interim["C-07"]["cod_punto"].nunique()),
        "clientes_cod_punto": int(interim["C-08"]["cod_punto"].nunique()),
        "fondos_dim": int(len(build_dim_fund())),
    }

    summary.dq, compliant_frames = _quality(interim, run_id)
    summary.processed = _curate_features(compliant_frames, run_id)
    return summary


def main() -> None:
    """Punto de entrada de consola para la unidad U0.

    Ejecuta `run()` end-to-end y escribe un resumen por consola. Codigo de
    salida != 0 si una validacion fatal (V-10) aborta la corrida.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u0",
        description="Orquesta la unidad U0 (ingest->quality->fondo->curate->features).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log a nivel INFO.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    summary = run()

    print(f"U0 run_id={summary.run_id}")
    print("Conteos interim:")
    for dataset, n in summary.counts_interim.items():
        print(f"  {dataset}: {n}")
    print("Entidades clave:")
    for k, n in summary.counts_entities.items():
        print(f"  {k}: {n}")
    print(f"DQ cuadra_global: {summary.dq.get('cuadra_global')}")
    print("Processed por modelo (entrenamiento/holdout/entidades):")
    for key, c in summary.processed.items():
        print(f"  {key}: train={c['entrenamiento']} holdout={c['holdout']} " f"entidades={c['entidades']}")


if __name__ == "__main__":
    main()
