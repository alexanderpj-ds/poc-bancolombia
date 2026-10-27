"""Capa de datos de M6 Fondos de efectivo (U6).

Prepara los insumos del balance prescriptivo de bovedas a partir de la SSOT
curada por modelo (`processed/m6_fondos`) y de los pronosticos ya publicados de
M1-M5 (`output/api/predicciones`). Resuelve, sin tocar el resto del pipeline:

- el saldo inicial por fondo+denominacion al corte (RN-69 / SUP-07);
- la mezcla historica de denominaciones por fondo (SUP-09);
- el efecto neto diario de M1-M5 sobre cada fondo (RN-70 / D-FLUJO-1 / SUP-12),
  RUTEANDO el id de cada prediccion a su `fondo_id` segun el `modelo` (m4/m5 ya
  traen el fondo; m1/m2 via `cp_historico`; m3 via `oficinas`);
- la distribucion del efecto por denominacion segun la mezcla;
- la matriz de operaciones habilitadas por fondo (SUP-08 / SUP-13 / D-OPS-1).

El mapeo id -> fondo lo posee ESTA capa (no el balance ni el recomendador, que
ya trabajan en el espacio `fondo_id`). Todo el I/O pasa por `daas.io.storage`.
NUNCA se inventa un dato: donde falta, supuesto documentado + ``logging.warning``
parametrizable en `conf/model_u6.yml`.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

from daas import alx
from daas.fondo.build_fund import build_fund_id
from daas.io import storage
from daas.modules.funds_m6 import correccion_disponibles

logger = logging.getLogger(__name__)

#: Prefijo del esquema abstracto de storage.
_DAAS = "daas://"

#: Maestros vigentes para el ruteo id -> fondo de M1/M2 (ATM) y M3 (sucursal).
_URI_CP_HISTORY = "daas://interim/cp_historico"
_URI_OFFICES = "daas://interim/oficinas"


def _uri(source: str) -> str:
    """Normaliza una ruta de config a URI abstracta ``daas://``.

    Args:
        source: Ruta ``<capa>/<dataset>`` o ya ``daas://...``.

    Returns:
        str: URI abstracta ``daas://<capa>/<dataset>``.
    """
    source = str(source).strip()
    if source.startswith(_DAAS):
        return source
    return _DAAS + source.lstrip("/")


def _to_date_or_none(series: pd.Series) -> pd.Series:
    """Convierte una columna a ``datetime.date`` (coerciona invalidos a NaT).

    Args:
        series: Columna de fechas en cualquier representacion.

    Returns:
        pd.Series: Columna de objetos ``datetime.date`` (o NaT donde falte).
    """
    return pd.to_datetime(series, errors="coerce").dt.date


def load_available_cash(config: dict) -> pd.DataFrame:
    """Carga el curado de disponibles por fondo+denominacion (RN-69).

    Lee `processed/m6_fondos` (o `config['fuentes']['disponibles']`) via
    ``daas://``, normaliza la fecha a ``datetime.date`` y restringe el universo a
    los 6 fondos de `dim_fondo` (invariante: filas con `fondo_id` fuera de
    `dim_fondo` se descartan a cuarentena con WARNING).

    Args:
        config: Configuracion de `conf/model_u6.yml` ya cargada.

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `fecha`, `denominacion`, `valor` (y, con la correccion SUP-29 de
        ALX activa, `fuera_ventana_minmax`).
    """
    source = config.get("fuentes", {}).get("disponibles", "processed/m6_fondos")
    df = storage.read_table(_uri(source)).copy()
    df["fecha"] = _to_date_or_none(df["fecha"])
    df["denominacion"] = pd.to_numeric(df["denominacion"], errors="coerce").astype("Int64")
    # ALX: marca del blanco de la fuente antes de rellenar (la usa SUP-29; se descarta al proyectar columnas).
    df[correccion_disponibles.COL_BLANCO] = pd.to_numeric(df["valor"], errors="coerce").isna()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)

    # Invariante del universo (6 fondos de dim_fondo); cuarentena de lo demas.
    dim = storage.read_table("daas://processed/_dim/dim_fondo")
    valid_ids = set(dim["fondo_id"].astype(str).tolist())
    before = len(df)
    df = df[df["fondo_id"].astype(str).isin(valid_ids)].copy()
    discarded = before - len(df)
    if discarded:
        logger.warning(
            "cargar_disponibles: %d filas con fondo_id fuera de dim_fondo "
            "descartadas a cuarentena (invariante del universo M6).",
            discarded,
        )

    # SUP-29 (ALX, D3): excluir `TOTAL` y pasar a pesos la TRANSPORTADORA_001 en billetes, detectado por datos.
    # Va antes de proyectar columnas porque necesita `calidad`. Clave ausente o `aplicar: false` = Santiago.
    correction = config.get("correccion_disponibles") or {}
    # ALX PARTE 7: ademas exige el interruptor `correccion_m6` de conf/alx.yml (apagado = Santiago).
    if correction.get("aplicar", False) and alx.interruptor("correccion_m6"):
        df, _evidence = correccion_disponibles.corregir_disponibles(df, correction)

    columns = ["fondo_id", "fecha", "denominacion", "valor"]
    if correccion_disponibles.COL_FUERA in df.columns:  # ALX: marca de dias fuera de la ventana de SUP-10
        columns.append(correccion_disponibles.COL_FUERA)
    return df[columns].reset_index(drop=True)


def _window(df: pd.DataFrame, cutoff: _dt.date, window_days: int) -> pd.DataFrame:
    """Acota un DataFrame a la ventana `(corte - ventana_dias, corte]`.

    Args:
        df: DataFrame con columna `fecha` (``datetime.date``).
        cutoff: Fecha de corte (inclusive).
        window_days: Tamano de la ventana en dias (0 = todo el historico <= corte).

    Returns:
        pd.DataFrame: Subconjunto dentro de la ventana que termina en el corte.
    """
    base = df[df["fecha"] <= cutoff]
    if window_days and window_days > 0:
        since = cutoff - _dt.timedelta(days=int(window_days) - 1)
        base = base[base["fecha"] >= since]
    return base


def initial_balance_by_fund_denomination(
    available_cash: pd.DataFrame,
    cutoff: _dt.date,
    denominations: list[int],
    config: dict,
) -> pd.DataFrame:
    """Saldo inicial por fondo+denominacion al corte (RN-69 / SUP-07).

    Para cada combinacion (fondo_id, denominacion) en alcance toma el ULTIMO dia
    con `fecha <= corte` y SUMA el `valor` de todas las calidades/familias de ese
    dia. Si una combinacion no tiene registro <= corte, el saldo inicial es 0.0
    (parametrizable `saldo_inicial.faltante_a_cero`) + ``logging.warning``
    (SUP-07; NUNCA se inventa un saldo).

    Args:
        available_cash: Salida de `load_available_cash`.
        cutoff: Fecha de corte del saldo inicial.
        denominations: Denominaciones en alcance.
        config: Configuracion de M6 (usa `saldo_inicial.faltante_a_cero`).

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `denominacion`, `saldo_inicial`,
        `fecha_saldo_inicial`, `saldo_inicial_faltante` (bool). Una fila por
        (fondo x denominacion en alcance), con las 6 denominaciones por fondo.
    """
    missing_to_zero = bool(config.get("saldo_inicial", {}).get("faltante_a_cero", True))
    base = available_cash[available_cash["fecha"] <= cutoff].copy()
    # Saldo diario = suma de valor sobre calidad x familia por (fondo, den, dia).
    daily = base.groupby(["fondo_id", "denominacion", "fecha"], as_index=False)["valor"].sum()

    funds = sorted(available_cash["fondo_id"].dropna().astype(str).unique().tolist())
    rows: list[dict[str, Any]] = []
    for fund in funds:
        for denom in denominations:
            sub = daily[(daily["fondo_id"].astype(str) == fund) & (daily["denominacion"] == denom)].sort_values("fecha")
            if not sub.empty:
                last = sub.iloc[-1]
                rows.append(
                    {
                        "fondo_id": fund,
                        "denominacion": int(denom),
                        "saldo_inicial": float(last["valor"]),
                        "fecha_saldo_inicial": last["fecha"],
                        "saldo_inicial_faltante": False,
                    }
                )
            else:
                if missing_to_zero:
                    logger.warning(
                        "saldo_inicial: fondo %s denominacion %s sin registro <= "
                        "%s; saldo_inicial=0.0 (SUP-07, no se inventa saldo).",
                        fund,
                        denom,
                        cutoff.isoformat(),
                    )
                rows.append(
                    {
                        "fondo_id": fund,
                        "denominacion": int(denom),
                        "saldo_inicial": 0.0,
                        "fecha_saldo_inicial": None,
                        "saldo_inicial_faltante": True,
                    }
                )
    columns = [
        "fondo_id",
        "denominacion",
        "saldo_inicial",
        "fecha_saldo_inicial",
        "saldo_inicial_faltante",
    ]
    return pd.DataFrame(rows, columns=columns)


def denomination_mix_by_fund(available_cash: pd.DataFrame, cutoff: _dt.date, config: dict) -> pd.DataFrame:
    """Mezcla historica de denominaciones por fondo (SUP-09).

    Para cada fondo calcula la fraccion del `valor` historico por denominacion
    sobre el total del fondo, en una ventana parametrizable que termina en el
    corte (`mezcla_denominacion.ventana_dias`). Si un fondo no tiene historico de
    mezcla (todo 0 en la ventana), se cae al reparto uniforme (1/n sobre las
    denominaciones en alcance) + ``logging.warning`` (SUP-09, no se inventa
    mezcla). Los pesos de cada fondo suman 1.0.

    Args:
        available_cash: Salida de `load_available_cash`.
        cutoff: Fecha de corte de la ventana.
        config: Configuracion de M6 (usa `mezcla_denominacion`, `denominaciones`).

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `denominacion`, `peso` (los pesos de
        un fondo suman 1.0).
    """
    cfg = config.get("mezcla_denominacion", {})
    window_days = int(cfg.get("ventana_dias", 180))
    denominations = [int(d) for d in config.get("denominaciones", [])]
    n = len(denominations)

    base = _window(available_cash, cutoff, window_days)
    agg = base.groupby(["fondo_id", "denominacion"], as_index=False)["valor"].sum()

    funds = sorted(available_cash["fondo_id"].dropna().astype(str).unique().tolist())
    rows: list[dict[str, Any]] = []
    for fund in funds:
        sub = agg[agg["fondo_id"].astype(str) == fund]
        total = float(sub["valor"].sum()) if not sub.empty else 0.0
        if total <= 0.0:
            logger.warning(
                "mezcla_denominacion: fondo %s sin historico de mezcla en la "
                "ventana; reparto uniforme 1/%d (SUP-09, no se inventa mezcla).",
                fund,
                n,
            )
            for denom in denominations:
                rows.append({"fondo_id": fund, "denominacion": int(denom), "peso": 1.0 / n})
            continue
        mapping = {int(d): float(v) for d, v in zip(sub["denominacion"], sub["valor"], strict=False)}
        for denom in denominations:
            weight = mapping.get(int(denom), 0.0) / total
            rows.append({"fondo_id": fund, "denominacion": int(denom), "peso": weight})

    return pd.DataFrame(rows, columns=["fondo_id", "denominacion", "peso"])


def _atm_code_to_fund_map() -> dict[str, str | None]:
    """Construye el mapa `cod_cajero(str) -> fondo_id` para M1/M2 via cp_historico.

    Returns:
        dict[str, str | None]: Mapa del id de ATM (str) a su `fondo_id`
        (`build_fund_id(ciudad, admon)`); `None` cuando el par queda fuera de
        dominio (p.ej. `admon='SUC'`).
    """
    cp = storage.read_table(_URI_CP_HISTORY)
    mapping: dict[str, str | None] = {}
    for code, city, admin in zip(
        cp["cod_cajero"].astype(str).str.strip(),
        cp.get("ciudad"),
        cp.get("admon"),
        strict=False,
    ):
        mapping[code] = build_fund_id(city, admin)
    return mapping


def _norm_code(value: object) -> str | None:
    """Codigo comparable: recortado y, si es numerico, sin decimales (`"70.0"` -> `"70"`); vacio/NA -> None."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else text


def _atm_code_to_fund_map_suc() -> tuple[dict[str, str | None], dict[str, str]]:
    """Mapa cajero -> fondo con los cajeros administrados por sucursal (SUP-12, `m6_cajeros_sucursal`).

    Parte de `_atm_code_to_fund_map()` (que no cambia) y, para cada cajero con `admon = SUC` (RN-08A: "administrado
    por la sucursal indicada en codigo_sucursal"), usa el fondo de su sucursal en `oficinas` (`CIUDAD FONDO` +
    `TTADORA`, el mismo puente de M3). Si la sucursal no esta en `oficinas` o su fondo no esta en `dim_fondo`, el
    cajero queda sin fondo (`None`) con su motivo; nunca se le asigna un fondo arbitrario.

    Returns:
        tuple[dict, dict]: `(mapa, motivos)`; `motivos` tiene una entrada por cada cajero SUC del maestro:
        `ok` (mapeado), `sucursal_sin_oficina` o `fondo_fuera_de_dim`.
    """
    mapping = dict(_atm_code_to_fund_map())
    cp = storage.read_table(_URI_CP_HISTORY)
    office = storage.read_table(_URI_OFFICES)
    for col in ("ciudad", "transportadora"):
        if col not in office.columns:
            raise KeyError(f"oficinas sin la columna {col!r}: no se puede mapear la sucursal al fondo (SUP-12).")
    branch = {
        _norm_code(c): build_fund_id(city, tdv)
        for c, city, tdv in zip(office["cod_sucursal"], office["ciudad"], office["transportadora"], strict=False)
    }
    dim = storage.read_table("daas://processed/_dim/dim_fondo")
    funds_dim = set(dim["fondo_id"].astype(str))
    reasons: dict[str, str] = {}
    codes = cp["cod_cajero"].astype(str).str.strip()
    for code, admin, suc in zip(codes, cp["admon"], cp["cod_sucursal"], strict=False):
        if not (isinstance(admin, str) and admin.strip().upper() == "SUC"):
            continue
        key = _norm_code(suc)
        if key is None or key not in branch:
            mapping[code] = None
            reasons[code] = "sucursal_sin_oficina"
            continue
        fund = branch[key]
        if fund is None or str(fund) not in funds_dim:
            mapping[code] = None
            reasons[code] = "fondo_fuera_de_dim"
            continue
        mapping[code] = str(fund)
        reasons[code] = "ok"
    return mapping, reasons


def _branch_code_to_fund_map() -> dict[str, str | None]:
    """Construye el mapa `cod_sucursal(str) -> fondo_id` para M3 via oficinas.

    Returns:
        dict[str, str | None]: Mapa del `cod_sucursal` (str) a su `fondo_id`
        (`build_fund_id(ciudad, transportadora)`); `None` fuera de dominio.
    """
    office = storage.read_table(_URI_OFFICES)
    mapping: dict[str, str | None] = {}
    for code, city, tdv in zip(
        office["cod_sucursal"].astype(str).str.strip(),
        office.get("ciudad"),
        office.get("transportadora"),
        strict=False,
    ):
        mapping[code] = build_fund_id(city, tdv)
    return mapping


def total_correction_factors(
    metrics: pd.DataFrame | None,
    config: dict,
    cutoff: _dt.date | None = None,
) -> dict[str, float]:
    """Factor de red por modelo para corregir el total que consume M6.

    Metodo `movil` (por defecto, sin fuga): para cada modelo toma el sesgo de red
    de los ULTIMOS `ventana_origenes` origenes ya cerrados (bloque `bloque_origen`
    del contrato `metricas`, columna `origen`), calcula por origen la razon
    real/pronostico `1 / (1 + bias)` y promedia. Un origen solo cuenta si su
    ventana de evaluacion termina `<= corte` (`origen + horizonte_evaluacion_dias
    <= corte`), es decir, si todo su real era observable antes del origen de la
    corrida. El promedio se acota a `[factor_min, factor_max]`. Sin origenes
    suficientes (`min_origenes`) o desactivado, no corrige (con WARNING).

    Metodo `fijo` (legado): usa el sesgo agregado del bloque `bloque`
    (`1 / (1 + bias)`), que incluye origenes posteriores al de la corrida (fuga).

    Es UN factor por modelo (red), no por fondo: por fondo falla cuando una serie
    tiene un quiebre. Lo publicado por M4/M5 no se toca.

    Args:
        metrics: Contrato `output/api/metricas` (puede ser `None` o vacio).
        config: Configuracion de M6 (usa `correccion_total`).
        cutoff: Fecha de corte (origen de la corrida); necesaria para `movil`.

    Returns:
        dict[str, float]: `modelo -> factor` solo para los modelos corregidos.
    """
    return {m: d["factor"] for m, d in total_correction_detail(metrics, config, cutoff).items()}


def total_correction_detail(
    metrics: pd.DataFrame | None,
    config: dict,
    cutoff: _dt.date | None = None,
) -> dict[str, dict[str, Any]]:
    """Detalle del factor de red por modelo: factor final y factor por origen.

    Misma logica que `total_correction_factors`, pero devuelve para cada modelo
    corregido `{'factor', 'crudo', 'metodo', 'por_origen': {origen_iso: razon}}`
    para reportarlo en `metricas` (trazabilidad del factor movil).

    Args:
        metrics: Contrato `output/api/metricas` (puede ser `None` o vacio).
        config: Configuracion de M6 (usa `correccion_total`).
        cutoff: Fecha de corte (origen de la corrida).

    Returns:
        dict[str, dict]: Detalle por modelo corregido.
    """
    cfg = config.get("correccion_total") or {}
    if not cfg.get("activo") or metrics is None or metrics.empty:
        return {}
    method = str(cfg.get("metodo", "movil"))
    fmin, fmax = float(cfg["factor_min"]), float(cfg["factor_max"])
    out: dict[str, dict[str, Any]] = {}
    for model in cfg.get("modelos", []):
        by_origin: dict[str, float] = {}
        if method == "movil":
            sub = metrics[
                (metrics["bloque"].astype(str) == str(cfg["bloque_origen"]))
                & (metrics["modelo"].astype(str) == str(model))
            ]
            if "origen" in sub.columns and not sub.empty:
                sub = sub.assign(
                    _origen=pd.to_datetime(sub["origen"], errors="coerce"),
                    _bias=pd.to_numeric(sub["bias"], errors="coerce"),
                ).dropna(subset=["_origen", "_bias"])
                if cutoff is not None:
                    limit = pd.Timestamp(cutoff) - pd.Timedelta(days=int(cfg.get("horizonte_evaluacion_dias", 15)))
                    sub = sub[sub["_origen"] <= limit]
                sub = sub[sub["_bias"] > -1.0].sort_values("_origen")
                sub = sub.tail(int(cfg.get("ventana_origenes", 3)))
                by_origin = {
                    o.date().isoformat(): 1.0 / (1.0 + float(b))
                    for o, b in zip(sub["_origen"], sub["_bias"], strict=False)
                }
            if len(by_origin) < int(cfg.get("min_origenes", 1)):
                logger.warning(
                    "correccion_total: %d origenes cerrados para %s (min %s); su " "total entra a M6 sin corregir.",
                    len(by_origin),
                    model,
                    cfg.get("min_origenes", 1),
                )
                continue
            raw = sum(by_origin.values()) / len(by_origin)
        else:
            row = metrics[
                (metrics["bloque"].astype(str) == str(cfg["bloque"])) & (metrics["modelo"].astype(str) == str(model))
            ]
            bias = pd.to_numeric(row["bias"], errors="coerce").dropna()
            if bias.empty or float(bias.iloc[0]) <= -1.0:
                logger.warning(
                    "correccion_total: sin sesgo de red publicado para %s; su total " "entra a M6 sin corregir.",
                    model,
                )
                continue
            raw = 1.0 / (1.0 + float(bias.iloc[0]))
        factor = min(max(raw, fmin), fmax)
        if factor != raw:
            logger.warning(
                "correccion_total: factor de %s acotado de %.3f a %.3f.",
                model,
                raw,
                factor,
            )
        out[str(model)] = {
            "factor": factor,
            "crudo": raw,
            "metodo": method,
            "por_origen": by_origin,
        }
    return out


def net_effect_m1_m5_by_fund_day(
    predictions: pd.DataFrame,
    dates: list[_dt.date],
    config: dict,
    factors: dict[str, float] | None = None,
    diagnostics: dict | None = None,
) -> pd.DataFrame:
    """Efecto neto diario de M1-M5 por fondo (RN-70 / D-FLUJO-1 / SUP-12).

    Con el interruptor `m6_cajeros_sucursal` encendido, los cajeros `admon = SUC` se rutean al fondo de su sucursal
    (`_atm_code_to_fund_map_suc`) y, si se pasa `diagnostics`, se llena con `sin_fondo` (lista de
    `{modelo, objetivo, cod_cajero, motivo, cop}`), `suc_mapeados` y `suc_total`.

    Agrega el flujo neto (ingreso - egreso) que M1-M5 pronostican por
    (`fondo_id`, `fecha`) sobre el horizonte. Ruteo del id a `fondo_id` segun el
    `modelo`: m4/m5 `cod_cajero` ES `fondo_id`; m1/m2 join
    `cp_historico[str(cod_cajero)] -> build_fund_id(ciudad, admon)`; m3
    `cod_cajero` ES el `cod_sucursal`, join `oficinas[str(cod_sucursal)] ->
    build_fund_id(ciudad, transportadora)`. Ambas claves se castean a `str` y se
    recortan (strip) antes del merge; un merge con 0 matches donde se esperaban
    >0 se avisa con WARNING por modelo (evita exclusion silenciosa de M3). El
    signo por (modelo, objetivo) sale de `config['efecto_m1_m5']`. Los
    `cod_cajero` sin fondo mapeable (sin match / `admon='SUC'`) se EXCLUYEN con
    WARNING (SUP-12); nunca se les asigna un fondo arbitrario.

    Args:
        predictions: Contrato `output/api/predicciones` (M1-M5 publicadas).
        dates: Fechas del horizonte (dias calendario).
        config: Configuracion de M6 (usa `efecto_m1_m5`).
        factors: `modelo -> factor` de `total_correction_factors`; el `yhat`
            de esos modelos se multiplica por su factor. `None` = sin correccion.
        diagnostics: Diccionario que se llena con los cajeros de sucursal sin fondo (solo con
            `m6_cajeros_sucursal`); `None` = no se reporta.

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `fecha`, `efecto_neto`, `ingreso`,
        `egreso` (ambos >= 0; `efecto_neto = ingreso - egreso`). Una fila
        por (fondo_id, fecha) con flujo neto != 0 u observado.
    """
    cfg = config.get("efecto_m1_m5", {})
    inflows: dict[str, list[str]] = cfg.get("ingresos", {})
    outflows: dict[str, list[str]] = cfg.get("egresos", {})

    # Signo por (modelo, objetivo): +1 ingreso, -1 egreso.
    sign: dict[tuple[str, str], int] = {}
    for model, targets in inflows.items():
        for obj in targets:
            sign[(str(model), str(obj))] = 1
    for model, targets in outflows.items():
        for obj in targets:
            # Un (modelo, objetivo) puede ser egreso sin solapar un ingreso.
            sign[(str(model), str(obj))] = sign.get((str(model), str(obj)), 0) - 1

    df = predictions.copy()
    df["modelo"] = df["modelo"].astype(str).str.strip()
    df["objetivo"] = df["objetivo"].astype(str).str.strip()
    df["cod_cajero"] = df["cod_cajero"].astype(str).str.strip()
    df["fecha"] = _to_date_or_none(df["fecha"])
    df["yhat"] = pd.to_numeric(df["yhat"], errors="coerce").fillna(0.0)
    df = df[df["fecha"].isin(set(dates))]
    # M6 consume SOLO M1-M5; se descartan filas de otros modelos (p.ej. m6 de una
    # corrida previa en el mismo contrato) ANTES de evaluar el mapa de signos.
    models_source = {m for (m, _o) in sign}
    df = df[df["modelo"].isin(models_source)]

    # Aplica el signo; (modelo, objetivo) desconocido -> fila ignorada + WARNING.
    df["_signo"] = [sign.get((m, o), None) for m, o in zip(df["modelo"], df["objetivo"], strict=False)]
    unknown = df[df["_signo"].isna()]
    if not unknown.empty:
        pairs = sorted({(m, o) for m, o in zip(unknown["modelo"], unknown["objetivo"], strict=False)})
        logger.warning(
            "efecto_neto: %d filas con (modelo, objetivo) fuera del mapa de " "signos %s; se ignoran.",
            int(len(unknown)),
            pairs,
        )
    df = df[df["_signo"].notna()].copy()
    correction = df["modelo"].map(factors or {}).fillna(1.0)
    df["_flujo"] = df["_signo"].astype(float) * df["yhat"] * correction

    with_suc = alx.interruptor("m6_cajeros_sucursal")
    if with_suc:
        map_atm, reasons_suc = _atm_code_to_fund_map_suc()
        suc_codes = set(reasons_suc)
        n_mapped = sum(1 for r in reasons_suc.values() if r == "ok")
        if suc_codes and n_mapped == 0:
            raise RuntimeError(
                f"m6_cajeros_sucursal: 0 de {len(suc_codes)} cajeros administrados por sucursal se mapearon a un "
                "fondo (posible desalineacion de claves cod_sucursal/oficinas; SUP-12)."
            )
        if diagnostics is not None:
            diagnostics["suc_total"] = len(suc_codes)
            diagnostics["suc_mapeados"] = n_mapped
            diagnostics["sin_fondo"] = []
    else:
        map_atm = _atm_code_to_fund_map()
        reasons_suc = {}
    map_branch = _branch_code_to_fund_map()

    parts: list[pd.DataFrame] = []
    excluded = 0
    for model, group in df.groupby("modelo", sort=True):
        resolved = group.copy()
        if model in {"m4", "m5"}:
            resolved["fondo_id"] = resolved["cod_cajero"]
        elif model in {"m1", "m2"}:
            resolved["fondo_id"] = resolved["cod_cajero"].map(map_atm)
            _warn_unmatched(model, resolved, "cp_historico")
        elif model == "m3":
            resolved["fondo_id"] = resolved["cod_cajero"].map(map_branch)
            _warn_unmatched(model, resolved, "oficinas")
        else:
            logger.warning(
                "efecto_neto: modelo %r sin regla de ruteo id->fondo; se ignora.",
                model,
            )
            continue
        without_fund = resolved[resolved["fondo_id"].isna()]
        if not without_fund.empty:
            excluded += int(without_fund["cod_cajero"].nunique())
            logger.warning(
                "efecto_neto: %d cajeros de %s sin fondo mapeable (sin match / "
                "admon=SUC); excluidos del efecto (SUP-12).",
                int(without_fund["cod_cajero"].nunique()),
                model,
            )
            if with_suc and model in {"m1", "m2"}:
                keys = [without_fund["objetivo"], without_fund["cod_cajero"]]
                cop = without_fund["_flujo"].abs().groupby(keys).sum()
                for (obj, code), value in cop.items():
                    reason = reasons_suc.get(str(code), "sin_match_cp")
                    logger.warning(
                        "efecto_neto: cajero %s (%s %s) sin fondo (%s): %.0f COP fuera del balance (SUP-12).",
                        code, model, obj, reason, float(value),
                    )
                    if diagnostics is not None:
                        diagnostics["sin_fondo"].append(
                            {"modelo": model, "objetivo": str(obj), "cod_cajero": str(code), "motivo": reason,
                             "cop": float(value)}
                        )
        parts.append(resolved[resolved["fondo_id"].notna()])

    if not parts:
        return pd.DataFrame(columns=["fondo_id", "fecha", "efecto_neto", "ingreso", "egreso"])

    everything = pd.concat(parts, ignore_index=True)
    everything["ingreso"] = everything["_flujo"].clip(lower=0.0)
    everything["egreso"] = (-everything["_flujo"]).clip(lower=0.0)
    effect = (
        everything.groupby(["fondo_id", "fecha"], as_index=False)[["_flujo", "ingreso", "egreso"]]
        .sum()
        .rename(columns={"_flujo": "efecto_neto"})
    )
    return effect.sort_values(["fondo_id", "fecha"]).reset_index(drop=True)


def _warn_unmatched(model: str, resolved: pd.DataFrame, master: str) -> None:
    """Emite WARNING si el ruteo id->fondo de un modelo da 0 matches (D-FLUJO-1).

    Un merge que produzca 0 matches donde se esperaban >0 es un error de
    alineacion (p.ej. tipos str desalineados), NO "sin datos": se avisa para que
    el fallo no sea silencioso.

    Args:
        model: Clave del modelo ruteado (`m1`/`m2`/`m3`).
        resolved: DataFrame del modelo con la columna `fondo_id` ya mapeada.
        master: Nombre del maestro usado para el ruteo (para el mensaje).
    """
    if not resolved.empty and resolved["fondo_id"].notna().sum() == 0:
        logger.warning(
            "efecto_neto: el ruteo id->fondo de %s via %s dio 0 matches donde se "
            "esperaban >0 (posible desalineacion de tipos); se excluye %s del "
            "efecto. Revisar la clave del merge (D-FLUJO-1).",
            model,
            master,
            model,
        )


def distribute_effect_by_denomination(effect: pd.DataFrame, mix: pd.DataFrame) -> pd.DataFrame:
    """Reparte el efecto por fondo-dia entre denominaciones segun la mezcla (RN-70).

    Multiplica `efecto_neto(fondo, fecha)` por el `peso` de cada denominacion del
    fondo (SUP-09). La suma sobre denominaciones de un fondo-dia reconstruye el
    `efecto_neto` del fondo-dia.

    Args:
        effect: Salida de `net_effect_m1_m5_by_fund_day`.
        mix: Salida de `denomination_mix_by_fund`.

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `fecha`, `denominacion`,
        `efecto_neto_den`, `ingreso_den`, `egreso_den` (ingresos y egresos
        por separado; `efecto_neto_den = ingreso_den - egreso_den`).
    """
    columns = [
        "fondo_id",
        "fecha",
        "denominacion",
        "efecto_neto_den",
        "ingreso_den",
        "egreso_den",
    ]
    if effect.empty:
        return pd.DataFrame(columns=columns)
    cross = effect.merge(mix, on="fondo_id", how="left")
    weight = cross["peso"].astype(float)
    cross["efecto_neto_den"] = cross["efecto_neto"].astype(float) * weight
    for origin, destination in (("ingreso", "ingreso_den"), ("egreso", "egreso_den")):
        # Compatibilidad: un efecto sin columnas ingreso/egreso (legado) se separa por signo.
        base = (
            cross[origin].astype(float)
            if origin in cross.columns
            else (
                cross["efecto_neto"].clip(lower=0.0) if origin == "ingreso" else (-cross["efecto_neto"]).clip(lower=0.0)
            ).astype(float)
        )
        cross[destination] = base * weight
    return cross[columns].sort_values(["fondo_id", "fecha", "denominacion"]).reset_index(drop=True)


def sales_rate_by_fund(sales: pd.DataFrame, cutoff: _dt.date, config: dict) -> dict[str, float]:
    """Tasa de referencia de la venta por fondo (RN-76).

    Mediana de la `tasa` (COP por cada `decision.venta.tasa_por_monto` vendidos) de
    `consolidado_ventas` por fondo, sobre una ventana que termina en el corte
    (`decision.venta.ventana_dias`). Solo cuentan filas con tasa numerica > 0 (la
    tasa NaN o 0 es una venta sin comision o una fila desplazada de la fuente, no un
    precio). Es un SUPUESTO de referencia, no un beneficio garantizado: un fondo sin
    tasa observable no tiene venta recomendable (no se inventa).

    Args:
        sales: `interim/consolidado_ventas` (`fondo_id`, `fecha`, `tasa`).
        cutoff: Fecha de corte (no se usa informacion posterior).
        config: Configuracion de M6 (usa `decision.venta`).

    Returns:
        dict[str, float]: `fondo_id -> tasa mediana` solo para fondos con dato.
    """
    cfg = config.get("decision", {}).get("venta", {})
    base = sales[["fondo_id", "fecha", "tasa"]].copy()
    base["fecha"] = _to_date_or_none(base["fecha"])
    base["tasa"] = pd.to_numeric(base["tasa"], errors="coerce")
    base = _window(base.dropna(subset=["fecha"]), cutoff, int(cfg.get("ventana_dias", 365)))
    base = base[base["tasa"].notna() & (base["tasa"] > 0.0)]
    return {str(f): float(t) for f, t in base.groupby(base["fondo_id"].astype(str))["tasa"].median().items()}


def enabled_operations_matrix(
    exchanges: pd.DataFrame,
    sales: pd.DataFrame,
    available_cash: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Matriz de operaciones habilitadas por fondo (SUP-08 / SUP-13 / D-OPS-1).

    Reglas CERRADAS por operacion, todas parametrizables en
    `conf/model_u6.yml::operaciones`:

    - `venta`: habilitada si el fondo aparece en `consolidado_ventas`.
    - `intercambio`: habilitada si el fondo aparece en `intercambios`.
    - `cambio_denominacion`: hereda la habilitacion de `intercambio`.
    - `banrep`: `operaciones.banrep_desde_anexo_e` AND la transportadora del
      fondo tiene tarifa `Consignacion/Retiro BanRep` en Anexo E Fondos AND (RN-75)
      la ciudad del fondo esta en `operaciones.banrep.ciudades_habilitadas`
      (SUP-13: NO hay historico de movimientos BanRep; la lista es un supuesto de
      configuracion, p. ej. Cali; vacia = sin restriccion de ciudad).
    - `traslado`: SIEMPRE habilitada entre pares de `dim_fondo` (la falta de
      tarifa del par NO deshabilita: sale costo NULL + flag).

    WARNING por cada (fondo, operacion) que resulte `habilitada=False` por falta
    de soporte historico (venta/intercambio), para que la ausencia sea explicita.

    Args:
        exchanges: `interim/intercambios` (historico por fondo).
        sales: `interim/consolidado_ventas` (historico por fondo).
        available_cash: Salida de `load_available_cash` (universo de fondos).
        config: Configuracion de M6 (usa `operaciones`).

    Returns:
        pd.DataFrame: Columnas `fondo_id`, `operacion`, `habilitada` (bool). Las
        operaciones son: traslado, venta, banrep, intercambio, cambio_denominacion.
    """
    cfg_ops = config.get("operaciones", {})
    banrep_since_anexo = bool(cfg_ops.get("banrep_desde_anexo_e", True))

    dim = storage.read_table("daas://processed/_dim/dim_fondo")
    funds = dim[["fondo_id", "transportadora", "ciudad"]].copy()
    funds["fondo_id"] = funds["fondo_id"].astype(str)
    # RN-75: BanRep (consignacion/retiro) solo en las ciudades habilitadas por config.
    # Lista vacia = sin restriccion de ciudad (regla anterior: solo la tarifa).
    cities_banrep = {
        str(c).strip().upper() for c in (cfg_ops.get("banrep", {}) or {}).get("ciudades_habilitadas", []) or []
    }

    with_sale = set(sales["fondo_id"].astype(str).unique().tolist())
    with_exchange = set(exchanges["fondo_id"].astype(str).unique().tolist())

    # Transportadoras con tarifa BanRep en Anexo E Fondos (SUP-13).
    tdv_banrep: set[str] = set()
    if banrep_since_anexo:
        anexo = storage.read_table("daas://interim/costos_anexo_e")
        fon = anexo[anexo["ambito"] == "Fondos"].copy()
        banrep = fon[fon["concepto"].astype(str).str.contains("BanRep", case=False, na=False)]
        valid_rows = banrep[pd.to_numeric(banrep["tarifa"], errors="coerce").notna()]
        tdv_banrep = set(valid_rows["transportadora"].astype(str).unique().tolist())

    rows: list[dict[str, Any]] = []
    for fund, tdv, city in zip(
        funds["fondo_id"],
        funds["transportadora"].astype(str),
        funds["ciudad"].astype(str),
        strict=False,
    ):
        sale_ok = fund in with_sale
        exchange_ok = fund in with_exchange
        banrep_ok = tdv in tdv_banrep if banrep_since_anexo else False
        if cities_banrep and city.strip().upper() not in cities_banrep:
            banrep_ok = False
        if not sale_ok:
            logger.warning(
                "matriz_operaciones: fondo %s sin historico de venta; " "venta habilitada=False (SUP-08).",
                fund,
            )
        if not exchange_ok:
            logger.warning(
                "matriz_operaciones: fondo %s sin historico de intercambio; "
                "intercambio/cambio_denominacion habilitada=False (SUP-08).",
                fund,
            )
        rows.append({"fondo_id": fund, "operacion": "traslado", "habilitada": True})
        rows.append({"fondo_id": fund, "operacion": "venta", "habilitada": sale_ok})
        rows.append({"fondo_id": fund, "operacion": "banrep", "habilitada": bool(banrep_ok)})
        rows.append({"fondo_id": fund, "operacion": "intercambio", "habilitada": exchange_ok})
        rows.append(
            {
                "fondo_id": fund,
                "operacion": "cambio_denominacion",
                "habilitada": exchange_ok,
            }
        )

    if alx.interruptor("m6_operaciones_rn84"):
        # RN-84 / SUP-14: el cambio de denominacion es con BanRep y el intercambio con otras entidades; no se
        # recomiendan dentro del fondo. Se deshabilitan con motivo explicito (lo usa `simulator._is_allowed`).
        reason = str((cfg_ops.get("rn84") or {}).get("texto_descartada", "RN-84 (SUP-14)"))
        for row in rows:
            row["motivo"] = None
            if row["operacion"] in {"intercambio", "cambio_denominacion"}:
                row["habilitada"] = False
                row["motivo"] = reason
        return pd.DataFrame(rows, columns=["fondo_id", "operacion", "habilitada", "motivo"])
    return pd.DataFrame(rows, columns=["fondo_id", "operacion", "habilitada"])
