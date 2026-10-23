"""Publica la explicabilidad de los pronosticos como artefacto lateral.

No es uno de los 4 contratos de `output/api`: es un insumo de la hoja 04 del Anexo D
(`variables_mas_relevantes`). Vive en `daas://output/explicabilidad/importancias`, una fila por
(modelo, objetivo, tipo, grupo). UPSERT por modelo, como los contratos.
"""

from __future__ import annotations

import logging

import pandas as pd

from daas.io import storage

logger = logging.getLogger(__name__)

URI = "daas://output/explicabilidad/importancias"
COLUMNS = ["modelo", "objetivo", "receta", "tipo", "grupo", "valor", "n_obs"]


def block(model: str, by_target: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Arma el bloque de un modelo desde `{objetivo publicado: Pronostico.explicacion}`."""
    parts = [df.assign(modelo=model, objetivo=obj) for obj, df in by_target.items() if not df.empty]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(parts, ignore_index=True)[COLUMNS]


def upsert(blocks: list[pd.DataFrame], models: list[str]) -> str | None:
    """Reemplaza las filas de `modelos` en el artefacto y conserva las de los demas.

    Args:
        blocks: Bloques frescos (pueden venir vacios).
        models: Modelos que esta corrida reemplaza (aunque su bloque venga vacio).

    Returns:
        str | None: Ruta escrita, o `None` si no hay nada que publicar.
    """
    parts = [b for b in blocks if not b.empty]
    if storage.exists(URI):
        current = storage.read_table(URI)
        parts.insert(0, current[~current["modelo"].isin(models)])
    parts = [p for p in parts if not p.empty]
    if not parts:
        return None
    file_path = storage.write_table(pd.concat(parts, ignore_index=True)[COLUMNS], URI)
    logger.info("Explicabilidad publicada en %s (modelos %s).", file_path, models)
    return file_path
