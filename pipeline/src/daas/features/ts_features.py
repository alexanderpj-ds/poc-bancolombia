"""Features de serie temporal del subpaquete `features`.

Regla de negocio: agrega lags (1/7/14/28) y rolling (7/28) por entidad, mas
features de estacionalidad. Los rolling EXCLUYEN los dias con
`missing_anexo_c=True` (no son demanda cero) y toda la ventana respeta el
corte de entrenamiento (no se filtra informacion futura).

Contrato de reutilizacion: `add_ts_features(df, entity_col, target)` es
una funcion pura que recibe una serie diaria densa por entidad (idealmente la
salida de `quality.anexo_c.mark_missing`, con `missing_anexo_c`) y devuelve el
mismo DataFrame con columnas de features anadidas. No lee ni escribe; cada
modelo la invoca con su entidad y objetivo.

Decisiones:
  - Los lags se calculan sobre la serie ordenada por fecha dentro de cada
    entidad. Como la serie es densa (una fila por entidad-dia), `shift(k)`
    equivale al valor de hace `k` dias naturales.
  - Los rolling (media y desv) se calculan **ignorando** los dias
    `missing_anexo_c` (sus valores NULL no entran al promedio): se usa
    `min_periods=1` sobre la serie con los faltantes como NaN para que la media
    movil no los cuente como cero.
  - No hay fuga > corte: los lags/rolling solo miran el pasado (`shift`,
    ventanas con `closed` por defecto que excluyen el futuro). Opcionalmente se
    puede pasar `corte` para anular (NaN) cualquier feature calculado a partir
    de fechas posteriores al corte, dejando el holdout sin features de
    entrenamiento.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd

#: Lags del objetivo (dia, semana, quincena, 4 semanas).
LAGS = (1, 7, 14, 28)
#: Ventanas de rolling (media/desv movil).
ROLLINGS = (7, 28)


def _to_date(value: object) -> _dt.date:
    """Coerciona un valor (str ISO o date) a `datetime.date`."""
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value))


def add_ts_features(
    df: pd.DataFrame,
    entity_col: str,
    target: str,
    date_col: str = "fecha",
    cutoff: _dt.date | str | None = None,
) -> pd.DataFrame:
    """Agrega features de serie temporal a `df` por `entity_col` sobre `target`.

    Lags 1/7/14/28, rolling 7/28 excluyendo `missing_anexo_c`, estacionalidad
    (indices dia-de-semana / dia-del-mes y flags de quincena/fin de mes) y
    respeto del corte de entrenamiento.

    Args:
        df: Serie diaria densa por entidad. Debe traer `entity_col`, `date_col`
            y `target`; si trae `missing_anexo_c` (bool) se usa para excluir esos
            dias de los rolling.
        entity_col: Columna de entidad (p.ej. `cod_cajero`, `fondo_id`).
        target: Columna objetivo sobre la que se calculan lags/rolling.
        date_col: Columna de fecha (`datetime.date`). Por defecto `fecha`.
        cutoff: Si se indica, los features calculados a partir de fechas
            posteriores al corte se dejan NaN (el holdout no recibe features de
            entrenamiento).

    Returns:
        pd.DataFrame: Copia de `df` ordenada por `(entity_col, date_col)` con las
        columnas de features anadidas:
        `lag_{1,7,14,28}`, `roll_mean_{7,28}`, `roll_std_{7,28}`,
        `idx_dia_semana`, `idx_dia_mes`, `es_quincena`, `es_fin_de_mes`.
    """
    columns_min = {entity_col, date_col, target}
    missing = columns_min - set(df.columns)
    if missing:
        raise KeyError(f"add_ts_features: faltan columnas {sorted(missing)} en el DataFrame.")

    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col]).dt.date
    out = out.sort_values([entity_col, date_col]).reset_index(drop=True)

    # Serie objetivo con los dias Anexo C como NaN (no cuentan en rolling).
    target_label = pd.to_numeric(out[target], errors="coerce")
    if "missing_anexo_c" in out.columns:
        target_label = target_label.mask(out["missing_anexo_c"].fillna(False).astype(bool))

    group = target_label.groupby(out[entity_col], sort=False, group_keys=False)

    # Lags (miran solo el pasado; shift excluye el futuro -> sin fuga).
    for k in LAGS:
        out[f"lag_{k}"] = group.shift(k)

    # Rolling sobre el pasado (shift(1) para no incluir el dia actual) con los
    # dias missing_anexo_c ya como NaN. CRITICO: el rolling se reagrupa POR
    # ENTIDAD para que la ventana no cruce la frontera entre entidades (si no,
    # las primeras w-1 filas de cada entidad promediarian la cola de la
    # entidad anterior -> fuga de demanda entre entidades). `shift(1)` tambien
    # agrupado para no mezclar el ultimo dia de una entidad con el primero de
    # la siguiente.
    base = group.shift(1)
    base_by_entity = base.groupby(out[entity_col], sort=False, group_keys=False)
    for w in ROLLINGS:
        out[f"roll_mean_{w}"] = base_by_entity.rolling(window=w, min_periods=1).mean().reset_index(level=0, drop=True)
        out[f"roll_std_{w}"] = base_by_entity.rolling(window=w, min_periods=2).std().reset_index(level=0, drop=True)

    # Estacionalidad: indices de dia-de-semana y dia-del-mes.
    ts = pd.to_datetime(out[date_col])
    out["idx_dia_semana"] = ts.dt.dayofweek.astype("int64")
    out["idx_dia_mes"] = ts.dt.day.astype("int64")
    out["es_quincena"] = ts.dt.day == 15
    out["es_fin_de_mes"] = ts.dt.is_month_end.to_numpy()

    # Sin fuga > corte: anula (NaN) los features de filas posteriores al corte.
    if cutoff is not None:
        cutoff_date = _to_date(cutoff)
        post = out[date_col].map(lambda d: d > cutoff_date)
        cols_feat = (
            [f"lag_{k}" for k in LAGS] + [f"roll_mean_{w}" for w in ROLLINGS] + [f"roll_std_{w}" for w in ROLLINGS]
        )
        out.loc[post, cols_feat] = pd.NA

    return out.reset_index(drop=True)
