"""Calendario de Colombia del subpaquete `features`.

Construye `dim_calendario` para Colombia. Regla de negocio: marca
`es_festivo_co` via `holidays[CO]` (con overrides operativos de
`conf/calendario_co.yml`), `es_habil`, `es_quincena`, `es_fin_de_mes`,
`bloque_evaluacion` (ventana 2026-09-01..2026-09-15) y propaga
`missing_anexo_c` de la ventana del Anexo C.

Columnas:
  `fecha` (date, PK), `anio`, `mes`, `dia`, `dia_semana`, `semana_iso` (int),
  `es_festivo_co`, `es_habil`, `es_quincena`, `es_fin_de_mes`,
  `es_vispera_festivo`, `es_post_festivo` (bool),
  `bloque_evaluacion` (category: `bloque1`/`bloque2`/`<NA>`),
  `missing_anexo_c` (bool).

Los festivos CO se calculan con la libreria `holidays` (RN-04 / ley Emiliani,
que ya aplica el traslado al lunes); `conf/calendario_co.yml` permite anadir o
sobre-escribir dias por decision operativa (`overrides_operativos`).
`missing_anexo_c` marca las 27 fechas del Anexo C (desde `conf/dq_rules.yml`).
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

import holidays
import pandas as pd
import yaml

from daas.quality.anexo_c import anexo_c_window

#: Pais ISO para la libreria `holidays`.
_PAIS = "CO"


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``)."""
    return Path(__file__).resolve().parents[3]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o fallback)."""
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def _load_calendar_conf() -> dict:
    """Carga `conf/calendario_co.yml` (overrides operativos).

    Returns:
        dict: Contenido del YAML (``{}`` si no existe o esta vacio).
    """
    file_path = _conf_dir() / "calendario_co.yml"
    if not file_path.is_file():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _evaluation_window() -> tuple[_dt.date, _dt.date]:
    """Lee la ventana de evaluacion (1-15 sep) de `conf/dq_rules.yml`.

    Returns:
        tuple[date, date]: `(inicio, fin)`; default 2026-09-01..2026-09-15.
    """
    file_path = _conf_dir() / "dq_rules.yml"
    window_start, fin = _dt.date(2026, 9, 1), _dt.date(2026, 9, 15)
    if file_path.is_file():
        with file_path.open("r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        window = cfg.get("ventana_evaluacion", {}) or {}
        if window.get("inicio"):
            window_start = _to_date(window["inicio"])
        if window.get("fin"):
            fin = _to_date(window["fin"])
    return window_start, fin


def _to_date(value: object) -> _dt.date:
    """Coerciona un valor (str ISO o date) a `datetime.date`."""
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value))


def _co_holidays(years: list[int]) -> dict[_dt.date, bool]:
    """Construye el conjunto de festivos CO con `holidays` + overrides.

    Args:
        years: Anios cubiertos por el calendario.

    Returns:
        dict[date, bool]: Mapa de fecha -> operativo. ``True`` significa
        "forzado festivo" (no habil) por un override; las fechas que no estan en
        el mapa se consideran por `holidays`. Para simplificar el consumo se
        devuelve el conjunto efectivo de festivos como set via la clave.
    """
    base = holidays.country_holidays(_PAIS, years=years)
    holiday_dates: set[_dt.date] = set(base.keys())

    conf = _load_calendar_conf()
    # Overrides operativos: fecha -> {operativo: bool, nota: str}. Si
    # operativo=False se fuerza festivo; si operativo=True se quita de festivos.
    overrides = conf.get("overrides_operativos", {}) or {}
    for date_raw, meta in overrides.items():
        date = _to_date(date_raw)
        operational = bool((meta or {}).get("operativo", False))
        if operational:
            holiday_dates.discard(date)
        else:
            holiday_dates.add(date)
    return {f: True for f in holiday_dates}


def build_calendar(start: str, end: str) -> pd.DataFrame:
    """Construye `dim_calendario` entre `start` y `end` (fechas ISO).

    Args:
        start: Fecha inicial ISO (``YYYY-MM-DD``), inclusive.
        end: Fecha final ISO (``YYYY-MM-DD``), inclusive.

    Returns:
        pd.DataFrame: Una fila por fecha con las columnas del calendario:
        (`es_festivo_co` via holidays + overrides, `es_habil`, `es_quincena`,
        `es_fin_de_mes`, `es_vispera_festivo`, `es_post_festivo`,
        `bloque_evaluacion`, `missing_anexo_c`).
    """
    date_start = _to_date(start)
    date_fin = _to_date(end)
    if date_fin < date_start:
        raise ValueError(f"Rango invalido: {start} > {end}.")

    value_range = pd.date_range(date_start, date_fin, freq="D")
    dates = [d.date() for d in value_range]
    years = sorted({d.year for d in dates})
    holiday_dates = _co_holidays(years)
    is_holiday = pd.Series([f in holiday_dates for f in dates])

    df = pd.DataFrame({"fecha": dates})
    ts = pd.to_datetime(df["fecha"])
    df["anio"] = ts.dt.year.astype("int64")
    df["mes"] = ts.dt.month.astype("int64")
    df["dia"] = ts.dt.day.astype("int64")
    df["dia_semana"] = ts.dt.dayofweek.astype("int64")  # 0=lunes
    df["semana_iso"] = ts.dt.isocalendar().week.astype("int64")

    df["es_festivo_co"] = is_holiday.to_numpy()
    is_weekend = df["dia_semana"] >= 5
    df["es_habil"] = (~is_weekend) & (~df["es_festivo_co"])
    df["es_quincena"] = df["dia"] == 15
    df["es_fin_de_mes"] = ts.dt.is_month_end.to_numpy()

    # Vispera / post festivo (dia habil adyacente a un festivo).
    holiday_prev = df["es_festivo_co"].shift(-1, fill_value=False)
    holiday_sig = df["es_festivo_co"].shift(1, fill_value=False)
    df["es_vispera_festivo"] = holiday_prev & (~df["es_festivo_co"])
    df["es_post_festivo"] = holiday_sig & (~df["es_festivo_co"])

    # Bloque de evaluacion (1-7 sep = bloque1; 8-15 sep = bloque2; resto NA).
    start_eval, fin_eval = _evaluation_window()
    half = start_eval + _dt.timedelta(days=6)  # bloque1 = 7 dias
    block = []
    for f in dates:
        if start_eval <= f <= half:
            block.append("bloque1")
        elif half < f <= fin_eval:
            block.append("bloque2")
        else:
            block.append(pd.NA)
    df["bloque_evaluacion"] = pd.Series(block, dtype="category")

    # Ventana Anexo C (27 dias): marca missing_anexo_c en el calendario.
    window = set(anexo_c_window())
    df["missing_anexo_c"] = df["fecha"].isin(window)

    return df.reset_index(drop=True)
