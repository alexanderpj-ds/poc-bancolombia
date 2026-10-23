"""Matrices corregidas al grano del pronostico para el workflow de imputacion (PARTE 1, tarea 1.2 del plan).

Todo se lee de la replica en S3 a memoria (`datos_poc`, perfil `alx-poc`, solo lectura). Las correcciones son de
DATOS, no imputacion (DI-04 del plan): el duplicado exacto de sucursales se quita y los valores corruptos pasan a
faltante (NaN, nunca 0). Cada correccion queda registrada en una tabla `correcciones`.

- M1/M2 (cajero-dia), M3 (sucursal-dia), M4/M5 (fondo-dia): `matriz_corregida(dataset)`, que parte de
  `datos_poc.matriz_arnes` (paridad exacta con `lab/evaluation/harness.py::load_dataset`).
- M6 (fondo|denominacion-dia habil): `matriz_m6()`, con `datos_poc.matriz_eda("m6", corregido=True)`
  (= `disponibles(corregido=True)`: sin filas TOTAL y TDV_001 en pesos).
- `cp_snapshots()`: historico de snapshots del maestro de cajeros (lo usa la PARTE 2 para el V4 "as of").
"""

from __future__ import annotations

import io

import datos_poc as dp
import numpy as np
import pandas as pd
import yaml

import imputacion  # noqa: F401  (agrega ALX y pipeline/src a sys.path)

#: Los 7 datasets del arnes (lab/conf/evaluacion.yml:54-92). M6 va aparte (`matriz_m6`).
DATASETS = ("m1", "m2_pagado", "m2_cash_in", "m3_entradas", "m3_salidas", "m4", "m5")
#: Columnas de la tabla de correcciones.
COLUMNAS_CORRECCIONES = ["dataset", "entidad", "fecha", "tipo", "valor_antes", "valor_despues", "detalle"]


def _vacia() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNAS_CORRECCIONES)


def _catalogo_cdgtrn(objetivo: str) -> list[int]:
    """Catalogo de cdgtrn del objetivo (pipeline/conf/model_u1_u2.yml), el mismo que usa el arnes."""
    from lab import PIPELINE_CONF_DIR

    return yaml.safe_load((PIPELINE_CONF_DIR / "model_u1_u2.yml").read_text())["cdgtrn"][objetivo]


def _corruptos_cajeros(dataset: str, dataset_conf: dict, wide: pd.DataFrame) -> pd.DataFrame:
    """Cajero-dias cuyo total incluye una fila con `monto` nulo (valor corrupto en la fuente) del catalogo.

    Caso conocido: `884s0000` del cajero 6303 el 25-jul-2026 (ALX/guia_datos_bucket.md:329), que la capa
    processed deja nulo. El arnes suma las demas filas del dia (`sum(min_count=1)`) y el total queda
    incompleto: se pasa a faltante (NaN).
    """
    tabla = dp.leer(dataset_conf["tabla"].removesuffix(".parquet"))
    tabla = tabla[tabla["cdgtrn"].isin(_catalogo_cdgtrn(dataset_conf["objetivo"]))]
    nulos = tabla[tabla["monto"].isna()].copy()
    if nulos.empty:
        return _vacia()
    nulos["cod_cajero"] = nulos["cod_cajero"].astype(str)
    nulos["fecha"] = pd.to_datetime(nulos["fecha"])
    filas = []
    for (cod, fecha), grupo in nulos.groupby(["cod_cajero", "fecha"]):
        if cod not in wide.columns or fecha not in wide.index:
            continue
        filas.append(
            {
                "dataset": dataset,
                "entidad": cod,
                "fecha": fecha,
                "tipo": "valor_corrupto_a_faltante",
                "valor_antes": float(wide.at[fecha, cod]),
                "valor_despues": np.nan,
                "detalle": f"{len(grupo)} fila(s) con monto nulo (cdgtrn {sorted(grupo['cdgtrn'].unique())})",
            }
        )
    return pd.DataFrame(filas, columns=COLUMNAS_CORRECCIONES)


def _duplicados_sucursales(dataset: str, objetivo: str, wide: pd.DataFrame) -> pd.DataFrame:
    """Sucursal-dias con filas duplicadas exactas en processed/m3_sucursales (13-may-2026: 44 sucursales x 2).

    Aborta si, quitando los duplicados exactos, quedan llaves (sucursal, fecha) repetidas con valores distintos:
    ese caso no es un duplicado de carga y no se corrige sin evidencia.
    """
    tabla = dp.leer("processed/m3_sucursales")
    tabla["cod_sucursal"] = tabla["cod_sucursal"].astype(str)
    tabla["fecha"] = pd.to_datetime(tabla["fecha"])
    sin_dup = tabla.drop_duplicates()
    repetidas = int(sin_dup.duplicated(["cod_sucursal", "fecha"]).sum())
    if repetidas:
        raise RuntimeError(f"m3: {repetidas} llaves (sucursal, fecha) repetidas con valores distintos; no se corrige")
    dup = tabla[tabla.duplicated(keep=False)]
    if dup.empty:
        return _vacia()
    filas = []
    for (cod, fecha), grupo in dup.groupby(["cod_sucursal", "fecha"]):
        despues = float(sin_dup.loc[(sin_dup["cod_sucursal"] == cod) & (sin_dup["fecha"] == fecha), objetivo].sum())
        filas.append(
            {
                "dataset": dataset,
                "entidad": cod,
                "fecha": fecha,
                "tipo": "duplicado_exacto_deduplicado",
                "valor_antes": float(wide.at[fecha, cod]),
                "valor_despues": despues,
                "detalle": f"{len(grupo)} filas identicas en processed/m3_sucursales; se conserva 1",
            }
        )
    return pd.DataFrame(filas, columns=COLUMNAS_CORRECCIONES)


def aplicar_correcciones(wide: pd.DataFrame, correcciones: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia de `wide` con `valor_despues` en cada celda corregida (NaN = pasa a faltante)."""
    out = wide.copy()
    for fila in correcciones.itertuples(index=False):
        out.at[pd.Timestamp(fila.fecha), fila.entidad] = fila.valor_despues
    return out


def matriz_corregida(dataset: str, conf: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Matriz fecha x entidad del arnes con las correcciones de datos DI-04, hasta el corte (31-ago-2026).

    Args:
        dataset: uno de `DATASETS`.
        conf: contrato de evaluacion (lab/conf/evaluacion.yml) ya leido; None = `harness.load_conf()`.

    Returns:
        (wide, attrs, correcciones). `wide`: indice diario denso, NaN donde no hay dato (Anexo C incluido, nunca 0).
        `attrs`: `ciudad`, `rn07` (como `datos_poc.matriz_arnes`). `correcciones`: `COLUMNAS_CORRECCIONES`.
    """
    dp._asegurar_lab()
    from lab.evaluation.harness import load_conf

    conf = conf or load_conf()
    dataset_conf = conf["datasets"][dataset]
    wide, attrs = dp.matriz_arnes(dataset, conf)
    wide = wide.loc[: dp.CORTE]
    if dataset_conf["forma"] == "cdgtrn":
        correcciones = _corruptos_cajeros(dataset, dataset_conf, wide)
    elif dataset.startswith("m3_"):
        correcciones = _duplicados_sucursales(dataset, dataset_conf["objetivo"], wide)
    else:
        correcciones = _vacia()
    return aplicar_correcciones(wide, correcciones), attrs, correcciones


def matriz_m6() -> tuple[pd.DataFrame, pd.DataFrame]:
    """M6: saldo por fondo|denominacion x dia (`datos_poc.matriz_eda('m6', corregido=True)`) con blancos a faltante.

    Las filas de `processed/m6_fondos` con `valor` en blanco (23 de CALI|TRANSPORTADORA_004, 50000, calidad
    CLASIFICADO TERCEROS, 9-jul a 11-ago-2026; ALX/.agents/tasks/imputacion/plan.md §1 n.o 5) dejan incompleto el
    saldo de ese fondo|denominacion-dia (la suma de pandas las ignora): ese dia pasa a faltante (NaN).

    Returns:
        (wide, correcciones). `wide` conserva el indice de `matriz_eda` (dias habiles + dias no habiles con dato).
    """
    wide = dp.matriz_eda("m6", corregido=True)
    m6 = dp.leer("processed/m6_fondos")
    blancos = m6[m6["valor"].isna()].copy()
    filas = []
    if not blancos.empty:
        blancos["fecha"] = pd.to_datetime(blancos["fecha"])
        blancos["entidad"] = blancos["fondo_id"].astype(str) + "|" + blancos["denominacion"].astype(str)
        for (entidad, fecha), grupo in blancos.groupby(["entidad", "fecha"]):
            if entidad not in wide.columns or fecha not in wide.index:
                continue
            filas.append(
                {
                    "dataset": "m6",
                    "entidad": entidad,
                    "fecha": fecha,
                    "tipo": "valor_en_blanco_a_faltante",
                    "valor_antes": float(wide.at[fecha, entidad]),
                    "valor_despues": np.nan,
                    "detalle": f"{len(grupo)} fila(s) en blanco (calidad {sorted(grupo['calidad'].unique())})",
                }
            )
    correcciones = pd.DataFrame(filas, columns=COLUMNAS_CORRECCIONES)
    marcados = wide.attrs.get("desinstalados", {})
    wide = aplicar_correcciones(wide, correcciones)
    wide.attrs["desinstalados"] = marcados
    return wide, correcciones


def cp_snapshots() -> pd.DataFrame:
    """Historico completo de snapshots del maestro de cajeros (`raw/cp_historico.xlsx`), leido a memoria.

    Renombra con `daas.ingest.readers.cp_history._RENAMES` (primera hoja del libro; el lector de Santiago usa
    `cp_historico_enmascarado`, pipeline/conf/sources.yml:24-28) y arma `fecha_snapshot` con `ingestion_*`.

    Returns:
        DataFrame con `fecha_snapshot, cod_cajero (str), ciudad, admon, cupo, disp_mf, estado`.
    """
    import boto3
    from daas.ingest.readers.cp_history import _RENAMES

    s3 = boto3.Session(profile_name=dp.PERFIL).client("s3")
    cuerpo = s3.get_object(Bucket=dp.BUCKET.removeprefix("s3://"), Key="raw/cp_historico.xlsx")["Body"].read()
    crudo = pd.read_excel(io.BytesIO(cuerpo), sheet_name=0)
    presentes = {k: v for k, v in _RENAMES.items() if k in crudo.columns}
    df = crudo[list(presentes)].rename(columns=presentes)
    partes = {c: pd.to_numeric(df[f"ingestion_{c}"], errors="coerce") for c in ("year", "month", "day")}
    df["fecha_snapshot"] = pd.to_datetime(pd.DataFrame(partes))
    df["cod_cajero"] = df["cod_cajero"].astype(str)
    columnas = ["fecha_snapshot", "cod_cajero", "ciudad", "admon", "cupo", "disp_mf", "estado"]
    return df[columnas].sort_values(["cod_cajero", "fecha_snapshot"]).reset_index(drop=True)
