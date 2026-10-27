"""Hoja `03_Metricas_Desarrollo`: metricas reales de backtest por modelo, segmento y KPI."""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import pandas as pd

from daas import alx
from daas.forecasting import metrics
from daas.publish.anexo_d import masters
from daas.publish.anexo_d.cell_values import to_date_or_none
from daas.publish.anexo_d.config import load_export_config, resolve_config
from daas.publish.anexo_d.constants import HEADERS, METHODOLOGY, PROVIDER_ID
from daas.publish.anexo_d.masters import cap_m1, capitalize_city, city_from_fund, city_map_m3
from daas.publish.contracts import BASE_READING, RN08_READING


def backtest_periods(cutoff: _dt.date | None = None) -> dict[str, tuple[_dt.date, _dt.date]]:
    """Ventana del backtest por modelo: los ultimos `backtest.dias` dias hasta el corte.

    Sale de la configuracion (corte de `export_anexo_d.yml`; `backtest.dias` de cada
    unidad), no de fechas escritas aqui. M6 no tiene backtest: reporta la de M1.
    """
    from daas.modules.atm_m1_m2.config import load_config as load_u12
    from daas.modules.branches_m3.config import load_config as load_m3
    from daas.modules.funds_inflows_m4_m5.config import load_config as load_u45

    until = cutoff or to_date_or_none(load_export_config().get("corte"))
    days = {}
    for cfg, models in ((load_u12(), ("m1", "m2", "m6")), (load_m3(), ("m3",)), (load_u45(), ("m4", "m5"))):
        for mdl in models:
            days[mdl] = int(cfg["backtest"]["dias"])
    return {mdl: (until - _dt.timedelta(days=n - 1), until) for mdl, n in days.items()}


#: Variable objetivo por modelo para la hoja 03 (de los contratos / predicciones).
_METRIC_TARGET = {
    "m1": "pagado",
    "m2": "pagado",
    "m4": "ingreso_efectivo_cbr",
    "m5": "ingreso_efectivo_clientes",
}


def _row_03(
    mdl: str,
    kpi: str,
    kind: str,
    metric: str,
    value: object,
    unit: str,
    segment: str,
    since: _dt.date | None,
    until: _dt.date | None,
    methodology: str,
    comment: object,
) -> dict[str, Any]:
    """Una fila de `03_Metricas_Desarrollo` con las 12 columnas oficiales."""
    return {
        "id_proveedor": PROVIDER_ID,
        "modelo": mdl.upper(),
        "variable_o_kpi_evaluado": kpi,
        "tipo_metrica": kind,
        "metrica": metric,
        "valor_metrica": value,
        "unidad": unit,
        "segmento": segment,
        "periodo_desde": since,
        "periodo_hasta": until,
        "metodologia_validacion": methodology,
        "comentarios": comment,
    }


def _with_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Copia de `df` con las columnas opcionales del contrato que falten, en nulo (contratos anteriores)."""
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            out[c] = float("nan")
    return out


def _series_wape(y: pd.Series, yhat: pd.Series) -> float | None:
    """WAPE = suma |y - yhat| / suma |y|; ``None`` si la base es 0."""
    base = float(y.abs().sum())
    return None if base == 0 else float((y - yhat).abs().sum() / base)


def segment_rows(
    backtest: pd.DataFrame | None,
    cutoff: _dt.date,
    periods: dict[str, tuple[_dt.date, _dt.date]],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """WAPE del backtest por ciudad, por semana de la ventana y (M4/M5) por fondo.

    Usa el contrato opcional `output/api/backtest` (`modelo, objetivo, cod_cajero, fecha, y, yhat`).
    Sin el contrato no hay segmentos y la hoja queda con el global (la brecha se anota en el informe).
    """
    if backtest is None or backtest.empty:
        return []
    h3 = cfg["hoja_03"]
    days = int(h3["semana_dias"])
    bt = backtest.copy()
    bt["cod_cajero"] = bt["cod_cajero"].astype(str)
    bt["fecha"] = pd.to_datetime(bt["fecha"]).dt.date
    cp = masters.city_capacity_map_m1_m2(cutoff)
    m3 = city_map_m3(cutoff)
    mapping = {
        "m1": dict(zip(cp["cod_cajero"], cp["ciudad"], strict=False)),
        "m2": dict(zip(cp["cod_cajero"], cp["ciudad"], strict=False)),
        "m3": dict(zip(m3["cod_sucursal"], m3["ciudad"], strict=False)),
    }
    if "lectura" not in bt.columns:  # contrato anterior: solo la lectura base
        bt["lectura"] = BASE_READING
    rows: list[dict[str, Any]] = []
    methodology = METHODOLOGY
    for (mdl, obj), gm in bt.groupby(["modelo", "objetivo"]):
        mdl, obj = str(mdl), str(obj)
        since, until = periods.get(mdl, periods["m1"])
        if mdl in mapping:
            gm = gm.assign(ciudad=gm["cod_cajero"].map(mapping[mdl]).map(capitalize_city))
        else:
            gm = gm.assign(ciudad=gm["cod_cajero"].map(city_from_fund))
        # Semanas de calendario desde el inicio de la ventana, con las fechas de todas las lecturas
        # para que sus etiquetas coincidan; la etiqueta lleva la primera y la ultima fecha con dato.
        dates = sorted(gm["fecha"].unique())
        start = min(since, dates[0])
        span = (max(until, dates[-1]) - start).days + 1
        n_weeks = max(int(span / days + 0.5), 1)  # round() con mitades hacia arriba, minimo 1
        idx = {f: min((f - start).days // days, n_weeks - 1) for f in dates}  # la ultima semana absorbe el resto
        gm = gm.assign(semana=gm["fecha"].map(idx))
        for reading, g in gm.groupby("lectura"):
            metric = "WAPE"
            if reading == RN08_READING:  # lectura con la que puntua el banco, al lado de la actual y rotulada
                metric = h3["lectura_rn08"]["rotulo_metrica"].format(metrica=metric)
            segments: list[tuple[str, pd.DataFrame, str, _dt.date, _dt.date]] = []
            for city, gc in g.dropna(subset=["ciudad"]).groupby("ciudad"):
                segments.append((str(city), gc, "WAPE por ciudad.", since, until))
            for k in sorted(g["semana"].unique()):
                days_k = [f for f in dates if idx[f] == k]
                label = h3["segmento_semana"].format(n=k + 1, desde=days_k[0], hasta=days_k[-1])
                segments.append((label, g[g["semana"] == k], "WAPE por semana de la ventana.", days_k[0], days_k[-1]))
            if mdl in ("m4", "m5"):
                for fund, gf in g.groupby("cod_cajero"):
                    segments.append((str(fund), gf, "Diagnostico por fondo (la ciudad agrega fondos).", since, until))
            # ALX (SUP-02 / SUP-27, interruptor `sup02_denominador_cero`): la entidad con todos sus reales en 0 en la
            # ventana sale del WAPE de todos los segmentos (mismo conjunto que el global); vacio = Santiago.
            excluded = (
                metrics.zero_denominator_entities(g["y"], g["cod_cajero"])
                if alx.interruptor("sup02_denominador_cero")
                else set()
            )
            for segment, gs, note, d0, d1 in segments:
                if excluded:
                    gs = gs[~gs["cod_cajero"].isin(excluded)]
                value = _series_wape(gs["y"], gs["yhat"])
                if value is None:
                    continue
                rows.append(
                    _row_03(
                        mdl, str(obj), "predictiva", metric, value, "porcentaje", segment, d0, d1, methodology, note
                    )
                )
    return rows


def _depletion_m1(contracts: dict[str, pd.DataFrame], cutoff: _dt.date) -> tuple[int, int, list[float]]:
    """Reconstruye la trayectoria de M1 en el horizonte con el plan publicado.

    Parte del cupo operativo (RN-09); en cada dia la provision fija la apertura en su
    `saldo_despues` y el pronostico `pagado` la consume. Un ATM-dia esta agotado si el pronostico
    supera la apertura.

    Returns:
        tuple: ``(n_agotados, n_atm_dia, ocupaciones_antes_provision)``.
    """
    pred = contracts["predicciones"]
    pred = pred[(pred["modelo"] == "m1") & (pred["objetivo"] == "pagado")].copy()
    rec = _with_columns(contracts["recomendaciones"], ("accion", "saldo_antes", "saldo_despues", "cupo"))
    rec = rec[(rec["modelo"] == "m1") & (rec["accion"] == "provision")].copy()
    pred["cod_cajero"] = pred["cod_cajero"].astype(str)
    rec["cod_cajero"] = rec["cod_cajero"].astype(str)
    rec["fecha"] = pd.to_datetime(rec["fecha_sugerida"]).dt.date
    pred["fecha"] = pd.to_datetime(pred["fecha"]).dt.date
    opening = {(c, f): v for c, f, v in zip(rec["cod_cajero"], rec["fecha"], rec["saldo_despues"], strict=False)}
    cp = masters.city_capacity_map_m1_m2(cutoff)
    cap = cap_m1()
    capacity = {
        c: (min(float(v), cap) if cap is not None else float(v))
        for c, v in zip(cp["cod_cajero"], cp["cupo"], strict=False)
        if pd.notna(v)
    }
    depleted = total = 0
    for code, g in pred.sort_values(["cod_cajero", "fecha"]).groupby("cod_cajero"):
        balance = capacity.get(code)
        if balance is None:
            continue
        for date, yhat in zip(g["fecha"], g["yhat"], strict=False):
            if (code, date) in opening and pd.notna(opening[(code, date)]):
                balance = float(opening[(code, date)])
            consumption = max(float(yhat), 0.0) if pd.notna(yhat) else 0.0
            total += 1
            depleted += consumption > balance
            balance = max(balance - consumption, 0.0)
    capacity_row = rec["cupo"].where(rec["cupo"].notna(), rec["cod_cajero"].map(capacity))
    occupancy = [
        max(float(a), 0.0) / float(c)
        for a, c in zip(rec["saldo_antes"], capacity_row, strict=False)
        if pd.notna(a) and pd.notna(c) and float(c) > 0
    ]
    return int(depleted), int(total), occupancy


def balance_consistency(contracts: dict[str, pd.DataFrame], tolerance: float) -> tuple[float, float, int] | None:
    """Fraccion de filas del balance M6 que cumplen la identidad de RN-71 y su diferencia maxima.

    Por fila fondo-denominacion-dia: (a) `saldo_antes_acciones = saldo_inicial + ingresos - (egresos -
    deficit)`; (b) `saldo_proyectado = saldo_antes_acciones + acciones_netas`; (c) `acciones_netas` =
    suma de efecto x monto de las recomendaciones M6; (d) `saldo_inicial(t+1) = saldo_proyectado(t)`.

    Returns:
        tuple | None: ``(fraccion, diferencia_maxima_cop, n_filas)``; ``None`` si el contrato no trae
        las columnas del balance.
    """
    pred = contracts["predicciones"]
    bal = pred[pred["modelo"] == "m6"].copy()
    cols = [
        "saldo_inicial_dia",
        "ingresos_esperados",
        "egresos_esperados",
        "deficit",
        "saldo_antes_acciones",
        "acciones_netas",
        "saldo_proyectado",
        "denominacion",
    ]
    if bal.empty or any(c not in bal.columns for c in cols):
        return None
    for c in cols:
        bal[c] = pd.to_numeric(bal[c], errors="coerce")
    bal["cod_cajero"] = bal["cod_cajero"].astype(str)
    bal["dia"] = pd.to_datetime(bal["fecha"]).dt.strftime("%Y-%m-%d")
    bal = bal.sort_values(["cod_cajero", "denominacion", "dia"])
    d_a = (
        bal["saldo_antes_acciones"]
        - (bal["saldo_inicial_dia"] + bal["ingresos_esperados"] - (bal["egresos_esperados"] - bal["deficit"]))
    ).abs()
    d_b = (bal["saldo_proyectado"] - (bal["saldo_antes_acciones"] + bal["acciones_netas"])).abs()
    previous = bal.groupby(["cod_cajero", "denominacion"])["saldo_proyectado"].shift(1)
    d_d = (bal["saldo_inicial_dia"] - previous).abs()
    rec6 = contracts["recomendaciones"]
    rec6 = rec6[rec6["modelo"] == "m6"].copy()
    if rec6.empty:
        net = pd.Series(0.0, index=bal.index)
    else:
        rec6["cod_cajero"] = rec6["cod_cajero"].astype(str)
        rec6["denominacion"] = pd.to_numeric(rec6["denominacion"], errors="coerce")
        rec6["dia"] = pd.to_datetime(rec6["fecha_sugerida"]).dt.strftime("%Y-%m-%d")
        rec6["firmado"] = pd.to_numeric(rec6["monto"], errors="coerce").fillna(0.0) * rec6["efecto"].map(
            {"entrada": 1.0, "salida": -1.0}
        ).fillna(0.0)
        sum_total = rec6.groupby(["cod_cajero", "denominacion", "dia"])["firmado"].sum()
        keys = list(zip(bal["cod_cajero"], bal["denominacion"], bal["dia"], strict=False))
        net = pd.Series([float(sum_total.get(k, 0.0)) for k in keys], index=bal.index)
    d_c = (bal["acciones_netas"] - net).abs()
    diffs = pd.concat([d_a, d_b, d_c, d_d], axis=1)
    ok = (diffs.fillna(0.0) <= tolerance).all(axis=1)
    return float(ok.mean()), float(diffs.max().max(skipna=True)), int(len(bal))


def _policy_backtest_rows(h3: dict[str, Any], segment: str) -> list[dict[str, Any]]:
    """Filas del backtest de la politica contra el saldo real (`hoja_03.backtest_politica`); vacio si no esta."""
    bt = h3.get("backtest_politica")
    if not bt:
        return []
    since, until = to_date_or_none(bt["periodo_desde"]), to_date_or_none(bt["periodo_hasta"])
    return [
        _row_03(
            f["modelo"],
            f["kpi"],
            f["tipo"],
            f["metrica"],
            float(f["valor"]),
            f["unidad"],
            segment,
            since,
            until,
            bt["metodologia"],
            f["comentario"],
        )
        for f in bt["filas"]
    ]


def _kpi_rows(contracts: dict[str, pd.DataFrame], cutoff: _dt.date, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """KPI operativos de la hoja 03 calculados de las salidas del horizonte."""
    h3 = cfg["hoja_03"]
    kpi = h3["kpi"]
    since, until = to_date_or_none(cfg["horizonte"]["inicio"]), to_date_or_none(cfg["horizonte"]["fin"])
    seg, methodology = h3["segmento_global"], h3["metodologia_plan"]
    rows: list[dict[str, Any]] = []

    def _add_row(mdl: str, key: str, value: object, **text: object) -> None:
        k = kpi[key]
        rows.append(
            _row_03(
                mdl,
                key,
                k["tipo"],
                k["metrica"],
                value,
                k["unidad"],
                seg,
                since,
                until,
                methodology,
                k["comentario"].format(**text),
            )
        )

    pred_m1 = contracts["predicciones"]
    if ((pred_m1["modelo"] == "m1") & (pred_m1["objetivo"] == "pagado")).any():
        depleted, total, occupancy = _depletion_m1(contracts, cutoff)
        if total:
            _add_row("m1", "tasa_agotamiento", depleted / total, n_agotados=depleted, n_total=total)
        _add_row(
            "m1",
            "remanente_antes_provision",
            sum(occupancy) / len(occupancy) if occupancy else cfg["vocabulario"]["no_aplica"],
            n=len(occupancy),
        )
        rows += _policy_backtest_rows(h3, seg)

    rec = _with_columns(contracts["recomendaciones"], ("costo", "monto", "efecto"))
    for mdl in ("m1", "m2", "m3"):
        sub = rec[rec["modelo"] == mdl]
        if sub.empty:
            continue
        cost = pd.to_numeric(sub["costo"], errors="coerce")
        _add_row(mdl, "costo_total", float(cost.fillna(0.0).sum()), n_sin_tarifa=int(cost.isna().sum()))

    met = contracts["metricas"]
    rec6 = rec[rec["modelo"] == "m6"]
    storage_rows = met[(met["modelo"] == "m6") & (met["bloque"] == "costo_almacenamiento_horizonte")]
    if not rec6.empty:
        actions = pd.to_numeric(rec6["costo"], errors="coerce")
        _add_row("m6", "costo_total", float(actions.fillna(0.0).sum()), n_sin_tarifa=int(actions.isna().sum()))
    if not storage_rows.empty:
        _add_row("m6", "costo_almacenamiento", float(storage_rows["valor"].iloc[0]))
    consistency = balance_consistency(contracts, float(h3["tolerancia_cop"]))
    if consistency is not None:
        fraction, diff_max, _ = consistency
        _add_row("m6", "consistencia_balance", fraction, dif_max=f"{diff_max:,.0f}".replace(",", "."))
    return rows


def sheet_03_metrics(
    contracts: dict[str, pd.DataFrame], cutoff: _dt.date | None = None, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Construye `03_Metricas_Desarrollo` (una fila por modelo x metrica x segmento).

    Reporta las metricas del bloque `backtest` (WAPE/MAE/Bias; el MAE en COP entero) por
    modelo/objetivo con segmento global; el WAPE por ciudad, por semana y (M4/M5) por fondo cuando
    el contrato `backtest` existe; los KPI operativos del horizonte (tasa de agotamiento y
    remanente de M1, costo total de M1-M3 y M6, consistencia del balance de M6) calculados de las
    salidas; y las dos metricas operativas de M6 (`completitud_saldo_inicial`,
    `cobertura_recomendaciones`) sin WAPE (SUP-11). Nunca se fuerza un numero: lo no calculable se omite.

    Args:
        contracts: Contratos cargados.
        cutoff: Fecha de corte; ``None`` usa la de `export_anexo_d.yml`.
        cfg: Configuracion de ``export_anexo_d.yml`` (``None`` la carga).

    Returns:
        pd.DataFrame: columnas = HEADERS['03_Metricas_Desarrollo'], en orden.
    """
    cfg = resolve_config(cfg)
    cutoff = cutoff or to_date_or_none(cfg.get("corte"))
    seg_global = cfg["hoja_03"]["segmento_global"]
    met = contracts["metricas"].copy()
    rows: list[dict] = []
    periods = backtest_periods(cutoff)

    backtest = met[met["bloque"] == "backtest"]
    for _, row in backtest.iterrows():
        mdl = str(row["modelo"])
        target = row.get("objetivo")
        if target is None or (isinstance(target, float) and pd.isna(target)):
            target = _METRIC_TARGET.get(mdl, mdl)
        comment = _backtest_comment(mdl, row.get("nota"))
        is_rn08 = _is_rn08_reading(row.get("nota"), cfg)
        since, until = periods.get(mdl, periods["m1"])
        for metric, column, unit in (
            ("WAPE", "wape", "porcentaje"),
            ("MAE", "mae", "COP"),
            ("Bias", "bias", "porcentaje"),
        ):
            value = row.get(column)
            if value is None or pd.isna(value):
                continue  # no se fuerza; metrica no calculable se omite
            value = int(round(float(value))) if unit == "COP" else float(value)
            if is_rn08:  # lectura con la que puntua el banco, al lado de la actual y rotulada
                metric = cfg["hoja_03"]["lectura_rn08"]["rotulo_metrica"].format(metrica=metric)
            rows.append(
                _row_03(mdl, target, "predictiva", metric, value, unit, seg_global, since, until, METHODOLOGY, comment)
            )

    rows += segment_rows(contracts.get("backtest"), cutoff, periods, cfg)
    rows += _kpi_rows(contracts, cutoff, cfg)

    # M6: metricas operativas (sin WAPE, SUP-11).
    m6 = met[(met["modelo"] == "m6")]
    since, until = periods["m6"]
    for _, row in m6.iterrows():
        block = str(row["bloque"])
        n_obs = row.get("n_obs")
        n_excluded = row.get("n_excluidas")
        if block == "completitud_saldo_inicial":
            kpi, value = "completitud_saldo_inicial", _coverage(n_obs, n_excluded)
        elif block == "cobertura_recomendaciones":
            kpi, value = "cobertura_recomendaciones", _coverage_rec(n_obs, n_excluded)
        else:
            continue
        rows.append(
            _row_03(
                "m6", kpi, "operativa", kpi, value, "porcentaje", seg_global, since, until, METHODOLOGY, row.get("nota")
            )
        )

    out = pd.DataFrame(rows, columns=HEADERS["03_Metricas_Desarrollo"])
    if alx.interruptor("hoja03_textos_v2"):
        out = texts_v2(out, cfg)
    return out


def texts_v2(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Hoja 03 v2 (interruptor `hoja03_textos_v2`): comentarios y metodologia limpios; ningun valor cambia.

    Aplica los reemplazos y las tildes de ``hoja_03_v2`` a `comentarios` y `metodologia_validacion` y quita las
    oraciones repetidas de cada celda.
    """
    h3 = cfg["hoja_03_v2"]
    out = df.copy()
    out["metodologia_validacion"] = out["metodologia_validacion"].map(lambda t: h3["metodologia"].get(t, t))
    words = {str(k): str(v) for k, v in (h3.get("tildes") or {}).items()}
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b")

    def clean(text: object) -> object:
        if not isinstance(text, str):
            return text
        for regex, repl in h3["reemplazos"]:
            text = re.sub(regex, repl, text)
        text = pattern.sub(lambda m: words[m.group(1)], text) if words else text
        seen, parts = set(), []
        for sentence in re.split(r"(?<=\.) ", text.strip()):
            key = sentence.strip()
            if key and key not in seen:
                seen.add(key)
                parts.append(key)
        return " ".join(parts)

    out["comentarios"] = out["comentarios"].map(clean)
    return out


def _is_rn08_reading(note: object, cfg: dict[str, Any]) -> bool:
    """True si la fila de `metricas` es la lectura RN-08 (la `nota` empieza por el prefijo del conf)."""
    prefix = cfg["hoja_03"]["lectura_rn08"]["prefijo_nota"]
    return isinstance(note, str) and note.startswith(prefix)


def rn08_text(mdl: str, target: str, contracts: dict[str, pd.DataFrame] | None, cfg: dict[str, Any]) -> str | None:
    """Limitacion RN-04B sobre la lectura RN-08, con el WAPE de ambas lecturas leido de `metricas`.

    Solo se emite si el contrato trae filas de lectura RN-08 para el modelo y el objetivo; sin ellas, ``None``.
    """
    if contracts is None or mdl not in ("M1", "M2"):
        return None
    met = contracts["metricas"]
    bt = met[(met["modelo"] == mdl.lower()) & (met["bloque"] == "backtest")]
    mark = bt["nota"].map(lambda n: _is_rn08_reading(n, cfg))
    rn08, base = bt[mark], bt[~mark]
    if rn08.empty:
        return None
    parts = []
    for _, row in rn08.iterrows():
        row_target = row.get("objetivo")
        row_target = _METRIC_TARGET.get(mdl.lower(), mdl) if row_target is None or pd.isna(row_target) else row_target
        if str(row_target) != target:
            continue
        prior_rows = (
            base[base["objetivo"].fillna("").astype(str).isin(["", str(row_target)])]
            if "objetivo" in base.columns
            else base
        )
        if pd.isna(row.get("wape")) or prior_rows.empty or pd.isna(prior_rows["wape"].iloc[0]):
            continue
        parts.append(
            cfg["hoja_04"]["limitaciones_adicionales"]["rn08_cifras"].format(
                objetivo=row_target, wape_base=float(prior_rows["wape"].iloc[0]), wape_rn08=float(row["wape"])
            )
        )
    if not parts:
        return None
    return cfg["hoja_04"]["limitaciones_adicionales"]["rn08"].format(cifras=" ".join(parts))


def _backtest_comment(model: str, note: object) -> str:
    """Compone el comentario de la metrica (exclusion Anexo C + holdout 0-obs).

    Args:
        model: Clave de modelo (minuscula).
        note: Nota del contrato de metricas (si existe).

    Returns:
        str: Comentario para la hoja 03.
    """
    parts = []
    if model in ("m1", "m2"):
        parts.append("Excluye los dias del Anexo C y cajeros RN-07 (SUP-01).")
    parts.append(
        "Backtest interno (ultima ventana del entrenamiento, D7); el holdout "
        "1-15 sep tiene 0 observaciones reales (datos hasta 31-ago, SUP-02)."
    )
    if isinstance(note, str) and note:
        parts.append(note)
    return " ".join(parts)


def _coverage(n_obs: object, n_excluded: object) -> float | None:
    """Cobertura = n_obs / (n_obs + n_excluidas); None si no hay base.

    Args:
        n_obs: Observaciones con dato.
        n_excluded: Observaciones excluidas.

    Returns:
        float | None: Fraccion de cobertura, o ``None`` si la base es 0.
    """
    try:
        a = float(n_obs)
        b = float(n_excluded)
    except (TypeError, ValueError):
        return None
    total = a + b
    return (a / total) if total > 0 else None


def _coverage_rec(n_obs: object, n_excluded: object) -> float | None:
    """Cobertura de recomendaciones = (n_obs - n_excl) / n_obs; None si base 0.

    En el contrato m6, `n_obs` = riesgos totales y `n_excluidas` = riesgos sin
    accion; la cobertura es la fraccion cubierta.

    Args:
        n_obs: Riesgos totales.
        n_excluded: Riesgos sin accion.

    Returns:
        float | None: Fraccion cubierta, o ``None`` si no hay riesgos.
    """
    try:
        total = float(n_obs)
        without = float(n_excluded)
    except (TypeError, ValueError):
        return None
    return ((total - without) / total) if total > 0 else None
