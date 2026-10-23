"""Orquestacion de la unidad U7 (Anexo D) del `pipeline`.

U7 es el ULTIMO entregable del componente analitico: genera el Excel de entrega
`POC_Efectivo_PRAGMA.xlsx` (nombre exigido por el pliego seccion 9) que el banco
recibe y evalua. Encadena:

  1. CONFIG : carga `conf/export_anexo_d.yml` (id_proveedor='PRAGMA', ruta de la
              plantilla oficial, ruta de salida, corte y horizonte).
  2. GENERA : `publish.anexo_d.generate_anexo_d` lee los contratos `output/api/*`
              via `daas.io.storage`, abre la plantilla oficial con openpyxl
              (preservando formato), borra las filas de ejemplo `PROVEEDOR_DEMO`,
              puebla las 5 hojas obligatorias con los datos reales
              (`id_proveedor='PRAGMA'`), conserva `06_Diccionario_Campos` y
              guarda el `.xlsx` en `output/anexo_d/`.
  3. VALIDA : `publish.validate_xlsx` abre el `.xlsx` y comprueba listas de la plantilla, enteros,
              obligatorias y RN-02; si algo incumple, la corrida FALLA despues de escribir el manifiesto.
  4. MANIFEST: escribe el manifiesto `.meta.json` del artefacto (hojas, filas por
              hoja, pregunta abierta #35) via `lineage.manifest`.

El entregable va a `output/anexo_d/` (bajo `local.root`), que esta gitignored
(datos confidenciales): NO se versiona ni la plantilla ni el `.xlsx`.
Implementacion y verificacion 100% LOCAL (no toca S3).

Pregunta abierta #35: la plantilla recibida tiene 6 hojas (5 obligatorias +
`06_Diccionario_Campos`); el pliego menciona 3 hojas informativas que NO estan
en el archivo y NO se inventan (ver `docs/supuestos.md`).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field

from daas.lineage import manifest
from daas.publish import anexo_d, validate_xlsx
from daas.publish.anexo_d.cell_values import to_date_or_none
from daas.publish.anexo_d.masters import load_contracts

logger = logging.getLogger(__name__)

#: Pregunta abierta #35 (documentada en el manifiesto; NO se inventan hojas).
_QUESTION_35 = (
    "La plantilla recibida tiene 6 hojas (5 obligatorias + 06_Diccionario_Campos). "
    "El pliego menciona 3 hojas informativas (00_Instrucciones, "
    "GUIA_Descripcion_Solucion, 07_Catalogo_Ejemplos) que NO estan en el archivo; "
    "no se crean (pregunta abierta #35, ver docs/supuestos.md)."
)


class InvalidAnexoDError(RuntimeError):
    """El `.xlsx` generado incumple la validacion de `publish.validate_xlsx`."""

    def __init__(self, output: str, errors: list[str]) -> None:
        self.output, self.errors = output, errors
        detail = "\n  - ".join(errors)
        super().__init__(f"El Anexo D {output} incumple la validacion ({len(errors)}):\n  - {detail}")


@dataclass
class SummaryU7:
    """Resumen de una corrida completa de `run_u7` (CLI y verificacion).

    Attributes:
        run_id: Identificador de corrida.
        salida: Ruta fisica del `.xlsx` generado.
        filas_por_hoja: Nº de filas de datos por hoja obligatoria.
        hojas: Lista de hojas obligatorias pobladas.
    """

    run_id: str
    output: str = ""
    rows_by_sheet: dict[str, int] = field(default_factory=dict)
    sheets: list[str] = field(default_factory=list)


def run() -> SummaryU7:
    """Orquesta U7: config -> genera el Anexo D -> manifiesto.

    Returns:
        ResumenU7: Resumen de la corrida (run_id, salida, filas por hoja, hojas).
    """
    run_id = manifest.new_run_id()
    logger.info("U7 (Anexo D) run_id=%s", run_id)

    cfg = anexo_d.load_export_config()
    cutoff = to_date_or_none(cfg.get("corte", "2026-08-31"))

    # Construir las hojas una vez para contar filas y luego generar el archivo.
    contracts = load_contracts()
    sheets = anexo_d.build_sheets(contracts, cutoff)
    rows_by_sheet = {name: int(len(df)) for name, df in sheets.items()}

    output = anexo_d.generate_anexo_d(cfg)
    errors = validate_xlsx.validate_anexo_d(output, cfg)

    manifest.write_manifest(
        output,
        {
            "capa": "output",
            "dataset": "anexo_d/POC_Efectivo_PRAGMA",
            "entregable": "Anexo D",
            "id_proveedor": anexo_d.PROVIDER_ID,
            "hojas": list(anexo_d.REQUIRED_SHEETS),
            "filas_por_hoja": rows_by_sheet,
            "pregunta_abierta_35": _QUESTION_35,
            "validacion": {"ok": not errors, "incumplimientos": errors},
        },
    )
    if errors:
        # Falla visible: el entregable queda escrito (para revisarlo) pero la corrida no cierra en verde.
        raise InvalidAnexoDError(output, errors)

    return SummaryU7(
        run_id=run_id,
        output=output,
        rows_by_sheet=rows_by_sheet,
        sheets=list(anexo_d.REQUIRED_SHEETS),
    )


def main() -> None:
    """Punto de entrada de consola para la unidad U7 (Anexo D).

    Ejecuta `run()` end-to-end y escribe un resumen por consola.
    """
    parser = argparse.ArgumentParser(
        prog="daas.pipeline.run_u7",
        description=(
            "Orquesta U7 (Anexo D): genera el Excel de entrega POC_Efectivo_PRAGMA.xlsx "
            "desde la plantilla oficial, poblando las 5 hojas obligatorias con los "
            "datos reales de output/api/* (id_proveedor=PRAGMA). 100% LOCAL."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log a nivel INFO.")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    summary = run()

    print(f"U7 run_id={summary.run_id}")
    print(f"Anexo D: {summary.output}")
    print("Filas por hoja (datos reales, sin PROVEEDOR_DEMO):")
    for sheet in summary.sheets:
        print(f"  {sheet}: {summary.rows_by_sheet.get(sheet, 0)}")
    print(f"Hoja informativa conservada: {anexo_d.DICTIONARY_SHEET}")
    print(f"Pregunta abierta #35: {_QUESTION_35}")


if __name__ == "__main__":
    main()
