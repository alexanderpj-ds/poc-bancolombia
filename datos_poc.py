"""Carga de las series de tiempo de la PoC DaaS desde la replica en S3 (solo lectura).

Lee las capas `processed/`, `features/` y `output/` del bucket replica con el
perfil SSO `alx-poc`. Los datos se leen a memoria: nada se copia a disco.

Las series se derivan con la MISMA logica que usan los modelos del repo
(`poc-daas-bancolombia/poc-daas/src/daas/model/*/dataset.py`), para que lo que
se ve aqui sea lo que ve cada modelo:

- M1/M2: `pagado` = suma de `monto` con cdgtrn 220/420/520; `cash_in` (solo M2)
  = suma con cdgtrn 401/501/629; por cajero-dia.
- M3: `entradas` y `salidas` por sucursal-dia.
- M4/M5: `valor` agregado por fondo-dia (fondo = CIUDAD|TRANSPORTADORA).
- M6: `valor` de disponibles por fondo-denominacion-dia (ver `disponibles`).

Si la sesion SSO vencio: ejecutar `aws sso login --profile alx-poc` en la terminal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import yaml

#: Perfil SSO configurado en ~/.aws/config.
PERFIL = "alx-poc"
#: Bucket replica de la PoC (cuenta 903641686926).
BUCKET = "s3://poc-daas-bancolombia-replica-903641686926"

#: Catalogos de codigos de transaccion (conf/model_u1_u2.yml del repo).
CDGTRN_PAGADO = (220, 420, 520)
CDGTRN_CASH_IN = (401, 501, 629)

#: Fecha de corte y horizonte oficial de evaluacion.
CORTE = pd.Timestamp("2026-08-31")
HORIZONTE = (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-15"))
#: Origen del backtest del pipeline (pronostica 17-31 ago 2026); `chequeo_pipeline` de lab/conf/evaluacion.yml.
CORTE_BACKTEST = pd.Timestamp("2026-08-16")

#: En TRANSPORTADORA_001 (Cali y Pasto) `valor` viene en CANTIDAD DE BILLETES
#: hasta el 17-jul-2026 y en PESOS desde el 21-jul-2026 (verificado: antes del
#: cambio la suma diaria es ~5 millones de "unidades" y valor x denominacion da
#: ~50 mil millones COP, el mismo nivel que se observa en pesos despues).
CAMBIO_UNIDADES_TDV001 = pd.Timestamp("2026-07-21")

#: Orden y nombres de los 6 fondos (dim_fondo del repo).
FONDOS = (
    "CALI|TRANSPORTADORA_001",
    "CALI|TRANSPORTADORA_002",
    "CALI|TRANSPORTADORA_003",
    "CALI|TRANSPORTADORA_004",
    "PASTO|TRANSPORTADORA_001",
    "IPIALES|TRANSPORTADORA_002",
)
CIUDADES = ("CALI", "PASTO", "IPIALES")
DENOMINACIONES = (100000, 50000, 20000, 10000, 5000, 2000)


# --------------------------------------------------------------------------- #
# Acceso a S3                                                                  #
# --------------------------------------------------------------------------- #
def _storage_options() -> dict:
    """Credenciales temporales del perfil SSO para pandas/s3fs (no se imprimen)."""
    try:
        cred = boto3.Session(profile_name=PERFIL).get_credentials()
        congeladas = cred.get_frozen_credentials()
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            f"No hay sesion AWS valida para el perfil '{PERFIL}'. Ejecuta en la "
            f"terminal: aws sso login --profile {PERFIL}"
        ) from error
    return {
        "key": congeladas.access_key,
        "secret": congeladas.secret_key,
        "token": congeladas.token,
    }


def leer(ruta: str) -> pd.DataFrame:
    """Lee `<capa>/<dataset>` (sin extension) de la replica como DataFrame."""
    return pd.read_parquet(f"{BUCKET}/{ruta}.parquet", storage_options=_storage_options())


def _con_fecha(df: pd.DataFrame, col: str = "fecha") -> pd.DataFrame:
    out = df.copy()
    out[col] = pd.to_datetime(out[col])
    return out


# --------------------------------------------------------------------------- #
# Calendario y maestros                                                        #
# --------------------------------------------------------------------------- #
def calendario() -> pd.DataFrame:
    """Calendario Colombia del Feature Store (festivos, quincena, Anexo C...)."""
    return _con_fecha(leer("features/dim_calendario"))


def dias_anexo_c(cal: pd.DataFrame) -> list[pd.Timestamp]:
    """Los 27 dias sin registro declarados en el Anexo C."""
    return sorted(cal.loc[cal["missing_anexo_c"], "fecha"].tolist())


def rangos_contiguos(fechas: list[pd.Timestamp]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Agrupa fechas en rangos de dias consecutivos (para sombrear en graficos)."""
    rangos: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for f in sorted(fechas):
        if rangos and f - rangos[-1][1] == pd.Timedelta(days=1):
            rangos[-1] = (rangos[-1][0], f)
        else:
            rangos.append((f, f))
    return rangos


def maestro_atm() -> pd.DataFrame:
    """Snapshot vigente de cajeros: ciudad, administrador (TDV o SUC), cupo, tipo."""
    cp = leer("interim/cp_historico")
    cp["cod_cajero"] = cp["cod_cajero"].astype(str)
    return cp[["cod_cajero", "ciudad", "admon", "cupo", "disp_mf", "estado"]]


def desinstalados() -> pd.DataFrame:
    """Cajeros desinstalados (interim/cp_desinstalados, C-03; RN-07).

    Columnas: cod_cajero (str), fecha_desinstalacion (Timestamp; NaT en los 32 sin fecha), observaciones.
    Un codigo puede aparecer varias veces (3.157 filas, 3.087 codigos).
    """
    df = leer("interim/cp_desinstalados")
    df["cod_cajero"] = df["cod_cajero"].astype(str)
    df["fecha_desinstalacion"] = pd.to_datetime(df["fecha_desinstalacion"])
    return df[["cod_cajero", "fecha_desinstalacion", "observaciones"]]


def maestro_sucursales() -> pd.DataFrame:
    """Oficinas: ciudad, transportadora y tipo de ubicacion por sucursal."""
    ofi = leer("interim/oficinas")
    ofi["cod_sucursal"] = ofi["cod_sucursal"].astype(str)
    return ofi[["cod_sucursal", "ciudad", "transportadora", "ubicacion"]]


# --------------------------------------------------------------------------- #
# Series por modelo (formato largo: entidad, fecha, variable, valor)           #
# --------------------------------------------------------------------------- #
def serie_atm(modelo: str) -> pd.DataFrame:
    """M1 (`m1`) o M2 (`m2`): pagado (y cash_in en M2) por cajero-dia.

    Columnas: cod_cajero, fecha, variable, valor, ciudad, admon, rn07_conflicto.
    Los dias sin transacciones NO aparecen (no se rellenan con 0).
    """
    nombre = {"m1": "m1_atm_dispensador", "m2": "m2_atm_multifuncional"}[modelo]
    df = _con_fecha(leer(f"processed/{nombre}"))
    df["cod_cajero"] = df["cod_cajero"].astype(str)
    catalogos = {"pagado": CDGTRN_PAGADO}
    if modelo == "m2":
        catalogos["cash_in"] = CDGTRN_CASH_IN
    partes = []
    for variable, codigos in catalogos.items():
        sel = df[df["cdgtrn"].isin(codigos)]
        g = sel.groupby(["cod_cajero", "fecha"], as_index=False)["monto"].sum()
        g = g.rename(columns={"monto": "valor"})
        g["variable"] = variable
        partes.append(g)
    out = pd.concat(partes, ignore_index=True)
    conflicto = df.groupby("cod_cajero")["__rn07_conflicto"].max().rename("rn07_conflicto")
    out = out.merge(conflicto, on="cod_cajero", how="left")
    out = out.merge(maestro_atm()[["cod_cajero", "ciudad", "admon"]], on="cod_cajero", how="left")
    return out[["cod_cajero", "fecha", "variable", "valor", "ciudad", "admon", "rn07_conflicto"]]


def serie_sucursales(deduplicar: bool = False) -> pd.DataFrame:
    """M3: entradas y salidas por sucursal-dia (formato largo) + cupo_max_suc.

    Args:
        deduplicar: si es True elimina las filas duplicadas exactas por (cod_sucursal, fecha) antes del
            melt (caso del 13-may-2026: las 44 sucursales vienen dos veces) e informa cuantas quito.
            Por defecto False, igual que el repo (C-04 no deduplica) y que el arnes de Santiago.
    """
    df = _con_fecha(leer("processed/m3_sucursales"))
    df["cod_sucursal"] = df["cod_sucursal"].astype(str)
    if deduplicar:
        antes = len(df)
        df = df.drop_duplicates()
        print(f"serie_sucursales: {antes - len(df)} filas duplicadas exactas eliminadas.")
        repetidas = df.duplicated(["cod_sucursal", "fecha"]).sum()
        if repetidas:
            print(f"serie_sucursales: quedan {repetidas} llaves (cod_sucursal, fecha) repetidas con valores distintos.")
    largo = df.melt(
        id_vars=["cod_sucursal", "fecha", "cupo_max_suc"],
        value_vars=["entradas", "salidas"],
        var_name="variable",
        value_name="valor",
    )
    largo["valor"] = largo["valor"].astype(float)
    return largo.merge(maestro_sucursales(), on="cod_sucursal", how="left")


def serie_puntos(modelo: str, incluir_holdout: bool = False) -> pd.DataFrame:
    """M4 (`m4`, CBR) o M5 (`m5`, clientes): valor por punto-dia con su fondo."""
    nombre = {"m4": "m4_cbr", "m5": "m5_clientes"}[modelo]
    df = _con_fecha(leer(f"processed/{nombre}"))
    if incluir_holdout:
        df = pd.concat([df, _con_fecha(leer(f"processed/_holdout/{nombre}"))], ignore_index=True)
    df["cod_punto"] = df["cod_punto"].astype(str)
    df["fondo_id"] = df["ciudad"].astype(str) + "|" + df["transportadora"].astype(str)
    df["variable"] = "ingreso_efectivo_cbr" if modelo == "m4" else "ingreso_efectivo_clientes"
    return df[["cod_punto", "fecha", "fondo_id", "ciudad", "transportadora", "variable", "valor"]]


def disponibles(corregido: bool = True, incluir_holdout: bool = False) -> pd.DataFrame:
    """M6: saldo disponible por fondo-denominacion-dia (suma de calidades y familias).

    corregido=False reproduce la suma que hace el modelo M6 del repo.
    corregido=True aplica dos correcciones detectadas en los datos:
      1. Excluye las filas `calidad == 'TOTAL'` (subtotal que traen las
         TRANSPORTADORA_002 y _003 y que duplica el saldo al sumar).
      2. En TRANSPORTADORA_001, antes de CAMBIO_UNIDADES_TDV001 `valor` es
         cantidad de billetes: se convierte a pesos (valor x denominacion).
    """
    df = _con_fecha(leer("processed/m6_fondos"))
    if incluir_holdout:
        df = pd.concat([df, _con_fecha(leer("processed/_holdout/m6_fondos"))], ignore_index=True)
    df["valor_cop"] = df["valor"].astype(float)
    if corregido:
        df = df[df["calidad"].astype(str).str.strip().str.upper() != "TOTAL"].copy()
        en_billetes = (df["transportadora"] == "TRANSPORTADORA_001") & (
            df["fecha"] < CAMBIO_UNIDADES_TDV001
        )
        df.loc[en_billetes, "valor_cop"] = df.loc[en_billetes, "valor"] * df.loc[en_billetes, "denominacion"]
    g = df.groupby(["fondo_id", "denominacion", "fecha"], as_index=False)["valor_cop"].sum()
    return g.rename(columns={"valor_cop": "saldo"})


def predicciones() -> pd.DataFrame:
    """Contrato output/api/predicciones (M1-M6, 1-15 sep 2026)."""
    df = _con_fecha(leer("output/api/predicciones"))
    df["cod_cajero"] = df["cod_cajero"].astype(str)
    return df


# --------------------------------------------------------------------------- #
# Utilidades de analisis                                                       #
# --------------------------------------------------------------------------- #
def metricas() -> pd.DataFrame:
    """Contrato output/api/metricas (WAPE/MAE/Bias del backtest interno)."""
    return leer("output/api/metricas")


def serie_diaria(df: pd.DataFrame, desde=None, hasta=None) -> pd.Series:
    """Suma `valor` por dia sobre un calendario DIARIO COMPLETO.

    Los dias sin ningun registro quedan NaN (faltante), nunca 0: asi los huecos
    del Anexo C se ven como huecos y no como caidas a cero.
    """
    desde = pd.Timestamp(desde) if desde is not None else df["fecha"].min()
    hasta = pd.Timestamp(hasta) if hasta is not None else df["fecha"].max()
    serie = df.groupby("fecha")["valor"].sum(min_count=1)
    serie = serie.reindex(pd.date_range(desde, hasta, freq="D"))
    serie.index.name = "fecha"
    return serie


def total_diario(df: pd.DataFrame, por: str, desde=None, hasta=None) -> pd.DataFrame:
    """Como `serie_diaria`, pero una columna por cada valor de `por` (p. ej. ciudad)."""
    desde = pd.Timestamp(desde) if desde is not None else df["fecha"].min()
    hasta = pd.Timestamp(hasta) if hasta is not None else df["fecha"].max()
    tabla = df.groupby(["fecha", por])["valor"].sum(min_count=1).unstack(por)
    tabla = tabla.reindex(pd.date_range(desde, hasta, freq="D"))
    tabla.index.name = "fecha"
    return tabla


def indice_relativo(serie: pd.Series, ventana: int = 28) -> pd.Series:
    """Valor del dia / media movil centrada de `ventana` dias (quita la tendencia).

    1.0 = un dia "normal"; 1.3 = 30% por encima de su entorno. Sirve para
    comparar patrones (dia de semana, dia del mes, festivos) entre series de
    escalas muy distintas.
    """
    media = serie.rolling(ventana, center=True, min_periods=ventana // 2).mean()
    return serie / media


# --------------------------------------------------------------------------- #
# Matrices por serie (fecha x entidad), al grano de los pronosticos            #
# --------------------------------------------------------------------------- #
#: Raiz de ALX (contiene `lab/` y `pipeline/src`); se agrega a sys.path al usar el arnes.
_ALX_DIR = Path(__file__).resolve().parent


def _asegurar_lab() -> None:
    """Hace importables `lab` y `daas` (lab/__init__.py agrega pipeline/src a sys.path)."""
    if str(_ALX_DIR) not in sys.path:
        sys.path.insert(0, str(_ALX_DIR))
    import lab  # noqa: F401


def _tabla(ruta_parquet: str, columnas: list[str]) -> pd.DataFrame:
    """Equivale a `pd.read_parquet(root / ruta_parquet, columns=columnas)` del arnes, pero desde S3."""
    return leer(ruta_parquet.removesuffix(".parquet"))[columnas]


def _ciudad_por_entidad(dataset_conf: dict) -> pd.Series:
    """Replica `harness._city_by_entity` (lab/evaluation/harness.py:44): foto vigente del maestro."""
    entidad = dataset_conf["entidad"]
    maestro = _tabla(dataset_conf["maestro"], [entidad, "ciudad"])
    return maestro.drop_duplicates(entidad).set_index(entidad)["ciudad"]


def _largo_cdgtrn(dataset_conf: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replica `harness._long_from_cdgtrn` (harness.py:55): suma de `monto` sobre el catalogo de cdgtrn."""
    from lab import PIPELINE_CONF_DIR

    entidad = dataset_conf["entidad"]
    catalogo = yaml.safe_load((PIPELINE_CONF_DIR / "model_u1_u2.yml").read_text())["cdgtrn"][dataset_conf["objetivo"]]
    tabla = _tabla(dataset_conf["tabla"], [entidad, "fecha", "monto", "cdgtrn", "__rn07_conflicto"])
    rn07 = tabla.groupby(entidad)["__rn07_conflicto"].max().astype(bool)
    en_catalogo = tabla[tabla["cdgtrn"].isin(catalogo)]
    largo = en_catalogo.groupby([entidad, "fecha"], as_index=False)["monto"].sum(min_count=1)
    ciudad = _ciudad_por_entidad(dataset_conf)
    return largo.rename(columns={entidad: "entidad", "monto": "y"}), pd.DataFrame({"ciudad": ciudad, "rn07": rn07})


def _largo_columna(dataset_conf: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replica `harness._long_from_column` (harness.py:69). Sin deduplicar el 13-may, igual que Santiago."""
    entidad, objetivo = dataset_conf["entidad"], dataset_conf["objetivo"]
    tabla = _tabla(dataset_conf["tabla"], [entidad, "fecha", objetivo])
    largo = tabla.groupby([entidad, "fecha"], as_index=False)[objetivo].sum(min_count=1)
    ciudad = _ciudad_por_entidad(dataset_conf)
    return largo.rename(columns={entidad: "entidad", objetivo: "y"}), pd.DataFrame({"ciudad": ciudad})


def _largo_fondo(dataset_conf: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replica `harness._long_from_fund` (harness.py:78): suma de `valor` por fondo = ciudad|transportadora."""
    from daas.fondo.build_fund import build_fund_id

    objetivo = dataset_conf["objetivo"]
    tabla = _tabla(dataset_conf["tabla"], ["fecha", "ciudad", "transportadora", objetivo]).copy()
    tabla["entidad"] = [
        build_fund_id(ciudad, tdv) for ciudad, tdv in zip(tabla["ciudad"], tabla["transportadora"], strict=False)
    ]
    tabla = tabla[tabla["entidad"].notna()].copy()
    tabla["y"] = pd.to_numeric(tabla[objetivo], errors="coerce")
    largo = tabla.groupby(["entidad", "fecha"], as_index=False)["y"].sum(min_count=1)
    ciudad = pd.Series({fondo: fondo.split("|")[0] for fondo in largo["entidad"].unique()})
    return largo, pd.DataFrame({"ciudad": ciudad})


_CONSTRUCTORES_LARGO = {"cdgtrn": _largo_cdgtrn, "columna": _largo_columna, "fondo": _largo_fondo}


def matriz_arnes(dataset: str, conf: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Matriz fecha x entidad y atributos por entidad, identicos a `harness.load_dataset` pero desde S3.

    Replica linea por linea lab/evaluation/harness.py:44-121 (`_city_by_entity`, `_long_from_cdgtrn`,
    `_long_from_column`, `_long_from_fund` y `load_dataset`) leyendo la replica en memoria en vez de disco,
    para que cualquier modelo nuevo (p. ej. SARIMA) se mida exactamente igual que los de Santiago.

    Args:
        dataset: clave de `datasets` en lab/conf/evaluacion.yml: 'm1', 'm2_pagado', 'm2_cash_in',
            'm3_entradas', 'm3_salidas', 'm4' o 'm5'.
        conf: contrato de evaluacion ya leido; si es None se lee con `harness.load_conf()`.

    Returns:
        (wide, attrs): wide con indice DatetimeIndex diario denso (min..max de los datos), NaN donde no hay
        dato (Anexo C incluido, nunca 0); attrs con columnas `ciudad` (SIN_CIUDAD si falta) y `rn07` (bool).
    """
    _asegurar_lab()
    from daas.quality.anexo_c import mark_missing
    from lab.evaluation.harness import load_conf

    conf = conf or load_conf()
    dataset_conf = conf["datasets"][dataset]
    largo, atributos = _CONSTRUCTORES_LARGO[dataset_conf["forma"]](dataset_conf)
    largo["fecha"] = pd.to_datetime(largo["fecha"]).dt.date
    denso = mark_missing(largo, entity_col="entidad", date_col="fecha", target_col="y")
    wide = denso.pivot(index="fecha", columns="entidad", values="y")
    wide.index = pd.to_datetime(wide.index)
    if "rn07" not in atributos:
        atributos["rn07"] = False
    atributos = atributos.reindex(wide.columns)
    attrs = pd.DataFrame({"ciudad": atributos["ciudad"].fillna("SIN_CIUDAD"), "rn07": atributos["rn07"].eq(True)})
    return wide, attrs


def desinstalados_sin_dato(wide: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Cajeros de `wide` desinstalados (ultima fecha de cp_desinstalados) sin ningun dato posterior.

    Los codigos con dato posterior a la desinstalacion NO se marcan (codigo reutilizado, RN-06).
    """
    fechas = desinstalados().dropna(subset=["fecha_desinstalacion"])
    fechas = fechas.groupby("cod_cajero")["fecha_desinstalacion"].max()
    marcados: dict[str, pd.Timestamp] = {}
    for cod, fecha in fechas.items():
        if cod not in wide.columns or fecha >= wide.index.max() or fecha < wide.index.min():
            continue
        if wide.loc[wide.index > fecha, cod].notna().any():
            continue
        marcados[cod] = fecha
    return marcados


def _cortar_desinstalados(wide: pd.DataFrame) -> pd.DataFrame:
    """Deja NaN desde el dia siguiente a la desinstalacion; los marcados quedan en `attrs['desinstalados']`."""
    out = wide.copy()
    marcados = desinstalados_sin_dato(out)
    for cod, fecha in marcados.items():
        out.loc[out.index > fecha, cod] = np.nan
    out.attrs["desinstalados"] = marcados
    return out


def _forzar_anexo_c(wide: pd.DataFrame) -> pd.DataFrame:
    """Anexo C = NaN (nunca 0) en las fuentes de cajeros, que no tienen registro esos 27 dias."""
    _asegurar_lab()
    from daas.quality.anexo_c import anexo_c_window

    dias = pd.to_datetime(anexo_c_window())
    out = wide.copy()
    out.loc[out.index.isin(dias), :] = np.nan
    return out


def _matriz_m3(objetivo: str, corregido: bool) -> pd.DataFrame:
    """M3 sucursal x dia; corregido=True quita las filas duplicadas exactas del 13-may-2026."""
    if not corregido:
        return matriz_arnes(f"m3_{objetivo}")[0]
    largo = serie_sucursales(deduplicar=True)
    largo = largo[largo["variable"] == objetivo]
    wide = largo.pivot_table(index="fecha", columns="cod_sucursal", values="valor", aggfunc="sum")
    wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="D"))
    wide.index.name, wide.columns.name = "fecha", "entidad"
    return wide


def _matriz_m6(corregido: bool) -> pd.DataFrame:
    """M6 fondo|denominacion x dia habil (mas cualquier dia no habil con dato real)."""
    disp = disponibles(corregido=corregido)
    disp["entidad"] = disp["fondo_id"].astype(str) + "|" + disp["denominacion"].astype(str)
    wide = disp.pivot_table(index="fecha", columns="entidad", values="saldo", aggfunc="sum")
    cal = calendario()
    habiles = cal.loc[cal["es_habil"] & cal["fecha"].between(wide.index.min(), CORTE), "fecha"]
    wide = wide.reindex(pd.DatetimeIndex(habiles).union(wide.index))
    wide.index.name = "fecha"
    return wide


def matriz_eda(modelo: str, objetivo: str | None = None, corregido: bool = True) -> pd.DataFrame:
    """Series por entidad (fecha x entidad) hasta CORTE, al MISMO grano que los pronosticos, para el EDA.

    - m1: pagado por cajero; m2: `pagado` (defecto) o `cash_in` por cajero (via `matriz_arnes`).
    - m3: `entradas` (defecto) o `salidas` por sucursal.
    - m4 / m5: `valor` por fondo (build_fund_id), via `matriz_arnes`.
    - m6: saldo por fondo y denominacion (columnas 'FONDO|DENOM'), con `disponibles(corregido)`, sobre el
      indice de dias habiles de dim_calendario (el hueco 31-jul..9-sep-2024 queda NaN).

    Los dias sin registro quedan NaN, nunca 0. Anexo C: en M1/M2 (fuente de cajeros) se fuerza NaN; en
    M3-M6 las fuentes si traen dato esos dias y se conserva, igual que `daas.quality.anexo_c.mark_missing`.

    Args:
        modelo: 'm1'..'m6'.
        objetivo: variable para m2 ('pagado'|'cash_in') y m3 ('entradas'|'salidas'); se ignora en el resto.
        corregido: True aplica las correcciones declaradas: M3 deduplicado (13-may-2026), M1/M2 NaN desde el
            dia siguiente a la desinstalacion de los cajeros sin dato posterior (lista en
            `resultado.attrs['desinstalados']`) y M6 con `disponibles(corregido=True)`.

    Returns:
        DataFrame con DatetimeIndex `fecha` y una columna por entidad.
    """
    if modelo in ("m1", "m2"):
        objetivo = "pagado" if modelo == "m1" else (objetivo or "pagado")
        wide = _forzar_anexo_c(matriz_arnes("m1" if modelo == "m1" else f"m2_{objetivo}")[0])
        if corregido:
            wide = _cortar_desinstalados(wide)
    elif modelo == "m3":
        wide = _matriz_m3(objetivo or "entradas", corregido)
    elif modelo in ("m4", "m5"):
        wide = matriz_arnes(modelo)[0]
    elif modelo == "m6":
        wide = _matriz_m6(corregido)
    else:
        raise ValueError(f"Modelo desconocido: {modelo}")
    marcados = wide.attrs.get("desinstalados", {})
    wide = wide.loc[:CORTE]
    wide.attrs["desinstalados"] = marcados
    return wide


def efecto_correcciones() -> pd.DataFrame:
    """Efecto de cada correccion de `matriz_eda(corregido=True)` frente a los datos tal cual.

    Returns:
        DataFrame con columnas serie, correccion, filas_afectadas, valor_antes, valor_despues, detalle.
    """
    filas = []
    # M3: duplicado exacto del 13-may-2026 (el arnes de Santiago lo suma dos veces).
    m3 = _con_fecha(leer("processed/m3_sucursales"))
    sin_dup = m3.drop_duplicates()
    for objetivo in ("entradas", "salidas"):
        dias = m3.loc[m3.duplicated(keep=False), "fecha"].unique()
        filas.append(
            {
                "serie": f"m3_{objetivo}",
                "correccion": "deduplicar filas exactas",
                "filas_afectadas": int(len(m3) - len(sin_dup)),
                "valor_antes": float(m3.loc[m3["fecha"].isin(dias), objetivo].sum()),
                "valor_despues": float(sin_dup.loc[sin_dup["fecha"].isin(dias), objetivo].sum()),
                "detalle": "dias: " + ", ".join(str(pd.Timestamp(d).date()) for d in dias),
            }
        )
    # M1/M2: cajeros desinstalados sin dato posterior.
    for dataset in ("m1", "m2_pagado", "m2_cash_in"):
        wide = _forzar_anexo_c(matriz_arnes(dataset)[0])
        for cod, fecha in desinstalados_sin_dato(wide).items():
            celdas = wide.loc[wide.index > fecha, cod]
            filas.append(
                {
                    "serie": f"{dataset}|{cod}",
                    "correccion": "NaN despues de la desinstalacion",
                    "filas_afectadas": int(len(celdas)),
                    "valor_antes": float(celdas.sum()),
                    "valor_despues": 0.0,
                    "detalle": (
                        f"desinstalado {fecha.date()}; de los dias posteriores {int(celdas.notna().sum())} traian "
                        "dato: quedan NaN (nunca 0) y la entidad se declara fuera del horizonte"
                    ),
                }
            )
    # M6: calidad TOTAL excluida y TRANSPORTADORA_001 de billetes a pesos antes del cambio de unidades.
    m6 = _con_fecha(leer("processed/m6_fondos"))
    es_total = m6["calidad"].astype(str).str.strip().str.upper() == "TOTAL"
    en_billetes = ~es_total & (m6["transportadora"] == "TRANSPORTADORA_001") & (m6["fecha"] < CAMBIO_UNIDADES_TDV001)
    antes = disponibles(corregido=False).groupby("fondo_id")["saldo"].sum()
    despues = disponibles(corregido=True).groupby("fondo_id")["saldo"].sum()
    for fondo in antes.index:
        del_fondo = m6["fondo_id"] == fondo
        n_total, n_billetes = int((es_total & del_fondo).sum()), int((en_billetes & del_fondo).sum())
        if not (n_total or n_billetes):
            continue
        correcciones = [nombre for nombre, n in (("excluir TOTAL", n_total), ("billetes a pesos", n_billetes)) if n]
        filas.append(
            {
                "serie": f"m6|{fondo}",
                "correccion": " + ".join(correcciones),
                "filas_afectadas": n_total + n_billetes,
                "valor_antes": float(antes[fondo]),
                "valor_despues": float(despues.get(fondo, np.nan)),
                "detalle": f"filas TOTAL={n_total}; filas en billetes={n_billetes}; suma de saldo diario",
            }
        )
    return pd.DataFrame(filas)
