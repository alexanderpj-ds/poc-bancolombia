"""Simulador secuencial del balance y de las decisiones de M6 (U6).

A diferencia del par (`balance.simular_balance_fondo_denominacion` +
`recomendador.recomendar_acciones_m6`), que emite TODAS las alternativas sobre un
balance sin acciones y deja que U7 elija, aqui el saldo se evoluciona dia a dia
por (`fondo_id`, `denominacion`) y las acciones SE APLICAN al saldo, de modo que:

- el saldo despues de una accion es el saldo antes de la siguiente (RN-71/85);
- el cierre del dia es el saldo inicial del dia siguiente;
- por cada necesidad (faltante o excedente de un fondo-denominacion-dia) se elige UNA
  alternativa de bajo costo y se explica por que es preferible a las demas
  (RN-80);
- cada traslado y cada cambio de denominacion son DOS filas pareadas (origen y destino,
  mismo monto, fecha y denominacion; costo solo en el origen) (RN-74);
- sabados, domingos y festivos no admiten BanRep, ventas ni cambios de denominacion
  (RN-71A), segun el calendario CO existente;
- BanRep solo opera en las ciudades habilitadas por configuracion (RN-75);
- una venta no se costea con tarifa (no existe en el Anexo E): su beneficio de
  referencia es la TASA historica de `consolidado_ventas`, un supuesto declarado y no
  garantizado (RN-76);
- el excedente puede conservarse si guardarlo cuesta menos que actuar (RN-78/79).

Orden de atencion de las necesidades del dia (RN-81): primero faltantes (mayor monto
primero) y luego excedentes. Todo parametro vive en `conf/model_u6.yml`
(`decision`, `operaciones`, `costos.almacenamiento`). El nucleo es determinista y no
confia en ningun texto externo (LLM01): solo lee numeros de los contratos y maestros.

Supuestos de modelado (limitaciones declaradas):
sin `decision.traslado_disponible_t1` (entregable v1) el traslado se aplica el mismo dia y
puede cubrir un faltante de ese dia. Con `traslado_disponible_t1` (interruptor `m6_traslado_t1`,
SUP-52; nota del Anexo E, Fondos: "El efectivo sale del fondo origen en la fecha de ejecucion
y se encuentra disponible en el fondo destino al dia siguiente") un traslado ejecutado el dia T
solo cubre el faltante proyectado para T+1: al cierre de T se proyecta el saldo de T+1 con los
flujos de M1-M5 y, si queda bajo el minimo, se ordena el traslado con fecha T (las dos filas con
la misma fecha, RN-74); el destino lo recibe al cierre de T, que es su saldo inicial de T+1
(RN-71). Un faltante del mismo dia ya no se cubre con traslado. La capacidad de un fondo origen
es su saldo sobre el minimo de esa denominacion (con T+1, tambien despues de sus flujos del dia
siguiente); el cambio de denominacion toma solo del exceso sobre el maximo de otra denominacion
del mismo fondo. La tarifa de un traslado es la de la transportadora del fondo origen (SUP-53).
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from daas.costs import anexo_e

logger = logging.getLogger(__name__)

#: Etiqueta legible por operacion (columna `accion` del contrato).
_LABEL = {
    "traslado": "Trasladar efectivo entre fondos",
    "venta": "Vender efectivo",
    "banrep_consignacion": "Consignar excedente en BanRep",
    "banrep_retiro": "Retirar efectivo de BanRep",
    "cambio_denominacion": "Cambiar denominacion dentro del fondo",
    "sin_accion": "Sin accion",
}

#: Orden de desempate determinista entre operaciones con el mismo costo.
_PREFERENCE = {
    "traslado": 0,
    "cambio_denominacion": 1,
    "venta": 2,
    "banrep_retiro": 3,
    "banrep_consignacion": 3,
}


@dataclass
class SimulationResult:
    """Salida del simulador.

    Attributes:
        balance: Una fila por (fondo_id, denominacion, fecha) con el saldo encadenado.
        acciones: Una fila por accion y por fondo-denominacion afectado (los traslados
            y cambios de denominacion tienen dos filas pareadas por `id_par`).
        necesidades: Una fila por necesidad detectada (tipo, monto, alternativa elegida).
    """

    balance: pd.DataFrame
    actions: pd.DataFrame
    needs: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def _ceiling(x: float, unit: int) -> float:
    """Redondea hacia arriba al multiplo de `unidad` (>= 0)."""
    return float(math.ceil(max(x, 0.0) / unit) * unit)


def _floor(x: float, unit: int) -> float:
    """Redondea hacia abajo al multiplo de `unidad` (>= 0)."""
    return float(math.floor(max(x, 0.0) / unit + 1e-9) * unit)


def _cop(x: float) -> str:
    """Formato legible de pesos (separador de miles con punto, sin decimales)."""
    return f"${x:,.0f}".replace(",", ".")


def storage_rate(rates: pd.DataFrame, config: dict) -> dict[str, float]:
    """Tarifa diaria de almacenamiento por transportadora (Anexo E, RN-78).

    Args:
        rates: Tarifas de Fondos (`anexo_e._cargar_tarifas_fondos`).
        config: Configuracion de M6 (usa `costos.almacenamiento.concepto`).

    Returns:
        dict[str, float]: `transportadora -> COP por dia por cada `unidad_cop``; vacio
        si el Anexo E no trae el concepto (entonces no se costea, no se inventa).
    """
    concept = anexo_e._norm_concept(config.get("costos", {}).get("almacenamiento", {}).get("concepto", ""))
    out: dict[str, float] = {}
    if rates.empty or not concept:
        return out
    for _, r in rates.iterrows():
        if anexo_e._norm_concept(r["concepto"]) == concept and anexo_e._valid_rate(r.get("tarifa")):
            out[str(r["transportadora"])] = float(r["tarifa"])
    return out


class _Simulator:
    """Estado y reglas de la simulacion (uso interno de `simular`)."""

    def __init__(
        self,
        balance_initial: pd.DataFrame,
        effect_denom: pd.DataFrame,
        minmax: pd.DataFrame,
        dates: list[_dt.date],
        dim_fund: pd.DataFrame,
        matrix_ops: pd.DataFrame,
        rates: pd.DataFrame,
        rates_sale: dict[str, float],
        business: dict[_dt.date, bool],
        config: dict,
    ) -> None:
        self.cfg = config
        dec = config.get("decision", {})
        self.max_acc = int(dec.get("max_acciones_por_necesidad", 1))
        self.sin_habil = set(dec.get("dias_no_habiles_sin", []))
        self.conservar_ok = bool(dec.get("conservar_excedente", True))
        self.riesgo = dec.get("riesgo_residual", {})
        # SUP-52 (`m6_traslado_t1`): disponible en el destino al dia siguiente (nota del Anexo E, Fondos).
        self.t1 = bool(dec.get("traslado_disponible_t1", False))
        # SUP-53 (`m6_tarifa_traslado_declarada`): la explicacion declara la tarifa usada y la alternativa.
        self.tariff_text = bool(dec.get("tarifa_traslado_declarada", False))
        self.tasa_por_monto = float(dec.get("venta", {}).get("tasa_por_monto", 10000))
        storage = config.get("costos", {}).get("almacenamiento", {})
        self.alm_ok = bool(storage.get("habilitado", True))
        self.alm_unidad = float(storage.get("unidad_cop", 10_000_000_000))
        self.rates = rates
        self.rate_storage = storage_rate(rates, config) if self.alm_ok else {}
        self.sale_rates = rates_sale
        self.business = business
        self.dates = sorted(dates)
        self.city = {str(f): str(c) for f, c in zip(dim_fund["fondo_id"], dim_fund["ciudad"], strict=False)}
        self.tdv = {str(f): str(t) for f, t in zip(dim_fund["fondo_id"], dim_fund["transportadora"], strict=False)}
        self.ops = {
            (str(f), str(o)): bool(h)
            for f, o, h in zip(matrix_ops["fondo_id"], matrix_ops["operacion"], matrix_ops["habilitada"], strict=False)
        }
        # Motivo explicito de una operacion deshabilitada (columna opcional `motivo`; p.ej. RN-84, SUP-14).
        self.ops_motivo: dict[tuple[str, str], str] = {}
        if "motivo" in matrix_ops.columns:
            for f, o, m in zip(matrix_ops["fondo_id"], matrix_ops["operacion"], matrix_ops["motivo"], strict=False):
                if isinstance(m, str) and m.strip():
                    self.ops_motivo[(str(f), str(o))] = m.strip()
        self.current_balance: dict[tuple[str, int], float] = {
            (str(f), int(d)): float(s)
            for f, d, s in zip(
                balance_initial["fondo_id"],
                balance_initial["denominacion"],
                balance_initial["saldo_inicial"],
                strict=False,
            )
        }
        self.min_value: dict[tuple[str, int], float] = {}
        self.max_value: dict[tuple[str, int], float] = {}
        for f, d, mn, mx in zip(
            minmax["fondo_id"], minmax["denominacion"], minmax["minimo"], minmax["maximo"], strict=False
        ):
            self.min_value[(str(f), int(d))] = float(mn)
            self.max_value[(str(f), int(d))] = float(mx)
        self.effect: dict[tuple[str, _dt.date, int], tuple[float, float]] = {}
        if not effect_denom.empty:
            has = {"ingreso_den", "egreso_den"} <= set(effect_denom.columns)
            for _, r in effect_denom.iterrows():
                net = float(r["efecto_neto_den"])
                inflow = float(r["ingreso_den"]) if has else max(net, 0.0)
                outflow = float(r["egreso_den"]) if has else max(-net, 0.0)
                self.effect[(str(r["fondo_id"]), r["fecha"], int(r["denominacion"]))] = (
                    inflow,
                    outflow,
                )
        self.actions: list[dict[str, Any]] = []
        self.needs: list[dict[str, Any]] = []
        self._n_par = 0
        self._orden: dict[tuple[str, int, _dt.date], int] = {}

    # ------------------------------------------------------------------ costos
    def _compute_cost(self, rows: list[dict[str, Any]]) -> list[tuple[float | None, str]]:
        """Costea candidatos con el motor del Anexo E (`compute_costs_m6`).

        Returns:
            list: `(costo | None, costo_regla)` por fila; `None` = sin tarifa (prohibida).
        """
        if not rows:
            return []
        df = pd.DataFrame(rows)
        out = anexo_e.compute_costs_m6(df, rates=self.rates)
        res: list[tuple[float | None, str]] = []
        for c, without_t, without_td, rule in zip(
            out["costo"], out["sin_tarifa"], out["sin_transportadora"], out["costo_regla"], strict=False
        ):
            if bool(without_t) or bool(without_td) or c is None or pd.isna(c):
                res.append((None, str(rule)))
            else:
                res.append((float(c), str(rule)))
        return res

    def _keep_cost(self, fund: str, amount: float, days: int) -> float | None:
        """Costo de guardar `monto` durante `dias` (RN-78/79); None si no hay tarifa."""
        t = self.rate_storage.get(self.tdv[fund])
        if t is None:
            return None
        return amount / self.alm_unidad * t * days

    # ------------------------------------------------------------- habilitacion
    def _is_allowed(self, fund: str, operation: str, date: _dt.date) -> tuple[bool, str]:
        """Indica si la operacion esta habilitada en el fondo y es dia permitido.

        Returns:
            tuple[bool, str]: `(ok, razon_si_no)`.
        """
        if operation in self.sin_habil and not self.business.get(date, True):
            return False, "dia no habil (sabado, domingo o festivo; RN-71A)"
        key = {"banrep_consignacion": "banrep", "banrep_retiro": "banrep"}.get(operation, operation)
        if not self.ops.get((fund, key), False):
            if (fund, key) in self.ops_motivo:
                return False, self.ops_motivo[(fund, key)]
            return False, "no habilitada en este fondo (sin historico o fuera de las ciudades BanRep)"
        return True, ""

    # ---------------------------------------------------------------- acciones
    def _registrar(
        self,
        date: _dt.date,
        fund: str,
        denom: int,
        operation: str,
        effect: str,
        amount: float,
        role: str | None,
        id_pair: str | None,
        counterpart: str | None,
        denom_origin: int | None,
        denom_destination: int | None,
        cost: float | None,
        cost_rule: str,
        reason: str,
        criterion: str,
        need_id: int,
        tdv: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Aplica el efecto al saldo del fondo-denominacion y registra la fila."""
        key = (fund, denom)
        before = self.current_balance[key]
        after = before + amount if effect == "entrada" else before - amount
        if after < -1e-6:  # no deberia ocurrir: las capacidades acotan el monto
            raise AssertionError(f"accion dejaria saldo negativo en {fund} {denom} {date}: {after}")
        self.current_balance[key] = max(after, 0.0)
        order = self._orden.get((fund, denom, date), 0) + 1
        self._orden[(fund, denom, date)] = order
        row = {
            "fondo_id": fund,
            "denominacion": denom,
            "fecha": date,
            "operacion": operation,
            "accion": _LABEL[operation],
            "efecto": effect,
            "monto": amount,
            "rol": role,
            "id_par": id_pair,
            "fondo_contraparte": counterpart,
            "denominacion_origen": denom_origin,
            "denominacion_destino": denom_destination,
            "ciudad_origen": (
                self.city.get(fund if role != "destino" else counterpart) if operation == "traslado" else None
            ),
            "ciudad_destino": (
                self.city.get(counterpart if role != "destino" else fund) if operation == "traslado" else None
            ),
            "transportadora": tdv if tdv is not None else self.tdv.get(fund),
            "costo": cost,
            "costo_regla": cost_rule,
            "motivo": reason,
            "criterio": criterion,
            "saldo_antes": before,
            "saldo_despues": self.current_balance[key],
            "orden_aplicacion": order,
            "necesidad_id": need_id,
        }
        if extra:
            row.update(extra)
        self.actions.append(row)

    def _new_pair(self) -> str:
        self._n_par += 1
        return f"P{self._n_par:05d}"

    # ------------------------------------------------------------- necesidades
    def _roundings(self, denom: int) -> int:
        return denom if self.cfg.get("decision", {}).get("redondeo", "denominacion") == "denominacion" else 1

    def _shortfall_candidates(
        self, fund: str, denom: int, date: _dt.date, missing: float, transfer: str = "mismo_dia"
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Alternativas para cubrir un faltante; devuelve (candidatos, descartadas).

        `transfer`: ``mismo_dia`` (v1: el traslado cubre el faltante del dia), ``no`` (SUP-52: un faltante de hoy
        no se cubre con un traslado de hoy) o ``anticipado`` (SUP-52: faltante proyectado para `date`, que se
        cubre con un traslado ejecutado el dia anterior; la capacidad del origen descuenta sus flujos de `date`).
        """
        u = self._roundings(denom)
        target = _ceiling(missing, u)
        candidates: list[dict[str, Any]] = []
        discarded: list[str] = []
        # (1) traslado entrante desde otro fondo con capacidad sobre su minimo.
        origins = []
        items = sorted(self.current_balance.items()) if transfer != "no" else []
        if transfer == "no":
            discarded.append(
                "traslado: el efectivo trasladado esta disponible en el fondo destino al dia siguiente (Anexo E, "
                "Fondos); un faltante de hoy no se cubre con un traslado de hoy (SUP-52)"
            )
        for (g, d2), s in items:
            if d2 != denom or g == fund:
                continue
            cap = s - self.min_value[(g, d2)]
            if transfer == "anticipado":
                inflow_g, outflow_g = self.effect.get((g, date, d2), (0.0, 0.0))
                cap = min(cap, s + inflow_g - outflow_g - self.min_value[(g, d2)])
            amount = _floor(min(target, cap), u)
            if amount <= 0:
                continue
            origins.append(
                {
                    "operacion": "traslado",
                    "origen": g,
                    "monto": amount,
                    "completo": amount >= target,
                    "fila_costo": {
                        "operacion": "traslado",
                        "monto": amount,
                        "transportadora": self.tdv[g],
                        "ciudad_origen": self.city[g],
                        "ciudad_destino": self.city[fund],
                    },
                }
            )
        costs = self._compute_cost([c["fila_costo"] for c in origins])
        without_path = 0
        for c, (cost, rule) in zip(origins, costs, strict=False):
            if cost is None:
                without_path += 1
                continue
            c["costo"], c["regla"] = cost, rule
            candidates.append(c)
        if without_path:
            discarded.append(
                f"traslado desde {without_path} fondo(s) con saldo disponible: "
                "ruta sin tarifa en el Anexo E (prohibida)"
            )
        if not origins and transfer != "no":
            discarded.append("traslado: ningun otro fondo tiene saldo sobre su minimo en esta denominacion")
        # (2) retiro BanRep.
        ok, ratio = self._is_allowed(fund, "banrep_retiro", date)
        if ok:
            row = {"operacion": "banrep_retiro", "monto": target, "transportadora": self.tdv[fund]}
            ((cost, rule),) = self._compute_cost([row])
            if cost is None:
                discarded.append("retiro BanRep: sin tarifa en el Anexo E")
            else:
                candidates.append(
                    {"operacion": "banrep_retiro", "monto": target, "completo": True, "costo": cost, "regla": rule}
                )
        else:
            discarded.append(f"retiro BanRep: {ratio}")
        # (3) cambio de denominacion con el exceso sobre el maximo de otra denominacion.
        ok, ratio = self._is_allowed(fund, "cambio_denominacion", date)
        if ok:
            others = []
            for (g, d2), s in sorted(self.current_balance.items()):
                if g != fund or d2 == denom:
                    continue
                excess = s - self.max_value[(g, d2)]
                unit = math.lcm(denom, d2)
                amount = _floor(min(target, excess), unit)
                if amount > 0:
                    others.append(
                        {
                            "operacion": "cambio_denominacion",
                            "den_origen": d2,
                            "monto": amount,
                            "completo": amount >= target,
                            "fila_costo": {
                                "operacion": "cambio_denominacion",
                                "monto": amount,
                                "transportadora": self.tdv[fund],
                            },
                        }
                    )
            for c, (cost, rule) in zip(others, self._compute_cost([o["fila_costo"] for o in others]), strict=False):
                if cost is not None:
                    c["costo"], c["regla"] = cost, rule
                    candidates.append(c)
            if not others:
                discarded.append("cambio de denominacion: ninguna otra denominacion del fondo supera su maximo")
        else:
            discarded.append(f"cambio de denominacion: {ratio}")
        return candidates, discarded

    def _surplus_candidates(
        self, fund: str, denom: int, date: _dt.date, excess: float, days_remaining: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Alternativas para un excedente; devuelve (candidatos, descartadas)."""
        u = self._roundings(denom)
        cap_limit = _floor(self.current_balance[(fund, denom)] - self.min_value[(fund, denom)], u)
        target = min(_ceiling(excess, u), cap_limit)
        candidates: list[dict[str, Any]] = []
        discarded: list[str] = []
        if target <= 0:
            return candidates, ["el excedente es menor que una unidad de la denominacion"]
        # (1) venta, con beneficio de referencia (tasa) como supuesto.
        ok, ratio = self._is_allowed(fund, "venta", date)
        sale_rate = self.sale_rates.get(fund)
        if ok and sale_rate is not None:
            benefit = target / self.tasa_por_monto * sale_rate
            candidates.append(
                {
                    "operacion": "venta",
                    "monto": target,
                    "completo": True,
                    "costo": 0.0,
                    "regla": "beneficio_referencia",
                    "beneficio": benefit,
                    "tasa": sale_rate,
                }
            )
        elif ok:
            discarded.append("venta: el fondo no tiene tasa historica en consolidado_ventas")
        else:
            discarded.append(f"venta: {ratio}")
        # (2) consignacion BanRep.
        ok, ratio = self._is_allowed(fund, "banrep_consignacion", date)
        if ok:
            ((cost, rule),) = self._compute_cost(
                [{"operacion": "banrep_consignacion", "monto": target, "transportadora": self.tdv[fund]}]
            )
            if cost is None:
                discarded.append("consignacion BanRep: sin tarifa en el Anexo E")
            else:
                candidates.append(
                    {
                        "operacion": "banrep_consignacion",
                        "monto": target,
                        "completo": True,
                        "costo": cost,
                        "regla": rule,
                    }
                )
        else:
            discarded.append(f"consignacion BanRep: {ratio}")
        # (3) traslado saliente a un fondo con espacio bajo su maximo.
        destinations = []
        for (g, d2), s in sorted(self.current_balance.items()):
            if d2 != denom or g == fund:
                continue
            space = self.max_value[(g, d2)] - s
            amount = _floor(min(target, space), u)
            if amount > 0:
                destinations.append(
                    {
                        "operacion": "traslado",
                        "destino": g,
                        "monto": amount,
                        "completo": amount >= target,
                        "fila_costo": {
                            "operacion": "traslado",
                            "monto": amount,
                            "transportadora": self.tdv[fund],
                            "ciudad_origen": self.city[fund],
                            "ciudad_destino": self.city[g],
                        },
                    }
                )
        without_path = 0
        for c, (cost, rule) in zip(
            destinations, self._compute_cost([d["fila_costo"] for d in destinations]), strict=False
        ):
            if cost is None:
                without_path += 1
                continue
            c["costo"], c["regla"] = cost, rule
            candidates.append(c)
        if without_path:
            discarded.append(
                f"traslado hacia {without_path} fondo(s) con espacio: ruta sin tarifa en el Anexo E (prohibida)"
            )
        if not destinations:
            discarded.append("traslado: ningun otro fondo tiene espacio bajo su maximo en esta denominacion")
        # (4) conservar (guardar el excedente) con su costo de almacenamiento.
        if self.conservar_ok:
            storage_cost_total = self._keep_cost(fund, target, days_remaining)
            if storage_cost_total is None:
                discarded.append("conservar: el Anexo E no trae tarifa de almacenamiento para la transportadora")
            else:
                candidates.append(
                    {
                        "operacion": "sin_accion",
                        "monto": 0.0,
                        "completo": True,
                        "costo": 0.0,
                        "regla": "conservar",
                        "alm": storage_cost_total,
                        "monto_conservado": target,
                    }
                )
        return candidates, discarded

    @staticmethod
    def _net(c: dict[str, Any]) -> float:
        """Costo neto de una alternativa: costo - beneficio (venta) o costo de almacenar."""
        if c["operacion"] == "venta":
            return c["costo"] - c["beneficio"]
        if c["operacion"] == "sin_accion":
            return c["alm"]
        return c["costo"]

    def _choose(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Elige UNA alternativa.

        Las que cubren completo, por menor costo neto; si ninguna cubre, la de mayor cobertura
        y luego menor costo.
        """
        if not candidates:
            return None
        complete = [c for c in candidates if c["completo"]]
        if complete:
            return min(
                complete,
                key=lambda c: (
                    round(self._net(c), 6),
                    c["operacion"] != "sin_accion",
                    _PREFERENCE.get(c["operacion"], 9),
                    c.get("origen") or c.get("destino") or "",
                ),
            )
        return min(
            candidates,
            key=lambda c: (
                -c["monto"],
                round(self._net(c), 6),
                _PREFERENCE.get(c["operacion"], 9),
                c.get("origen") or c.get("destino") or "",
            ),
        )

    @staticmethod
    def _desc(c: dict[str, Any]) -> str:
        """Descripcion corta de una alternativa para la explicacion."""
        name = {
            "traslado": "traslado",
            "venta": "venta",
            "banrep_retiro": "retiro BanRep",
            "banrep_consignacion": "consignacion BanRep",
            "cambio_denominacion": "cambio de denominacion",
            "sin_accion": "conservar",
        }[c["operacion"]]
        extra = ""
        if c["operacion"] == "traslado":
            extra = f" con {c.get('origen') or c.get('destino')}"
        elif c["operacion"] == "cambio_denominacion":
            extra = f" desde {c['den_origen']}"
        if c["operacion"] == "venta":
            detail = f"beneficio de referencia {_cop(c['beneficio'])}"
        elif c["operacion"] == "sin_accion":
            detail = f"costo de almacenar {_cop(c['alm'])}"
        else:
            detail = f"costo {_cop(c['costo'])}"
        partial = "" if c["completo"] else ", cubre solo una parte"
        return f"{name}{extra} ({_cop(c['monto'] or c.get('monto_conservado', 0))}; {detail}{partial})"

    # --------------------------------------------------------------- una necesidad
    def _resolve(
        self,
        date: _dt.date,
        fund: str,
        denom: int,
        kind: str,
        days_remaining: int,
        nid: int,
    ) -> None:
        """Detecta, decide y aplica la accion de una necesidad (estado actual)."""
        key = (fund, denom)
        s, mn, mx = self.current_balance[key], self.min_value[key], self.max_value[key]
        if kind == "faltante":
            need = mn - s
            if need <= 1e-9:
                return
            candidates, discarded = self._shortfall_candidates(
                fund, denom, date, need, transfer="no" if self.t1 else "mismo_dia"
            )
            text_need = (
                f"Faltante de {_cop(need)} en la denominacion {denom}: saldo {_cop(s)} " f"bajo el minimo {_cop(mn)}."
            )
        else:
            need = s - mx
            if need <= 1e-9:
                return
            candidates, discarded = self._surplus_candidates(fund, denom, date, need, days_remaining)
            text_need = (
                f"Excedente de {_cop(need)} en la denominacion {denom}: saldo {_cop(s)} " f"sobre el maximo {_cop(mx)}."
            )
        chosen = self._choose(candidates)
        other = [c for c in candidates if c is not chosen]
        other_txt = [self._desc(c) for c in sorted(other, key=self._net)] + discarded
        if chosen is None:
            reason = f"{text_need} No hay alternativa viable. Descartadas: " + "; ".join(other_txt) + "."
            self._no_action(date, fund, denom, kind, need, reason, "sin_solucion", nid)
            return
        if chosen["operacion"] == "sin_accion":
            reason = (
                f"{text_need} Se conserva: guardarlo hasta el fin del horizonte cuesta "
                f"{_cop(chosen['alm'])} (Anexo E, almacenamiento), menos que cualquier accion. "
                "Alternativas: " + "; ".join(other_txt) + "."
            )
            self._no_action(date, fund, denom, kind, need, reason, "conservar", nid, storage_cost_total=chosen["alm"])
            return
        criterion = (
            "Menor costo neto entre las alternativas que cubren la necesidad completa"
            if chosen["completo"]
            else "Ninguna alternativa cubre la necesidad completa: mayor cobertura y luego menor costo"
        )
        reason = (
            f"{text_need} Elegida: {self._desc(chosen)}. "
            + (
                "Es preferible porque tiene el menor costo neto."
                if chosen["completo"]
                else "Cubre solo una parte; el resto queda como riesgo residual."
            )
            + (" Otras alternativas: " + "; ".join(other_txt) + "." if other_txt else "")
        )
        self._apply(date, fund, denom, kind, need, chosen, reason, criterion, nid)

    def _anticipate(self, date: _dt.date, next_date: _dt.date, keys: list[tuple[str, int]]) -> None:
        """SUP-52: ordena hoy (`date`) los traslados que cubren el faltante proyectado para `next_date`.

        El saldo proyectado de `next_date` es el cierre actual mas sus ingresos menos sus salidas de M1-M5. Si queda
        bajo el minimo, se evalua el traslado (ejecutado hoy, disponible manana) frente a las alternativas de
        `next_date` (retiro BanRep si el dia es habil y el fondo lo tiene habilitado). Solo si el traslado es la
        alternativa elegida se registra hoy; si no, la necesidad se resuelve manana con las alternativas de ese dia.
        Orden de atencion: mayor faltante primero (RN-81).
        """
        projected = []
        for key in keys:
            fund, denom = key
            inflow, outflow = self.effect.get((fund, next_date, denom), (0.0, 0.0))
            proj = self.current_balance[key] + inflow - outflow
            if proj < self.min_value[key]:
                projected.append((self.min_value[key] - proj, key, proj, inflow, outflow))
        for need, (fund, denom), proj, inflow, outflow in sorted(projected, key=lambda t: (-t[0], t[1])):
            key = (fund, denom)
            # El estado pudo cambiar por un traslado anterior de esta misma pasada (origen = este fondo).
            inflow, outflow = self.effect.get((fund, next_date, denom), (0.0, 0.0))
            proj = self.current_balance[key] + inflow - outflow
            need = self.min_value[key] - proj
            if need <= 1e-9:
                continue
            candidates, discarded = self._shortfall_candidates(fund, denom, next_date, need, transfer="anticipado")
            chosen = self._choose(candidates)
            if chosen is None or chosen["operacion"] != "traslado":
                continue  # se resuelve el dia de la necesidad con sus alternativas
            nid = len(self.needs)
            self.needs.append(
                {
                    "necesidad_id": nid,
                    "fondo_id": fund,
                    "denominacion": denom,
                    "fecha": next_date,
                    "tipo": "faltante",
                    "monto_necesidad": need,
                    "operacion": None,
                    "resultado": None,
                    "monto_accion": 0.0,
                }
            )
            mn = self.min_value[key]
            text_need = (
                f"Faltante proyectado para el {next_date:%d/%m/%Y} de {_cop(need)} en la denominacion {denom}: saldo "
                f"proyectado {_cop(proj)} (cierre del {date:%d/%m/%Y} {_cop(self.current_balance[key])} mas ingresos "
                f"{_cop(inflow)} menos salidas {_cop(outflow)}) bajo el minimo {_cop(mn)}. El traslado se ejecuta el "
                f"{date:%d/%m/%Y} porque el efectivo sale del fondo origen en la fecha de ejecucion y esta disponible "
                "en el fondo destino al dia siguiente (Anexo E, Fondos; SUP-52)."
            )
            other = [c for c in candidates if c is not chosen]
            other_txt = [self._desc(c) for c in sorted(other, key=self._net)] + discarded
            criterion = (
                "Menor costo neto entre las alternativas que cubren la necesidad completa"
                if chosen["completo"]
                else "Ninguna alternativa cubre la necesidad completa: mayor cobertura y luego menor costo"
            )
            reason = (
                f"{text_need} Elegida: {self._desc(chosen)}. "
                + (
                    "Es preferible porque tiene el menor costo neto."
                    if chosen["completo"]
                    else "Cubre solo una parte; el resto se evalua el dia de la necesidad."
                )
                + (" Otras alternativas: " + "; ".join(other_txt) + "." if other_txt else "")
            )
            self._apply(date, fund, denom, "faltante", need, chosen, reason, criterion, nid)

    def _tariff_sentence(self, origin: str, destination: str, amount: float, cost: float | None) -> str:
        """SUP-53: frase de la tarifa del traslado con costo (la del origen) y su alternativa (la del destino)."""
        if not self.tariff_text or cost is None or cost <= 0:
            return ""
        tdv_o, tdv_d = self.tdv[origin], self.tdv[destination]
        if tdv_o == tdv_d:
            return f" Tarifa del Anexo E de {tdv_o}, transportadora de los dos fondos (SUP-53)."
        ((alt, _rule),) = self._compute_cost(
            [
                {
                    "operacion": "traslado",
                    "monto": amount,
                    "transportadora": tdv_d,
                    "ciudad_origen": self.city[origin],
                    "ciudad_destino": self.city[destination],
                }
            ]
        )
        alt_txt = (
            f"con la de {tdv_d}, transportadora del fondo destino, costaria {_cop(alt)}"
            if alt is not None
            else f"{tdv_d}, transportadora del fondo destino, no tiene tarifa para esta ruta"
        )
        return (
            f" Tarifa del Anexo E de {tdv_o}, transportadora del fondo origen, que entrega el efectivo y en cuya fila "
            f"se registra el costo (RN-74; SUP-53); {alt_txt}."
        )

    def _no_action(
        self,
        date: _dt.date,
        fund: str,
        denom: int,
        kind: str,
        need: float,
        reason: str,
        result: str,
        nid: int,
        storage_cost_total: float | None = None,
    ) -> None:
        """Registra una necesidad que no se actua (conservada o sin solucion)."""
        order = self._orden.get((fund, denom, date), 0) + 1
        self._orden[(fund, denom, date)] = order
        s = self.current_balance[(fund, denom)]
        self.actions.append(
            {
                "fondo_id": fund,
                "denominacion": denom,
                "fecha": date,
                "operacion": "sin_accion",
                "accion": _LABEL["sin_accion"],
                "efecto": "ninguno",
                "monto": 0.0,
                "rol": None,
                "id_par": None,
                "fondo_contraparte": None,
                "denominacion_origen": None,
                "denominacion_destino": None,
                "ciudad_origen": None,
                "ciudad_destino": None,
                "transportadora": self.tdv.get(fund),
                "costo": 0.0,
                "costo_regla": result,
                "motivo": reason,
                "criterio": (
                    "Costo de almacenar menor que el de actuar" if result == "conservar" else "Sin alternativa viable"
                ),
                "saldo_antes": s,
                "saldo_despues": s,
                "orden_aplicacion": order,
                "necesidad_id": nid,
                "costo_almacenamiento": storage_cost_total,
            }
        )
        self.needs[nid]["resultado"] = result
        self.needs[nid]["operacion"] = "sin_accion"

    def _counterpart_reason(
        self,
        operation: str,
        id_pair: str,
        fund: str,
        denom: int,
        need_fund: str,
        need_denom: int,
        amount: float,
        delivers: bool,
        need_reason: str,
    ) -> str:
        """Explicacion de la fila contraparte de una accion pareada, desde el fondo de la fila.

        La fila contraparte no tiene necesidad propia: describe lo que entrega o recibe, su
        saldo antes y despues frente a su propio rango, y cita la necesidad que la origina.
        """
        key = (fund, denom)
        before = self.current_balance[key]
        after = before - amount if delivers else before + amount
        other = need_fund if need_fund != fund else f"la denominacion {need_denom}"
        verb, prep = ("entrega", "a") if delivers else ("recibe", "de")
        return (
            f"Contraparte del {operation} {id_pair} en la denominacion {denom}: {verb} "
            f"{_cop(amount)} {prep} {other}. Saldo de esta fila: {_cop(before)} antes y {_cop(after)} despues "
            f"(minimo {_cop(self.min_value[key])}, maximo {_cop(self.max_value[key])}). "
            f"Necesidad que la origina, en {other}: {need_reason}"
        )

    def _apply(
        self,
        date: _dt.date,
        fund: str,
        denom: int,
        kind: str,
        need: float,
        c: dict[str, Any],
        reason: str,
        criterion: str,
        nid: int,
    ) -> None:
        """Aplica la alternativa elegida (una o dos filas pareadas) al saldo."""
        op, amount = c["operacion"], c["monto"]
        self.needs[nid]["operacion"] = op
        self.needs[nid]["resultado"] = "resuelta" if c["completo"] else "parcial"
        self.needs[nid]["monto_accion"] = amount
        if op in ("banrep_retiro", "banrep_consignacion", "venta"):
            effect = "entrada" if op == "banrep_retiro" else "salida"
            extra = None
            rule = c["regla"]
            if op == "venta":
                extra = {"beneficio": c["beneficio"], "tasa_referencia": c["tasa"]}
            self._registrar(
                date,
                fund,
                denom,
                op,
                effect,
                amount,
                None,
                None,
                None,
                None,
                None,
                c["costo"],
                rule,
                reason,
                criterion,
                nid,
                extra=extra,
            )
            return
        if op == "traslado":
            origin = c.get("origen") or fund
            destination = fund if kind == "faltante" else c["destino"]
            if kind == "excedente":
                origin = fund
            idp = self._new_pair()
            counterpart = destination if origin == fund else origin
            reason = reason + self._tariff_sentence(origin, destination, amount, c["costo"])
            reason_cp = self._counterpart_reason(
                "traslado", idp, counterpart, denom, fund, denom, amount, origin == counterpart, reason
            )
            # salida en el origen (lleva el costo) y entrada en el destino (sin costo).
            self._registrar(
                date,
                origin,
                denom,
                "traslado",
                "salida",
                amount,
                "origen",
                idp,
                destination,
                None,
                None,
                c["costo"],
                c["regla"],
                reason_cp if origin == counterpart else reason,
                criterion,
                nid,
                tdv=self.tdv[origin],
            )
            self._registrar(
                date,
                destination,
                denom,
                "traslado",
                "entrada",
                amount,
                "destino",
                idp,
                origin,
                None,
                None,
                0.0,
                "contraparte_sin_costo",
                reason_cp if destination == counterpart else reason,
                criterion,
                nid,
                tdv=self.tdv[origin],
            )
            return
        if op == "cambio_denominacion":
            d_origin = c["den_origen"]
            idp = self._new_pair()
            reason_cp = self._counterpart_reason(
                "cambio de denominacion", idp, fund, d_origin, fund, denom, amount, True, reason
            )
            self._registrar(
                date,
                fund,
                d_origin,
                "cambio_denominacion",
                "salida",
                amount,
                "origen",
                idp,
                fund,
                d_origin,
                denom,
                c["costo"],
                c["regla"],
                reason_cp,
                criterion,
                nid,
            )
            self._registrar(
                date,
                fund,
                denom,
                "cambio_denominacion",
                "entrada",
                amount,
                "destino",
                idp,
                fund,
                d_origin,
                denom,
                0.0,
                "contraparte_sin_costo",
                reason,
                criterion,
                nid,
            )
            return
        raise ValueError(f"operacion desconocida: {op}")

    # ------------------------------------------------------------------- bucle
    def run(self) -> SimulationResult:
        """Recorre el horizonte aplicando efecto, detectando y resolviendo necesidades."""
        rows_bal: dict[tuple[str, int, _dt.date], dict[str, Any]] = {}
        keys = sorted(self.current_balance)
        n_days = len(self.dates)
        for i, date in enumerate(self.dates):
            days_remaining = n_days - i
            # 1) efecto M1-M5 del dia (clip a 0 con deficit).
            for key in keys:
                fund, denom = key
                inflow, outflow = self.effect.get((fund, date, denom), (0.0, 0.0))
                s0 = self.current_balance[key]
                gross = s0 + inflow - outflow
                deficit = max(-gross, 0.0)
                self.current_balance[key] = max(gross, 0.0)
                rows_bal[(fund, denom, date)] = {
                    "fondo_id": fund,
                    "denominacion": denom,
                    "fecha": date,
                    "saldo_inicial_dia": s0,
                    "ingresos_esperados": inflow,
                    "egresos_esperados": outflow,
                    "efecto_neto_den": inflow - outflow,
                    "deficit": deficit,
                    "saldo_antes_acciones": self.current_balance[key],
                    "minimo": self.min_value[key],
                    "maximo": self.max_value[key],
                }
            # 2) necesidades detectadas (antes de actuar): faltantes y luego excedentes.
            shortfalls = [
                (self.min_value[k] - self.current_balance[k], k)
                for k in keys
                if self.current_balance[k] < self.min_value[k]
            ]
            surpluses = [
                (self.current_balance[k] - self.max_value[k], k)
                for k in keys
                if self.current_balance[k] > self.max_value[k]
            ]
            for kind, items in (("faltante", shortfalls), ("excedente", surpluses)):
                for amount, (fund, denom) in sorted(items, key=lambda t: (-t[0], t[1])):
                    nid = len(self.needs)
                    self.needs.append(
                        {
                            "necesidad_id": nid,
                            "fondo_id": fund,
                            "denominacion": denom,
                            "fecha": date,
                            "tipo": kind,
                            "monto_necesidad": amount,
                            "operacion": None,
                            "resultado": None,
                            "monto_accion": 0.0,
                        }
                    )
                    self._resolve(date, fund, denom, kind, days_remaining, nid)
            # 2b) SUP-52: traslados de hoy para el faltante proyectado de manana (disponible al dia siguiente).
            if self.t1 and i + 1 < n_days:
                self._anticipate(date, self.dates[i + 1], keys)
            # 3) cierre del dia = saldo inicial del siguiente.
            for key in keys:
                fund, denom = key
                fb = rows_bal[(fund, denom, date)]
                fb["saldo_proyectado"] = self.current_balance[key]
                fb["nivel_riesgo"] = self._level(self.current_balance[key], key)
        balance = pd.DataFrame(list(rows_bal.values()))
        actions = pd.DataFrame(self.actions)
        needs = pd.DataFrame(self.needs)
        # Acciones netas por clave-dia (suma con signo) y banderas de riesgo previo.
        if not actions.empty:
            a = actions[actions["operacion"] != "sin_accion"].copy()
            a["_signo"] = a["efecto"].map({"entrada": 1.0, "salida": -1.0}).fillna(0.0)
            a["_neto"] = a["_signo"] * a["monto"]
            net = a.groupby(["fondo_id", "denominacion", "fecha"], as_index=False)["_neto"].sum()
            net = net.rename(columns={"_neto": "acciones_netas"})
            balance = balance.merge(net, on=["fondo_id", "denominacion", "fecha"], how="left")
        else:
            balance["acciones_netas"] = 0.0
        balance["acciones_netas"] = balance["acciones_netas"].fillna(0.0)
        balance["riesgo_deficit"] = balance["saldo_antes_acciones"] < balance["minimo"]
        balance["riesgo_exceso"] = balance["saldo_antes_acciones"] > balance["maximo"]
        balance = balance.sort_values(["fondo_id", "denominacion", "fecha"]).reset_index(drop=True)
        if not actions.empty:
            actions = actions.sort_values(
                ["fecha", "necesidad_id", "orden_aplicacion", "fondo_id", "denominacion"]
            ).reset_index(drop=True)
        return SimulationResult(balance=balance, actions=actions, needs=needs)

    def _level(self, current_balance: float, key: tuple[str, int]) -> str:
        """Nivel de riesgo RESIDUAL (despues de actuar) segun la config."""
        mn, mx = self.min_value[key], self.max_value[key]
        frac = float(self.riesgo.get("alto_si_fraccion_minimo_menor", 0.5))
        if current_balance < mn:
            return "alto" if (current_balance <= 0.0 or current_balance < frac * mn) else "medio"
        if current_balance > mx:
            return str(self.riesgo.get("exceso", "medio"))
        return "bajo"


def simulate(
    balance_initial: pd.DataFrame,
    effect_denom: pd.DataFrame,
    minmax: pd.DataFrame,
    dates: list[_dt.date],
    dim_fund: pd.DataFrame,
    matrix_ops: pd.DataFrame,
    rates: pd.DataFrame,
    rates_sale: dict[str, float],
    business: dict[_dt.date, bool],
    config: dict,
) -> SimulationResult:
    """Simula el horizonte aplicando el efecto M1-M5 y UNA accion por necesidad.

    Args:
        balance_initial: Salida de `dataset.saldo_inicial_por_fondo_denominacion`.
        effect_denom: Salida de `dataset.distribuir_efecto_por_denominacion` (con
            `ingreso_den`/`egreso_den`).
        minmax: Salida de `balance.minmax_operativos`.
        dates: Dias corridos del horizonte.
        dim_fund: `fondo_id`, `ciudad`, `transportadora`.
        matrix_ops: Salida de `dataset.matriz_operaciones_habilitadas`.
        rates: Tarifas de Fondos del Anexo E (`anexo_e._cargar_tarifas_fondos`).
        rates_sale: `fondo_id -> tasa` (COP por cada `tasa_por_monto`) de
            `dataset.tasa_venta_por_fondo`.
        business: `fecha -> es dia habil` (calendario CO).
        config: Configuracion de M6.

    Returns:
        ResultadoSimulacion: balance, acciones y necesidades.
    """
    return _Simulator(
        balance_initial,
        effect_denom,
        minmax,
        dates,
        dim_fund,
        matrix_ops,
        rates,
        rates_sale,
        business,
        config,
    ).run()
