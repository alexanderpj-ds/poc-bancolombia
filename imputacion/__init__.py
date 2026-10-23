"""Imputacion de faltantes de la PoC DaaS (workflow de imputacion, oct-2026).

Hace importables `lab`, `ml`, `datos_poc` (raiz de ALX) y `daas` (pipeline/src, no instalado en el venv). Todo lo
pesado (checkpoints, logs, cachés) vive FUERA de Google Drive, en `CACHE_IMP`; en ALX solo quedan codigo,
configuracion (`conf/`) y resultados chicos (`resultados/`).
"""

import sys
from pathlib import Path

IMP_DIR = Path(__file__).resolve().parent
ALX_DIR = IMP_DIR.parent
CONF_DIR = IMP_DIR / "conf"
RESULTADOS_DIR = IMP_DIR / "resultados"
#: Raiz de checkpoints y cachés fuera de Drive.
CACHE_IMP = Path("/Users/alexanderpelaez/.cache/poc-daas/imputacion")

for _ruta in (ALX_DIR, ALX_DIR / "pipeline" / "src"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))
