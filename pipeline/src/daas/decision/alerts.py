"""Alertas de severidad/estado del subpaquete `forecasting`, `decision` y `modules` (SUP-04/RN-34).

Reuso portado de la demo de 1a ronda, adaptado a la PoC. `classify_alerts`
clasifica la alerta de **agotamiento** a partir de la serie de saldo simulado
por cajero-dia (M1 dispensador; reutilizable por M2 para la misma dimension de
agotamiento). Umbral del 8% del cupo operativo (SUP-04/RN-34), parametrizable.

En M1 y M2 la alerta de agotamiento mira el saldo del dia SIN la provision (`saldo_sin_provision`):
es la alerta que dispara la provision (Anexo B RN-21, RN-34). `classify_alerts_m2` anade la de
**recoleccion**: el saldo al cierre, antes de recoger, supera el cupo (RN-21, RN-35).

`classify_alerts_m3` (U3) anade la **doble alerta** de la boveda de sucursal
fisica: **agotamiento** (reutiliza la dimension saldo<umbral de
`classify_alerts`) y **excedente** (el saldo alcanza el cap duro de la boveda
`cupo_max_suc`). Opera sobre la serie de saldo simulado de M3, cuyo id de
entidad ya viene renombrado a `cod_cajero` (id compartido enmascarado) por el
orquestador `run_u3`. NO modifica `classify_alerts`/`classify_alerts_m2`.
"""

from __future__ import annotations

import pandas as pd

#: Columnas minimas esperadas en la serie de saldo simulado.
_COL_BALANCE = "saldo"
_COL_THRESHOLD = "umbral_valor"
_COL_ATM = "cod_cajero"
_COL_DATE = "fecha"
#: Saldo del dia sin provision (M1/M2) y saldo al cierre antes de recoger (M2).
_COL_WITHOUT_PROVISION = "saldo_sin_provision"
_COL_BEFORE_COLLECTION = "saldo_antes_recoleccion"
_COL_CAPACITY = "cupo_operativo"


def _depletion_severity(balance: float, threshold: float) -> str:
    """Deriva la severidad de agotamiento de un dia (ok/alerta/critico).

    Con el motor de saldo corregido el saldo esta siempre en
    `[0, cupo]`: un saldo agotado se expresa como `saldo == 0` (el ATM se quedo
    sin efectivo ese dia), ya no como un numero negativo.

    Args:
        balance: Saldo simulado del dia (clipado en `[0, cupo]`).
        threshold: Valor umbral de agotamiento (`umbral * cupo_operativo`).

    Returns:
        str: `'critico'` si el saldo esta agotado (`saldo <= 0`), `'alerta'` si
        `0 < saldo < umbral` y `'ok'` en caso contrario.
    """
    if pd.isna(balance) or pd.isna(threshold):
        return "ok"
    if balance <= 0:
        return "critico"
    if balance < threshold:
        return "alerta"
    return "ok"


def classify_alerts(df: pd.DataFrame, col_balance: str = _COL_BALANCE) -> pd.DataFrame:
    """Clasifica la alerta de agotamiento por cajero-dia (SUP-04/RN-34).

    Dada la serie de saldo simulado (salida de
    `modules.atm_m1_m2.balance.simular_saldo_m1`), marca el estado/severidad de
    agotamiento: riesgo cuando el saldo cae por debajo del umbral (8% del cupo
    operativo por defecto). Devuelve SOLO las filas en riesgo (severidad distinta
    de `'ok'`), reutilizable por M2 para la misma dimension.

    Args:
        df: Serie de saldo simulado con columnas `cod_cajero`, `fecha`, `col_saldo`
            y `umbral_valor` (valor umbral absoluto de agotamiento).
        col_balance: Saldo que se compara con el umbral (`saldo`, o `saldo_sin_provision` en M1/M2).
            Se reporta con piso en 0.

    Returns:
        pd.DataFrame: Alertas con columnas `cod_cajero`, `fecha`,
        `tipo` (='agotamiento'), `severidad`, `saldo`, `umbral`. Vacio (con esas
        columnas) si ningun cajero-dia esta en riesgo.

    Raises:
        KeyError: Si faltan columnas obligatorias en `df`.
    """
    columns = ["cod_cajero", "fecha", "tipo", "severidad", "saldo", "umbral"]
    missing = {col_balance, _COL_THRESHOLD, _COL_ATM, _COL_DATE} - set(df.columns)
    if missing:
        raise KeyError(f"classify_alerts: faltan columnas {sorted(missing)}.")

    work = df.copy()
    work["severidad"] = [
        _depletion_severity(s, u) for s, u in zip(work[col_balance], work[_COL_THRESHOLD], strict=False)
    ]
    work[_COL_BALANCE] = work[col_balance].clip(lower=0.0)
    in_risk = work[work["severidad"] != "ok"].copy()
    if in_risk.empty:
        return pd.DataFrame(columns=columns)

    in_risk["tipo"] = "agotamiento"
    in_risk = in_risk.rename(columns={_COL_THRESHOLD: "umbral"})
    out = in_risk[columns].sort_values(["cod_cajero", "fecha"]).reset_index(drop=True)
    return out


def classify_alerts_m2(df: pd.DataFrame) -> pd.DataFrame:
    """Clasifica la DOBLE alerta del multifuncional M2 (Anexo B RN-21, RN-33).

    - `'agotamiento'` (provision): sin la provision, el saldo del dia bajaria del umbral
      (`saldo_sin_provision < umbral_valor`); `critico` si se agotaria.
    - `'recoleccion'`: el saldo al cierre, antes de recoger, supera el cupo
      (`saldo_antes_recoleccion > cupo_operativo`, RN-35).

    Args:
        df: Salida de `modules.atm_m1_m2.balance.simular_saldo_m2`, concatenada por cajero.

    Returns:
        pd.DataFrame: Alertas con columnas `cod_cajero`, `fecha`, `tipo`, `severidad`, `nivel`,
        `limite`. En agotamiento `nivel` es el saldo sin provision y `limite` el umbral; en
        recoleccion, el saldo antes de recoger y el cupo. Vacio si ningun cajero-dia esta en riesgo.

    Raises:
        KeyError: Si faltan columnas obligatorias en `df`.
    """
    columns = ["cod_cajero", "fecha", "tipo", "severidad", "nivel", "limite"]
    required = {
        _COL_WITHOUT_PROVISION,
        _COL_THRESHOLD,
        _COL_ATM,
        _COL_DATE,
        _COL_BEFORE_COLLECTION,
        _COL_CAPACITY,
    }
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"classify_alerts_m2: faltan columnas {sorted(missing)}.")

    depletion = classify_alerts(df, col_balance=_COL_WITHOUT_PROVISION)
    depletion = depletion.rename(columns={"saldo": "nivel", "umbral": "limite"})

    collection = df[df[_COL_BEFORE_COLLECTION] > df[_COL_CAPACITY]].copy()
    if not collection.empty:
        collection["tipo"] = "recoleccion"
        collection["severidad"] = "alerta"
        collection = collection.rename(columns={_COL_BEFORE_COLLECTION: "nivel", _COL_CAPACITY: "limite"})
        collection = collection[columns]

    parts = [
        p for p in (depletion[columns], collection if not collection.empty else None) if p is not None and not p.empty
    ]
    if not parts:
        return pd.DataFrame(columns=columns)
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["cod_cajero", "fecha", "tipo"]).reset_index(drop=True)
    return out


def _surplus_severity(balance: float, cap: float) -> str:
    """Deriva la severidad de excedente de la boveda de un dia (ok/alerta/critico).

    Con el motor de saldo M3 el saldo esta clipado a `[0, cupo_max_suc]`: un
    excedente se expresa como `saldo >= cap` (la boveda alcanzo su maximo y hubo
    que recolectar).

    Args:
        balance: Saldo simulado del dia (clipado en `[0, cap]`, U3).
        cap: Cap duro de la boveda (`cupo_max_suc`).

    Returns:
        str: `'critico'` si el saldo alcanza o supera el cap (`saldo >= cap`) y
        `'ok'` en caso contrario.
    """
    if pd.isna(balance) or pd.isna(cap):
        return "ok"
    if balance >= cap:
        return "critico"
    return "ok"


def classify_alerts_m3(df: pd.DataFrame) -> pd.DataFrame:
    """Clasifica la DOBLE alerta de la boveda de sucursal M3 (U3).

    Emite dos tipos de alerta sobre la serie de saldo simulado de M3 (salida de
    `modules.branches_m3.balance.simular_saldo_m3`, con el id de entidad ya renombrado a
    `cod_cajero` por `run_u3`):

    - `'agotamiento'`: riesgo de quedarse sin efectivo; reutiliza la dimension
      de agotamiento de `classify_alerts` (saldo < umbral del cupo).
    - `'excedente'`: la boveda alcanza su cap duro `cupo_max_suc` (hubo que
      recolectar el exceso): `nivel = saldo`, `limite = cupo_max_suc`.

    Args:
        df: Serie de saldo simulado M3 con columnas `cod_cajero`, `fecha`,
            `saldo`, `umbral_valor` y `cupo_operativo` (= `cupo_max_suc`).

    Returns:
        pd.DataFrame: Alertas con columnas `cod_cajero`, `fecha`, `tipo`
        (`'agotamiento'` o `'excedente'`), `severidad`, `nivel`, `limite`. En las
        de agotamiento `nivel` es el saldo y `limite` el umbral; en las de
        excedente `nivel` es el saldo y `limite` el cap `cupo_max_suc`. Vacio
        (con esas columnas) si ninguna sucursal-dia esta en riesgo.

    Raises:
        KeyError: Si faltan columnas obligatorias en `df`.
    """
    columns = ["cod_cajero", "fecha", "tipo", "severidad", "nivel", "limite"]
    required = {_COL_BALANCE, _COL_THRESHOLD, _COL_ATM, _COL_DATE, _COL_CAPACITY}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"classify_alerts_m3: faltan columnas {sorted(missing)}.")

    # (a) Agotamiento: reutiliza la dimension de M1/.
    depletion = classify_alerts(df)
    depletion = depletion.rename(columns={"saldo": "nivel", "umbral": "limite"})

    # (b) Excedente: la boveda alcanza su cap duro cupo_max_suc.
    work = df.copy()
    work["severidad"] = [_surplus_severity(s, c) for s, c in zip(work[_COL_BALANCE], work[_COL_CAPACITY], strict=False)]
    surplus = work[work["severidad"] != "ok"].copy()
    if not surplus.empty:
        surplus["tipo"] = "excedente"
        surplus = surplus.rename(columns={_COL_BALANCE: "nivel", _COL_CAPACITY: "limite"})
        surplus = surplus[columns]

    parts = [p for p in (depletion[columns], surplus if not surplus.empty else None) if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=columns)
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["cod_cajero", "fecha", "tipo"]).reset_index(drop=True)
    return out


#: Columnas de la dimension de balance de fondo (M6).
_COL_FUND = "fondo_id"
_COL_BALANCE_M6 = "saldo_proyectado"
_COL_MIN = "minimo"
_COL_MAX = "maximo"
_COL_DEFICIT = "deficit"
_COL_DENOM = "denominacion"


def classify_alerts_m6(df: pd.DataFrame) -> pd.DataFrame:
    """Clasifica la DOBLE alerta de fondo por denominacion de M6 (U6).

    Emite dos tipos de alerta sobre el balance simulado de M6 (salida de
    `modules.funds_m6.balance.simular_balance_fondo_denominacion`), que trae la llave
    como `fondo_id` (NO `cod_cajero` todavia) y una fila por
    (fondo_id, denominacion, fecha):

    - `'deficit'`: el saldo proyectado cae por debajo del minimo operativo
      (`saldo < minimo`); severidad `'critico'` si el saldo quedo agotado
      (`saldo == 0` con `deficit > 0`), `'alerta'` en otro caso. `nivel = saldo`,
      `limite = minimo`.
    - `'exceso'`: el saldo supera el maximo operativo (`saldo > maximo`);
      severidad `'critico'`. `nivel = saldo`, `limite = maximo`.

    Replica el reparto de responsabilidades de `classify_alerts_m3`: NO anade la
    columna `modelo` ni renombra la llave; es el orquestador `run_u6` quien
    renombra `fondo_id -> cod_cajero` y anade `modelo='m6'` (`.assign`) antes de
    publicar.

    Args:
        df: Balance simulado M6 con columnas `fondo_id`, `fecha`,
            `saldo_proyectado`, `minimo`, `maximo`, `deficit`, `denominacion` y
            las banderas `riesgo_deficit`/`riesgo_exceso`.

    Returns:
        pd.DataFrame: Alertas con columnas `fondo_id`, `fecha`, `tipo`
        (`'deficit'`/`'exceso'`), `severidad`, `nivel`, `limite`, `denominacion`.
        Vacio (con esas columnas) si ningun fondo-denominacion-dia esta en riesgo.

    Raises:
        KeyError: Si faltan columnas obligatorias en `df`.
    """
    columns = [
        _COL_FUND,
        _COL_DATE,
        "tipo",
        "severidad",
        "nivel",
        "limite",
        _COL_DENOM,
    ]
    required = {
        _COL_FUND,
        _COL_DATE,
        _COL_BALANCE_M6,
        _COL_MIN,
        _COL_MAX,
        _COL_DEFICIT,
        _COL_DENOM,
    }
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"classify_alerts_m6: faltan columnas {sorted(missing)}.")

    work = df.copy()

    # (a) Deficit: saldo < minimo (critico si saldo==0 con deficit>0).
    deficit = work[work[_COL_BALANCE_M6] < work[_COL_MIN]].copy()
    if not deficit.empty:
        deficit["tipo"] = "deficit"
        deficit["severidad"] = [
            "critico" if (s <= 0.0 and d > 0.0) else "alerta"
            for s, d in zip(deficit[_COL_BALANCE_M6], deficit[_COL_DEFICIT], strict=False)
        ]
        deficit["nivel"] = deficit[_COL_BALANCE_M6]
        deficit["limite"] = deficit[_COL_MIN]
        deficit = deficit[columns]

    # (b) Exceso: saldo > maximo (critico).
    excess = work[work[_COL_MAX].notna() & (work[_COL_BALANCE_M6] > work[_COL_MAX])].copy()
    if not excess.empty:
        excess["tipo"] = "exceso"
        excess["severidad"] = "critico"
        excess["nivel"] = excess[_COL_BALANCE_M6]
        excess["limite"] = excess[_COL_MAX]
        excess = excess[columns]

    parts = [
        p
        for p in (
            deficit if not deficit.empty else None,
            excess if not excess.empty else None,
        )
        if p is not None and not p.empty
    ]
    if not parts:
        return pd.DataFrame(columns=columns)
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values([_COL_FUND, _COL_DENOM, _COL_DATE, "tipo"]).reset_index(drop=True)
    return out
