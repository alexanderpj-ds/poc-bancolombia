r"""Contexto V4 "as of": maestro vigente EN CADA ORIGEN, nunca el snapshot del 8-sep (D2 ii; SUP-28; DI-03).

PARTE 2, tareas 2.3 y 2.4 del plan (`ALX/.agents/tasks/imputacion/plan.md`). El contexto de la fase 2
(`ml/correr_ml.py:construir_contexto`) toma los atributos de `interim/cp_historico` (snapshot 2026-09-08, posterior a
todos los origenes: posible fuga leve declarada en `global_ml.py:18-20`). Aqui:

- M1/M2: `cupo`, `disp_mf`, `admon` y `ciudad` del ULTIMO snapshot con `fecha_snapshot <= origen` de
  `raw/cp_historico.xlsx` (`imputacion.datos.cp_snapshots`, 557 snapshots 2023-01-02..2026-09-08). Se toma la fila
  completa del snapshot (si una variable viene en blanco en esa fila, queda NaN: no se rellena con otro snapshot).
  Cajero sin snapshot <= origen -> NaN.
- M3: `cupo_max_suc` = ultimo valor no nulo con fecha <= origen (SUP-M3-02 aplicado al origen y no al corte); si ese
  dia trae varios valores, el maximo (respaldo best-effort) con `logging.warning`. Sin valor <= origen -> NaN con
  warning: el respaldo de SUP-M3-02 al maximo historico usaria datos posteriores al origen (fuga) y no se aplica.
- `ciudad` de M3/M4/M5 y la de evaluacion: la de `attrs` (maestro de oficinas / id del fondo; no tienen historia).

El modelo recibe el contexto por `con_contexto_asof`, envoltura picklable (loky) que arma los atributos con el origen
del pronostico (`dates[0] - 1 dia`) y llama a la funcion original. El efecto en el pronostico se mide en la PARTE 5.

CLI:
    [P] "$ALX/imputacion/contexto_asof.py" --piloto        # 3 origenes de M1: cajeros con cupo/admon distintos
    [P] "$ALX/imputacion/contexto_asof.py" --efecto        # 19 origenes x 7 datasets -> resultados/arnes/v4_asof_*.csv
    [P] "$ALX/imputacion/contexto_asof.py" --guarda-fuga   # ml_lgbm_v4_tw, 20 cajeros, 1 origen
"""

from __future__ import annotations

import argparse
import logging
import time
from functools import partial

import numpy as np
import pandas as pd

import imputacion  # noqa: F401  (agrega ALX y pipeline/src a sys.path)

logger = logging.getLogger(__name__)

SALIDA = imputacion.RESULTADOS_DIR / "arnes"
ATM = ("m1", "m2_pagado", "m2_cash_in")
M3 = ("m3_entradas", "m3_salidas")
VARIABLES_ATM = ("cupo", "disp_mf", "admon", "ciudad")
HERMANOS = {"m2_pagado": "m2_cash_in", "m2_cash_in": "m2_pagado", "m3_entradas": "m3_salidas",
            "m3_salidas": "m3_entradas"}


def atributos_al(snapshots: pd.DataFrame, origen: pd.Timestamp, columnas: pd.Index) -> pd.DataFrame:
    """Atributos del ultimo snapshot con `fecha_snapshot <= origen` por cajero, alineados a `columnas`.

    Args:
        snapshots: `imputacion.datos.cp_snapshots()` (fecha_snapshot, cod_cajero, ciudad, admon, cupo, disp_mf, ...).
        origen: Origen del pronostico; nunca se mira un snapshot posterior.
        columnas: Entidades (codigos de cajero) en el orden de la matriz.

    Returns:
        DataFrame indexado por `columnas` con cupo, disp_mf, admon, ciudad y `fecha_snapshot` (NaN/NaT sin snapshot).
    """
    previos = snapshots[snapshots["fecha_snapshot"] <= pd.Timestamp(origen)]
    ultimo = previos.sort_values(["cod_cajero", "fecha_snapshot"], kind="mergesort").groupby("cod_cajero").tail(1)
    ultimo = ultimo.set_index(ultimo["cod_cajero"].astype(str))
    alineado = ultimo.reindex(pd.Index(columnas).astype(str))
    salida = pd.DataFrame(index=columnas)
    for col in (*VARIABLES_ATM, "fecha_snapshot"):
        salida[col] = alineado[col].to_numpy()
    return salida


def cupo_m3_al(tabla_m3: pd.DataFrame, origen: pd.Timestamp, columnas: pd.Index) -> pd.Series:
    """`cupo_max_suc` vigente al origen por sucursal (SUP-M3-02 con fecha <= origen), alineado a `columnas`."""
    tabla = tabla_m3[["cod_sucursal", "fecha", "cupo_max_suc"]].copy()
    tabla["cod_sucursal"] = tabla["cod_sucursal"].astype(str)
    tabla["fecha"] = pd.to_datetime(tabla["fecha"])
    tabla = tabla[(tabla["fecha"] <= pd.Timestamp(origen)) & tabla["cupo_max_suc"].notna()]
    ultima = tabla.groupby("cod_sucursal")["fecha"].transform("max")
    del_dia = tabla[tabla["fecha"] == ultima].groupby("cod_sucursal")["cupo_max_suc"]
    varios = del_dia.nunique()
    if (varios > 1).any():
        logger.warning("SUP-M3-02: %s sucursales con varios cupo_max_suc el ultimo dia <= %s; se usa el maximo",
                       int((varios > 1).sum()), pd.Timestamp(origen).date())
    cupo = del_dia.max()
    claves = pd.Index(columnas).astype(str)
    faltan = sorted(set(claves) - set(cupo.index))
    if faltan:
        logger.warning("SUP-M3-02: %s sucursales sin cupo_max_suc <= %s (quedan NaN, sin respaldo posterior): %s",
                       len(faltan), pd.Timestamp(origen).date(), faltan[:10])
    return pd.Series(cupo.reindex(claves).to_numpy(dtype=float), index=columnas, name="cupo_max_suc")


def construir_contexto_asof(
    dataset: str, wide: pd.DataFrame, attrs: pd.DataFrame, conf: dict, *, snapshots: pd.DataFrame | None = None,
    tabla_m3: pd.DataFrame | None = None, cruzada: pd.DataFrame | None = None, cruzada_corregida: bool = True,
) -> dict:
    """Insumos del contexto "as of" (se resuelven por origen en `atributos_contexto`).

    Args:
        dataset: Uno de los 7 datasets del arnes.
        wide: Matriz fecha x entidad del dataset.
        attrs: Atributos del arnes (`ciudad`, `rn07`).
        conf: Contrato de evaluacion.
        snapshots: Snapshots del maestro (M1/M2); None = `imputacion.datos.cp_snapshots()`.
        tabla_m3: `processed/m3_sucursales` (M3); None = lectura de S3.
        cruzada: Matriz del objetivo hermano; None = `imputacion.datos.matriz_corregida` (o `matriz_arnes` si
            `cruzada_corregida=False`, para aislar el efecto del maestro).
        cruzada_corregida: Ver `cruzada`.

    Returns:
        {'dataset', 'ciudad', 'snapshots', 'tabla_m3', 'cruzada'}.
    """
    import datos_poc as dp

    from imputacion import datos

    contexto = {"dataset": dataset, "ciudad": attrs["ciudad"].reindex(wide.columns), "snapshots": None,
                "tabla_m3": None, "cruzada": None}
    if dataset in ATM:
        contexto["snapshots"] = snapshots if snapshots is not None else datos.cp_snapshots()
    elif dataset in M3:
        tabla = tabla_m3 if tabla_m3 is not None else dp.leer("processed/m3_sucursales")
        contexto["tabla_m3"] = tabla[["cod_sucursal", "fecha", "cupo_max_suc"]].copy()
    if dataset in HERMANOS:
        if cruzada is None:
            otro = (datos.matriz_corregida(HERMANOS[dataset], conf)[0] if cruzada_corregida
                    else dp.matriz_arnes(HERMANOS[dataset], conf)[0])
            cruzada = otro
        contexto["cruzada"] = cruzada.reindex(index=wide.index, columns=wide.columns)
    return contexto


def atributos_contexto(contexto_asof: dict, origen: pd.Timestamp, columnas: pd.Index) -> pd.DataFrame:
    """`contexto['atributos']` al origen, con las mismas columnas que `ml.correr_ml.construir_contexto`."""
    atributos = pd.DataFrame(index=columnas)
    atributos["ciudad"] = contexto_asof["ciudad"].reindex(columnas)
    if contexto_asof["snapshots"] is not None:
        al = atributos_al(contexto_asof["snapshots"], origen, columnas)
        atributos["ciudad"] = al["ciudad"].to_numpy()
        for col in ("cupo", "disp_mf", "admon"):
            atributos[col] = al[col].to_numpy()
    elif contexto_asof["tabla_m3"] is not None:
        atributos["cupo_max_suc"] = cupo_m3_al(contexto_asof["tabla_m3"], origen, columnas).to_numpy()
    return atributos


def con_contexto_asof(funcion, history: pd.DataFrame, dates: pd.DatetimeIndex, *, contexto_asof: dict, **kw):
    """Envoltura del pronosticador: contexto armado con datos <= origen (origen = `dates[0]` - 1 dia).

    Es funcion de modulo para que `functools.partial(con_contexto_asof, funcion, contexto_asof=...)` sea picklable.
    """
    origen = pd.Timestamp(dates[0]) - pd.Timedelta(days=1)
    if history.index.max() > origen:
        raise ValueError(f"La historia pasa del origen {origen.date()}: {history.index.max().date()}")
    contexto = {"atributos": atributos_contexto(contexto_asof, origen, history.columns),
                "cruzada": contexto_asof["cruzada"]}
    return funcion(history, dates, contexto=contexto, **kw)


# --------------------------------------------------------------------------- #
# Medicion (sin repetir el ML)                                                 #
# --------------------------------------------------------------------------- #
def _distintos(a: pd.Series, b: pd.Series) -> pd.Series:
    """True donde a y b difieren (NaN = NaN cuenta como igual)."""
    a, b = a.astype(object), b.astype(object)
    ambos_nulos = a.isna() & b.isna()
    na, nb = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    if (na.notna() == a.notna()).all() and (nb.notna() == b.notna()).all():  # numericas: 3.5e9 == 3499794560
        iguales = na.astype(float).to_numpy() == nb.astype(float).to_numpy()
    else:
        iguales = (a.astype(str) == b.astype(str)).to_numpy()
    return pd.Series(~ambos_nulos.to_numpy() & (a.isna().to_numpy() | b.isna().to_numpy() | ~iguales), index=a.index)


def comparar(dataset: str, wide: pd.DataFrame, attrs: pd.DataFrame, conf: dict, origenes: list[pd.Timestamp],
             contexto_asof: dict, vigente: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Por origen: entidades del universo (dato <= origen) cuyos atributos "as of" difieren del vigente.

    Returns:
        (resumen por origen x variable, detalle entidad x origen x variable con valor vigente y as of).
    """
    from lab.evaluation import harness

    filas, detalle = [], []
    for origen in origenes:
        columnas = wide.loc[:origen].dropna(axis=1, how="all").columns
        asof = atributos_contexto(contexto_asof, origen, columnas)
        vig = vigente.reindex(columnas)
        fecha = (atributos_al(contexto_asof["snapshots"], origen, columnas)["fecha_snapshot"]
                 if contexto_asof["snapshots"] is not None else pd.Series(pd.NaT, index=columnas))
        cambia_alguna = pd.Series(False, index=columnas)
        for var in [c for c in asof.columns if c in vig.columns]:
            dif = _distintos(vig[var], asof[var])
            cambia_alguna |= dif
            filas.append({"dataset": dataset, "particion": _particion(origen, conf, harness), "origen": origen.date(),
                          "variable": var, "entidades": len(columnas), "entidades_cambian": int(dif.sum()),
                          "sin_dato_asof": int(asof[var].isna().sum()),
                          "snapshot_mas_reciente": fecha.max().date() if fecha.notna().any() else None,
                          "snapshot_mas_antiguo": fecha.min().date() if fecha.notna().any() else None})
            for ent in columnas[dif.to_numpy()]:
                detalle.append({"dataset": dataset, "origen": origen.date(), "entidad": ent, "variable": var,
                                "vigente": vig.at[ent, var], "asof": asof.at[ent, var],
                                "fecha_snapshot": fecha.get(ent)})
        filas.append({"dataset": dataset, "particion": _particion(origen, conf, harness), "origen": origen.date(),
                      "variable": "alguna", "entidades": len(columnas), "entidades_cambian": int(cambia_alguna.sum()),
                      "sin_dato_asof": int(asof.drop(columns="ciudad").isna().all(axis=1).sum())
                      if asof.shape[1] > 1 else 0,
                      "snapshot_mas_reciente": fecha.max().date() if fecha.notna().any() else None,
                      "snapshot_mas_antiguo": fecha.min().date() if fecha.notna().any() else None})
    return pd.DataFrame(filas), pd.DataFrame(detalle)


def _particion(origen, conf, harness) -> str:
    for particion in ("seleccion", "bloqueados", "chequeo_pipeline"):
        if origen in harness.list_origins(conf, particion):
            return particion
    return "otro"


def _origenes(conf) -> list[pd.Timestamp]:
    from lab.evaluation import harness

    return sorted({o for p in ("seleccion", "bloqueados", "chequeo_pipeline") for o in harness.list_origins(conf, p)})


def efecto(datasets: list[str], origenes: list[pd.Timestamp] | None = None, escribir: bool = True):
    """Cambios de atributos "as of" vs vigente en los 19 origenes (sin repetir el ML)."""
    import datos_poc as dp
    from lab.evaluation import harness
    from ml import correr_ml as cm

    from imputacion import datos

    conf = harness.load_conf()
    origenes = origenes or _origenes(conf)
    snapshots = datos.cp_snapshots()
    tabla_m3 = dp.leer("processed/m3_sucursales")
    resumenes, detalles = [], []
    for ds in datasets:
        wide, attrs = dp.matriz_arnes(ds, conf)
        vigente = cm.construir_contexto(ds, wide, attrs, conf)["atributos"]
        ctx = construir_contexto_asof(ds, wide, attrs, conf, snapshots=snapshots, tabla_m3=tabla_m3,
                                      cruzada=pd.DataFrame(index=wide.index, columns=wide.columns))
        res, det = comparar(ds, wide, attrs, conf, origenes, ctx, vigente)
        resumenes.append(res)
        detalles.append(det)
        alguna = res[res["variable"] == "alguna"]
        print(f"   {ds}: entidades-origen que cambian {int(alguna['entidades_cambian'].sum())} de "
              f"{int(alguna['entidades'].sum())}", flush=True)
    resumen = pd.concat(resumenes, ignore_index=True)
    detalle = pd.concat([d for d in detalles if len(d)], ignore_index=True) if any(len(d) for d in detalles) \
        else pd.DataFrame()
    if escribir:
        SALIDA.mkdir(parents=True, exist_ok=True)
        resumen.to_csv(SALIDA / "v4_asof_cambios.csv", index=False)
        detalle.to_csv(SALIDA / "v4_asof_detalle.csv", index=False)
    return resumen, detalle


def guarda_fuga(muestra: int = 20, origen: str = "2025-06-30", modelo: str = "ml_lgbm_v4_tw") -> pd.DataFrame:
    """Alterar los snapshots POSTERIORES al origen no cambia el pronostico; el contexto vigente si puede cambiarlo."""
    import datos_poc as dp
    from lab.evaluation import harness
    from lab.forecasting import registry
    from ml import correr_ml as cm

    from imputacion import datos

    conf = harness.load_conf()
    origen = pd.Timestamp(origen)
    wide, attrs = dp.matriz_arnes("m1", conf)
    wide = harness._stratified_sample(wide, muestra)
    attrs = attrs.loc[wide.columns]
    snapshots = datos.cp_snapshots()
    alterados = snapshots.copy()
    posteriores = alterados["fecha_snapshot"] > origen
    alterados.loc[posteriores, "cupo"] = alterados.loc[posteriores, "cupo"] * 9.0 + 1e9
    alterados.loc[posteriores, "admon"] = "ALTERADO"
    extra = alterados.drop_duplicates("cod_cajero").assign(fecha_snapshot=origen + pd.Timedelta(days=1),
                                                           cupo=1.0, admon="FUTURO")
    alterados = pd.concat([alterados, extra], ignore_index=True)
    original = cm._ORIGINALES[modelo]
    base = {"hilos": 4, "cache_variables": None}
    salida = {}
    variantes = {
        "asof": partial(con_contexto_asof, original, contexto_asof=construir_contexto_asof(
            "m1", wide, attrs, conf, snapshots=snapshots), **base),
        "asof_futuro_alterado": partial(con_contexto_asof, original, contexto_asof=construir_contexto_asof(
            "m1", wide, attrs, conf, snapshots=alterados), **base),
        "vigente_8sep": partial(original, contexto=cm.construir_contexto("m1", wide, attrs, conf), **base),
    }
    for nombre, funcion in variantes.items():
        registry.MODELS[f"_guarda_{nombre}"] = funcion
        inicio = time.perf_counter()
        salida[nombre] = harness.forecast_origin(wide, origen, f"_guarda_{nombre}", conf["horizonte_dias"])
        print(f"   {nombre}: {time.perf_counter() - inicio:.1f} s", flush=True)
        del registry.MODELS[f"_guarda_{nombre}"]
    asof, alterado, vigente = (salida[k].set_index(["entidad", "fecha"])["yhat"] for k in variantes)
    cambios = atributos_contexto(construir_contexto_asof("m1", wide, attrs, conf, snapshots=snapshots), origen,
                                 wide.loc[:origen].dropna(axis=1, how="all").columns)
    vig = cm.construir_contexto("m1", wide, attrs, conf)["atributos"].reindex(cambios.index)
    n_cambian = int(sum(_distintos(vig[c], cambios[c]) for c in ("cupo", "disp_mf", "admon")).gt(0).sum())
    tabla = pd.DataFrame([{
        "modelo": modelo, "origen": origen.date(), "cajeros": int(wide.shape[1]),
        "cajeros_con_atributos_distintos_asof_vs_vigente": n_cambian,
        "snapshots_alterados_posteriores": int(posteriores.sum()) + len(extra),
        "max_abs_dif_asof_vs_alterado": float((asof - alterado).abs().max()),
        "identico_asof_vs_alterado": bool(np.array_equal(asof.to_numpy(), alterado.to_numpy())),
        "max_abs_dif_asof_vs_vigente": float((asof - vigente).abs().max()),
        "max_rel_dif_asof_vs_vigente": float(((asof - vigente).abs() / vigente.abs().clip(lower=1.0)).max()),
    }])
    SALIDA.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(SALIDA / "v4_asof_guarda_fuga.csv", index=False)
    return tabla


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada de la linea de comandos."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--piloto", action="store_true")
    grupo.add_argument("--efecto", action="store_true")
    grupo.add_argument("--guarda-fuga", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    pd.set_option("display.width", 250)
    inicio = time.perf_counter()
    if args.piloto:
        origenes = [pd.Timestamp(o) for o in ("2025-02-28", "2025-08-31", "2026-08-16")]
        resumen, _ = efecto(["m1"], origenes, escribir=False)
        print(resumen.to_string(index=False))
    elif args.efecto:
        from imputacion.datos import DATASETS

        resumen, _ = efecto(list(DATASETS))
        print(resumen[resumen["variable"] == "alguna"].groupby("dataset")[["entidades", "entidades_cambian"]].sum())
    else:
        print(guarda_fuga().T.to_string())
    print(f"Listo en {time.perf_counter() - inicio:.0f} s")


if __name__ == "__main__":
    main()
