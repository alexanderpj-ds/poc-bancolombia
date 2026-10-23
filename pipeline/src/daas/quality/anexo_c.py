"""Ventana Anexo C del subpaquete `quality`.

Densifica el calendario diario por entidad y marca los 27 dias de la ventana
del Anexo C como `missing_anexo_c=True` con el target en NULL (NUNCA 0). Regla
de negocio: los dias sin operacion del Anexo C son datos faltantes, no demanda
cero; imputarlos con 0 sesgaria el pronostico.

La ventana (27 dias de 2026) se lee de `conf/dq_rules.yml::anexo_c_window`;
si una fuente trae dato real en esas fechas, se **conserva** y se registra la
excepcion. Las fechas son: 6-17 abr; {10,16-18,20,22-25,30} jun;
6-10 jul 2026.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

import pandas as pd
import yaml

#: Clave de la ventana en `conf/dq_rules.yml`.
_WINDOW_KEY = "ventana_anexo_c"


def _package_root() -> Path:
    """Devuelve la raiz del proyecto (donde vive ``conf/``)."""
    return Path(__file__).resolve().parents[3]


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o fallback)."""
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return _package_root() / "conf"


def anexo_c_window() -> list[_dt.date]:
    """Devuelve las 27 fechas de la ventana Anexo C desde `conf/dq_rules.yml`.

    Returns:
        list[datetime.date]: Fechas de la ventana (orden ascendente).
    """
    file_path = _conf_dir() / "dq_rules.yml"
    with file_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    dates = cfg.get(_WINDOW_KEY, [])
    out: list[_dt.date] = []
    for f in dates:
        if isinstance(f, _dt.date):
            out.append(f)
        else:
            out.append(_dt.date.fromisoformat(str(f)))
    return sorted(out)


def training_cutoff() -> _dt.date:
    """Corte de entrenamiento (`training_cutoff` de `conf/dq_rules.yml`)."""
    with (_conf_dir() / "dq_rules.yml").open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    value = cfg["corte_entrenamiento"]
    return value if isinstance(value, _dt.date) else _dt.date.fromisoformat(str(value))


def mark_missing(
    df: pd.DataFrame,
    entity_col: str,
    date_col: str,
    target_col: str = "valor",
) -> pd.DataFrame:
    """Densifica el calendario por entidad y marca la ventana Anexo C.

    Construye el producto cartesiano entidad x calendario denso (del minimo al
    maximo de `date_col`), hace left-join del dato observado y marca
    `missing_anexo_c=True` en los 27 dias de la ventana. En esos dias el target
    se deja NULL **salvo** que exista dato observado (se conserva y se marca la
    excepcion `anexo_c_con_dato=True`).

    Args:
        df: DataFrame con al menos `entity_col`, `date_col` y `target_col`.
        entity_col: Columna de entidad (p.ej. `cod_cajero`, `fondo_id`).
        date_col: Columna de fecha (`datetime.date`).
        target_col: Columna objetivo a dejar NULL en los dias faltantes.

    Returns:
        pd.DataFrame: Calendario denso por entidad con columnas adicionales
        `missing_anexo_c` (bool) y `anexo_c_con_dato` (bool).
    """
    if df.empty:
        out = df.copy()
        out["missing_anexo_c"] = pd.Series(dtype="bool")
        out["anexo_c_con_dato"] = pd.Series(dtype="bool")
        return out

    work = df.copy()
    work[date_col] = pd.to_datetime(work[date_col]).dt.date

    date_min = min(work[date_col])
    date_max = max(work[date_col])
    calendar = [d.date() for d in pd.date_range(date_min, date_max, freq="D")]
    entities = work[entity_col].dropna().unique().tolist()

    dense = pd.MultiIndex.from_product([entities, calendar], names=[entity_col, date_col]).to_frame(index=False)

    # Left-join del dato observado (agregado por entidad+fecha si hay varias filas).
    observed = work.groupby([entity_col, date_col], as_index=False)[target_col].sum(min_count=1)
    out = dense.merge(observed, on=[entity_col, date_col], how="left")

    window = set(anexo_c_window())
    in_window = out[date_col].isin(window)
    has_data = out[target_col].notna()

    out["missing_anexo_c"] = in_window & ~has_data
    out["anexo_c_con_dato"] = in_window & has_data
    # En los dias de ventana sin dato, el target queda NULL (ya lo esta por el join).
    return out.reset_index(drop=True)
