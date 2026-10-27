"""Publicación de los pronósticos en la forma de los contratos, parametrizada por versión (PUBLICACIONES).

  - v2 (por defecto): entrega v2 (Excel 167a52e4…), prefijo output/pronosticos/v2/, insumos de la corrida B2_v2
    (local, ~/.cache/poc-daas/corrida_entrega_v2/B2_v2; mismo conf/ que ALX/pipeline/conf salvo paths.yml).
  - v0_provisional: reproduce la publicación v1 (revisión 2, Excel 52e7547f…) con el respaldo
    ALX/entrega/historico/v1_2026-10-21, insumos de S3 y el alx.yml v1 (conf de la corrida A2_v1). Solo `generar`:
    `subir` se niega a escribir en ese prefijo.

Los contratos OpenAPI de ALX/consumo-pronosticos/contratos (entregados por el arquitecto) son la especificación
DOMINANTE de las vistas api/: esquema y semántica. Las tablas/ siguen siendo copia fiel de output_api.

Lee (solo lectura), según la versión:
  - <fuente>/  (predicciones, recomendaciones, alertas, métricas, backtest, silenciosos de output_api)
  - <excel> hoja 03 (solo para comprobar que las métricas coinciden; en v2 además se copia a anexo_d/)
  - insumos (a memoria, con la capa storage del pipeline y DAAS_CONF de la versión): maestros interim/cp_historico e
    interim/oficinas (ciudad), processed/ (insumos de la simulación M1-M3) y processed/m6_fondos (disponibles).
La lógica del pipeline se IMPORTA de ALX/pipeline/src/daas (simulación M1-M3, corrección de disponibles M6,
fórmulas de métricas); no se edita ni se reentrena nada.

Escribe, fuera de Drive:
  <salida>/
    manifest.json                       versión, revisión, fecha, fuente, champions, decisiones, discrepancias, sha256
    tablas/<tabla>/modelo=mX[/fecha=AAAA-MM-DD]/part-0.parquet   tablas de output_api, Hive-particionadas
    esquemas/<tabla>.schema.json        JSON Schema (2020-12) por tabla + contrato de origen (_schemas)
    api/flujo_b/... flujo_c/... flujo_d/... flujo_e/...   vistas JSON con la forma de los contratos OpenAPI
    validacion/validacion_openapi.json  errores de esquema (jsonschema 2020-12) y discrepancias semánticas
    validacion/verificaciones.json      comprobaciones de trazabilidad (simulación, métricas, diaCruce, disponibles)
    anexo_d/POC_Efectivo_PRAGMA_v2.xlsx copia del Excel de la entrega (solo v2; incluida en el manifest)

Uso (desde /tmp; ver README.md):
    python publicar.py generar   <salida> [--version v2|v0_provisional]
    python publicar.py verificar <directorio_descargado_de_s3>
    python publicar.py subir     <salida> --dry-run      lista claves, bytes y sha256; no escribe
    python publicar.py subir     <salida>                sube a output/pronosticos/v2/ + version_vigente.json

Salvaguardas de `subir`: solo escribe claves bajo output/pronosticos/v2/ y la clave única
output/pronosticos/version_vigente.json; exige que output/pronosticos/v2/ esté vacío (sin objetos ni versiones) y
que version_vigente.json no exista; nunca borra.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import jsonschema
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ALX = Path(__file__).resolve().parents[1]
CONTRATOS = ALX / "consumo-pronosticos" / "contratos"
BANDAS_YML = ALX / "lab" / "conf" / "bandas.yml"
CORRIDAS = Path.home() / ".cache" / "poc-daas" / "corrida_entrega_v2"

BUCKET = "poc-daas-bancolombia-777937796305"
PERFIL_AWS = "alx-mx"
RAIZ_PRONOSTICOS = "output/pronosticos/"
# Salvaguarda (a): `subir` solo escribe bajo este prefijo y en esta clave única. Nada más.
PREFIJO_ESCRITURA = "output/pronosticos/v2/"
CLAVE_VIGENTE = "output/pronosticos/version_vigente.json"

# Parámetros por versión publicada. v0_provisional reproduce la publicación v1 (revisión 2, 22-oct-2026).
PUBLICACIONES = {
    "v0_provisional": {
        "revision": 2,
        "entrega": "v1",
        "fuente": ALX / "entrega" / "historico" / "v1_2026-10-21" / "output_api",
        "excel": ALX / "entrega" / "historico" / "v1_2026-10-21" / "POC_Efectivo_PRAGMA.xlsx",
        "excel_sha256": "52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688",
        "insumos": "s3",  # la publicación v1 leyó las capas del bucket (perfil alx-mx)
        "daas_conf": CORRIDAS / "A2_v1" / "conf",  # conf vigente + alx.yml v1 (sha256 e841aca2…6832)
        "anexo_d": None,  # el anexo_d/POC_Efectivo_PRAGMA_v1.xlsx de v0_provisional se subió aparte (24-oct)
        "nota": ("Estructura PROVISIONAL, revisión 2 (22-oct-2026): las vistas api/ cumplen los contratos OpenAPI del "
                 "arquitecto (consumo-pronosticos, especificación dominante); las tablas/ son copia fiel de "
                 "output_api. Se reemplazará cuando el arquitecto entregue la especificación de almacenamiento en "
                 "S3."),
    },
    "v2": {
        "revision": 1,
        "entrega": "v2",
        "fuente": ALX / "entrega" / "output_api",
        "excel": ALX / "entrega" / "POC_Efectivo_PRAGMA.xlsx",
        "excel_sha256": "167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461",
        "insumos": "local",  # capas de la corrida que generó la entrega v2 (no las del bucket)
        "daas_conf": CORRIDAS / "B2_v2" / "conf",  # = ALX/pipeline/conf (alx.yml v2) salvo paths.yml -> B2_v2/data
        "anexo_d": "POC_Efectivo_PRAGMA_v2.xlsx",
        "nota": ("Entrega v2 (26-oct-2026, Excel 167a52e4…): misma estructura que v0_provisional revisión 2; las "
                 "vistas api/ cumplen los contratos OpenAPI del arquitecto (consumo-pronosticos, especificación "
                 "dominante); las tablas/ son copia fiel de output_api v2. Estructura aún provisional hasta la "
                 "especificación de almacenamiento en S3 del arquitecto."),
    },
}
VERSION_POR_DEFECTO = "v2"

# Variables de la versión activa (las fija configurar()).
VERSION = REVISION = DESTINO_S3 = NOTA = FUENTE = EXCEL = EXCEL_SHA256 = None
PUB: dict = {}


def configurar(version: str) -> None:
    """Fija la versión activa y el entorno de la capa storage del pipeline (antes de importar daas)."""
    global VERSION, REVISION, DESTINO_S3, NOTA, FUENTE, EXCEL, EXCEL_SHA256, PUB
    if version not in PUBLICACIONES:
        raise SystemExit(f"Versión desconocida: {version} (opciones: {sorted(PUBLICACIONES)})")
    PUB = PUBLICACIONES[version]
    VERSION, REVISION, NOTA = version, PUB["revision"], PUB["nota"]
    DESTINO_S3 = f"s3://{BUCKET}/{RAIZ_PRONOSTICOS}{version}/"
    FUENTE, EXCEL, EXCEL_SHA256 = PUB["fuente"], PUB["excel"], PUB["excel_sha256"]
    os.environ["AWS_PROFILE"] = PERFIL_AWS
    os.environ["DAAS_CONF"] = str(PUB["daas_conf"])
    if PUB["insumos"] == "s3":
        os.environ["DAAS_SCHEME"] = "s3"
        os.environ["DAAS_S3_BUCKET"] = BUCKET
    else:
        os.environ["DAAS_SCHEME"] = "local"
        os.environ.pop("DAAS_S3_BUCKET", None)


configurar(os.environ.get("PUBLICAR_VERSION", VERSION_POR_DEFECTO))

# Convenciones transversales del handoff (README-handoff-datos.md §3); NO salen del pipeline.
CORRIDA = "0007"
CORTE = "2026-08-31"
ORIGEN_BACKTEST = dt.date(2026, 8, 16)  # el backtest 17-31 ago pronostica h = 1..15 desde este origen
DIAS_NO_HABILES = ["2026-09-05", "2026-09-06", "2026-09-12", "2026-09-13"]
CIUDADES = ["CALI", "PASTO", "IPIALES"]
BLOQUES = {"1-7": (1, 7), "8-15": (8, 15)}

TABLAS = {  # tabla -> columnas de partición (Hive)
    "predicciones": ["modelo", "fecha"],
    "alertas": ["modelo", "fecha"],
    "recomendaciones": ["modelo", "fecha_sugerida"],
    "metricas": ["modelo"],
    "backtest": ["modelo"],
    "silenciosos": ["modelo"],
}

MODELO_API = {"m1": "cajeros", "m2": "multifuncionales", "m3": "sucursales",
              "m4": "corresponsales", "m5": "clientes"}
NOMBRE_ENTIDAD = {"m1": "Cajero", "m2": "Multifuncional", "m3": "Sucursal"}
CANAL_FONDO = {"m4": "CORRESPONSALES", "m5": "CLIENTES"}
# (modelo, tipo interno) -> TipoReglaAlerta del contrato. m2 'recoleccion' -> ALERTA_PROVISION según el ejemplo
# A-104 de historias-flujo-e.md ("Exceso en multifuncional").
TIPO_REGLA = {("m1", "agotamiento"): "ALERTA_PROVISION", ("m2", "agotamiento"): "ALERTA_PROVISION",
              ("m2", "recoleccion"): "ALERTA_PROVISION", ("m3", "excedente"): "SUCURSAL_EXCESO",
              ("m6", "deficit"): "FALTANTE_FONDO", ("m6", "exceso"): "EXCEDENTE_FONDO"}
# Decisión 7: criticidad del catálogo de historias-flujo-e.md (A-101…A-108) cuando el tipo de regla tiene una
# sola criticidad: A-102 FALTANTE_FONDO Crítica, A-107 EXCEDENTE_FONDO Moderada, A-103 (exceso en sucursal) Media.
# ALERTA_PROVISION aparece con las tres criticidades (A-101/A-104/A-105): se usa la severidad del pipeline.
CRITICIDAD_POR_REGLA = {"FALTANTE_FONDO": "CRITICA", "EXCEDENTE_FONDO": "MODERADA", "SUCURSAL_EXCESO": "MEDIA"}
CRITICIDAD = {"critico": "CRITICA", "alerta": "MEDIA"}
# Decisión 8: tipoDato de las vistas api/ según contratos e historias (las tablas conservan origen_dato).
TIPO_SIMULADO = "SIMULADO"   # montos en riesgo (E: "Amounts at risk are in COP and SIMULADO") y saldos simulados
TIPO_REPARTO = "ESTIMADO"    # reparto por billete (historias-flujo-d: "Estimado | Reparto por billete")
ORDEN_ESTADO = {"FALTANTE": 3, "EXCEDENTE": 2, "EN_BANDA": 1}

JSON_TIPO = {"str": "string", "object": "string", "date": "string", "float": "number", "float64": "number",
             "int": "integer", "Int64": "integer", "bool": "boolean"}

INSUMOS_S3 = ["interim/cp_historico", "interim/oficinas", "interim/cp_desinstalados", "processed/m1_atm_dispensador",
              "processed/m2_atm_multifuncional", "processed/m3_sucursales", "processed/m6_fondos",
              "processed/_dim/dim_fondo"]

DECISIONES = {
    "1_ciudad": "ciudad de M1-M3 = maestro vigente con el criterio del arnés (lab/evaluation/harness.py "
                "_city_by_entity: primera fila por entidad): interim/cp_historico para cajeros y multifuncionales, "
                "interim/oficinas para sucursales; M4-M6 = prefijo del código de fondo.",
    "2_disponible_observado": "disponibleObservado = suma por fondo del último disponible observado <= corte por "
                              "denominación, sobre los disponibles CORREGIDOS (funds_m6.dataset.load_available_cash: "
                              "sin TOTAL, TDV_001 a pesos, días con blancos o doble formato fuera). reconstruido = "
                              "true solo si ese valor se transformó (filas convertidas de piezas a pesos o TOTAL "
                              "excluido ese día).",
    "3_saldo_diario": "serie de 15 días de la simulación del pipeline (simulate_balance_m1/m2/m3) recalculada con "
                      "las predicciones vigentes; reproduce exactamente recomendaciones y alertas publicadas. B: saldo "
                      "= cierre del día. C: en día con acción saldoAntes/saldoDespues = antes/después de la acción "
                      "(= recomendaciones.saldo_antes/saldo_despues); sin acción, saldoAntes = saldoDespues = cierre.",
    "4_metricas": "forecast/metrics por ciudad x bloque (1-7 = 17-23 ago, 8-15 = 24-31 ago) sobre backtest lectura "
                  "base, mismas filas y exclusión SUP-27 que la hoja 03; WAPE/MAE/Bias con daas.forecasting.metrics.",
    "5_dia_cruce": "diaCruce = primer día en que el saldo simulado cruza una regla: umbral de alerta (alertas) o "
                   "umbral de la política que dispara un servicio (reserva/techo de M3, umbral de M1/M2) = "
                   "min(primera alerta, primera acción). servicioSugerido = primera acción. Ambos nulos sin cruce.",
    "6_fondo_id": "fondoId = CIUDAD|TDV_00X (TRANSPORTADORA_00X -> TDV_00X) en las vistas api/; las tablas conservan "
                  "TRANSPORTADORA_00X. Se incluye TDV_004 (dato real) aunque el contrato solo use TDV_001-003.",
    "7_criticidad": "criticidad del catálogo A-101…A-108: FALTANTE_FONDO CRITICA, EXCEDENTE_FONDO MODERADA, "
                    "SUCURSAL_EXCESO MEDIA (A-103); ALERTA_PROVISION por severidad (critico CRITICA, alerta MEDIA). "
                    "Las tablas conservan la severidad original.",
    "8_tipo_dato": "SIMULADO en montos en riesgo, alertas y saldos simulados; ESTIMADO en reparto por billete; "
                   "PROYECTADO en pronósticos y flujos por canal; OBSERVADO en observado y disponible. Las tablas "
                   "conservan origen_dato original.",
}

DISCREPANCIAS_SEMANTICAS = [
    {"id": "DS-1", "tema": "DESBALANCE_DENOMINACION (estado y tipoRegla)",
     "detalle": "No se deriva: RN-72 c exige que el total del fondo esté en banda y no existe banda del total en "
                "ningún dato; crearla sería inventar una regla.",
     "pregunta_arquitecto": "¿Quién define la banda del total del fondo (o se omite el estado en la PoC)?"},
    {"id": "DS-2", "tema": "EXCEDENTE_NO_EVACUABLE",
     "detalle": "No se deriva: el pipeline no marca excedentes no evacuables (los 24 conservados de M6 lo son por "
                "costo de almacenamiento menor, no por imposibilidad). Todo exceso de M6 sale como EXCEDENTE_FONDO.",
     "pregunta_arquitecto": "¿Qué regla define 'no evacuable' (día no hábil, fondo sin operación habilitada)?"},
    {"id": "DS-3", "tema": "Cuarta transportadora (TDV_004)",
     "detalle": "Los datos tienen CALI|TRANSPORTADORA_004 (M5 y M6); se publica como CALI|TDV_004. El contrato no "
                "tiene enum de fondoId, por eso valida, pero sus ejemplos solo usan TDV_001-003.",
     "pregunta_arquitecto": "¿Se confirma CALI|TDV_004 como fondoId (handoff §5)?"},
    {"id": "DS-4", "tema": "Criticidad de SUCURSAL_EXCESO y uso de MODERADA en ALERTA_PROVISION",
     "detalle": "SUCURSAL_EXCESO no está en el catálogo; se toma MEDIA de A-103 ('Exceso en sucursal', rotulado "
                "SUCURSAL_INSUFICIENCIA). ALERTA_PROVISION nunca sale MODERADA (A-105) porque los umbrales de "
                "criticidad siguen pendientes (Anexo B).",
     "pregunta_arquitecto": "¿Criticidad de SUCURSAL_EXCESO y umbrales CRITICA/MEDIA/MODERADA de ALERTA_PROVISION?"},
    {"id": "DS-5", "tema": "forecast/series niveles OVERVIEW y MODEL",
     "detalle": "Solo se publica nivel POINT: el contrato no define cómo agregar objetivos distintos (pagado, "
                "cash_in, entradas/salidas) en un MODEL u OVERVIEW.",
     "pregunta_arquitecto": "¿Qué agregación espera pronostico-ms para OVERVIEW/MODEL?"},
    {"id": "DS-6", "tema": "observado limitado al backtest",
     "detalle": "observado = backtest.y lectura base de la ventana 17-31 ago; 47 de 646 series no están en el "
                "backtest y salen con observado [] y huecos [] (ausencia de dato, nunca cero).",
     "pregunta_arquitecto": "¿Cuántos días de observado antes del corte espera el gráfico (HU-05)?"},
    {"id": "DS-7", "tema": "reconstruido de disponibleObservado",
     "detalle": "El valor al corte de los 6 fondos ya viene en pesos (la conversión de piezas a pesos de TDV_001 "
                "afecta solo historia anterior al 21-jul-2026), así que reconstruido = false; la nota lo explica.",
     "pregunta_arquitecto": "¿La marca debe aplicarse al fondo cuya historia se convirtió aunque el valor al corte no?"},
    {"id": "DS-8", "tema": "MAE y Bias por celda ciudad x bloque",
     "detalle": "La hoja 03 solo trae WAPE por ciudad y por semana (marginales) y WAPE/MAE/Bias globales; las celdas "
                "ciudad x bloque se calculan con las mismas filas y fórmulas. Se publica la lectura base, no la RN-08.",
     "pregunta_arquitecto": "¿forecast/metrics debe llevar también la lectura RN-08?"},
    {"id": "DS-9", "tema": "saldoAntes/saldoDespues en días sin acción (C)",
     "detalle": "SaldoPoint no admite campos extra; sin acción se publica saldoAntes = saldoDespues = saldo de "
                "cierre simulado. Montos en COP redondeados a entero desde float.",
     "pregunta_arquitecto": "¿Se confirma esa semántica para los días sin servicio?"},
]


# ----------------------------------------------------------------------------------------------- utilidades
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def entero(x):
    """float/NaN -> int redondeado o None (los contratos piden int64 en COP)."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x):
        return None
    return int(round(float(x)))


def billete(den) -> str | None:
    return None if pd.isna(den) else "$" + f"{int(den):,}".replace(",", ".")


def ciudad_de(cod: str) -> str | None:
    """Ciudad desde un código de fondo CIUDAD|TRANSPORTADORA (None si no es código de fondo)."""
    return cod.split("|")[0] if "|" in cod else None


def fondo_api(cod: str) -> str:
    """Decisión 6: CIUDAD|TRANSPORTADORA_00X -> CIUDAD|TDV_00X (nomenclatura del contrato)."""
    return cod.replace("|TRANSPORTADORA_", "|TDV_") if isinstance(cod, str) else cod


def nombre_fondo(cod: str) -> str:
    """Nombre largo del fondo para frases (historias-flujo-d: 'Fondo Cali · Transp. 001')."""
    ciudad, tdv = cod.split("|")
    return f"Fondo {ciudad.title()} · Transp. {tdv.rsplit('_', 1)[-1]}"


def criticidad(tipo_regla: str | None, severidad: str) -> str | None:
    return CRITICIDAD_POR_REGLA.get(tipo_regla) or CRITICIDAD.get(severidad)


def escribir_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def leer_fuente() -> dict[str, pd.DataFrame]:
    return {t: pd.read_parquet(FUENTE / f"{t}.parquet") for t in TABLAS}


def mapear_alerta(row) -> dict:
    """Campos comunes de alerta en la forma de los contratos (B/C/E)."""
    regla = TIPO_REGLA.get((row.modelo, row.tipo))
    return {
        "tipoRegla": regla,
        "criticidad": criticidad(regla, row.severidad),
        "montoEnRiesgo": entero(abs(row.nivel - row.limite)),
        "fechaCritica": row.fecha,
        "tipoDato": TIPO_SIMULADO,
    }


def estado_banda(saldo, minimo, maximo) -> str:
    if saldo < minimo:
        return "FALTANTE"
    if saldo > maximo:
        return "EXCEDENTE"
    return "EN_BANDA"


# ------------------------------------------------------------------------------------------- insumos S3
def ciudades_maestro() -> dict[str, pd.Series]:
    """Brecha 1: ciudad por entidad con el criterio del arnés (primera fila por entidad del maestro)."""
    from daas.io import storage
    def primera(tabla: str, llave: str) -> pd.Series:
        df = storage.read_table(f"daas://interim/{tabla}").drop_duplicates(llave)
        return df.set_index(df[llave].astype(str))["ciudad"].str.upper()

    cajeros = primera("cp_historico", "cod_cajero")
    return {"m1": cajeros, "m2": cajeros, "m3": primera("oficinas", "cod_sucursal")}


def simular_m1_m3(pred: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, set]]:
    """Brecha 3: serie diaria de saldo simulado de M1-M3, con las funciones de simulación del pipeline y las
    predicciones vigentes (no reentrena). Misma orquestación que run_u1_u2._process_model y run_u3._process_m3."""
    from daas.modules.atm_m1_m2 import balance as bal12, inactivity
    from daas.modules.atm_m1_m2.config import load_config as conf12
    from daas.modules.atm_m1_m2.dataset import load_series
    from daas.modules.branches_m3.balance import simulate_balance_m3
    from daas.modules.branches_m3.config import load_config as conf3
    from daas.modules.branches_m3.dataset import load_series_m3
    from daas.modules.branches_m3.policy import load_policy, policy_params
    from daas.pipeline.run_u1_u2 import _read_uninstalled

    dates = sorted(pd.to_datetime(pred[pred.modelo == "m1"].fecha.unique()).date)
    cfg = conf12()
    sims, inactivos = {}, {}
    for m in ("m1", "m2"):
        targets = ["pagado", "cash_in"] if m == "m2" else ["pagado"]
        data = load_series(m)
        by_atm = data.groupby("cod_cajero").agg(cupo=("cupo", "first")).reset_index()
        ina = inactivity.inactive_entities(data, _read_uninstalled(cfg["inactividad"]), cfg["inactividad"], targets)
        inactivos[m] = set(ina["cod_cajero"].astype(str))
        pm = pred[pred.modelo == m]
        yhat = {o: pm[pm.objetivo == o].pivot(index="fecha", columns="cod_cajero", values="yhat").sort_index()
                for o in targets}
        partes = []
        for _, info in by_atm.iterrows():
            code = str(info["cod_cajero"])
            if code in inactivos[m]:
                continue  # RN-07/RN-08: sin saldo simulado, igual que el pipeline
            h = pd.DataFrame({"fecha": dates, "yhat": yhat["pagado"][code].to_numpy()})
            if m == "m2":
                h["cash_in"] = yhat["cash_in"][code].to_numpy()
                partes.append(bal12.simulate_balance_m2(h, capacity=info["cupo"], params=cfg, code_atm=code))
            else:
                partes.append(bal12.simulate_balance_m1(h, capacity=info["cupo"], params=cfg, code_atm=code))
        sims[m] = pd.concat(partes, ignore_index=True)
    c3 = conf3()
    data = load_series_m3()
    caps = data.groupby("cod_sucursal")["cupo_max_suc"].first().to_dict()
    branches = sorted(data["cod_sucursal"].dropna().unique().tolist())
    pol = load_policy(c3)
    params = None
    if pol["activa"]:
        hist = data[data["fecha"] <= dates[0] - dt.timedelta(days=1)]
        params = policy_params(
            hist.pivot(index="fecha", columns="cod_sucursal", values="entradas").sort_index(),
            hist.pivot(index="fecha", columns="cod_sucursal", values="salidas").sort_index(),
            pd.Series(caps).reindex(branches).rename_axis("cod_sucursal"),
            float(c3["m3"]["umbral_agotamiento"]), pol)
    # SUP-43 (entrega v2): monto mínimo de recolección por sucursal, igual que run_u3._process_m3; con el
    # interruptor apagado (alx.yml v1) no hay mínimo y la simulación es la de la v1.
    from daas import alx
    from daas.modules.branches_m3.policy import min_collection_factor
    from daas.pipeline.run_u3 import _min_collection_by_branch
    con_minimo = alx.interruptor("monto_minimo_recoleccion")
    minimos = _min_collection_by_branch(branches, min_collection_factor(pol)) if con_minimo else {}
    pm = pred[pred.modelo == "m3"]
    yhat = {o: pm[pm.objetivo == o].pivot(index="fecha", columns="cod_cajero", values="yhat").sort_index()
            for o in ("entradas", "salidas")}
    partes = []
    for code in branches:
        h = pd.DataFrame({"fecha": dates, "entradas": yhat["entradas"][str(code)].to_numpy(),
                          "salidas": yhat["salidas"][str(code)].to_numpy()})
        pair = None
        if params is not None and pd.notna(params.loc[code, "reserva"]):
            pair = {k: params.loc[code, k] for k in ("reserva", "objetivo", "techo")}
            pair["usa_pronostico"] = bool(params.loc[code, "usa_pronostico"])
            if con_minimo:
                pair["monto_min_recoleccion"] = minimos.get(str(code))
        partes.append(simulate_balance_m3(h, branch_max_capacity=float(caps.get(code, float("nan"))), params=c3,
                                          code_branch=code, policy=pair))
    sims["m3"] = pd.concat(partes, ignore_index=True).rename(columns={"cod_sucursal": "cod_cajero"})
    inactivos["m3"] = set()
    for m, s in sims.items():
        s["cod_cajero"] = s["cod_cajero"].astype(str)
        s["fecha"] = pd.to_datetime(s["fecha"]).dt.date.astype(str)
        for c in ("recoleccion", "saldo_antes_recoleccion"):
            if c not in s.columns:
                s[c] = 0.0 if c == "recoleccion" else float("nan")
    return sims, inactivos


def verificar_simulacion(sims: dict[str, pd.DataFrame], dfs) -> dict:
    """La simulación recalculada debe reproducir EXACTAMENTE recomendaciones y alertas publicadas."""
    from daas.decision import alerts as alerts_mod, optimizer
    rec, al = dfs["recomendaciones"], dfs["alertas"]
    out = {}
    for m, s in sims.items():
        if m == "m1":
            b = optimizer.recommend_provision_m1(s)
            r = b[b["requiere_provision"]].rename(columns={"fecha_sugerida_provision": "fecha_sugerida",
                                                           "monto_para_completar": "monto"}).assign(accion="provision")
            a = alerts_mod.classify_alerts(s, col_balance="saldo_sin_provision")
        elif m == "m2":
            r, a = optimizer.recommend_actions_m2(s), alerts_mod.classify_alerts_m2(s)
        else:
            r, a = optimizer.recommend_actions_m3(s), alerts_mod.classify_alerts_m3(s)
        r = r.assign(fecha_sugerida=r.fecha_sugerida.astype(str))
        a = a.rename(columns={"saldo": "nivel", "umbral": "limite"}).assign(fecha=a.fecha.astype(str))
        k = ["cod_cajero", "fecha_sugerida", "accion"]
        mr = rec[rec.modelo == m].merge(r, on=k, how="outer", suffixes=("_p", "_s"), indicator=True)
        ma = al[al.modelo == m].merge(a, on=["cod_cajero", "fecha", "tipo"], how="outer", suffixes=("_p", "_s"),
                                      indicator=True)
        out[m] = {
            "entidades_simuladas": int(s.cod_cajero.nunique()),
            "recomendaciones_publicadas": int((rec.modelo == m).sum()),
            "recomendaciones_coinciden": int(((mr._merge == "both") & (mr.monto_p == mr.monto_s)
                                              & (mr.saldo_antes_p == mr.saldo_antes_s)
                                              & (mr.saldo_despues_p == mr.saldo_despues_s)).sum()),
            "recomendaciones_sobrantes": int((mr._merge != "both").sum()),
            "alertas_publicadas": int((al.modelo == m).sum()),
            "alertas_coinciden": int(((ma._merge == "both") & (ma.nivel_p == ma.nivel_s)
                                      & (ma.severidad_p == ma.severidad_s)).sum()),
            "alertas_sobrantes": int((ma._merge != "both").sum()),
        }
    return out


def disponibles_observados() -> tuple[pd.DataFrame, dict]:
    """Brecha 2: último disponible observado <= corte por fondo y denominación, sobre los disponibles CORREGIDOS
    (la misma corrección que M6: funds_m6.dataset.load_available_cash -> correccion_disponibles)."""
    from daas import alx
    from daas.io import storage
    from daas.modules.funds_m6 import config as c6, correccion_disponibles as cd, dataset as d6
    cfg = c6.load_config()
    corte = pd.to_datetime(cfg["saldo_inicial"]["corte"]).date()
    dens = [int(d) for d in cfg["denominaciones"]]
    if not ((cfg.get("correccion_disponibles") or {}).get("aplicar") and alx.interruptor("correccion_m6")):
        raise SystemExit("La corrección de disponibles de M6 no está activa en la configuración del pipeline")
    disp = d6.load_available_cash(cfg)
    saldo0 = d6.initial_balance_by_fund_denomination(disp, corte, dens, cfg)
    # Evidencia de la corrección (mismo preproceso que load_available_cash; solo para la marca reconstruido).
    raw = storage.read_table("daas://processed/m6_fondos").copy()
    raw["fecha"] = pd.to_datetime(raw["fecha"], errors="coerce").dt.date
    raw["denominacion"] = pd.to_numeric(raw["denominacion"], errors="coerce").astype("Int64")
    raw[cd.COL_BLANCO] = pd.to_numeric(raw["valor"], errors="coerce").isna()
    raw["valor"] = pd.to_numeric(raw["valor"], errors="coerce").fillna(0.0)
    dim = storage.read_table("daas://processed/_dim/dim_fondo")
    raw = raw[raw["fondo_id"].astype(str).isin(set(dim["fondo_id"].astype(str)))]
    _, evid = cd.corregir_disponibles(raw, cfg["correccion_disponibles"])
    evid = evid.set_index(["fondo_id", "fecha"])
    valido = disp[(disp["fecha"] <= corte) & ~disp[cd.COL_FUERA].astype(bool)]
    diario = valido.groupby(["fondo_id", "denominacion", "fecha"], as_index=False)["valor"].sum()
    ult = diario.sort_values("fecha").groupby(["fondo_id", "denominacion"], as_index=False).last()
    ult["reconstruido"] = [bool(evid.loc[(f, d), "filas_convertidas"] > 0 or evid.loc[(f, d), "filas_total_excluidas"] > 0)
                           for f, d in zip(ult.fondo_id, ult.fecha, strict=True)]
    conv = evid[evid["filas_convertidas"] > 0].reset_index().groupby("fondo_id")["fecha"].agg(["min", "max"])
    ult["historia_convertida"] = ult.fondo_id.map(lambda f: None if f not in conv.index else
                                                  f"{conv.loc[f, 'min']}..{conv.loc[f, 'max']}")
    cmp = ult.merge(saldo0, on=["fondo_id", "denominacion"], how="outer")
    check = {
        "combinaciones": int(len(saldo0)),
        "sin_registro_al_corte": int(saldo0["saldo_inicial_faltante"].sum()),
        "coinciden_con_saldo_inicial_SUP07": int(((cmp.valor == cmp.saldo_inicial)
                                                  & (cmp.fecha == cmp.fecha_saldo_inicial)).sum()),
        "fechas_observacion": sorted({str(f) for f in ult.fecha}),
        "reconstruidos": int(ult.reconstruido.sum()),
        "fondos_con_historia_convertida": {k: f"{v['min']}..{v['max']}" for k, v in conv.iterrows()},
    }
    return ult, check


# ------------------------------------------------------------------------------------------------- tablas
def escribir_tablas(dfs: dict[str, pd.DataFrame], salida: Path) -> dict:
    info = {}
    for t, part in TABLAS.items():
        df = dfs[t].sort_values(list(dfs[t].columns[:4])).reset_index(drop=True)
        destino = salida / "tablas" / t
        tabla = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_to_dataset(tabla, root_path=str(destino), partition_cols=part,
                            basename_template="part-{i}.parquet", existing_data_behavior="error")
        info[t] = {"filas": len(df), "particion": part,
                   "archivos": len(list(destino.rglob("*.parquet")))}
    return info


def escribir_esquemas(dfs: dict[str, pd.DataFrame], salida: Path) -> None:
    for t, part in TABLAS.items():
        contrato = json.loads((FUENTE / "_schemas" / f"{t}.json").read_text(encoding="utf-8"))
        df = dfs[t]
        props, req = {}, []
        for c in contrato["columnas"]:
            tipo = contrato["tipos"][c]
            p = {"type": [JSON_TIPO[tipo], "null"] if df[c].isna().any() else JSON_TIPO[tipo]}
            if tipo == "date":
                p["format"] = "date"
            if c == "origen_dato":
                p["enum"] = ["OBSERVADO", "PROYECTADO", "SIMULADO", "ESTIMADO", "SIN_REGISTRO"]
            if c in part:
                p["x-particion"] = True
            props[c] = p
            if not df[c].isna().any():
                req.append(c)
        escribir_json(salida / "esquemas" / f"{t}.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{t} ({VERSION})",
            "description": f"Fila de tablas/{t}/. Columnas de partición Hive: {part} (van en la ruta, no dentro "
                           "del parquet). " + NOTA,
            "type": "object", "properties": props, "required": req, "additionalProperties": False,
            "x-filas": len(df), "x-particion": part, "x-contrato_origen": contrato,
        })


# ------------------------------------------------------------------------------------------- vistas de API
def ciudad_entidad(m: str, cod: str, ciudades: dict[str, pd.Series]) -> str | None:
    if m in ciudades:
        return ciudades[m].get(str(cod))
    return ciudad_de(cod)


def vista_forecast_series(dfs, ciudades) -> dict[str, list]:
    """Flujo B GET /forecast/series (nivel POINT): proyectado = predicciones m1-m5; observado = backtest.y
    (lectura 'base', ventana 17-31 ago); huecos = días de esa ventana sin observación 'base'."""
    pred, bt = dfs["predicciones"], dfs["backtest"]
    base = bt[bt.lectura == "base"]
    ventana = sorted(bt.fecha.unique())
    obs = {k: g for k, g in base.groupby(["modelo", "cod_cajero", "objetivo"])}
    en_bt = set(bt.groupby(["modelo", "cod_cajero", "objetivo"]).groups)
    salida = {}
    for m, api in MODELO_API.items():
        items = []
        for (cod, obj), g in pred[pred.modelo == m].groupby(["cod_cajero", "objetivo"], sort=True):
            o = obs.get((m, cod, obj))
            observado = [] if o is None else [
                {"fecha": r.fecha, "valor": entero(r.y), "tipoDato": "OBSERVADO"}
                for r in o.sort_values("fecha").itertuples()]
            huecos = [] if (m, cod, obj) not in en_bt else sorted(set(ventana) - {p["fecha"] for p in observado})
            items.append({
                "corrida": CORRIDA, "corte": CORTE, "nivel": "POINT", "entidad": fondo_api(cod), "unidad": "COP",
                "observado": observado,
                "proyectado": [{"fecha": r.fecha, "valor": entero(r.yhat), "tipoDato": r.origen_dato,
                                "bandaMin": entero(r.band_low), "bandaMax": entero(r.band_high)}
                               for r in g.sort_values("fecha").itertuples()],
                "huecos": huecos,
                # extensiones (el contrato no las prohíbe): permiten filtrar por modelo/ciudad sin parsear 'entidad'
                "modelo": api, "objetivo": obj, "ciudad": ciudad_entidad(m, cod, ciudades),
            })
        salida[api] = items
    return salida


def _wape(y: pd.Series, yhat: pd.Series) -> float | None:
    base = float(y.abs().sum())
    return None if base == 0 else float((y - yhat).abs().sum() / base)


def vista_forecast_metrics(dfs, ciudades) -> dict[str, dict]:
    """Flujo B GET /forecast/metrics: WAPE/MAE/Bias por ciudad y bloque (1-7, 8-15) del backtest lectura base, con
    las mismas filas, ciudades y exclusión SUP-27 que la hoja 03 (publish/anexo_d/sheet_03_metrics.segment_rows).
    WAPE excluye las entidades con denominador cero en la ventana; MAE y Bias usan todas las filas (SUP-27).
    Extensión `marginales`: WAPE por ciudad, por bloque y global (las cifras de la hoja 03)."""
    from daas import alx
    from daas.forecasting import metrics
    bt = dfs["backtest"][dfs["backtest"].lectura == "base"].copy()
    bt["h"] = (pd.to_datetime(bt.fecha) - pd.Timestamp(ORIGEN_BACKTEST)).dt.days
    bt["bloque"] = None
    for b, (d0, d1) in BLOQUES.items():
        bt.loc[bt.h.between(d0, d1), "bloque"] = b
    salida = {}
    for m, api in MODELO_API.items():
        metricas, marginales = [], []
        for obj, g in bt[bt.modelo == m].groupby("objetivo", sort=True):
            g = g.assign(ciudad=[ciudad_entidad(m, c, ciudades) for c in g.cod_cajero])
            excl = metrics.zero_denominator_entities(g.y, g.cod_cajero) if alx.interruptor(
                "sup02_denominador_cero") else set()
            gw = g[~g.cod_cajero.isin(excl)]
            for c in CIUDADES:
                for b in BLOQUES:
                    sub, subw = g[(g.ciudad == c) & (g.bloque == b)], gw[(gw.ciudad == c) & (gw.bloque == b)]
                    w = _wape(subw.y, subw.yhat)
                    if sub.empty or w is None:
                        continue
                    metricas.append({"ciudad": c, "bloque": b, "wape": w, "mae": entero(metrics.mae(sub.y, sub.yhat)),
                                     "bias": float(metrics.bias(sub.y, sub.yhat)),
                                     "modelo": api, "objetivo": obj, "n": int(len(sub)), "nWape": int(len(subw))})
            segs = [("ciudad", c, gw.ciudad == c) for c in CIUDADES] + [("bloque", b, gw.bloque == b) for b in BLOQUES]
            for tipo, seg, mask in segs:
                w = _wape(gw[mask].y, gw[mask].yhat)
                if w is not None:
                    marginales.append({"segmento": tipo, "valor": seg, "objetivo": obj, "wape": w})
            marginales.append({"segmento": "global", "valor": "GLOBAL", "objetivo": obj,
                               "wape": _wape(gw.y, gw.yhat), "mae": entero(metrics.mae(g.y, g.yhat)),
                               "bias": float(metrics.bias(g.y, g.yhat))})
        salida[api] = {"corrida": CORRIDA, "corte": CORTE, "metricas": metricas,
                       "lectura": "base", "ventana": {"desde": "2026-08-17", "hasta": "2026-08-31"},
                       "marginales": marginales}
    return salida


def comparar_metricas_excel(vistas: dict[str, dict]) -> dict:
    """Brecha 4: las marginales (WAPE por ciudad y por semana) deben ser las cifras de la hoja 03 del Excel."""
    x = pd.read_excel(EXCEL, "03_Metricas_Desarrollo", header=1)
    x = x[(x.metrica == "WAPE") & (x.tipo_metrica == "predictiva")]
    inv = {v: k for k, v in MODELO_API.items()}
    filas = []
    for api, v in vistas.items():
        m = inv[api].upper()
        for mg in v["marginales"]:
            if mg["segmento"] == "ciudad":
                seg = x.segmento == mg["valor"].title()
            elif mg["segmento"] == "bloque":
                seg = x.segmento.str.startswith("Semana 1" if mg["valor"] == "1-7" else "Semana 2")
            else:
                seg = x.segmento == "Global"
            e = x[(x.modelo == m) & (x.variable_o_kpi_evaluado == mg["objetivo"]) & seg]
            if len(e) == 1:
                filas.append({"modelo": m, "objetivo": mg["objetivo"], "tipo": mg["segmento"],
                              "segmento": str(e.segmento.iloc[0]), "excel": float(e.valor_metrica.iloc[0]),
                              "publicado": mg["wape"], "dif": abs(float(e.valor_metrica.iloc[0]) - mg["wape"])})
    # Global: además del WAPE, el MAE (COP entero) y el Bias de la hoja 03.
    xa = pd.read_excel(EXCEL, "03_Metricas_Desarrollo", header=1)
    for api, v in vistas.items():
        for mg in (g for g in v["marginales"] if g["segmento"] == "global"):
            for met, clave in (("MAE", "mae"), ("Bias", "bias")):
                e = xa[(xa.modelo == inv[api].upper()) & (xa.variable_o_kpi_evaluado == mg["objetivo"])
                       & (xa.metrica == met) & (xa.segmento == "Global")]
                if len(e) == 1:
                    filas.append({"modelo": inv[api].upper(), "objetivo": mg["objetivo"], "tipo": "global",
                                  "segmento": f"Global {met}", "excel": float(e.valor_metrica.iloc[0]),
                                  "publicado": mg[clave], "dif": abs(float(e.valor_metrica.iloc[0]) - mg[clave])})
    marg = [f for f in filas if f["tipo"] != "global"]
    glob = [f for f in filas if f["tipo"] == "global"]
    n_excel = int(x.segmento.isin(["Cali", "Pasto", "Ipiales"]).sum() + x.segmento.str.startswith("Semana").sum())
    return {"filas_excel_wape_ciudad_semana": n_excel,
            "ciudad_semana_comparadas": len(marg), "ciudad_semana_coinciden_1e-12": sum(f["dif"] <= 1e-12 for f in marg),
            "ciudad_semana_max_dif": max(f["dif"] for f in marg),
            "global_comparadas": len(glob), "global_coinciden_1e-12": sum(f["dif"] <= 1e-12 for f in glob),
            "global_max_dif": max(f["dif"] for f in glob), "detalle": filas}


def _acciones(dfs, modelos):
    rec, al = dfs["recomendaciones"], dfs["alertas"]
    rec, al = rec[rec.modelo.isin(modelos)], al[al.modelo.isin(modelos)]
    recs = {k: g.sort_values("fecha_sugerida") for k, g in rec.groupby(["modelo", "cod_cajero"])}
    alts = {k: g.sort_values("fecha") for k, g in al.groupby(["modelo", "cod_cajero"])}
    return recs, alts


def dia_cruce(r, a) -> str | None:
    """Brecha 5: primer día en que el saldo simulado cruza una regla (alerta o política que dispara un servicio)."""
    fechas = ([] if r is None else list(r.fecha_sugerida)) + ([] if a is None else list(a.fecha))
    return min(fechas) if fechas else None


def puntos_dia(s: pd.DataFrame) -> list[dict]:
    """Serie diaria de C: antes/después de la acción del día; sin acción, ambos = saldo de cierre."""
    pts = []
    for r in s.sort_values("fecha").itertuples():
        if r.provision > 0 and r.recoleccion > 0:
            raise SystemExit(f"{r.cod_cajero} {r.fecha}: dos acciones el mismo día (no previsto)")
        if r.provision > 0:
            antes, despues = r.saldo_inicial_dia, r.saldo_inicial_dia + r.provision
        elif r.recoleccion > 0:
            antes, despues = r.saldo_antes_recoleccion, r.saldo_antes_recoleccion - r.recoleccion
        else:
            antes = despues = r.saldo
        pts.append({"fecha": r.fecha, "saldoAntes": entero(antes), "saldoDespues": entero(despues),
                    "tipoDato": TIPO_SIMULADO})
    return pts


def vista_plan(dfs, sims, ciudades) -> dict[str, dict]:
    """Flujo C GET /simulated-balance/plan (EntidadBalance, additionalProperties=false): todas las entidades
    simuladas de M1-M3, serie de 15 días, ciudad del maestro, diaCruce de la brecha 5."""
    recs, alts = _acciones(dfs, ["m1", "m2", "m3"])
    salida = {}
    for m, sim in sims.items():
        ents = []
        for cod, s in sim.groupby("cod_cajero", sort=True):
            r, a = recs.get((m, cod)), alts.get((m, cod))
            ents.append({
                "entidadId": cod, "modelo": MODELO_API[m], "ciudad": ciudades[m].get(cod),
                "cupo": entero(s.cupo_operativo.iloc[0]), "serie": puntos_dia(s), "diaCruce": dia_cruce(r, a),
                "diasSinRegistro": [],
                "alertas": [] if a is None else [
                    {"tipo": t["tipoRegla"], "fechaCritica": t["fechaCritica"], "montoEnRiesgo": t["montoEnRiesgo"]}
                    for t in (mapear_alerta(x) for x in a.itertuples())],
            })
        salida[MODELO_API[m]] = {"entidades": ents, "corrida": CORRIDA, "corte": CORTE, "escenario": None,
                                 "unidad": "COP"}
    return salida


def vista_simulated_balance(dfs, sims, ciudades) -> dict[str, list]:
    """Flujo B GET /simulated-balance: saldo de cierre de los 15 días; servicioSugerido = primera acción."""
    recs, alts = _acciones(dfs, ["m1", "m2", "m3"])
    salida = {}
    for m, sim in sims.items():
        items = []
        for cod, s in sim.groupby("cod_cajero", sort=True):
            r, a = recs.get((m, cod)), alts.get((m, cod))
            items.append({
                "puntoId": cod, "corrida": CORRIDA, "corte": CORTE, "escenario": "BASE",
                "cupo": entero(s.cupo_operativo.iloc[0]),
                "serie": [{"fecha": x.fecha, "saldo": entero(x.saldo), "tipoDato": TIPO_SIMULADO}
                          for x in s.sort_values("fecha").itertuples()],
                "diaCruce": dia_cruce(r, a),
                "servicioSugerido": None if r is None else {"fecha": r.fecha_sugerida.iloc[0],
                                                            "monto": entero(r.monto.iloc[0])},
                "alertas": [] if a is None else [mapear_alerta(x) for x in a.itertuples()],
                "modelo": MODELO_API[m], "ciudad": ciudades[m].get(cod),  # extensiones
            })
        salida[MODELO_API[m]] = items
    return salida


def vista_funds_map(dfs, disponibles: pd.DataFrame) -> dict:
    """Flujo D GET /funds/map: saldo por billete-día = saldo_antes_acciones de M6 (el que dispara las alertas);
    banda = minimo/maximo; estado contra la banda; flujos por canal = predicciones M4/M5 del fondo; reparto por
    billete = efecto_neto_den; disponibleObservado = brecha 2."""
    pred, al = dfs["predicciones"], dfs["alertas"]
    m6 = pred[pred.modelo == "m6"].sort_values(["cod_cajero", "fecha", "denominacion"])
    canales = pred[pred.modelo.isin(CANAL_FONDO)]
    fondos, fuera = [], defaultdict(lambda: {"dias": [], "monto": 0})
    for fondo, g in m6.groupby("cod_cajero", sort=True):
        fid = fondo_api(fondo)
        saldos = []
        for r in g.itertuples():
            est = estado_banda(r.saldo_antes_acciones, r.minimo, r.maximo)
            saldos.append({"billete": billete(r.denominacion), "fecha": r.fecha,
                           "saldo": entero(r.saldo_antes_acciones),
                           "banda": {"min": entero(r.minimo), "max": entero(r.maximo)},
                           "estado": est, "tipoDato": TIPO_SIMULADO,
                           "saldoConAcciones": entero(r.saldo_proyectado)})  # extensión: tras las acciones de M6
            if est != "EN_BANDA":
                f = fuera[(fid, billete(r.denominacion), est)]
                f["dias"].append(r.fecha)
                lim = r.minimo if est == "FALTANTE" else r.maximo
                f["monto"] = max(f["monto"], entero(abs(r.saldo_antes_acciones - lim)))
        peor = {}
        for s in saldos:
            if s["fecha"] not in peor or ORDEN_ESTADO[s["estado"]] > ORDEN_ESTADO[peor[s["fecha"]]]:
                peor[s["fecha"]] = s["estado"]
        c = canales[canales.cod_cajero == fondo].sort_values(["fecha", "modelo"])
        a = al[(al.modelo == "m6") & (al.cod_cajero == fondo)].sort_values(["fecha", "denominacion"])
        d = disponibles[disponibles.fondo_id == fondo].sort_values("denominacion")
        conv = d.historia_convertida.dropna()
        nota = None
        if d.reconstruido.any():
            nota = "Disponible convertido de piezas a pesos (corrección SUP-29)"
        elif not conv.empty:
            nota = (f"Historia de {fid.split('|')[1]} convertida de piezas a pesos ({conv.iloc[0]}); "
                    "el valor al corte ya viene en pesos")
        fondos.append({
            "fondoId": fid, "ciudad": ciudad_de(fondo),
            "peorEstadoPorDia": [{"fecha": f, "estado": e, "diaNoHabil": f in DIAS_NO_HABILES}
                                 for f, e in sorted(peor.items())],
            "saldosPorBilleteDia": saldos,
            "disponibleObservado": {
                "valor": entero(d.valor.sum()), "tipoDato": "OBSERVADO", "reconstruido": bool(d.reconstruido.any()),
                "nota": nota,
                # extensión: detalle por billete con la fecha de la observación (último día <= corte)
                "porBillete": [{"billete": billete(x.denominacion), "fecha": str(x.fecha), "valor": entero(x.valor),
                                "reconstruido": bool(x.reconstruido)} for x in d.itertuples()],
            },
            "flujosPorCanal": [{"canal": CANAL_FONDO[r.modelo], "fecha": r.fecha, "monto": entero(r.yhat),
                                "tipoDato": r.origen_dato} for r in c.itertuples()],
            "repartoPorBillete": [{"billete": billete(r.denominacion), "fecha": r.fecha,
                                   "monto": entero(r.efecto_neto_den), "tipoDato": TIPO_REPARTO}
                                  for r in g.itertuples()],
            "alertas": [{"fondoId": fid, "billete": billete(r.denominacion), "fecha": r.fecha,
                         "tipoRegla": TIPO_REGLA.get((r.modelo, r.tipo)),
                         "criticidad": criticidad(TIPO_REGLA.get((r.modelo, r.tipo)), r.severidad),
                         "monto": entero(abs(r.nivel - r.limite)), "tipoDato": TIPO_SIMULADO}
                        for r in a.itertuples()],
        })
    return {"fondos": fondos,
            "fueraDeBanda": [{"fondoId": k[0], "billete": k[1], "estado": k[2], "dias": v["dias"],
                              "montoMaximo": v["monto"]} for k, v in sorted(fuera.items())],
            "corrida": CORRIDA, "corte": CORTE, "diasNoHabiles": DIAS_NO_HABILES, "diasSinRegistro": []}


def _frase(r, den) -> str:
    """Frase en lenguaje de negocio, sin umbral de regla ni costo (son de gestion-ms, handoff §6)."""
    if r.modelo == "m6":
        return f"Billete de {den} {'bajo el mínimo' if r.tipo == 'deficit' else 'sobre el máximo'} del fondo"
    if r.tipo == "agotamiento":
        return "Saldo simulado bajo el umbral de provisión" + (" (se agota)" if r.nivel <= 0 else "")
    if r.tipo == "recoleccion":
        return "Saldo simulado sobre el cupo del multifuncional (requiere recolección)"
    return "Saldo simulado de la sucursal en su cupo máximo (requiere recolección)"


def vista_alerts(dfs, ciudades) -> dict:
    """Flujo E GET /alerts: una AlertaGenerada por fila de alertas (M1, M2, M3, M6)."""
    al = dfs["alertas"].sort_values(["modelo", "cod_cajero", "fecha", "denominacion"])
    alertas = []
    for r in al.itertuples():
        base = mapear_alerta(r)
        den = billete(r.denominacion)
        ciudad = ciudad_entidad(r.modelo, r.cod_cajero, ciudades)
        if r.modelo == "m6":
            entidad, punto = nombre_fondo(fondo_api(r.cod_cajero)), fondo_api(r.cod_cajero)
        else:
            entidad, punto = f"{NOMBRE_ENTIDAD[r.modelo]} {r.cod_cajero} ({ciudad.title()})", r.cod_cajero
        alertas.append({
            "tipoRegla": base["tipoRegla"], "entidad": entidad, "frase": _frase(r, den),
            "montoEnRiesgo": base["montoEnRiesgo"], "criticidad": base["criticidad"],
            "fechaCritica": base["fechaCritica"], "tipoDato": base["tipoDato"],
            "modelo": MODELO_API.get(r.modelo, "fondos"), "puntoId": punto, "billete": den,  # extensiones
            "ciudad": ciudad,
        })
    return {"alertas": alertas, "corrida": CORRIDA, "corte": CORTE, "source": "DATOS_API"}


# --------------------------------------------------------------------------------------------- validación
def _validador(contrato: str, puntero: str):
    doc = yaml.safe_load((CONTRATOS / contrato).read_text(encoding="utf-8"))
    esquema = {"$ref": f"#/components/schemas/{puntero}", "components": doc["components"]}
    return jsonschema.Draft202012Validator(esquema, format_checker=jsonschema.FormatChecker())


def validar(objetos: list[tuple[str, str, str, object]]) -> dict:
    """objetos: (archivo, contrato, puntero de esquema, instancia). Agrupa errores por patrón."""
    grupos, total = {}, defaultdict(int)
    cache = {}
    for archivo, contrato, puntero, inst in objetos:
        v = cache.setdefault((contrato, puntero), _validador(contrato, puntero))
        total[(contrato, puntero)] += 1
        for e in v.iter_errors(inst):
            ruta = "/".join("[]" if isinstance(p, int) else str(p) for p in e.absolute_path)
            clave = (contrato, puntero, ruta, e.validator)
            g = grupos.setdefault(clave, {"contrato": contrato, "esquema": puntero, "ruta": ruta,
                                          "regla": e.validator, "ocurrencias": 0, "ejemplo": e.message[:200],
                                          "archivo_ejemplo": archivo})
            g["ocurrencias"] += 1
    errores = defaultdict(int)
    for g in grupos.values():
        errores[f"{g['contrato']}#{g['esquema']}"] += g["ocurrencias"]
    return {"instancias_validadas": {f"{c}#{p}": n for (c, p), n in sorted(total.items())},
            "errores_por_esquema": {k: errores.get(k, 0) for k in (f"{c}#{p}" for c, p in sorted(total))},
            "discrepancias": sorted(grupos.values(), key=lambda g: (g["contrato"], g["esquema"], g["ruta"])),
            "discrepancias_semanticas": DISCREPANCIAS_SEMANTICAS}


def verificar_vistas(dfs, plan, sb) -> dict:
    """Saldo diario vs saldo_antes/saldo_despues publicados y regla diaCruce/servicioSugerido (brechas 3 y 5)."""
    rec = dfs["recomendaciones"]
    idx = {(MODELO_API[r.modelo], r.cod_cajero, r.fecha_sugerida): r for r in
           rec[rec.modelo.isin(["m1", "m2", "m3"])].itertuples()}
    coinciden, difieren, dias = 0, [], 0
    for api, data in plan.items():
        for e in data["entidades"]:
            dias += len(e["serie"]) == 15 and len({p["fecha"] for p in e["serie"]}) == 15
            for p in e["serie"]:
                r = idx.get((api, e["entidadId"], p["fecha"]))
                if r is not None:
                    ok = (p["saldoAntes"] == entero(r.saldo_antes) and p["saldoDespues"] == entero(r.saldo_despues))
                    coinciden += ok
                    if not ok:
                        difieren.append([api, e["entidadId"], p["fecha"]])
    regla, m3_solo_accion = 0, 0
    alertas = dfs["alertas"]
    con_alerta = set(zip(alertas.modelo.map(MODELO_API), alertas.cod_cajero, strict=True))
    for api, items in sb.items():
        for x in items:
            regla += (x["diaCruce"] is None) == (x["servicioSugerido"] is None)
            if api == "sucursales" and x["servicioSugerido"] and (api, x["puntoId"]) not in con_alerta:
                m3_solo_accion += 1
    n_ent = sum(len(v) for v in sb.values())
    return {
        "entidades_con_15_dias": int(dias), "entidades": n_ent,
        "acciones_m1_m3_publicadas": int(rec.modelo.isin(["m1", "m2", "m3"]).sum()),
        "dias_con_accion_coinciden": int(coinciden), "dias_con_accion_difieren": difieren,
        "regla_diaCruce_servicioSugerido_cumple": int(regla),
        "m3_con_servicio_sin_alerta": int(m3_solo_accion),
        "criterio_diaCruce": DECISIONES["5_dia_cruce"],
    }


# ------------------------------------------------------------------------------------------------ generar
def info_insumos_s3() -> dict:
    import s3fs
    fs = s3fs.S3FileSystem(profile=os.environ["AWS_PROFILE"])
    out = {}
    for k in INSUMOS_S3:
        i = fs.info(f"{BUCKET}/{k}.parquet")
        out[f"s3://{BUCKET}/{k}.parquet"] = {"etag": i.get("ETag", "").strip('"'), "bytes": i.get("size"),
                                            "last_modified": str(i.get("LastModified"))}
    return out


def info_insumos_locales() -> dict:
    """Insumos de la corrida local de la versión (v2: B2_v2/data), resueltos con la capa storage del pipeline."""
    from daas.io import storage
    out = {}
    for k in INSUMOS_S3:
        uri = storage.resolve_uri(f"daas://{k}")
        p = Path(uri.removeprefix("file://"))
        if not uri.startswith("file://") or not p.is_file():
            raise SystemExit(f"Insumo local no encontrado: {uri}")
        out[uri] = {"sha256": sha256(p), "bytes": p.stat().st_size}
    return out


def generar(salida: Path) -> dict:
    excel_sha = sha256(EXCEL)
    if excel_sha != EXCEL_SHA256:
        raise SystemExit(f"El Excel de {VERSION} no es el esperado: {excel_sha} (se esperaba {EXCEL_SHA256})")
    dfs = leer_fuente()
    ciudades = ciudades_maestro()
    sims, inactivos = simular_m1_m3(dfs["predicciones"])
    ver_sim = verificar_simulacion(sims, dfs)
    for m, v in ver_sim.items():
        if (v["recomendaciones_coinciden"] != v["recomendaciones_publicadas"] or v["recomendaciones_sobrantes"]
                or v["alertas_coinciden"] != v["alertas_publicadas"] or v["alertas_sobrantes"]):
            raise SystemExit(f"La simulación recalculada de {m} no reproduce lo publicado: {v}")
    disponibles, ver_disp = disponibles_observados()
    if ver_disp["coinciden_con_saldo_inicial_SUP07"] != ver_disp["combinaciones"]:
        raise SystemExit(f"El disponible observado no coincide con el saldo inicial de M6: {ver_disp}")

    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    info_tablas = escribir_tablas(dfs, salida)
    escribir_esquemas(dfs, salida)

    a_validar = []
    for modelo, items in vista_forecast_series(dfs, ciudades).items():
        ruta = f"api/flujo_b/forecast_series/modelo={modelo}.json"
        escribir_json(salida / ruta, items)
        a_validar += [(ruta, "openapi-datos-flujo-b.yaml", "SeriesResponse", x) for x in items]
    met = vista_forecast_metrics(dfs, ciudades)
    for modelo, data in met.items():
        ruta = f"api/flujo_b/forecast_metrics/modelo={modelo}.json"
        escribir_json(salida / ruta, data)
        a_validar.append((ruta, "openapi-datos-flujo-b.yaml", "MetricsResponse", data))
    sb = vista_simulated_balance(dfs, sims, ciudades)
    for modelo, items in sb.items():
        ruta = f"api/flujo_b/simulated_balance/modelo={modelo}.json"
        escribir_json(salida / ruta, items)
        a_validar += [(ruta, "openapi-datos-flujo-b.yaml", "SimulatedBalanceResponse", x) for x in items]
    plan = vista_plan(dfs, sims, ciudades)
    for modelo, data in plan.items():
        ruta = f"api/flujo_c/simulated_balance_plan/modelo={modelo}.json"
        escribir_json(salida / ruta, data)
        a_validar.append((ruta, "openapi-datos-plan-flujo-c.yaml", "PlanBalanceData", data))
    ruta = "api/flujo_d/funds_map.json"
    fm = vista_funds_map(dfs, disponibles)
    escribir_json(salida / ruta, fm)
    a_validar.append((ruta, "openapi-datos-fondos-flujo-d.yaml", "FundsMapComputedResponse/properties/data", fm))
    ruta = "api/flujo_e/alerts.json"
    ae = vista_alerts(dfs, ciudades)
    escribir_json(salida / ruta, ae)
    a_validar.append((ruta, "openapi-datos-alertas-flujo-e.yaml", "AlertsGeneratedData", ae))

    reporte = validar(a_validar)
    escribir_json(salida / "validacion" / "validacion_openapi.json", reporte)
    verificaciones = {
        "simulacion_vs_publicado": ver_sim,
        "entidades_inactivas_sin_simulacion": {m: sorted(v) for m, v in inactivos.items()},
        "saldo_diario_y_dia_cruce": verificar_vistas(dfs, plan, sb),
        "metricas_vs_excel_hoja_03": comparar_metricas_excel(met),
        "disponible_observado": ver_disp,
        "ciudad": {MODELO_API[m]: {"entidades": int(len(s.cod_cajero.unique())),
                                   "sin_ciudad": int(sum(ciudades[m].get(c) is None for c in s.cod_cajero.unique())),
                                   "por_ciudad": pd.Series([ciudades[m].get(c) for c in s.cod_cajero.unique()])
                                   .value_counts().to_dict()} for m, s in sims.items()},
    }
    escribir_json(salida / "validacion" / "verificaciones.json", verificaciones)
    if PUB["anexo_d"]:
        (salida / "anexo_d").mkdir()
        shutil.copyfile(EXCEL, salida / "anexo_d" / PUB["anexo_d"])
        if sha256(salida / "anexo_d" / PUB["anexo_d"]) != EXCEL_SHA256:
            raise SystemExit("La copia del Excel en anexo_d/ no coincide con el original")

    bandas = yaml.safe_load(BANDAS_YML.read_text(encoding="utf-8"))
    archivos = []
    for p in sorted(salida.rglob("*")):
        if p.is_file():
            rel = p.relative_to(salida).as_posix()
            item = {"ruta": rel, "bytes": p.stat().st_size, "sha256": sha256(p)}
            if p.suffix == ".parquet":
                item["filas"] = pq.ParquetFile(p).metadata.num_rows
            archivos.append(item)
    n_err = sum(reporte["errores_por_esquema"].values())
    manifest = {
        "version": VERSION,
        "revision": REVISION,
        "fecha_generacion": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "nota": NOTA,
        "destino_s3": DESTINO_S3,
        "fuente": {
            "entrega": PUB["entrega"],
            "ruta": FUENTE.relative_to(ALX.parent).as_posix(),
            "archivos": {f.name: sha256(f) for f in sorted(FUENTE.glob("*.parquet"))},
            "excel": {"ruta": EXCEL.relative_to(ALX.parent).as_posix(), "sha256": excel_sha,
                      "nota": ("Referencia de trazabilidad: el Excel no se publica ni se modifica; la hoja 03 se "
                               "usa para comprobar las métricas.") if not PUB["anexo_d"] else
                              (f"La hoja 03 se usa para comprobar las métricas; copia sin cambios en "
                               f"anexo_d/{PUB['anexo_d']} (mismo sha256).")},
            **({"insumos_s3": info_insumos_s3()} if PUB["insumos"] == "s3" else
               {"insumos_locales": info_insumos_locales(),
                "conf": {"daas_conf": str(PUB["daas_conf"]),
                         "alx_yml_sha256": sha256(Path(PUB["daas_conf"]) / "alx.yml")}}),
            "logica_importada": ["daas.modules.atm_m1_m2.balance", "daas.modules.branches_m3.balance/policy",
                                 "daas.decision.optimizer/alerts", "daas.modules.funds_m6.dataset/"
                                 "correccion_disponibles", "daas.forecasting.metrics"],
        },
        "modelos_champion": {
            "fuente": "ALX/lab/conf/bandas.yml (clave 'adoptado')",
            **bandas["adoptado"],
            "m6": "balance encadenado determinista (no es un pronóstico con modelo champion)",
        },
        "convenciones": {"corrida": CORRIDA, "corte": CORTE, "dias_no_habiles": DIAS_NO_HABILES,
                         "origen": "README-handoff-datos.md §3 (no salen del pipeline)",
                         "envoltura": "las vistas api/ son el 'data' (o el cuerpo) del contrato; statusCode, status, "
                                      "message, timestamp y transactionId los pone la API"},
        "decisiones_interpretacion": DECISIONES,
        "discrepancias_declaradas": DISCREPANCIAS_SEMANTICAS,
        "tablas": info_tablas,
        "vistas_api": {
            "flujo_b/forecast_series": "GET /datos-efectivo/v1/forecast/series (SeriesResponse, nivel POINT)",
            "flujo_b/forecast_metrics": "GET /datos-efectivo/v1/forecast/metrics (MetricsResponse)",
            "flujo_b/simulated_balance": "GET /datos-efectivo/v1/simulated-balance (SimulatedBalanceResponse)",
            "flujo_c/simulated_balance_plan": "GET /datos-efectivo/v1/simulated-balance/plan (PlanBalanceData; "
                                              "/entity/{id} = filtrar entidades)",
            "flujo_d/funds_map.json": "GET /datos-efectivo/v1/funds/map (data de FundsMapComputedResponse)",
            "flujo_e/alerts.json": "GET /datos-efectivo/v1/alerts (AlertsGeneratedData)",
        },
        "validacion_openapi": {"archivo": "validacion/validacion_openapi.json",
                               "instancias": sum(reporte["instancias_validadas"].values()),
                               "errores_de_esquema": n_err,
                               "discrepancias_semanticas": len(DISCREPANCIAS_SEMANTICAS)},
        "n_archivos": len(archivos),
        "archivos": archivos,
    }
    escribir_json(salida / "manifest.json", manifest)
    return manifest


def verificar(directorio: Path) -> list[str]:
    """Compara bytes y sha256 de cada archivo del manifest con una copia descargada de S3."""
    man = json.loads((directorio / "manifest.json").read_text(encoding="utf-8"))
    errores = []
    for a in man["archivos"]:
        p = directorio / a["ruta"]
        if not p.exists():
            errores.append(f"FALTA {a['ruta']}")
        elif p.stat().st_size != a["bytes"] or sha256(p) != a["sha256"]:
            errores.append(f"DIFIERE {a['ruta']}")
    extra = {p.relative_to(directorio).as_posix() for p in directorio.rglob("*") if p.is_file()}
    extra -= {a["ruta"] for a in man["archivos"]} | {"manifest.json"}
    errores += [f"SOBRA {e}" for e in sorted(extra)]
    return errores


# -------------------------------------------------------------------------------------------------- subir
TIPO_CONTENIDO = {".json": "application/json", ".parquet": "application/vnd.apache.parquet",
                  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def clave_permitida(clave: str) -> bool:
    """Salvaguarda (a): True solo para claves bajo output/pronosticos/v2/ o la clave única version_vigente.json."""
    if clave == CLAVE_VIGENTE:
        return True
    partes = clave.split("/")
    return (clave.startswith(PREFIJO_ESCRITURA) and len(clave) > len(PREFIJO_ESCRITURA)
            and "" not in partes and "." not in partes and ".." not in partes)


def version_vigente(man: dict, man_sha: str, fecha: str) -> dict:
    """Contenido de output/pronosticos/version_vigente.json (puntero a la versión que deben leer los consumidores)."""
    ant = PUBLICACIONES["v0_provisional"]
    return {
        "descripcion": ("Puntero a la versión vigente de los pronósticos publicados. Leer 'prefijo' y su "
                        "manifest.json; las versiones anteriores se conservan sin cambios en su propio prefijo."),
        "version_vigente": man["version"],
        "revision": man["revision"],
        "entrega": man["fuente"]["entrega"],
        "prefijo": man["destino_s3"],
        "manifest": f"{man['destino_s3']}manifest.json",
        "manifest_sha256": man_sha,
        "n_objetos": man["n_archivos"] + 1,
        "fecha_publicacion": fecha,
        "fecha_generacion": man["fecha_generacion"],
        "excel": {"sha256": man["fuente"]["excel"]["sha256"],
                  "copia": f"{man['destino_s3']}anexo_d/{PUB['anexo_d']}" if PUB["anexo_d"] else None},
        "version_anterior": {
            "version": "v0_provisional", "revision": ant["revision"], "entrega": ant["entrega"],
            "prefijo": f"s3://{BUCKET}/{RAIZ_PRONOSTICOS}v0_provisional/",
            "excel_sha256": ant["excel_sha256"],
            "estado": "reemplazada por la versión vigente; se conserva sin cambios (no se borra ni se sobrescribe)",
        },
    }


def subir(salida: Path, dry_run: bool) -> int:
    """Sube <salida> a output/pronosticos/<versión>/ y escribe version_vigente.json, con las salvaguardas (a)-(c)."""
    import boto3
    man_path = salida / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    if man["version"] != VERSION or man["destino_s3"] != DESTINO_S3:
        raise SystemExit(f"El manifest es de {man['version']} ({man['destino_s3']}), no de {VERSION}")
    errs = verificar(salida)
    if errs:
        raise SystemExit("La salida local no coincide con su manifest:\n" + "\n".join(errs))
    prefijo = DESTINO_S3.removeprefix(f"s3://{BUCKET}/")
    rutas = [a["ruta"] for a in man["archivos"]] + ["manifest.json"]  # el manifest se sube al final
    plan = [(salida / r, prefijo + r) for r in rutas]
    fuera = [k for _, k in plan if not clave_permitida(k)]
    if fuera or not clave_permitida(CLAVE_VIGENTE):
        raise SystemExit(f"Salvaguarda (a): {len(fuera)} claves fuera de {PREFIJO_ESCRITURA}, p. ej. {fuera[:3]}")

    s3 = boto3.Session(profile_name=PERFIL_AWS).client("s3")
    # Salvaguarda (b): el prefijo destino debe estar vacío (ni objetos ni versiones ni delete markers) y
    # version_vigente.json no debe existir: nunca se sobrescribe ni se borra nada.
    ocupado = []
    for pref in (prefijo, CLAVE_VIGENTE):
        for pg in s3.get_paginator("list_object_versions").paginate(Bucket=BUCKET, Prefix=pref):
            ocupado += [v["Key"] for v in pg.get("Versions", []) + pg.get("DeleteMarkers", [])
                        if pref == prefijo or v["Key"] == CLAVE_VIGENTE]
    print(f"{'DRY-RUN' if dry_run else 'SUBIDA'} {VERSION} -> s3://{BUCKET}/{prefijo}")
    print(f"comprobación previa: {len(ocupado)} objetos/versiones existentes en {prefijo} o {CLAVE_VIGENTE}")
    if ocupado:
        raise SystemExit(f"Salvaguarda (b): el destino no está vacío ({len(ocupado)}), p. ej. {ocupado[:3]}; "
                         "no se escribe nada")

    print("clave\tbytes\tsha256")
    for p, k in plan:
        print(f"{k}\t{p.stat().st_size}\t{sha256(p)}")
    total = sum(p.stat().st_size for p, _ in plan)
    fecha = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    vig = (json.dumps(version_vigente(man, sha256(man_path), fecha), ensure_ascii=False, indent=1) + "\n").encode()
    print(f"{CLAVE_VIGENTE}\t{len(vig)}\t{hashlib.sha256(vig).hexdigest()}")
    print(f"total: {len(plan)} objetos en {prefijo} ({total} bytes) + 1 ({CLAVE_VIGENTE})")
    if dry_run:
        print("version_vigente.json (fecha_publicacion se fija al subir):")
        print(vig.decode())
        return 0

    def poner(clave: str, cuerpo: bytes, tipo: str) -> None:
        if not clave_permitida(clave):  # salvaguarda (a), también en cada escritura
            raise SystemExit(f"Salvaguarda (a): clave no permitida {clave}")
        digest = hashlib.sha256(cuerpo).digest()
        s3.put_object(Bucket=BUCKET, Key=clave, Body=cuerpo, ContentType=tipo,
                      ChecksumSHA256=base64.b64encode(digest).decode(),  # S3 rechaza el objeto si no coincide
                      Metadata={"sha256": digest.hex()})

    for p, k in plan:
        poner(k, p.read_bytes(), TIPO_CONTENIDO.get(p.suffix, "application/octet-stream"))
    poner(CLAVE_VIGENTE, vig, "application/json")
    subidos = [o["Key"] for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefijo)
               for o in pg.get("Contents", [])]
    faltan = sorted({k for _, k in plan} - set(subidos))
    print(f"subidos: {len(subidos)} objetos en {prefijo} + {CLAVE_VIGENTE}; faltan {len(faltan)}")
    print(vig.decode())
    return 1 if faltan or len(subidos) != len(plan) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Publicación de pronósticos en S3 (ver README.md)")
    ap.add_argument("accion", choices=["generar", "verificar", "subir"])
    ap.add_argument("ruta", type=Path)
    ap.add_argument("--version", default=os.environ.get("PUBLICAR_VERSION", VERSION_POR_DEFECTO),
                    choices=sorted(PUBLICACIONES))
    ap.add_argument("--dry-run", action="store_true", help="subir: solo lista claves, bytes y sha256")
    args = ap.parse_args()
    configurar(args.version)
    if args.accion == "generar":
        m = generar(args.ruta)
        print(json.dumps({k: m[k] for k in ("version", "revision", "n_archivos", "tablas", "validacion_openapi")},
                         indent=1, ensure_ascii=False))
    elif args.accion == "verificar":
        errs = verificar(args.ruta)
        print("\n".join(errs) if errs else "OK: todos los archivos coinciden en bytes y sha256")
        sys.exit(1 if errs else 0)
    else:
        if VERSION != "v2":
            raise SystemExit(f"Salvaguarda (a): subir solo escribe en {PREFIJO_ESCRITURA} (versión v2)")
        sys.exit(subir(args.ruta, args.dry_run))
