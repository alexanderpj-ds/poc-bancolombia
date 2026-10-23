"""Correccion de los disponibles de M6 detectada en los datos (SUP-29, decision D3 del workflow de imputacion).

`processed/m6_fondos` trae dos problemas que inflan o desinflan el saldo diario que M6 suma por fondo y
denominacion (SUP-07, SUP-09, SUP-10):

1. **Filas `calidad == TOTAL`** (TRANSPORTADORA_002 hasta el 12-ago-2026 y TRANSPORTADORA_003 hasta el
   29-jul-2026): son el subtotal de las demas calidades de la misma familia. Sumarlas duplica el saldo.
   Se excluyen siempre; `verificar_total` deja la evidencia de que igualan la suma del resto.
2. **Unidades de TRANSPORTADORA_001** (`CALI|` y `PASTO|TRANSPORTADORA_001`): `valor` viene en cantidad de
   billetes hasta el 17-jul-2026 y en pesos desde el 21-jul-2026. El cambio se detecta POR DATOS, no por una
   fecha fija: un monto en pesos de una denominacion es multiplo de ella; una cantidad de billetes casi nunca.
   Un fondo-dia esta en billetes si la fraccion de sus filas con `valor != 0` que son multiplo de la denominacion
   es menor que `umbral_multiplo` (0,5 por defecto); entonces `valor` se multiplica por la denominacion.

Dos interruptores opcionales (decision del 20-oct-2026) sacan de la ventana de minimos y maximos (SUP-10), como
faltantes, los dias que no son una observacion valida del saldo: el fondo-denominacion-dia con algun `valor` en
blanco (23 filas de `CALI|TRANSPORTADORA_004|50000`, 9-jul a 11-ago-2026), en vez de sumarlo como 0, y el fondo-dia
con dos formatos de reporte (TOTAL distinto de la suma del resto: 30 fondo-dias de la TDV_002 y la TDV_003), en vez
de sumar los dos. Las filas se conservan con la marca `fuera_ventana_minmax`: el saldo inicial (SUP-07) y la mezcla
(SUP-09) no cambian.

Las correcciones son idempotentes: tras corregir no quedan filas `TOTAL` y `valor x denominacion` siempre es
multiplo de la denominacion, asi que una segunda pasada no cambia nada. Funciones puras: no hacen I/O.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Etiqueta de la calidad subtotal (comparacion sin espacios y en mayusculas).
CALIDAD_TOTAL = "TOTAL"
#: Umbral por defecto de la fraccion de filas multiplo de la denominacion (DI-09 del plan).
UMBRAL_MULTIPLO = 0.5
#: Tolerancia en COP para decir que `TOTAL` iguala la suma del resto.
TOLERANCIA_TOTAL = 0.5
#: Columna opcional con la marca de `valor` en blanco en la fuente (la agrega `load_available_cash` antes de
#: rellenar con 0). Si falta, se usa `valor.isna()`.
COL_BLANCO = "valor_en_blanco"
#: Columna de salida: True en los dias que no son una observacion valida del saldo (blanco o doble formato). Las
#: filas se conservan (SUP-07 y SUP-09 no cambian); solo `balance.operational_minmax` (SUP-10) las saca de su ventana.
COL_FUERA = "fuera_ventana_minmax"


def _es_total(df: pd.DataFrame) -> pd.Series:
    """Mascara de filas `calidad == TOTAL` (False si la tabla no trae `calidad`)."""
    if "calidad" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["calidad"].astype(str).str.strip().str.upper() == CALIDAD_TOTAL


def detectar_unidades(df: pd.DataFrame, umbral_multiplo: float = UMBRAL_MULTIPLO) -> pd.DataFrame:
    """Detecta por datos si `valor` esta en billetes o en pesos, por fondo y fecha.

    Ignora las filas `TOTAL` y las filas con `valor` 0 o faltante (un cero es multiplo de todo y no informa).

    Args:
        df: Disponibles con `fondo_id`, `fecha`, `denominacion`, `valor` (y `calidad`, opcional).
        umbral_multiplo: Fraccion minima de filas multiplo de la denominacion para decir "pesos".

    Returns:
        pd.DataFrame: Una fila por (`fondo_id`, `fecha`) con `filas_no_cero`, `filas_multiplo`, `frac_multiplo`,
        `suma_valor` (suma de `valor` tal cual, sin TOTAL) y `unidad` (`billetes` | `pesos`). Un fondo-dia sin
        filas distintas de 0 queda en `pesos` (no hay nada que convertir).
    """
    base = df.loc[~_es_total(df), ["fondo_id", "fecha", "denominacion", "valor"]].copy()
    valor = pd.to_numeric(base["valor"], errors="coerce").fillna(0.0)
    denominacion = pd.to_numeric(base["denominacion"], errors="coerce").astype(float)
    base["no_cero"] = valor.ne(0.0)
    base["multiplo"] = base["no_cero"] & np.isclose(np.mod(valor, denominacion), 0.0)
    base["valor_num"] = valor
    out = base.groupby(["fondo_id", "fecha"], as_index=False).agg(
        filas_no_cero=("no_cero", "sum"),
        filas_multiplo=("multiplo", "sum"),
        suma_valor=("valor_num", "sum"),
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        out["frac_multiplo"] = out["filas_multiplo"] / out["filas_no_cero"].where(out["filas_no_cero"] > 0)
    out["unidad"] = np.where(out["frac_multiplo"] < float(umbral_multiplo), "billetes", "pesos")
    return out[["fondo_id", "fecha", "filas_no_cero", "filas_multiplo", "frac_multiplo", "suma_valor", "unidad"]]


def verificar_total(df: pd.DataFrame) -> pd.DataFrame:
    """Compara cada `TOTAL` con la suma de las demas calidades de la misma celda.

    Celda = (`fondo_id`, `denominacion`, `fecha`, `familia` si existe). La verificacion es evidencia: no cambia la
    decision de excluir `TOTAL` (es un subtotal; mantenerlo duplica el saldo en cualquier caso).

    Args:
        df: Disponibles con `calidad` (si no la trae, devuelve una tabla vacia).

    Returns:
        pd.DataFrame: Una fila por celda con `TOTAL`: `total`, `suma_resto`, `diferencia` (total - resto) y
        `coincide` (|diferencia| <= `TOLERANCIA_TOTAL`).
    """
    columnas = ["fondo_id", "denominacion", "fecha", "familia", "total", "suma_resto", "diferencia", "coincide"]
    if "calidad" not in df.columns:
        return pd.DataFrame(columns=columnas)
    clave = ["fondo_id", "denominacion", "fecha"] + (["familia"] if "familia" in df.columns else [])
    datos = df.assign(valor=pd.to_numeric(df["valor"], errors="coerce").fillna(0.0))
    es_total = _es_total(datos)
    total = datos[es_total].groupby(clave)["valor"].sum().rename("total")
    if total.empty:
        return pd.DataFrame(columns=columnas)
    resto = datos[~es_total].groupby(clave)["valor"].sum().rename("suma_resto")
    out = pd.concat([total, resto], axis=1).loc[total.index].reset_index()
    out["suma_resto"] = out["suma_resto"].fillna(0.0)
    out["diferencia"] = out["total"] - out["suma_resto"]
    out["coincide"] = out["diferencia"].abs() <= TOLERANCIA_TOTAL
    if "familia" not in out.columns:
        out["familia"] = None
    return out[columnas]


def corregir_disponibles(df: pd.DataFrame, config: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Excluye las filas `TOTAL` y convierte a pesos los fondo-dia detectados en billetes (SUP-29).

    Args:
        df: Disponibles tal cual (`processed/m6_fondos`), con `valor` ya numerico.
        config: Bloque `correccion_disponibles` de `conf/model_u6.yml`: `umbral_multiplo`,
            `excluir_dias_con_blancos` (el fondo-denominacion-dia con un `valor` en blanco sale de la ventana de
            SUP-10, en vez de contar el blanco como 0) y `excluir_dias_doble_formato` (el fondo-dia con dos formatos
            de reporte, TOTAL distinto de la suma del resto, sale de la ventana de SUP-10). Los dos interruptores
            valen `False` si faltan.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: (disponibles corregidos con las mismas columnas, `valor` en pesos y la
        marca `fuera_ventana_minmax`,
        evidencia por (`fondo_id`, `fecha`): salida de `detectar_unidades` + `filas_convertidas`,
        `filas_total_excluidas` y `total_coincide` (todas las celdas `TOTAL` del dia iguales a la suma del resto;
        NA si el dia no tiene `TOTAL`)).
    """
    cfg = config or {}
    umbral = float(cfg.get("umbral_multiplo", UMBRAL_MULTIPLO))
    es_total = _es_total(df)
    unidades = detectar_unidades(df, umbral)
    verificacion = verificar_total(df)

    # Dias que salen de la ventana de SUP-10 (interruptores, decision del 20-oct-2026; apagados por defecto):
    # - blancos: el fondo-denominacion-dia con alguna fila `valor` en blanco queda incompleto -> faltante, nunca 0;
    # - doble formato: el fondo-dia en que TOTAL no iguala la suma del resto trae dos reportes -> faltante.
    blanco = df[COL_BLANCO].astype(bool) if COL_BLANCO in df.columns else df["valor"].isna()
    llave_den = pd.MultiIndex.from_frame(df[["fondo_id", "denominacion", "fecha"]].astype(object))
    dias_blancos = pd.MultiIndex.from_frame(df.loc[blanco, ["fondo_id", "denominacion", "fecha"]].astype(object))
    fuera_blancos = llave_den.isin(dias_blancos) if bool(cfg.get("excluir_dias_con_blancos", False)) else None
    doble = verificacion.loc[~verificacion["coincide"].astype(bool), ["fondo_id", "fecha"]].drop_duplicates()
    llave_dia = pd.MultiIndex.from_frame(df[["fondo_id", "fecha"]].astype(object))
    fuera_doble = (
        llave_dia.isin(pd.MultiIndex.from_frame(doble.astype(object)))
        if bool(cfg.get("excluir_dias_doble_formato", False)) and not doble.empty
        else None
    )
    excluir = np.zeros(len(df), bool)
    for marca_fuera in (fuera_blancos, fuera_doble):
        if marca_fuera is not None:
            excluir |= marca_fuera
    if COL_FUERA in df.columns:                     # idempotencia: conserva la marca de una pasada anterior
        excluir |= df[COL_FUERA].fillna(False).astype(bool).to_numpy()
    excluir = pd.Series(excluir, index=df.index)

    corregido = df.loc[~es_total].copy()
    corregido[COL_FUERA] = excluir.loc[corregido.index]
    billetes = unidades.loc[unidades["unidad"] == "billetes", ["fondo_id", "fecha"]]
    llave = pd.MultiIndex.from_frame(corregido[["fondo_id", "fecha"]])
    marca = llave.isin(pd.MultiIndex.from_frame(billetes)) if not billetes.empty else np.zeros(len(corregido), bool)
    en_billetes = pd.Series(marca, index=corregido.index)
    corregido.loc[en_billetes, "valor"] = (
        pd.to_numeric(corregido.loc[en_billetes, "valor"], errors="coerce").astype(float)
        * pd.to_numeric(corregido.loc[en_billetes, "denominacion"], errors="coerce").astype(float)
    )

    convertidas = corregido[en_billetes].groupby(["fondo_id", "fecha"]).size().rename("filas_convertidas")
    excluidas = df[es_total].groupby(["fondo_id", "fecha"]).size().rename("filas_total_excluidas")
    evidencia = unidades.set_index(["fondo_id", "fecha"])
    evidencia["filas_convertidas"] = convertidas.reindex(evidencia.index)
    evidencia["filas_total_excluidas"] = excluidas.reindex(evidencia.index)
    if verificacion.empty:
        evidencia["total_coincide"] = pd.Series(pd.NA, index=evidencia.index, dtype="boolean")
    else:
        coincide = verificacion.groupby(["fondo_id", "fecha"])["coincide"].all().astype("boolean")
        evidencia["total_coincide"] = coincide.reindex(evidencia.index)
    blancos_dia = df[blanco].groupby(["fondo_id", "fecha"])["denominacion"].nunique()
    evidencia["denominaciones_con_blancos"] = blancos_dia.reindex(evidencia.index)
    fuera_dia = df[excluir & ~es_total].groupby(["fondo_id", "fecha"]).size()
    evidencia["filas_fuera_ventana_minmax"] = fuera_dia.reindex(evidencia.index)
    cols = ["filas_convertidas", "filas_total_excluidas", "denominaciones_con_blancos", "filas_fuera_ventana_minmax"]
    evidencia[cols] = evidencia[cols].fillna(0).astype(int)
    evidencia["doble_formato"] = evidencia["total_coincide"].eq(False).fillna(False).astype(bool)
    evidencia = evidencia.reset_index()
    if bool(excluir.any()):
        logger.warning(
            "correccion_disponibles (SUP-29): %d filas marcadas fuera de la ventana de SUP-10 por dias faltantes "
            "(blancos=%s, doble formato=%s).",
            int((excluir & ~es_total).sum()),
            bool(cfg.get("excluir_dias_con_blancos", False)),
            bool(cfg.get("excluir_dias_doble_formato", False)),
        )

    n_total, n_conv = int(es_total.sum()), int(en_billetes.sum())
    if n_total or n_conv:
        logger.warning(
            "correccion_disponibles (SUP-29): %d filas TOTAL excluidas y %d filas convertidas de billetes a pesos "
            "en %d fondo-dias.",
            n_total,
            n_conv,
            int((evidencia["filas_convertidas"] > 0).sum()),
        )
    if not verificacion.empty and not bool(verificacion["coincide"].all()):
        logger.warning(
            "correccion_disponibles (SUP-29): %d de %d celdas TOTAL no igualan la suma del resto (dias con dos "
            "formatos de reporte); TOTAL se excluye igual.",
            int((~verificacion["coincide"]).sum()),
            len(verificacion),
        )
    return corregido.reset_index(drop=True), evidencia
