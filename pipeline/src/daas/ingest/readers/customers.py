"""Lector del contrato C-08 `clientes`.

Fuente real: `raw/CLIENTES_Y_CBR.xlsx`, hoja `Clientes` (mismo archivo que
C-07, hoja distinta). Maestro de clientes (universo real ~529 `cod_punto`).
Reglas de negocio:
  - Mismo esquema que CBR: usar `Formato Fecha` (NO `FECHAEFC`).
  - Llega hasta 2026-09-29 (pasa el corte 31-ago); el recorte temporal y el
    universo "vigente" (P24, ~529 vs 344 esperados) se tratan en curate/quality,
    nunca aqui (el lector no filtra ni fuerza conteos).
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._points import read_points


def read() -> pd.DataFrame:
    """Lee la fuente C-08 (`CLIENTES_Y_CBR.xlsx`, hoja `Clientes`).

    Ruta/hoja via `conf/sources.yml` (C-08). No aplica recorte temporal ni
    filtro de vigencia (eso es responsabilidad de curate/quality).

    Returns:
        pd.DataFrame: Esquema canonico de puntos (`cod_punto`, `fecha`,
        `ciudad`, `transportadora`, `valor`, ...).
    """
    return read_points("C-08")
