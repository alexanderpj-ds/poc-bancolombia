"""Laboratorio de evaluación. Importa `daas` desde `pipeline/src` (no está instalado en el venv)."""

import sys
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
CONF_DIR = LAB_DIR / "conf"
REPO_ROOT = LAB_DIR.parent
PIPELINE_SRC = REPO_ROOT / "pipeline" / "src"
PIPELINE_CONF_DIR = REPO_ROOT / "pipeline" / "conf"

if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))
