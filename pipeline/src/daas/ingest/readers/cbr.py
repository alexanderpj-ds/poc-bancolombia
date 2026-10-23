"""Lector del contrato C-07 `cbr`.

Fuente real: `raw/CLIENTES_Y_CBR.xlsx`, hoja `CBR` (mismo archivo que C-08,
hoja distinta). Corresponsales bancarios / CBR (39 `cod_punto`). Regla de
negocio: usar `Formato Fecha` (datetime real) como fecha canonica, NO
`FECHAEFC` (entero `YYYYMMDD`).
"""

from __future__ import annotations

import pandas as pd

from daas.ingest.readers._points import read_points


def read() -> pd.DataFrame:
    """Lee la fuente C-07 (`CLIENTES_Y_CBR.xlsx`, hoja `CBR`).

    Fecha canonica `Formato Fecha` (no `FECHAEFC`). Ruta/hoja via
    `conf/sources.yml` (C-07).

    Returns:
        pd.DataFrame: Esquema canonico de puntos (`cod_punto`, `fecha`,
        `ciudad`, `transportadora`, `valor`, ...).
    """
    return read_points("C-07")
