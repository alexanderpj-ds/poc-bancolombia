"""Generacion del Anexo D: el Excel de entrega que recibe y evalua el banco.

Se construye sobre la plantilla oficial con openpyxl (preserva titulos, encabezados, estilos y formatos),
borra las filas de ejemplo `PROVEEDOR_DEMO` y puebla las 5 hojas obligatorias con los contratos
`output/api/*` leidos por `daas.io.storage`. La hoja informativa `06_Diccionario_Campos` se conserva intacta.

Reglas de construccion:

- Las columnas que la plantilla define como formula (p. ej. `horizonte_dias`) se escriben como formula Excel,
  nunca como valor.
- M6 no va en `01_Predicciones` (su entidad y horizonte son los de M1-M5): tiene su hoja `05_M6_Fondos`, con el
  balance por denominacion como grano y una sola accion recomendada por fila (menor costo; empate: traslado,
  venta, banrep).
- `04_Descripcion_Solucion` declara el enfoque que corrio de verdad, las variables mas relevantes medidas y los
  SUP-xx por modelo.
- Nunca se inventa un dato: cada celda sale de un contrato o de un supuesto SUP-xx documentado; un dato ausente
  deja la celda vacia o con la nota del diccionario.

Un modulo por responsabilidad: `constants`, `config`, `masters`, `cell_values`, `sheet_01_predictions` a
`sheet_05_m6_funds`, `workbook` (escritura sobre la plantilla) y `generate` (orquestacion).
"""

from daas.publish.anexo_d.config import load_export_config, resolve_template_path
from daas.publish.anexo_d.constants import DICTIONARY_SHEET, HEADERS, PROVIDER_ID, REQUIRED_SHEETS
from daas.publish.anexo_d.generate import build_sheets, generate_anexo_d

__all__ = [
    "DICTIONARY_SHEET",
    "HEADERS",
    "PROVIDER_ID",
    "REQUIRED_SHEETS",
    "build_sheets",
    "generate_anexo_d",
    "load_export_config",
    "resolve_template_path",
]
