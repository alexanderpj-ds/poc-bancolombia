"""Lectores por contrato canonico (C-01..C-12) del subpaquete `ingest`.

Un modulo por contrato: cada uno expone `read() -> pd.DataFrame` que lee la
fuente real en disco (nombre/hoja/encoding/sep via `conf/sources.yml`) y
devuelve el DataFrame canonico correspondiente. Las reglas de coercion se documentan en
cada lector.
"""
