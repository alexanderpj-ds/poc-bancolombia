"""Reporte de calidad de datos del subpaquete `quality`.

Genera el reporte DQ (json + md) con los conteos por dataset/validacion y
escribe las filas no conformes a cuarentena en `daas://quality/rejected/...`
via `daas.io.storage`. Regla de negocio: el reporte **cuadra**
``conformes + rechazos == total`` por dataset y es la evidencia de la compuerta
de calidad.

El reporte se persiste en:
  - ``daas://quality/reports/<ts>`` (parquet con el resumen tabular).
  - ``daas://quality/rejected/<dataset>`` (una tabla por dataset con rechazos).
Ademas devuelve el resumen como ``dict`` y escribe un ``.md`` legible junto al
espejo local cuando es posible.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

from daas.io import storage


@dataclass
class DatasetResult:
    """Resultado de calidad de un dataset tras aplicar las validaciones.

    Attributes:
        dataset: Nombre canonico del dataset (p.ej. ``txn_cajeros``).
        total_entrada: Filas de entrada antes de las validaciones.
        conforme: DataFrame con las filas que pasaron la compuerta.
        rechazado: DataFrame con las filas en cuarentena (con metadata DQ).
        notas: Observaciones (p.ej. cobertura/universo, conflictos RN-07).
    """

    dataset: str
    total_inflow: int
    compliant: pd.DataFrame
    rejected: pd.DataFrame
    notes: dict = field(default_factory=dict)


def _dataset_summary(res: DatasetResult) -> dict:
    """Construye el resumen (dict) de un dataset y verifica el cuadre."""
    n_conf = int(len(res.compliant))
    n_rejected = int(len(res.rejected))
    reasons: dict[str, int] = {}
    if not res.rejected.empty and "__dq_rule" in res.rejected.columns:
        reasons = res.rejected["__dq_rule"].astype("string").value_counts().to_dict()
    return {
        "dataset": res.dataset,
        "total_entrada": int(res.total_inflow),
        "conformes": n_conf,
        "rechazos": n_rejected,
        "cuadra": (n_conf + n_rejected) == int(res.total_inflow),
        "rechazos_por_regla": {str(k): int(v) for k, v in reasons.items()},
        "notas": res.notes,
    }


def generate_report(
    results: Iterable[DatasetResult],
    ts: str | None = None,
) -> dict:
    """Genera el reporte DQ (json + md) y escribe la cuarentena.

    Args:
        results: Iterable de ``ResultadoDataset`` (uno por dataset validado).
        ts: Marca de tiempo del run; si es ``None`` se usa la hora actual.

    Returns:
        dict: Resumen con ``timestamp``, ``datasets`` (lista de resumenes) y
        ``cuadra_global`` (todos los datasets cuadran conformes+rechazos=total).
    """
    ts = ts or _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    results = list(results)

    summaries = []
    for res in results:
        summary = _dataset_summary(res)
        summaries.append(summary)
        # Escribir cuarentena por dataset (solo si hay rechazos).
        if not res.rejected.empty:
            storage.write_table(
                res.rejected,
                f"daas://quality/rejected/{res.dataset}",
            )

    report = {
        "timestamp": ts,
        "datasets": summaries,
        "cuadra_global": all(r["cuadra"] for r in summaries),
    }

    # Persistir el resumen tabular en quality/reports/<ts>.
    table = pd.DataFrame(
        [
            {
                "dataset": r["dataset"],
                "total_entrada": r["total_entrada"],
                "conformes": r["conformes"],
                "rechazos": r["rechazos"],
                "cuadra": r["cuadra"],
            }
            for r in summaries
        ]
    )
    path_physical = storage.write_table(table, f"daas://quality/reports/{ts}")

    # Escribir el .md legible junto al parquet (solo en espejo local).
    if path_physical.startswith("file://"):
        # unquote decodifica el percent-encoding (p.ej. %20) de file:// URIs.
        destination = Path(unquote(path_physical.replace("file://", "", 1))).with_suffix(".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_render_md(report), encoding="utf-8")
        # JSON completo (incluye motivos/notas) junto al md.
        destination.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    return report


def _render_md(report: dict) -> str:
    """Renderiza el reporte DQ como Markdown legible."""
    lines = [
        f"# Reporte de calidad de datos (DQ) - {report['timestamp']}",
        "",
        f"Cuadre global: {'OK' if report['cuadra_global'] else 'FALLA'}",
        "",
        "| dataset | total | conformes | rechazos | cuadra |",
        "|---|---:|---:|---:|:--:|",
    ]
    for r in report["datasets"]:
        lines.append(
            f"| {r['dataset']} | {r['total_entrada']} | {r['conformes']} | "
            f"{r['rechazos']} | {'si' if r['cuadra'] else 'NO'} |"
        )
    lines.append("")
    for r in report["datasets"]:
        if r["rechazos_por_regla"] or r["notas"]:
            lines.append(f"## {r['dataset']}")
            if r["rechazos_por_regla"]:
                lines.append(f"- Rechazos por regla: {r['rechazos_por_regla']}")
            if r["notas"]:
                lines.append(f"- Notas: {r['notas']}")
            lines.append("")
    return "\n".join(lines)
