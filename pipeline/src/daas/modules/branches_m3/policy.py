"""Politica diferenciada por sucursal para M3 (RN-37..RN-44).

Cada sucursal lleva tres numeros sacados de su historia (ultimos `historia_dias` <= corte): mu de salidas,
sigma del neto diario (salidas - entradas) y su perfil (entradas > salidas o al reves). De ahi salen tres
niveles en pesos enteros, todos DATO (`conf/model_m3.yml -> politica`), nada hardcodeado:

- reserva  = min(reserva_max, max(umbral, k_reserva * sigma / cupo)) * cupo      (cuando provisionar)
- objetivo = min(cupo, reserva + dias_cobertura * mu_salidas)                    (hasta donde provisionar;
             cupo si `dias_cobertura` es null)
- techo    = min(cupo, reserva + dias_techo * mu_salidas)                        (hasta donde recoger;
             cupo si `dias_techo` es null)

Con menos de `min_obs` dias validos la sucursal cae a la regla no diferenciada (reserva = umbral * cupo, llena
al cupo, recoge sobre el cupo). Si `historia_corta_regla_vigente` esta activo (RN-16/RN-52), esa sucursal
ademas decide SIN pronostico: aplica la regla vigente del banco (saldo de apertura < umbral -> cupo), porque con
menos de `min_obs` dias no se ha visto ni una quincena con su fin de mes y el pronostico extrapola.
Es la misma politica V3 `dif_ocioso` medida en el simulador de sucursales del laboratorio (el chequeo
`--chequeo-pipeline` del lab compara las dos implementaciones con diferencia 0 COP).
Este modulo es nucleo puro (sin FastAPI, sin I/O).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

#: Politica por defecto documentada (se aplica clave a clave si falta en `model_m3.yml`).
DEFAULT_POLICY: dict[str, Any] = {
    "activa": True,
    "historia_dias": 180,
    "min_obs": 30,
    "reserva_max": 0.5,
    "k_reserva": 1.0,
    "dias_cobertura": 3,
    "dias_techo": 6,
    "usa_pronostico": True,
    "historia_corta_regla_vigente": True,
}

OUTFLOW_PROFILE = "neto_salida"
INFLOW_PROFILE = "neto_entrada"
NO_HISTORY = "sin_historia"
CURRENT_RULE_PROFILE = "regla_vigente"


def load_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Politica efectiva: lo de `config['politica']` sobre `DEFAULT_POLICY`."""
    out = dict(DEFAULT_POLICY)
    out.update(config.get("politica") or {})
    return out


def policy_params(
    inflows: pd.DataFrame, outflows: pd.DataFrame, capacity: pd.Series, threshold: float, pol: dict[str, Any]
) -> pd.DataFrame:
    """Reserva, objetivo y techo en pesos enteros por sucursal, con la historia recibida (<= corte).

    Args:
        inflows: Ancho (fecha x sucursal) de entradas reales; ya recortado a fechas <= corte.
        outflows: Ancho (fecha x sucursal) de salidas reales; mismo recorte.
        capacity: `cupo_max_suc` vigente por sucursal (indice = sucursal).
        threshold: `m3.umbral_agotamiento` (fraccion del cupo).
        pol: Politica (ver `load_policy`).

    Returns:
        pd.DataFrame indexado por sucursal: `reserva`, `objetivo`, `techo`, `valido`, `perfil`, `mu_salidas`,
        `mu_entradas`, `sigma_neto`, `reserva_frac`, `usa_pronostico` (por sucursal: falso en la regla vigente de
        la historia corta; `perfil` = `regla_vigente`).
    """
    entities = list(capacity.index)
    h = int(pol["historia_dias"])
    e = inflows.reindex(columns=entities).tail(h)
    s = outflows.reindex(columns=entities).tail(h)
    net = s - e
    c = capacity.to_numpy(float)
    valid = net.notna().sum().to_numpy() >= int(pol["min_obs"])
    mu_s, mu_e = s.mean().to_numpy(), e.mean().to_numpy()
    sd = net.std(ddof=0).to_numpy()
    frac = np.where(
        valid,
        np.minimum(float(pol["reserva_max"]), np.maximum(threshold, float(pol["k_reserva"]) * sd / c)),
        threshold,
    )
    reserve = np.floor(frac * c)
    target, ceiling = c.copy(), c.copy()
    for days, destination in ((pol["dias_cobertura"], target), (pol["dias_techo"], ceiling)):
        if days is not None:
            destination[valid] = np.floor(np.minimum(c, reserve + float(days) * mu_s)[valid])
    current = (~valid) & bool(pol.get("historia_corta_regla_vigente", False))
    without_hist = CURRENT_RULE_PROFILE if bool(pol.get("historia_corta_regla_vigente", False)) else NO_HISTORY
    profile = np.where(valid & (mu_s > mu_e), OUTFLOW_PROFILE, np.where(valid, INFLOW_PROFILE, without_hist))
    uses_forecast = np.where(current, False, bool(pol.get("usa_pronostico", True)))
    return pd.DataFrame(
        {
            "reserva": reserve,
            "objetivo": target,
            "techo": ceiling,
            "valido": valid,
            "perfil": profile,
            "mu_salidas": mu_s,
            "mu_entradas": mu_e,
            "sigma_neto": sd,
            "reserva_frac": frac,
            "usa_pronostico": uses_forecast,
        },
        index=pd.Index(entities, name=capacity.index.name),
    )


def _cop(x: float) -> str:
    """Pesos enteros con separador de miles colombiano."""
    return "$" + f"{float(x):,.0f}".replace(",", ".")


def _pct(x: float) -> str:
    return f"{100 * float(x):.1f} %".replace(".", ",")


def explain_action(a: dict[str, Any], pol: dict[str, Any]) -> str:
    """Explicacion funcional de una accion (RN-40/41), con los numeros de la sucursal.

    Args:
        a: Fila de la accion con `accion`, `regla`, `monto`, `cupo`, `saldo_antes`, `saldo_despues`, `saldo_previsto`,
            `entradas`, `salidas`, parametros de la sucursal (`reserva`, `objetivo`, `techo`, `perfil`,
            `mu_salidas`, `mu_entradas`, `sigma_neto`, `reserva_frac`) y tarifa (`costo`, `costo_fijo`,
            `tarifa_10k`; pueden ser NaN).
        pol: Politica (para citar k, dias de cobertura y de techo).
    """
    profile = {
        OUTFLOW_PROFILE: "la sucursal paga más de lo que recibe (salidas medias {ms}/día > entradas medias {me}/día)",
        INFLOW_PROFILE: "la sucursal recibe más de lo que paga (entradas medias {me}/día > salidas medias {ms}/día)",
    }.get(a["perfil"])
    if a["perfil"] == CURRENT_RULE_PROFILE:
        hist = (
            f"Tiene menos de {pol['min_obs']} días válidos de historia "
            f"(no se ha visto ni una quincena con su fin de mes): "
            f"se aplica la regla vigente del banco, sin pronóstico "
            f"(provisiona hasta el cupo si el saldo de apertura queda "
            f"bajo el {_pct(a['reserva_frac'])} del cupo; recoge solo lo que pase del cupo) (RN-16, RN-52)."
        )
    elif profile:
        hist = (
            f"En sus últimos {pol['historia_dias']} días "
            + profile.format(ms=_cop(a["mu_salidas"]), me=_cop(a["mu_entradas"]))
            + f"; el neto diario varía {_cop(a['sigma_neto'])} (σ)."
        )
    else:
        hist = (
            f"Tiene menos de {pol['min_obs']} días válidos de historia: se aplica la regla no diferenciada "
            f"(reserva {_pct(a['reserva_frac'])} del cupo, llena al cupo, recoge solo lo que pase del cupo)."
        )
    reserve = f"reserva {_cop(a['reserva'])} = {_pct(a['reserva_frac'])} del cupo {_cop(a['cupo'])}" + (
        f" (máx(umbral, {pol['k_reserva']:g}·σ/cupo), tope {_pct(pol['reserva_max'])})" if profile else ""
    )
    if a["accion"] == "provision":
        if a["regla"] == "saldo_previsto_bajo_reserva":
            cause = (
                f"Provisión por riesgo de faltante: el saldo previsto del día ({_cop(a['saldo_previsto'])} = apertura "
                f"{_cop(a['saldo_antes'])} + entradas {_cop(a['entradas'])} − salidas {_cop(a['salidas'])}) "
                f"queda bajo la {reserve}."
            )
        else:
            cause = (
                f"Provisión por riesgo de faltante: el saldo de apertura ({_cop(a['saldo_antes'])}) "
                f"queda bajo la {reserve}."
            )
        destination = (
            f"Se sube el saldo a {_cop(a['saldo_despues'])} = reserva + {pol['dias_cobertura']} días "
            f"de salidas medias, con tope en el cupo."
            if profile and pol["dias_cobertura"] is not None
            else f"Se completa hasta el cupo ({_cop(a['saldo_despues'])})."
        )
    else:
        if a["regla"] == "exceso_sobre_cupo":
            cause = (
                f"Recolección por riesgo de exceder el cupo: el saldo al cierre ({_cop(a['saldo_antes'])}) "
                f"pasa el cupo {_cop(a['cupo'])}."
            )
        else:
            cause = (
                f"Recolección por efectivo ocioso: el saldo al cierre ({_cop(a['saldo_antes'])}) "
                f"pasa el techo {_cop(a['techo'])} "
                f"(reserva + {pol['dias_techo']} días de salidas medias, tope en el cupo {_cop(a['cupo'])})."
            )
        destination = f"Se recogen {_cop(a['monto'])} y el saldo queda en {_cop(a['saldo_despues'])}."
    if a["accion"] == "provision":
        destination = destination + f" Monto: {_cop(a['monto'])}."
    if pd.notna(a.get("costo")) and pd.notna(a.get("costo_fijo")) and pd.notna(a.get("tarifa_10k")):
        cost = (
            f" Costo estimado {_cop(a['costo'])} (Anexo E: fijo {_cop(a['costo_fijo'])} + "
            f"{_cop(a['tarifa_10k'])} por cada $10.000 movidos)."
        )
    else:
        cost = " Costo estimado: sin tarifa disponible en el Anexo E."
    return f"{cause} {destination} {hist}{cost}"
