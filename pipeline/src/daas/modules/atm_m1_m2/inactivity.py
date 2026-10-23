"""Equipos inactivos o desmontados: pronostico cero (RN-07 y RN-08 del Anexo B).

RN-07: "los equipos desmontados, retirados o inactivos se reportaran con valor pronosticado cero a
partir de la fecha de su cambio de estado". El cambio de estado sale del maestro de desinstalados
(`inactividad.desinstalados` en `conf/model_u1_u2.yml`): un equipo cuya `fecha_desinstalacion` es <= el corte
y que NO tiene dato posterior a esa fecha esta desmontado. Si tiene dato posterior, el codigo fue
reutilizado (RN-06) y se pronostica normal.

RN-08 (complemento): la ausencia de registros mientras el resto de la red opera es inactividad real. Una
entidad sin dato en los ultimos `sin_dato_reciente_dias` dias de operacion de la red se trata igual
(el umbral es el mismo de `lab/conf/evaluacion.yml -> soporte.sin_dato_reciente_dias`; `aplicar` lo apaga).

Todo es dato de configuracion: ningun codigo de equipo aparece aqui.
"""

from __future__ import annotations

import pandas as pd

COLUMNS = ["cod_cajero", "regla", "desde"]
SILENT_COLUMNS = ["modelo", "cod_cajero", "ultimo_dato", "dias_red_sin_dato", "tratamiento"]


def inactive_entities(
    data: pd.DataFrame,
    uninstalled: pd.DataFrame,
    params: dict,
    targets: list[str],
) -> pd.DataFrame:
    """Devuelve las entidades con pronostico cero: `cod_cajero`, `regla` (`RN-07`/`RN-08`) y `desde`.

    Args:
        data: Serie larga de `load_series` (`cod_cajero`, `fecha`, objetivos).
        uninstalled: Maestro de desinstalados (`cod_cajero` y la columna de fecha de `params`).
        params: Bloque `inactividad` de la configuracion.
        targets: Columnas objetivo que cuentan como "dato" (pagado y, en M2, cash_in).

    Returns:
        pd.DataFrame: Una fila por entidad inactiva (RN-07 tiene prioridad sobre RN-08).
    """
    dates = pd.to_datetime(data["fecha"])
    with_data = data[targets].notna().any(axis=1)
    cutoff = dates[with_data].max()
    if pd.isna(cutoff):
        return pd.DataFrame(columns=COLUMNS)
    last = dates[with_data].groupby(data.loc[with_data, "cod_cajero"]).max()

    rows: list[dict] = []
    col_date = params["col_fecha"]
    if uninstalled is not None and not uninstalled.empty and col_date in uninstalled.columns:
        low = pd.to_datetime(uninstalled[col_date], errors="coerce")
        low = low.groupby(uninstalled["cod_cajero"]).max()  # el cambio de estado mas reciente
        low = low[low <= cutoff]
        for code, f in low.items():
            u = last.get(code)
            if u is not None and u <= f:  # sin dato posterior: sigue desmontado (si hay, RN-06)
                rows.append({"cod_cajero": code, "regla": "RN-07", "desde": f.date()})

    rn08 = params.get("rn08", {})
    if rn08.get("aplicar", False):
        n = int(rn08["sin_dato_reciente_dias"])
        days_network = pd.DatetimeIndex(sorted(dates[with_data].unique()))  # dias en que la red opero
        already = {f["cod_cajero"] for f in rows}
        for code, u in last.items():
            if code in already:
                continue
            silence = int((days_network > u).sum())
            if silence >= n:
                rows.append({"cod_cajero": code, "regla": "RN-08", "desde": (u + pd.Timedelta(days=1)).date()})
    return pd.DataFrame(rows, columns=COLUMNS)


def silent_entities(
    model: str,
    data: pd.DataFrame,
    inactive: pd.DataFrame,
    params: dict,
    targets: list[str],
) -> pd.DataFrame:
    """Lista informativa de entidades con `sin_dato_reciente_dias` o mas dias de red sin dato al corte.

    Estan o no desinstaladas; no cambia ningun pronostico (RN-05 prohibe inferir estados: el silencio no prueba
    retiro). Se entrega para la hoja 04 y las preguntas al banco. El texto de `tratamiento` sale de
    `inactividad.rn08.textos` de la configuracion.

    Args:
        model: `m1`/`m2` (columna `modelo` de la salida).
        data: Serie larga de `load_series`.
        inactive: Salida de `inactive_entities` (para decir como se trato cada una).
        params: Bloque `inactividad` de la configuracion.
        targets: Columnas objetivo que cuentan como "dato".

    Returns:
        pd.DataFrame: `modelo`, `cod_cajero`, `ultimo_dato` (fecha), `dias_red_sin_dato` (int), `tratamiento`.
    """
    rn08 = params["rn08"]
    n = int(rn08["sin_dato_reciente_dias"])
    texts = rn08["textos"]
    dates = pd.to_datetime(data["fecha"])
    with_data = data[targets].notna().any(axis=1)
    if not with_data.any():
        return pd.DataFrame(columns=SILENT_COLUMNS)
    last = dates[with_data].groupby(data.loc[with_data, "cod_cajero"]).max()
    days_network = pd.DatetimeIndex(sorted(dates[with_data].unique()))
    handling = inactive.set_index("cod_cajero")["regla"].to_dict() if len(inactive) else {}
    rows = []
    for code, u in last.items():
        silence = int((days_network > u).sum())
        if silence < n:
            continue
        rule = handling.get(code)
        treatment = texts["cero"][rule] if rule else texts["normal"]
        rows.append(
            {
                "modelo": model,
                "cod_cajero": code,
                "ultimo_dato": u.date(),
                "dias_red_sin_dato": silence,
                "tratamiento": treatment,
            }
        )
    return (
        pd.DataFrame(rows, columns=SILENT_COLUMNS)
        .sort_values(["dias_red_sin_dato", "cod_cajero"], ascending=[False, True])
        .reset_index(drop=True)
    )


def apply_zero(forecast: pd.DataFrame) -> pd.DataFrame:
    """Pronostico y banda en cero en todo el horizonte (conserva fechas y columnas)."""
    out = forecast.copy()
    for c in ("yhat", "band_low", "band_high"):
        if c in out.columns:
            out[c] = 0.0
    return out
