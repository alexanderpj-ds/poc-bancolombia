"""Motor de costos del subpaquete `costs` (C-12).

Regla de negocio: el costo de un servicio de transporte de valores es
`costo = fijo + (monto / 10.000) x tarifa`, con `fijo` (`costo_fijo`) y
`tarifa` de la fila del Anexo E (contrato C-12, `interim/costos_anexo_e`) que
coincide en concepto, transportadora y servicio.

El concepto depende de la entidad y de la fecha (reglas en
`conf/costos.yml`, no en codigo):
  - Cajero (M1, M2): `tipo_facturacion` del maestro CP y el dia de la accion
    (`L-S` o `D-F`), p.ej. `ATM URBANO L-S ELITE`, `MF URBANO D-F`
    (`atm_concept`).
  - Sucursal (M3): `ubicacion` del maestro de oficinas, p.ej.
    `SUCURSAL URBANO MEDIO`; la accion elige la tabla de provision o de
    recoleccion (`branch_concept`).

Reglas duras (NUNCA inventar un dato):
  - Filas sin transportadora (p.ej. `admon='SUC'`): costo NULL +
    `sin_transportadora=True`.
  - Sin concepto, o concepto sin tarifa (`No Disponible`/NULL): costo NULL +
    `sin_tarifa=True`. Nunca se toma la tarifa de otra fila.

Extension M6 (U6): `compute_costs_m6` costea las recomendaciones de
fondos usando el ambito `Fondos` del Anexo E (traslado, BanRep, intercambio,
cambio de denominacion). Mantiene las mismas reglas duras
(NUNCA inventar tarifa) y anade el matcheo de concepto por `_norm_concept`
(NFKD + sin acentos + `strip` + `upper`) en AMBOS lados para salvar el title-case
del Anexo frente a las ciudades en MAYUSCULAS de `dim_fondo`.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

from daas import alx
from daas.features.calendar import _co_holidays
from daas.io import storage

logger = logging.getLogger(__name__)

#: URI del Anexo E (tarifas) en la capa interim.
_URI_COSTS_ANEXO_E = "daas://interim/costos_anexo_e"
#: Ambitos del Anexo E que costean cajeros y sucursales.
_ACTION_SCOPES = ("ATM", "Sucursales")
#: Ambito de las tarifas de Fondos (M6) dentro del Anexo E.
_FUNDS_SCOPE = "Fondos"
#: Marcadores textuales de tarifa no disponible (se tratan como NULL).
_RATE_UNAVAILABLE = {"no disponible", "nd", "n/a", "na", ""}
#: Domingo en `datetime.date.weekday()`.
_SUNDAY = 6


def compute_cost(amount: float, fixed: float, rate: float) -> float:
    """Calcula `costo = fijo + (monto / 10.000) x tarifa` (C-12).

    Args:
        amount: Monto del servicio (COP).
        fixed: Costo fijo del Anexo E.
        rate: Tarifa variable del Anexo E.

    Returns:
        float: Costo del servicio.
    """
    return float(fixed) + (float(amount) / 10000.0) * float(rate)


def _valid_rate(value: object) -> bool:
    """Indica si una tarifa es un numero utilizable (no NULL ni 'No Disponible').

    Args:
        value: Valor crudo de la tarifa leido del Anexo E.

    Returns:
        bool: `True` si la tarifa es numerica y no es un marcador de ausencia.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, str) and value.strip().lower() in _RATE_UNAVAILABLE:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_empty(value: object) -> bool:
    """`True` si el valor es None, NA/NaN o texto vacio."""
    if value is None:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and value.strip() == ""


def _key(text: object) -> str:
    """Concepto comparable: espacios colapsados y en mayusculas."""
    return " ".join(str(text).split()).upper()


def _conf_dir() -> Path:
    """Localiza el directorio ``conf/`` (``DAAS_CONF`` o el del paquete)."""
    env = os.environ.get("DAAS_CONF")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "conf"


def load_rules() -> dict:
    """Carga `conf/costos.yml` (reglas tipologia -> concepto del Anexo E).

    Returns:
        dict: Claves `dia`, `cajero` y `sucursal`.
    """
    with (_conf_dir() / "costos.yml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _day(date: object, rules: dict, holiday_dates: set[_dt.date]) -> str:
    """Etiqueta del dia en el Anexo E: domingo o festivo -> `D-F`; si no, `L-S`."""
    day = pd.Timestamp(date).date()
    if day.weekday() == _SUNDAY or day in holiday_dates:
        return str(rules["dia"]["domingo_festivo"])
    return str(rules["dia"]["otro"])


def _holidays(dates: pd.Series) -> set[_dt.date]:
    """Festivos del calendario del pipeline en los anios de `fechas`."""
    years = sorted({pd.Timestamp(f).year for f in dates if not _is_empty(f)})
    return set(_co_holidays(years)) if years else set()


def atm_concept(kind_billing: object, date: object, rules: dict, holiday_dates: set[_dt.date]) -> str | None:
    """Concepto del Anexo E de una accion en un cajero (M1, M2).

    Args:
        kind_billing: Tipologia del maestro CP (p.ej. `ELITE`, `MF`).
        date: Fecha de la accion (elige `L-S` o `D-F`).
        rules: `conf/costos.yml` cargado.
        holiday_dates: Festivos del calendario del pipeline.

    Returns:
        str | None: El concepto, o ``None`` si la tipologia falta o no tiene regla.
    """
    if _is_empty(kind_billing) or _is_empty(date):
        return None
    template = {_key(k): v for k, v in rules["cajero"].items()}.get(_key(kind_billing))
    if template is None:
        return None
    return template.format(dia=_day(date, rules, holiday_dates))


def _fix_mojibake(text: str) -> str:
    """Repara texto UTF-8 leido como cp1252/latin-1 (p. ej. `TULUÃ` + byte 0x81 -> `TULUÁ`); si no, lo deja igual."""
    if "Ã" not in text and "Â" not in text:
        return text
    raw = bytearray()
    for char in text:
        try:
            raw.extend(char.encode("cp1252"))
        except UnicodeEncodeError:
            if ord(char) < 256:
                raw.append(ord(char))
            else:
                return text
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return text


def _norm_place(value: object) -> str | None:
    """Nombre de lugar comparable: mojibake reparado, sin tildes (NFKD), mayusculas y espacios colapsados."""
    if _is_empty(value):
        return None
    decomposed = unicodedata.normalize("NFKD", _fix_mojibake(str(value)))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.split()).upper() or None


def mf_es_interurbano(municipio: object, ciudad_fondo: object) -> bool | None:
    """RN-04A (M2, multifuncional TDV): interurbano cuando el municipio del equipo no coincide con la ciudad del fondo.

    Args:
        municipio: `municipio` del maestro CP.
        ciudad_fondo: Ciudad del fondo (`fondo` del maestro CP, columna `ciudad`).

    Returns:
        bool | None: `True` si difieren, `False` si coinciden, `None` si falta alguno (no se inventa).
    """
    a, b = _norm_place(municipio), _norm_place(ciudad_fondo)
    if a is None or b is None:
        return None
    return a != b


def branch_concept(location: object, rules: dict, escalas: object = None) -> str | None:
    """Concepto del Anexo E de una sucursal (M3), segun su `ubicacion`.

    Con el interruptor `m3_escala_anexo_a` (SUP-22) y una ubicacion `INTERURBANO n`, la escala sale del campo
    `Escalas` de Oficinas (Anexo A: "Escala de transporte para sucursales interurbanas (tarifa INTERURBANA PR
    ESCALA del Anexo E)") cuando es un entero >= 1; si no, del numero de la `Ubicacion` (con WARNING).

    Args:
        location: Tipologia del maestro de oficinas (p.ej. `URBANO MEDIO`,
            `INTERURBANO 3`, `AEREO 1`, `ALTO`).
        rules: `conf/costos.yml` cargado.
        escalas: Campo `Escalas` de Oficinas (solo con `m3_escala_anexo_a`).

    Returns:
        str | None: El concepto, o ``None`` si la ubicacion falta o no tiene regla.
    """
    if _is_empty(location):
        return None
    text = _key(location)
    if alx.interruptor("m3_escala_anexo_a"):
        inter = re.match(r"^INTERURBANO (\d+)$", text)
        if inter:
            scale = None
            try:
                number = float(escalas) if not _is_empty(escalas) else None
            except (TypeError, ValueError):
                number = None
            if number is not None and number.is_integer() and number >= 1:
                scale = int(number)
            if scale is not None:
                return f"SUCURSAL INTERURBANA ESCALA {scale}"
            logger.warning(
                "Sucursal %r sin Escalas valida (%r): la escala sale del numero de la Ubicacion (SUP-22).",
                location, escalas,
            )
    for rule in rules["sucursal"]:
        coincide = re.match(rule["patron"], text)
        if coincide:
            return str(rule["concepto"]).format(coincide.group(0), *coincide.groups())
    return None


def atm_concepts(df: pd.DataFrame, rules: dict | None = None) -> pd.Series:
    """Concepto de cada accion de cajero (`tipo_facturacion` + `fecha_sugerida`)."""
    rules = rules if rules is not None else load_rules()
    holiday_dates = _holidays(df["fecha_sugerida"])
    return pd.Series(
        [
            atm_concept(t, f, rules, holiday_dates)
            for t, f in zip(df["tipo_facturacion"], df["fecha_sugerida"], strict=False)
        ],
        index=df.index,
        dtype=object,
    )


def branch_concepts(df: pd.DataFrame, rules: dict | None = None) -> pd.Series:
    """Concepto de cada accion de sucursal (`ubicacion`)."""
    rules = rules if rules is not None else load_rules()
    if "escalas" in df.columns:
        return pd.Series(
            [branch_concept(u, rules, e) for u, e in zip(df["ubicacion"], df["escalas"], strict=False)],
            index=df.index,
            dtype=object,
        )
    return pd.Series([branch_concept(u, rules) for u in df["ubicacion"]], index=df.index, dtype=object)


def load_rates() -> pd.DataFrame:
    """Lee las tarifas de cajeros y sucursales del Anexo E (`ATM`, `Sucursales`).

    Returns:
        pd.DataFrame: Columnas `concepto`, `transportadora`, `servicio`,
        `costo_fijo`, `tarifa` (una fila por combinacion).
    """
    anexo = storage.read_table(_URI_COSTS_ANEXO_E)
    table = anexo[anexo["ambito"].isin(_ACTION_SCOPES)].copy()
    if "servicio" not in table.columns:
        table["servicio"] = pd.NA
    columns = ["concepto", "transportadora", "servicio", "costo_fijo", "tarifa"]
    return table[columns].reset_index(drop=True)


def compute_costs(df: pd.DataFrame, rates: pd.DataFrame | None = None) -> pd.DataFrame:
    """Costea servicios con el Anexo E por concepto, transportadora y servicio (C-12).

    Cada fila de `df` trae `monto`, `transportadora`, `concepto` (de
    `atm_concepts`/`branch_concepts`) y, opcional, `accion`
    (`provision`/`recoleccion`). Se busca la tarifa con el mismo concepto y
    transportadora y con `servicio` igual a la accion; una tarifa con
    `servicio` NULL vale para cualquier accion (tabla unica de ATM).
    Marca:
      - `sin_transportadora=True` (costo NULL) cuando la fila no trae
        transportadora (p.ej. `admon='SUC'`).
      - `sin_tarifa=True` (costo NULL) cuando falta el concepto o no hay tarifa
        utilizable para el (concepto, transportadora, servicio). NO se inventa.

    Args:
        df: Servicios con `monto`, `transportadora`, `concepto` y opcional `accion`.
        rates: Tabla de tarifas ya cargada (opcional; util en tests). Si es
            `None` se lee de `interim/costos_anexo_e` (`load_rates`).

    Returns:
        pd.DataFrame: Copia de `df` con columnas `costo` (float o NULL),
        `sin_transportadora` (bool) y `sin_tarifa` (bool).
    """
    out = df.copy().reset_index(drop=True)
    table = rates if rates is not None else load_rates()

    # Indice (concepto, transportadora, servicio|None) -> (costo_fijo, tarifa).
    index: dict[tuple[str, str, str | None], tuple[object, object]] = {}
    for entry in table.itertuples(index=False):
        service = getattr(entry, "servicio", None)
        service = None if _is_empty(service) else str(service)
        index[(_key(entry.concepto), str(entry.transportadora), service)] = (
            entry.costo_fijo,
            entry.tarifa,
        )

    for col in ("transportadora", "concepto"):
        if col not in out.columns:
            out[col] = pd.NA
    actions = out["accion"] if "accion" in out.columns else pd.Series([None] * len(out))

    costs: list[float | None] = []
    without_carrier: list[bool] = []
    without_rate: list[bool] = []

    for amount, carrier, concept, action in zip(
        out["monto"], out["transportadora"], out["concepto"], actions, strict=False
    ):
        if _is_empty(carrier):
            without_carrier.append(True)
            without_rate.append(False)
            costs.append(None)
            continue

        without_carrier.append(False)
        pair = None
        if not _is_empty(concept):
            base = (_key(concept), str(carrier))
            service = None if _is_empty(action) else str(action)
            pair = index.get((*base, service)) or index.get((*base, None))
        if pair is None or not _valid_rate(pair[1]) or not _valid_rate(pair[0]):
            without_rate.append(True)
            costs.append(None)
            continue

        without_rate.append(False)
        costs.append(compute_cost(amount, float(pair[0]), float(pair[1])))

    out["costo"] = costs
    out["sin_transportadora"] = without_carrier
    out["sin_tarifa"] = without_rate
    return out


# --------------------------------------------------------------------------- #
# Extension M6 (U6): costeo de recomendaciones de fondos (ambito 'Fondos')     #
# Funciones propias de M6; no comparten el costeo por concepto de M1/M2/M3.  #
# --------------------------------------------------------------------------- #

#: Mapeo operacion M6 -> concepto base del Anexo E ambito 'Fondos'.
#: El traslado se resuelve aparte (concepto depende del par de ciudades).
_CONCEPT_BY_OPERATION: dict[str, str] = {
    "banrep_consignacion": "Consignación BanRep",
    "banrep_retiro": "Retiro BanRep",
    "intercambio": "Costo intercambio",
    "cambio_denominacion": "Costo intercambio",  # (misma tarifa)
}


def _is_note(concept: object) -> bool:
    """Indica si una fila del Anexo E es una nota (no una tarifa).

    Las filas-nota del Anexo E empiezan por `*` (reglas de negocio embebidas, no
    tarifas) y deben descartarse del motor de costos.

    Args:
        concept: Valor crudo de la columna `concepto`.

    Returns:
        bool: `True` si el concepto es una nota (empieza por `*`).
    """
    if concept is None or (isinstance(concept, float) and pd.isna(concept)):
        return False
    return str(concept).strip().startswith("*")


def _load_fund_rates() -> pd.DataFrame:
    """Lee las tarifas del Anexo E ambito 'Fondos' (descarta notas).

    Returns:
        pd.DataFrame: Columnas `concepto`, `transportadora`, `costo_fijo`,
        `tarifa`. Vacio con esas columnas si no hay datos de Fondos.
    """
    anexo = storage.read_table(_URI_COSTS_ANEXO_E)
    fon = anexo[anexo["ambito"] == _FUNDS_SCOPE].copy()
    fon = fon[~fon["concepto"].map(_is_note)]
    columns = [c for c in ("concepto", "transportadora", "costo_fijo", "tarifa") if c in fon.columns]
    return fon[columns].reset_index(drop=True)


def _norm_concept(s: object) -> str:
    """Normaliza una cadena de concepto/ciudad para el match.

    Quita acentos (NFKD), recorta espacios y pasa a MAYUSCULAS. Se aplica a AMBOS
    lados del match (clave construida y columna `concepto` del Anexo), de modo
    que el casing del Anexo (title-case) deje de importar frente a las ciudades
    en MAYUSCULAS de `dim_fondo`.

    Args:
        s: Cadena cruda (concepto o ciudad).

    Returns:
        str: Cadena normalizada (NFKD -> ASCII, strip, upper).
    """
    decomposed = unicodedata.normalize("NFKD", str(s))
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().upper()


def _concept_of_row(entry: pd.Series) -> str | None:
    """Resuelve el concepto del Anexo E para una recomendacion M6.

    Para `traslado` el concepto depende del par de ciudades
    (`Traslado {ciudad_origen}-{ciudad_destino}`); el resto usan el mapeo fijo
    `_CONCEPT_BY_OPERATION`. `venta` NO tiene concepto tarifado en Fondos
    -> `None`.

    Args:
        entry: Fila de la recomendacion con `operacion` y, para traslado,
            `ciudad_origen`/`ciudad_destino`.

    Returns:
        str | None: Concepto base (sin normalizar) o `None` si la operacion no
        tiene concepto tarifado en Fondos.
    """
    operation = str(entry.get("operacion", "")).strip()
    if operation == "traslado":
        city_o = entry.get("ciudad_origen")
        city_d = entry.get("ciudad_destino")
        if city_o is None or city_d is None:
            return None
        return f"Traslado {city_o}-{city_d}"
    return _CONCEPT_BY_OPERATION.get(operation)


def compute_costs_m6(df: pd.DataFrame, rates: pd.DataFrame | None = None) -> pd.DataFrame:
    """Costea las recomendaciones M6 por operacion -> concepto Anexo E.

    `df` trae `monto`, `transportadora`, `operacion` y, para traslado,
    `ciudad_origen`/`ciudad_destino`. Resuelve el concepto comparando SIEMPRE con
    `_norm_concept` en AMBOS lados, aplica
    `compute_cost(fijo + monto/10.000 x tarifa)` y las MISMAS reglas duras que
    `compute_costs`:
      - sin transportadora -> `sin_transportadora=True`, costo NULL.
      - tarifa/fijo `No Disponible`/NaN -> `sin_tarifa=True`, costo NULL.
      - traslado intra-ciudad distinta TDV -> costo 0 (nota oficial),
        `costo_regla='cero_misma_ciudad'` (requiere `ciudad_origen` ==
        `ciudad_destino`; la deteccion de distinta TDV la hace el recomendador).
      - venta -> sin concepto tarifado en Fondos: costo NULL,
        `sin_tarifa=True`, `costo_regla='sin_concepto'`.
    La tarifa de traslado se busca con la `transportadora` del df, que el
    recomendador fija = TDV del fondo ORIGEN. NUNCA inventa tarifa.

    Args:
        df: Recomendaciones M6 (salida de `u6.recomendador.recomendar_acciones_m6`).
        rates: Tabla de tarifas de Fondos ya cargada (opcional; util en tests).
            Si es `None` se leen de `interim/costos_anexo_e` (ambito `Fondos`).

    Returns:
        pd.DataFrame: Copia de `df` con columnas `costo` (float o NULL),
        `sin_transportadora` (bool), `sin_tarifa` (bool), `concepto_costo`
        (str o NULL) y `costo_regla` (str:
        `anexo_e`|`cero_misma_ciudad`|`sin_tarifa`|`sin_concepto`|`sin_transportadora`).
    """
    out = df.copy().reset_index(drop=True)
    table = rates if rates is not None else _load_fund_rates()

    # Indice (concepto_norm, transportadora) -> (costo_fijo, tarifa).
    index: dict[tuple[str, object], tuple[object, object]] = {}
    if not table.empty:
        for _, row in table.iterrows():
            key = (_norm_concept(row["concepto"]), row.get("transportadora"))
            index[key] = (row.get("costo_fijo"), row.get("tarifa"))

    if "transportadora" not in out.columns:
        out["transportadora"] = pd.NA

    costs: list[float | None] = []
    without_carrier: list[bool] = []
    without_rate: list[bool] = []
    concepts: list[str | None] = []
    rules: list[str] = []

    for _, entry in out.iterrows():
        amount = entry.get("monto")
        operation = str(entry.get("operacion", "")).strip()
        carrier = entry.get("transportadora")

        # Regla: traslado intra-ciudad (misma ciudad) = costo 0.
        if operation == "traslado":
            city_o = entry.get("ciudad_origen")
            city_d = entry.get("ciudad_destino")
            if city_o is not None and city_d is not None and _norm_concept(city_o) == _norm_concept(city_d):
                costs.append(0.0)
                without_carrier.append(False)
                without_rate.append(False)
                concepts.append(None)
                rules.append("cero_misma_ciudad")
                continue

        concept = _concept_of_row(entry)
        if concept is None:
            # venta u operacion sin concepto tarifado en Fondos.
            costs.append(None)
            without_carrier.append(False)
            without_rate.append(True)
            concepts.append(None)
            rules.append("sin_concepto")
            continue

        try:
            missing_carrier = bool(pd.isna(carrier))
        except (TypeError, ValueError):
            missing_carrier = False
        missing_carrier = missing_carrier or carrier is None or (isinstance(carrier, str) and carrier.strip() == "")
        if missing_carrier:
            costs.append(None)
            without_carrier.append(True)
            without_rate.append(False)
            concepts.append(concept)
            rules.append("sin_transportadora")
            continue

        fixed, rate = index.get((_norm_concept(concept), carrier), (None, None))
        if not _valid_rate(rate) or not _valid_rate(fixed):
            costs.append(None)
            without_carrier.append(False)
            without_rate.append(True)
            concepts.append(concept)
            rules.append("sin_tarifa")
            continue

        costs.append(compute_cost(amount, float(fixed), float(rate)))
        without_carrier.append(False)
        without_rate.append(False)
        concepts.append(concept)
        rules.append("anexo_e")

    out["costo"] = costs
    out["sin_transportadora"] = without_carrier
    out["sin_tarifa"] = without_rate
    out["concepto_costo"] = concepts
    out["costo_regla"] = rules
    return out
