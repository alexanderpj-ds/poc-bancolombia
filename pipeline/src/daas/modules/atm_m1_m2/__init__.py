"""Nucleo compartido U1/U2 (ATM) del subpaquete `forecasting`, `decision` y `modules`.

Contiene la base numerica comun a M1 (dispensador) y M2 (multifuncional):

- `config`: carga de `conf/model_u1_u2.yml` con default documentado.
- `dataset`: `load_series(modelo)` (derivacion pagado/cash_in por `cdgtrn`,
  join de `cupo`/`admon`, densificacion a dias calendario) y el mecanismo de
  exclusion de metricas RN-07 por cajero (SUP-01).

 (M1) y (M2) dependen de este nucleo; es independiente de
ambos en logica.
"""
