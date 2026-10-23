"""Calendario colombiano detallado para el ML global de la fase 2 (`global_ml.py`). Determinista: solo fechas.

Se construye SOBRE `daas.forecasting.global_gbm.calendar` (pagos corridos al habil anterior, dias desde/hasta pago)
y `daas.features.calendar.build_calendar` (festivos CO con `holidays` + overrides de `conf/calendario_co.yml`), sin
modificarlos: las columnas de Santiago siguen iguales y aqui solo se agregan columnas nuevas.

Por que existe: en `daas/features/calendar.py` `es_vispera_festivo`/`es_post_festivo` no exigen dia habil (el
domingo 16-ago-2026, antes del festivo lunes 17, es vispera; el sabado 8-ago, tras el festivo viernes 7, es post) y
no hay variable para "ultimo habil antes de un puente" ni para la longitud del bloque no habil. Las columnas
`*_habil` y `*_bloque` de abajo corrigen eso sin tocar las viejas.

Grupos (los usa `global_ml.GROUPS_ML`):
- `pago_detalle`: es_pago, pago_15, pago_fin, pago_mas_1..3, pago_menos_1, dia_1, dia_2, habiles_desde_pago,
  habiles_hasta_pago (dias habiles en (pago anterior, d] y en (d, pago siguiente]; tope 20).
- `festivo_detalle`: no_habil, largo_bloque_no_habil (dias seguidos no habiles que contienen a d; 0 si es habil),
  ultimo_habil_antes_bloque / primer_habil_tras_bloque (habil pegado a un bloque no habil CON festivo), puente
  (dia de un bloque no habil de >= 3 dias con festivo), vispera_habil / post_habil (habil antes / despues de un
  festivo), dias_a_festivo / dias_desde_festivo (dias calendario, tope 15), festivo_ecuador (`holidays` EC,
  frontera de Ipiales).
- `temporada`: mes, semana_mes, prima_jun (15-30 jun), prima_dic (15-24 dic), decembrina (dic), fin_anio (24 y 31
  dic), inicio_anio (1-10 ene), semana_santa (lunes a domingo de la semana del Jueves Santo), feria_cali (25-30 dic),
  carnaval_pasto (2-7 ene).
"""

from __future__ import annotations

from functools import lru_cache

import holidays
import numpy as np
import pandas as pd
from dateutil.easter import easter

from daas.features.calendar import build_calendar
from daas.forecasting.global_gbm import calendar

#: Columnas por grupo (en este orden).
COLUMNAS = {
    "pago_detalle": [
        "es_pago", "pago_15", "pago_fin", "pago_mas_1", "pago_mas_2", "pago_mas_3", "pago_menos_1", "dia_1", "dia_2",
        "habiles_desde_pago", "habiles_hasta_pago",
    ],
    "festivo_detalle": [
        "no_habil", "largo_bloque_no_habil", "ultimo_habil_antes_bloque", "primer_habil_tras_bloque", "puente",
        "vispera_habil", "post_habil", "dias_a_festivo", "dias_desde_festivo", "festivo_ecuador",
    ],
    "temporada": [
        "mes", "semana_mes", "prima_jun", "prima_dic", "decembrina", "fin_anio", "inicio_anio", "semana_santa",
        "feria_cali", "carnaval_pasto",
    ],
}
TOPE_PAGO = 20
TOPE_FESTIVO = 15
#: Margen extra para que bloques, pagos y festivos de los bordes se calculen con su contexto completo.
_MARGEN = pd.Timedelta(days=40)


def _pagos(habil: pd.Series, dias_pago: tuple) -> pd.DataFrame:
    """Fechas de pago por mes (mismo algoritmo que `global_gbm.calendar`) con el dia nominal que las origina."""
    filas = []
    for mes in habil.index.to_period("M").unique():
        for d in dias_pago:
            f = mes.end_time.normalize() if str(d) == "fin" else mes.start_time + pd.Timedelta(days=int(d) - 1)
            while f in habil.index and not habil[f]:
                f -= pd.Timedelta(days=1)
            filas.append({"fecha": f, "nominal": "fin" if str(d) == "fin" else str(int(d))})
    return pd.DataFrame(filas).drop_duplicates("fecha").sort_values("fecha").reset_index(drop=True)


def _habiles_entre(acumulado: np.ndarray, desde: np.ndarray, hasta: np.ndarray) -> np.ndarray:
    """Dias habiles en (desde, hasta] con `acumulado` = suma acumulada de habiles por posicion."""
    return acumulado[hasta] - acumulado[desde]


def _bloques(no_habil: np.ndarray, festivo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Longitud del bloque no habil de cada dia (0 si habil) y si el bloque contiene un festivo."""
    largo = np.zeros(len(no_habil), dtype=int)
    con_festivo = np.zeros(len(no_habil), dtype=bool)
    i = 0
    while i < len(no_habil):
        if not no_habil[i]:
            i += 1
            continue
        j = i
        while j < len(no_habil) and no_habil[j]:
            j += 1
        largo[i:j] = j - i
        con_festivo[i:j] = festivo[i:j].any()
        i = j
    return largo, con_festivo


def _dias_a_evento(evento: np.ndarray, hacia_adelante: bool, tope: int) -> np.ndarray:
    """Dias calendario hasta el proximo (o desde el ultimo) dia con evento; 0 el dia del evento; tope si no hay."""
    n = len(evento)
    salida = np.full(n, tope, dtype=int)
    ultimo = None
    rango = range(n - 1, -1, -1) if hacia_adelante else range(n)
    for i in rango:
        if evento[i]:
            ultimo = i
        if ultimo is not None:
            salida[i] = min(abs(ultimo - i), tope)
    return salida


def _semana_santa(fechas: pd.DatetimeIndex) -> np.ndarray:
    """1 de lunes a domingo de la semana del Jueves Santo (domingo = Pascua)."""
    marca = np.zeros(len(fechas), dtype=int)
    for anio in sorted(set(fechas.year)):
        domingo = pd.Timestamp(easter(anio))
        marca |= ((fechas >= domingo - pd.Timedelta(days=6)) & (fechas <= domingo)).astype(int)
    return marca


@lru_cache(maxsize=8)
def calendario_detallado(desde: pd.Timestamp, hasta: pd.Timestamp, dias_pago: tuple = ("15", "fin")) -> pd.DataFrame:
    """Variables de calendario de Santiago + las nuevas, por fecha, con el MISMO indice que `global_gbm.calendar`.

    El resultado se comparte por `lru_cache`: no modificarlo (copiar antes si hace falta).

    Args:
        desde: Primer dia de la historia (el indice arranca 45 dias antes, como `global_gbm.calendar`).
        hasta: Ultimo dia a pronosticar (el indice termina 45 dias despues).
        dias_pago: Dias nominales de pago ('15', 'fin' o enteros); se corren al habil anterior.

    Returns:
        pd.DataFrame: Indice de fechas; columnas de `global_gbm.calendar` + `COLUMNAS` de los tres grupos nuevos.
    """
    base = calendar(desde, hasta, tuple(dias_pago))
    inicio, fin = base.index.min() - _MARGEN, base.index.max() + _MARGEN
    cal = build_calendar(inicio.date(), fin.date())
    cal.index = pd.to_datetime(cal["fecha"])
    fechas = cal.index
    habil = cal["es_habil"].astype(bool)
    festivo = cal["es_festivo_co"].astype(bool).to_numpy()
    no_habil = ~habil.to_numpy()

    # Pagos: fecha efectiva y dia nominal; dias habiles desde/hasta con suma acumulada de habiles.
    pagos = _pagos(habil, tuple(dias_pago))
    posicion = pd.Series(np.arange(len(fechas)), index=fechas)
    pos_pagos = posicion.reindex(pagos["fecha"]).to_numpy()
    validos = ~np.isnan(pos_pagos)
    pagos, pos_pagos = pagos[validos], pos_pagos[validos].astype(int)
    acumulado = np.cumsum(habil.to_numpy().astype(int))
    i = np.arange(len(fechas))
    anterior = np.searchsorted(pos_pagos, i, side="right") - 1
    siguiente = np.searchsorted(pos_pagos, i, side="left")
    hay_anterior, hay_siguiente = anterior >= 0, siguiente < len(pos_pagos)
    p_ant = pos_pagos[np.clip(anterior, 0, len(pos_pagos) - 1)]
    p_sig = pos_pagos[np.clip(siguiente, 0, len(pos_pagos) - 1)]
    habiles_desde = np.where(hay_anterior, _habiles_entre(acumulado, p_ant, i), TOPE_PAGO)
    habiles_hasta = np.where(hay_siguiente, _habiles_entre(acumulado, i, p_sig), TOPE_PAGO)
    nominal = pd.Series(pagos["nominal"].to_numpy(), index=pd.DatetimeIndex(pagos["fecha"])).reindex(fechas)
    dias_desde_pago = np.where(hay_anterior, i - p_ant, TOPE_PAGO)
    dias_hasta_pago = np.where(hay_siguiente, p_sig - i, TOPE_PAGO)

    largo, con_festivo = _bloques(no_habil, festivo)
    especial = no_habil & con_festivo
    siguiente_especial = np.append(especial[1:], False)
    anterior_especial = np.insert(especial[:-1], 0, False)
    es_habil = habil.to_numpy()

    ecuador = holidays.country_holidays("EC", years=sorted(set(fechas.year)))
    dia, mes = fechas.day.to_numpy(), fechas.month.to_numpy()
    nuevas = pd.DataFrame(
        {
            "es_pago": nominal.notna().astype(int).to_numpy(),
            "pago_15": nominal.eq("15").astype(int).to_numpy(),
            "pago_fin": nominal.eq("fin").astype(int).to_numpy(),
            **{f"pago_mas_{k}": (dias_desde_pago == k).astype(int) for k in (1, 2, 3)},
            "pago_menos_1": (dias_hasta_pago == 1).astype(int),
            "dia_1": (dia == 1).astype(int),
            "dia_2": (dia == 2).astype(int),
            "habiles_desde_pago": np.clip(habiles_desde, 0, TOPE_PAGO),
            "habiles_hasta_pago": np.clip(habiles_hasta, 0, TOPE_PAGO),
            "no_habil": no_habil.astype(int),
            "largo_bloque_no_habil": largo,
            "ultimo_habil_antes_bloque": (es_habil & siguiente_especial).astype(int),
            "primer_habil_tras_bloque": (es_habil & anterior_especial).astype(int),
            "puente": (especial & (largo >= 3)).astype(int),
            "vispera_habil": (cal["es_vispera_festivo"].to_numpy() & es_habil).astype(int),
            "post_habil": (cal["es_post_festivo"].to_numpy() & es_habil).astype(int),
            "dias_a_festivo": _dias_a_evento(festivo, True, TOPE_FESTIVO),
            "dias_desde_festivo": _dias_a_evento(festivo, False, TOPE_FESTIVO),
            "festivo_ecuador": np.array([d.date() in ecuador for d in fechas], dtype=int),
            "mes": mes,
            "semana_mes": (dia - 1) // 7 + 1,
            "prima_jun": ((mes == 6) & (dia >= 15)).astype(int),
            "prima_dic": ((mes == 12) & (dia >= 15) & (dia <= 24)).astype(int),
            "decembrina": (mes == 12).astype(int),
            "fin_anio": ((mes == 12) & np.isin(dia, [24, 31])).astype(int),
            "inicio_anio": ((mes == 1) & (dia <= 10)).astype(int),
            "semana_santa": _semana_santa(fechas),
            "feria_cali": ((mes == 12) & (dia >= 25) & (dia <= 30)).astype(int),
            "carnaval_pasto": ((mes == 1) & (dia >= 2) & (dia <= 7)).astype(int),
        },
        index=fechas,
    )
    columnas = [c for grupo in COLUMNAS.values() for c in grupo]
    return base.join(nuevas[columnas].reindex(base.index))
