"""Loader y derivacion de objetivos U1/U2 (ATM).

Lee los `processed/{m1,m2}` via `daas.io.storage` (daas://), deriva los
objetivos `pagado` y `cash_in` a partir de `cdgtrn` (catalogo de
`conf/model_u1_u2.yml`), joina `cupo`/`admon` desde `interim/cp_historico`,
densifica a dias calendario (reutilizando `quality.anexo_c.mark_missing`) y
conserva `__rn07_conflicto` por cajero.

Incluye tambien el mecanismo de exclusion de metricas RN-07 por cajero
(SUP-01): `exclude_rn07_by_atm(df...)` quita del calculo de metricas
TODAS las filas de los cajeros marcados en conflicto, SIN eliminarlos del
DataFrame de pronostico, y reporta `n_excluidas` (nº de cajeros excluidos).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from daas import alx
from daas.io import storage
from daas.modules.atm_m1_m2.config import load_config
from daas.quality.anexo_c import mark_missing

logger = logging.getLogger(__name__)

#: Mapeo modelo -> dataset processed (daas://processed/<dataset>).
_DATASET_PROCESSED = {
    "m1": "m1_atm_dispensador",
    "m2": "m2_atm_multifuncional",
}

#: URI del snapshot vigente del maestro CP (cupo/admon por cajero).
_URI_CP_HISTORY = "daas://interim/cp_historico"


def _derive_target(df: pd.DataFrame, cdgtrn_catalog: list[int], name: str) -> pd.DataFrame:
    """Agrega `monto` por `(cod_cajero, fecha)` sobre un catalogo de `cdgtrn`.

    Args:
        df: Tabla processed con columnas `cod_cajero`, `fecha`, `monto`, `cdgtrn`.
        cdgtrn_catalog: Codigos de transaccion que componen el objetivo.
        name: Nombre de la columna objetivo resultante (`pagado`/`cash_in`).

    Returns:
        pd.DataFrame: Columnas `cod_cajero`, `fecha`, `<nombre>`. Si ninguna fila
        pertenece al catalogo, devuelve un DataFrame vacio con esas columnas.
    """
    sel = df[df["cdgtrn"].isin(cdgtrn_catalog)]
    aggregated = (
        sel.groupby(["cod_cajero", "fecha"], as_index=False)["monto"].sum(min_count=1).rename(columns={"monto": name})
    )
    # ALX PARTE 7 (SUP-35, interruptor `correcciones_datos`): un cajero-dia cuyo total incluye una fila del catalogo
    # con `monto` nulo (valor corrupto en la fuente, p. ej. `884s0000`) queda incompleto: pasa a faltante (NaN, nunca
    # 0), igual que `imputacion.datos.matriz_corregida` en el laboratorio.
    if alx.interruptor("correcciones_datos"):
        corrupt = sel.loc[sel["monto"].isna(), ["cod_cajero", "fecha"]].drop_duplicates()
        if len(corrupt):
            key = pd.MultiIndex.from_frame(aggregated[["cod_cajero", "fecha"]])
            bad = key.isin(pd.MultiIndex.from_frame(corrupt))
            aggregated.loc[bad, name] = float("nan")
            logger.info("SUP-35: %d cajero-dias de %s con monto corrupto pasan a faltante.", int(bad.sum()), name)
    return aggregated


def _densify(target: pd.DataFrame, name: str) -> pd.DataFrame:
    """Densifica un objetivo a dias calendario por cajero (reutiliza mark_missing).

    Usa `quality.anexo_c.mark_missing` para construir la rejilla densa
    `(cod_cajero x calendario)` del minimo al maximo observado y marcar los dias
    `missing_anexo_c` (target NULL, nunca 0). Renombra el target densificado al
    nombre del objetivo.

    Args:
        target: DataFrame largo `(cod_cajero, fecha, <nombre>)`.
        name: Nombre de la columna objetivo.

    Returns:
        pd.DataFrame: `(cod_cajero, fecha, <nombre>, missing_anexo_c,
        anexo_c_con_dato)` denso por dia calendario.
    """
    dense = mark_missing(
        target,
        entity_col="cod_cajero",
        date_col="fecha",
        target_col=name,
    )
    return dense


def load_series(model: str, conf_dir: Any | None = None) -> pd.DataFrame:
    """Carga la serie diaria densa de un modelo ATM con sus objetivos.

    Lee `processed/{m1_atm_dispensador|m2_atm_multifuncional}` via `daas://`,
    deriva `pagado = sum(monto)` sobre los `cdgtrn` del catalogo `pagado` y
    (solo M2) `cash_in = sum(monto)` sobre el catalogo `cash_in`, agregando por
    `(cod_cajero, fecha)`; joina `cupo`/`admon` del snapshot vigente
    `interim/cp_historico`; densifica a dias calendario conservando
    `__rn07_conflicto` por cajero.

    Args:
        model: `'m1'` (dispensador) o `'m2'` (multifuncional).
        conf_dir: Directorio `conf/` para la config de modelo (opcional; util en
            tests). Si es `None` se resuelve con `DAAS_CONF`/raiz del paquete.

    Returns:
        pd.DataFrame: DataFrame largo con columnas `cod_cajero`, `fecha`,
        `pagado`, (`cash_in` solo en M2), `cupo`, `admon`, `__rn07_conflicto`,
        `missing_anexo_c`.

    Raises:
        ValueError: Si `modelo` no es `'m1'`/`'m2'`, o si la tabla no trae
            NINGUN `cdgtrn` del catalogo requerido (hecho confirmado #7).
    """
    if model not in _DATASET_PROCESSED:
        raise ValueError(f"Modelo ATM desconocido: {model!r}. Validos: {sorted(_DATASET_PROCESSED)}.")

    config = load_config(conf_dir)
    catalog = config["cdgtrn"]
    paid_cdgtrn = list(catalog["pagado"])
    cash_in_cdgtrn = list(catalog["cash_in"])

    df = storage.read_table(f"daas://processed/{_DATASET_PROCESSED[model]}")
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    present = set(df["cdgtrn"].dropna().unique().tolist())

    # El objetivo `pagado` es obligatorio en M1 y M2.
    if not present.intersection(paid_cdgtrn):
        raise ValueError(
            f"La tabla processed/{_DATASET_PROCESSED[model]} no trae ningun "
            f"cdgtrn del catalogo 'pagado' {paid_cdgtrn}; no se puede derivar "
            "el objetivo (hecho confirmado #7)."
        )
    targets = ["pagado"]
    paid = _densify(_derive_target(df, paid_cdgtrn, "pagado"), "pagado")
    base = paid

    if model == "m2":
        # En M2 el objetivo `cash_in` tambien es obligatorio.
        if not present.intersection(cash_in_cdgtrn):
            raise ValueError(
                f"La tabla processed/{_DATASET_PROCESSED[model]} no trae ningun "
                f"cdgtrn del catalogo 'cash_in' {cash_in_cdgtrn}; no se puede "
                "derivar el objetivo del multifuncional (hecho confirmado #7)."
            )
        cash_in = _densify(_derive_target(df, cash_in_cdgtrn, "cash_in"), "cash_in")
        targets.append("cash_in")
        base = base.merge(
            cash_in[["cod_cajero", "fecha", "cash_in"]],
            on=["cod_cajero", "fecha"],
            how="outer",
        )
        # `missing_anexo_c` de la rejilla densa de `pagado` puede faltar en filas
        # que solo trae `cash_in`; se recompone como AND del faltante de ambos.
        base["missing_anexo_c"] = base["missing_anexo_c"].fillna(True)

    # Conflicto RN-07 por cajero (una bandera por cajero; se persistio en U0).
    conflict = (
        df.groupby("cod_cajero")["__rn07_conflicto"]
        .max()
        .fillna(False)
        .astype(bool)
        .rename("__rn07_conflicto")
        .reset_index()
    )
    base = base.merge(conflict, on="cod_cajero", how="left")
    base["__rn07_conflicto"] = base["__rn07_conflicto"].fillna(False).astype(bool)

    # Join de cupo/admon desde el snapshot vigente del maestro CP.
    cp = storage.read_table(_URI_CP_HISTORY)
    cp_cols = [c for c in ("cod_cajero", "cupo", "admon") if c in cp.columns]
    cp = cp[cp_cols].drop_duplicates(subset=["cod_cajero"])
    base = base.merge(cp, on="cod_cajero", how="left")

    columns = ["cod_cajero", "fecha", *targets, "cupo", "admon", "__rn07_conflicto", "missing_anexo_c"]
    for col in ("cupo", "admon"):
        if col not in base.columns:
            base[col] = pd.NA
    base = base[columns].sort_values(["cod_cajero", "fecha"]).reset_index(drop=True)
    return base


def actual_with_rn08_reading(backtest: pd.DataFrame, data: pd.DataFrame, target: str = "pagado") -> pd.DataFrame:
    """Rellena con 0 el real del backtest segun RN-08 (solo para medir; no toca entrenamiento ni carga).

    Una fila con `y` NaN pasa a 0 si la red opero esa fecha (algun cajero con `objetivo`), no es de la ventana
    Anexo C y la fecha es >= al primer registro del cajero (antes no cuenta: RN-07). El resto queda NaN.

    Args:
        backtest: `cod_cajero`, `fecha`, `y`, `yhat` (y otras columnas, que se conservan).
        data: Serie de `load_series` (`cod_cajero`, `fecha`, `objetivo`, `missing_anexo_c`).
        target: Columna objetivo que define "la red opera" y el primer registro.

    Returns:
        pd.DataFrame: Copia de `backtest` con `y` rellenado.
    """
    out = backtest.copy()
    dates = pd.to_datetime(data["fecha"])
    with_data = data[target].notna()
    network = set(dates[with_data].unique())
    first = dates[with_data].groupby(data.loc[with_data, "cod_cajero"]).min()
    anexo_c = set(dates[data["missing_anexo_c"].astype(bool)].unique())
    f = pd.to_datetime(out["fecha"])
    start = out["cod_cajero"].map(first)
    fill = out["y"].isna() & f.isin(network) & ~f.isin(anexo_c) & start.notna() & (f >= start)
    out.loc[fill, "y"] = 0.0
    return out


def exclude_rn07_by_atm(
    df: pd.DataFrame,
    conflict_col: str = "__rn07_conflicto",
    atm_col: str = "cod_cajero",
    active: bool = True,
) -> tuple[pd.DataFrame, int]:
    """Excluye del calculo de metricas los cajeros en conflicto RN-07 (SUP-01).

    Dado un DataFrame (tipicamente el de backtest con `(cod_cajero, fecha, y,
    yhat, __rn07_conflicto)`), elimina TODAS las filas de los cajeros con
    `__rn07_conflicto == True` para que no entren a WAPE/MAE/Bias, y devuelve el
    numero de cajeros distintos excluidos. Las filas NO se tocan en el DataFrame
    de pronostico/salida (ese sigue reportando a esos cajeros); esta funcion
    opera solo sobre la copia que alimenta las metricas.

    Args:
        df: DataFrame con `cajero_col` y `conflicto_col`.
        conflict_col: Columna booleana de conflicto RN-07 por fila/cajero.
        atm_col: Columna identificadora del cajero.
        active: Si es `False` (metricas.excluir_rn07_por_cajero=false) no se
            excluye nada; devuelve `(df, 0)`.

    Returns:
        tuple[pd.DataFrame, int]: `(df_para_metricas, n_excluidas)` donde
        `n_excluidas` es el nº de cajeros excluidos (0 si no hay conflicto o si
        `activo=False`).

    Raises:
        KeyError: Si faltan `cajero_col` o `conflicto_col` en `df`.
    """
    missing = {atm_col, conflict_col} - set(df.columns)
    if missing:
        raise KeyError(f"excluir_rn07_por_cajero: faltan columnas {sorted(missing)}.")
    if not active:
        return df.reset_index(drop=True), 0

    in_conflict = df[conflict_col].fillna(False).astype(bool)
    atms_excluded = df.loc[in_conflict, atm_col].dropna().unique()
    n_excluded = int(len(atms_excluded))
    filtered = df.loc[~df[atm_col].isin(atms_excluded)].reset_index(drop=True)
    return filtered, n_excluded
