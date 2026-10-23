"""Subpaquete M6 Fondos de efectivo (U6).

Modelo PRESCRIPTIVO aislado del nucleo congelado M1-M5 (`daas.modules.atm_m1_m2`,
`daas.modules.branches_m3`, `daas.modules.funds_inflows_m4_m5`): config + dataset + balance + recomendador
propios de los fondos de boveda. No es un forecaster clasico, sino un simulador
de balance por `fondo_id`+denominacion que consume los pronosticos ya publicados
de M1-M5, los proyecta dia a dia sobre el saldo inicial y recomienda acciones
logisticas costeadas (traslado entre fondos, venta, BanRep, intercambio y cambio
de denominacion). Reutiliza la maquinaria compartida (`costs.anexo_e`
-extendida de forma retrocompatible-, `publish.contracts`, `io.storage`,
`lineage.manifest`, `fondo.build_fund`) SIN modificarla.
"""
