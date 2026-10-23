"""Fase 2 de ALX: ML global (LightGBM, XGBoost, CatBoost, RandomForest/ExtraTrees, HGB), ensambles y conformal.

Hace importables `lab` (raiz de ALX) y `daas` (pipeline/src, no instalado en el venv). Todo lo pesado (caches de
predicciones y variables, logs, Optuna) vive FUERA de Google Drive, en `CACHE_ML`; en ALX solo quedan codigo,
configuracion (`conf/`) y resultados chicos (`resultados/`).
"""

import os
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
ALX_DIR = ML_DIR.parent
CONF_DIR = ML_DIR / "conf"
#: Resultados y caches por defecto (fase 2). La repeticion con imputacion (PARTE 5) los redirige por variables de
#: entorno, para que lleguen tambien a los workers loky: POC_ML_RESULTADOS y POC_ML_CACHE (sin ellas, como antes).
RESULTADOS_DIR = Path(os.environ.get("POC_ML_RESULTADOS") or ML_DIR / "resultados")
#: Raiz de caches fuera de Drive: pred/, variables/, log/, optuna/.
CACHE_ML = Path(os.environ.get("POC_ML_CACHE") or "/Users/alexanderpelaez/.cache/poc-daas/ml")

for _ruta in (ALX_DIR, ALX_DIR / "pipeline" / "src"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))
