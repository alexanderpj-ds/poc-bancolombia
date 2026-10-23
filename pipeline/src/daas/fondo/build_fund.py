"""Construccion del FONDO del subpaquete `fondo`.

El FONDO = ``CIUDAD|TRANSPORTADORA`` es la llave transversal de la PoC. Reglas
de negocio:

  - ``build_fund_id(ciudad, transportadora)`` normaliza (upper, sin tildes,
    trim) y valida el dominio: ``ciudad in {CALI, PASTO, IPIALES}`` y
    ``transportadora`` con patron ``TRANSPORTADORA_00[1-4]``. Fuera de dominio
    retorna ``None`` (marca de cuarentena) en lugar de adivinar.
  - ``dim_fondo`` es la dimension **autoritativa** y lista exactamente los
    **6 fondos** de la PoC: Cali (001-004), Pasto (001), Ipiales (002). La 002
    cubre Cali e Ipiales. Se deriva de la fuente operativa de disponibilidad
    (C-09 disponibles, filtrada a ciudades en alcance), que produce justamente
    estos 6 pares; clientes/CBR/intercambios traen pares adicionales
    (p.ej. Ipiales 001/003) que NO constituyen fondos operativos, por lo que
    ``dim_fondo`` se ancla a disponibles. V-10 es fatal si ``dim_fondo`` != 6.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

#: Ciudades validas del dominio FONDO (en alcance de la PoC).
VALID_CITIES = ("CALI", "PASTO", "IPIALES")
#: Patron de transportadora canonica (TRANSPORTADORA_001..004).
_TDV_PATTERN = re.compile(r"^TRANSPORTADORA_00[1-4]$")
#: Numero autoritativo de fondos de la PoC; V-10 es fatal si difiere.
EXPECTED_FUND_COUNT = 6

#: Composicion autoritativa de los 6 fondos (derivada de C-09 disponibles,
#: ciudades en alcance): (ciudad, transportadora).
_AUTHORITATIVE_FUNDS = (
    ("CALI", "TRANSPORTADORA_001"),
    ("CALI", "TRANSPORTADORA_002"),
    ("CALI", "TRANSPORTADORA_003"),
    ("CALI", "TRANSPORTADORA_004"),
    ("PASTO", "TRANSPORTADORA_001"),
    ("IPIALES", "TRANSPORTADORA_002"),
)


def _normalize(text: str) -> str:
    """Normaliza un texto a mayusculas, sin tildes y recortado.

    Args:
        text: Cadena cruda (ciudad o transportadora).

    Returns:
        str: Texto normalizado (NFKD -> ASCII, upper, strip).
    """
    if text is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().upper()


def build_fund_id(city: str, carrier: str) -> str | None:
    """Construye ``fondo_id = CIUDAD|TRANSPORTADORA`` normalizado y validado.

    Normaliza ambos componentes (upper, sin tildes, trim) y valida el dominio.
    Si la ciudad no esta en ``VALID_CITIES`` o la transportadora no cumple
    el patron ``TRANSPORTADORA_00[1-4]``, retorna ``None`` (fila candidata a
    cuarentena); no adivina.

    Args:
        city: Ciudad del fondo (p.ej. ``"Cali"``, ``"CALI "``).
        carrier: Transportadora (p.ej. ``"transportadora_001"``).

    Returns:
        str | None: ``"CIUDAD|TRANSPORTADORA"`` si es valido; ``None`` si no.
    """
    city_n = _normalize(city)
    tdv_n = _normalize(carrier)
    if city_n not in VALID_CITIES:
        return None
    if not _TDV_PATTERN.match(tdv_n):
        return None
    return f"{city_n}|{tdv_n}"


def build_dim_fund() -> pd.DataFrame:
    """Construye ``dim_fondo``, la dimension autoritativa de los 6 fondos.

    Returns:
        pd.DataFrame: Columnas ``fondo_id`` (str, llave), ``ciudad`` (str),
        ``transportadora`` (str). Exactamente ``EXPECTED_FUND_COUNT`` filas.
    """
    records = []
    for city, tdv in _AUTHORITATIVE_FUNDS:
        fund_id = build_fund_id(city, tdv)
        records.append({"fondo_id": fund_id, "ciudad": city, "transportadora": tdv})
    dim = pd.DataFrame.from_records(records)
    dim["fondo_id"] = dim["fondo_id"].astype("string")
    dim["ciudad"] = dim["ciudad"].astype("string")
    dim["transportadora"] = dim["transportadora"].astype("string")
    return dim.reset_index(drop=True)
