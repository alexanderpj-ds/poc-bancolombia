"""Paquete `daas` - PoC DaaS Administracion del Efectivo (Bancolombia).

Componente analitico de la PoC. Arquitectura medallion AWS-first (S3 como SSOT
+ SageMaker) con espejo local para desarrollo. Este paquete expone la capa de
I/O (`daas.io.storage`) y los modulos del pipeline (ingest, quality, fondo,
curate, features, model, costs, lineage, publish, pipeline).

La version del paquete se expone en `__version__`.
"""

__version__ = "0.1.0"
