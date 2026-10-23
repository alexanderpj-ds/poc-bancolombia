"""Subpaquete `modules.funds_inflows_m4_m5`: modelos M4 (CBR) y M5 (Clientes) (U4/U5).

Modelos mas livianos de la PoC: pronostico de ingreso de efectivo por FONDO-dia
(`fondo_id = CIUDAD|TRANSPORTADORA`), horizonte 1-15 sep 2026. SIN simulacion de
saldo, SIN recomendaciones, SIN alertas (son insumo de M6).

Expone la carga de configuracion (`config.cargar_config`) y el loader de series
fondo-dia (`dataset.cargar_serie_fondo_dia`). El orquestador vive en
`daas.pipeline.run_u4_u5`.
"""
