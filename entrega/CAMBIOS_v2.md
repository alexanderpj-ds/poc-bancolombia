# Cambios del entregable v2 (26-oct-2026)

`POC_Efectivo_PRAGMA.xlsx` y `output_api/` se regeneraron con el registro de supuestos propio como versión final
(`pipeline/docs/supuestos.md`). Toda información que el banco no suministró queda suplida con un supuesto declarado
(registro y hoja 04). Los pronósticos de M1–M5 (hoja 01) y las métricas predictivas (hoja 03) no cambian.

| Archivo | sha256 |
|---|---|
| v1 (respaldo en `historico/v1_2026-10-21/`) | `52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688` |
| v2 (este directorio) | `167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461` |

El sha256 de una corrida nueva nunca coincide con el anterior: el xlsx guarda la fecha de generación
(`docProps/core.xml`). La equivalencia se prueba celda a celda (abajo).

## Interruptores (`pipeline/conf/alx.yml`)

Valor por defecto de todos: `false` (clave ausente = `false` = comportamiento v1). Con los diez en `false` la corrida
reproduce v1 (corrida A, ver "Reproducción de v1").

| Interruptor | v2 | Qué cambia | Supuesto |
|---|---|---|---|
| `m6_cajeros_sucursal` | true | M6 integra los cajeros administrados por sucursal al fondo de su sucursal | SUP-12 |
| `m2_tarifa_interurbana` | true | Tarifa MF interurbano para MF de TDV fuera del municipio de la ciudad del fondo | SUP-21 |
| `m3_escala_anexo_a` | true (decisión D-1, confirmada SÍ el 26-oct-2026) | Escala de sucursal interurbana desde `Escalas` de Oficinas | SUP-22 |
| `nivel_riesgo_previo` | true | `nivel_riesgo` de la hoja 02 antes de la acción; cupo insuficiente declarado | SUP-42, SUP-44 |
| `monto_minimo_recoleccion` | true | M3 no recomienda recolecciones de efectivo ocioso que no pagan su visita | SUP-43 |
| `m6_operaciones_rn84` | true | Intercambio y cambio de denominación deshabilitados dentro del fondo | SUP-14 |
| `m6_traslado_t1` | true | Traslado disponible en el destino al día siguiente (nota del Anexo E); se ordena el día anterior al faltante, las dos filas con la fecha de ejecución (RN-74) | SUP-52 |
| `m6_tarifa_traslado_declarada` | true | Solo textos: la explicación de los traslados con costo declara la tarifa usada (TDV del origen) y la alternativa (TDV del destino); métrica `costo_traslado_tarifa_destino` | SUP-53 |
| `hoja04_v2` | true | Hoja 04 reescrita para el evaluador y validada (exige `supuestos_alx`) | todos |
| `hoja03_textos_v2` | true (decisión D-2, confirmada SÍ el 26-oct-2026) | Solo `comentarios` y `metodologia_validacion` de la hoja 03 | — |

## Qué cambió, por qué y cuánto

### 1. M6 integra los 84 cajeros de sucursal (SUP-12; pliego §7.1, RN-70, RN-08A, Anexo A Oficinas)

- 82 de 84 se rutean al fondo `CIUDAD FONDO|TTADORA` de su sucursal administradora (mismo puente que M3). 9859 y
  9860 quedan fuera (sucursal 787 ausente de Oficinas): 2.568.045.929 COP de pagado de M1, declarados en la hoja 04, en
  SUP-12 y en `metricas` (`flujo_sin_fondo`). 2691 va a `CALI|TRANSPORTADORA_002` (su sucursal 70 se atiende desde
  Cali); alternativa declarada: 1.360.258.526 COP a `PASTO|TRANSPORTADORA_001`.
- Hoja 05 (deduplicada por fondo × fecha × denominación): ingresos 1.348,99 → 1.391,20 mil M COP (+42,21);
  salidas 957,20 → 1.066,31 mil M COP (+109,11). Cuadre con los pronósticos ≤ 2 COP por fondo-día.
- Acciones (con SUP-52, punto 10): ventas 169 → 148 filas; traslados 200 → 198 filas (100 → 99 traslados); retiro
  BanRep 0 → 4; sin acción 196 → 216; filas 565 → 566. 0 faltantes sin acción; 0 saldos negativos.
- `supuesto_utilizado` de las 566 filas de la hoja 05 agrega SUP-12 (RN-73).

Tabla por fondo v1 → v2 (mil M COP; filas de la hoja 05):

| Fondo | Δ ingresos | Δ salidas | Ventas v1 → v2 | Filas de traslado v1 → v2 | Costo acciones v2 |
|---|---:|---:|---|---|---:|
| CALI\|TRANSPORTADORA_001 | +1,89 | +15,14 | 35 → 28 | 69 → 70 | 0 |
| CALI\|TRANSPORTADORA_002 | +28,70 | +67,67 | 47 → 41 | 0 → 2 | 0 |
| CALI\|TRANSPORTADORA_003 | +2,65 | +11,35 | 0 → 0 | 57 → 48 (+ 4 retiros BanRep) | 896.117 |
| CALI\|TRANSPORTADORA_004 | 0 | 0 | 0 → 0 | 74 → 74 | 0 |
| IPIALES\|TRANSPORTADORA_002 | +2,00 | +2,63 | 59 → 59 | 0 → 2 | 545.413 |
| PASTO\|TRANSPORTADORA_001 | +6,96 | +12,31 | 28 → 20 | 0 → 2 | 0 |

Costo de almacenamiento del horizonte (hoja 03): 43.368.281 → 41.460.623 COP (menos ventas y más salidas).

**Costo de M6 de 0 a 1.441.530 COP.** 545.413 COP son 2 traslados
`IPIALES|TRANSPORTADORA_002 → PASTO|TRANSPORTADORA_001` en la denominación 50.000: 709.150.000 COP ejecutado el 4-sep
(costo 257.330) y 799.600.000 COP ejecutado el 5-sep (costo 288.083), para los faltantes proyectados de Pasto del
sábado 5 y el domingo 6 (SUP-52: disponibles al día siguiente). Con los cajeros de sucursal de Pasto integrados, Pasto
quedaría bajo su mínimo de 50.000 ese sábado y ese domingo; BanRep y venta no se permiten en días no hábiles (RN-71A) y
el traslado desde Ipiales es la alternativa de menor costo (desde Cali costaba 1.486.729). Los otros 896.117 COP son 4
retiros BanRep del 1-sep en CALI|TRANSPORTADORA_003 (punto 10). Costo = fijo + monto / 10.000 × tarifa
con la fila `Traslado Ipiales-Pasto` de la TRANSPORTADORA_002 del Anexo E (Fondos): 16.219 + 709.150.000 / 10.000 ×
3,40 = 257.330 y 16.219 + 799.600.000 / 10.000 × 3,40 = 288.083 (RN-04A, RN-79); se registra una sola vez, en la fila
de salida del origen (RN-74). En v1 todos los traslados eran entre fondos de Cali, con costo 0 por la nota del Anexo E
de misma ciudad. La verificación recalcula los 99 traslados y los 4 retiros BanRep de v2 contra el Anexo E: 0 diferencias. Qué
transportadora cobra el traslado entre ciudades no lo dice el Anexo E: se declara en SUP-53 (punto 11).

### 2. Tarifa MF interurbano (SUP-21; RN-04A)

- 5 MF de TDV con municipio distinto de la ciudad del fondo (Cali): 1519 y 7352 (Palmira), 7814 (Tuluá), 9251
  (Pradera), 9650 (Yumbo). Sus 61 acciones (59 recolecciones, 2 provisiones) pasan de 9.888.680 a 13.825.215 COP
  (+3.936.535); costo total de M2 en la hoja 03: 71.404.981 → 75.341.516 COP. Las 61 explicaciones lo dicen.
- M1 no cambia: los 4 dispensadores INDIVIDUAL fuera de la ciudad del fondo (8416, 3568, 3781, 4458; 14 provisiones,
  2.360.392 COP) siguen con tarifa urbana; alternativa interurbana +575.069 COP (declarada en SUP-21).

### 3. Escala de sucursal desde `Escalas` (SUP-22; Anexo A, RN-04A)

Solo la sucursal 70 (`INTERURBANO 3`, `Escalas = 1`): 15 recolecciones, 18.279.543 → 11.521.605 COP (−6.757.937).

### 4. `nivel_riesgo` antes de la acción (SUP-42) y cupo insuficiente (SUP-44); RN-03, RN-12, RN-21, RN-34, RN-35, RN-38, RN-40

| Hoja 02 | v1 | v2 |
|---|---|---|
| M1 provisión | 1.349 bajo | 855 alto + 494 medio (= alertas crítico/alerta del mismo día) |
| M2 provisión | 28 bajo | 27 alto (26 de 8667 y 9311) + 1 medio |
| M2 recolección | 719 bajo | 719 medio |
| M3 provisión | 2 bajo | 2 medio (nunca bajo) |
| M3 recolección | 432 bajo | 216 alto (exceso sobre el cupo) + 209 bajo (efectivo ocioso) |
| sin_accion | 62 bajo | 62 bajo (peor severidad de alertas) |

8667 y 9311 (MF de sucursal, cupo 85.502.000): 100 % de sus filas en alto; la explicación dice "Cupo insuficiente",
los días con flujo neto > cupo (4 y 1), la demanda no atendida mínima (73.047.796 y 18.008.804 COP) y RN-28 como
"permite consolidar". Ninguna otra entidad cumple el criterio. No se publica ningún "22 días".

### 5. Monto mínimo de recolección (SUP-43; RN-40, RN-44, RN-38, RN-22, RN-35)

- M3: 7 recolecciones de efectivo ocioso omitidas por 548.282 COP (824 ×2, 869, 871, 997 ×3; su costo v1 sumaba
  634.217 COP); el efectivo se encadena y lo recoge la siguiente visita (6 recolecciones cambian de monto). 0
  recolecciones ociosas con monto ≤ costo (8 en v1). 0 omitidas con saldo sobre el cupo. Recolecciones de M3: 432 →
  425; costo total de M3: 147.650.688 → 140.258.965 COP (incluye la escala del punto 3).
- M2: 0 omisiones (RN-35 obliga); 1 recolección antieconómica mantenida y explicada (9251, 9-sep, 155.355 frente a
  213.153 COP de costo).
- Riesgo residual (REQ-4.8): quedan 31 recolecciones de M3 menores de 1 M COP cuyo monto sí supera su costo.

### 6. Hoja 04 v2 (RN-04, RN-04B, Anexo C, RN-84, §5, §13)

Las 80 celdas de texto de las 8 filas se reescribieron (sin jerga interna, con tildes, sin oraciones repetidas;
validación automática en U7): efecto estimado del bloque de abril (Anexo C) con las cifras de la evaluación de
imputación; definición de festivo, quincena y fin de mes (RN-04, SUP-49); variables de eventos (§5, SUP-51); dos
lecturas del WAPE en M1/M2 (RN-08 primero) y en M3 (fórmula literal frente a SUP-27); operaciones de RN-84 usadas
(traslado_fondos 198 filas, venta_efectivo 148, retiro_banrep 4) y no usadas con su razón; regla del traslado al día
siguiente (SUP-52) y tarifa del traslado entre ciudades (SUP-53); cajeros de sucursal; omisiones de M3; cada
SUP con su número y título del registro.

### 7. Hoja 03 (D-2)

Cambian los textos de 49 `comentarios` y de las 105 `metodologia_validacion`. Valores: solo 4 filas de costo (M2,
M3, M6 costo total y M6 almacenamiento). Las 91 predictivas iguales (2 con ruido de punto flotante de 1–2 ulp, ver
verificación).

### 8. `m6_operaciones_rn84` (SUP-14)

0 acciones de cambio de denominación o intercambio en v1 y en v2; cambia el texto del descarte en las explicaciones de
la hoja 05 ("RN-84: el cambio de denominación es con BanRep y el intercambio con otras entidades…").

### 9. Registro de supuestos

Todos los SUP con los 6 encabezados (No lo entregó el banco · Qué asumimos · Por qué · Efecto · Alternativa · Dónde),
sin renumerar; SUP-41 reservado; nuevos SUP-42 a SUP-53; reescritos SUP-01, 02, 03, 06, 08, 12, 13, 14, 18, 21, 22, 27,
29, 36, 37, 40 y M3-01. "Preguntas abiertas" pasa a "Preguntas convertidas en supuestos". Ninguna mención a Anexos B o
C no recibidos; los no recibidos son `Historico BANREP.xlsx` e `Historico Traslados.xlsx` del Anexo A (SUP-46).

### 10. Traslado disponible al día siguiente (SUP-52; Anexo E nota *, RN-74, RN-71, RN-71A, RN-80)

Hallazgo B-1 de la revisión: la v2 anterior acreditaba el traslado en el destino el mismo día, contra la nota del
Anexo E ("El efectivo sale del fondo origen en la fecha de ejecución y se encuentra disponible en el fondo destino al
día siguiente"). Ahora el traslado se ordena el día anterior al faltante proyectado. Sus dos filas llevan la fecha de
ejecución, como pide RN-74 ("con el mismo monto, fecha y denominación"). El destino lo recibe al cierre de ese día, que
es su saldo inicial del día siguiente (RN-71). Un faltante del mismo día no se cubre con traslado.

Efecto, v2 anterior → v2 (solo cambian la hoja 05, 2 valores de costo de la hoja 03 y la fila M6 de la hoja 04; las
hojas 01 y 02 son idénticas):

- Traslados: 105 → 99 (210 → 198 filas). 25 se ordenan el día anterior al faltante.
- Retiro BanRep: 0 → 4. Son los 4 faltantes del 1-sep en CALI|TRANSPORTADORA_003 (denominaciones 2.000, 5.000,
  10.000 y 20.000), que no admiten traslado porque habría que ordenarlo antes del corte: 947.993.000 COP con costo de
  896.117 COP.
- Ventas: 146 → 148. Sin acción: 213 → 216. Filas de la hoja 05: 569 → 566.
- `nivel_riesgo` de la hoja 05: 543 bajo + 26 medio → 543 bajo + 23 medio.
- Alertas de M6: 275 → 250.
- Costo de M6 en la hoja 03: 545.413 → 1.441.530 COP. Almacenamiento: 41.381.630 → 41.460.623 COP.
- Necesidades: siguen 275, 251 resueltas con una acción y 24 conservadas por costo. 0 parciales y 0 sin solución.
- Pasto: los dos traslados desde Ipiales pasan del 5 y 6-sep al 4 y 5-sep, con los mismos montos y costos.
  PASTO|TRANSPORTADORA_001 no queda bajo su mínimo ningún día.
- La verificación independiente (`verificar_t1.py`) confirma lo siguiente:
  - los pares tienen la misma fecha;
  - ninguna entrada cubre un faltante del mismo día;
  - cada traslado anticipado deja el saldo de T+1 sobre el mínimo y era necesario;
  - no hay BanRep ni ventas en días no hábiles;
  - los costos de BanRep y de los traslados coinciden con el Anexo E.
- Alternativas descartadas (en SUP-52): (a) traslado el mismo día (v2 anterior); (b) filas con fechas T y T+1, que
  contradicen la "misma fecha" de RN-74.

### 11. Tarifa del traslado entre ciudades (SUP-53; RN-74, Anexo E Fondos)

Hallazgo B-2 de la revisión. El Anexo E no dice qué transportadora cobra un traslado entre ciudades cuando los fondos
son de transportadoras distintas. Se declara la regla aplicada: la tarifa es la de la transportadora del fondo origen,
que entrega el efectivo y en cuya fila se registra el costo (RN-74). El comportamiento no cambia. Las 2 filas de
salida con costo de la hoja 05 dicen la tarifa usada y la alternativa, y su `supuesto_utilizado` cita SUP-53. La fila
M6 de la hoja 04 y la métrica informativa `costo_traslado_tarifa_destino` también lo declaran. Costo: 545.413 COP con
la TRANSPORTADORA_002 del origen; con la TRANSPORTADORA_001 del destino serían 938.560 COP (+393.147). SUP-16 se
corrigió: ya no dice que el T+1 del código es de M6, sino que M6 sigue la nota del Anexo E (SUP-52).

## Reproducción de v1 (corrida A)

Código nuevo (iteración 2, con SUP-52 y SUP-53) y el `alx.yml` v1 (sha256 `e841aca2…6832`): las 6 hojas iguales
celda a celda (valor, fórmula y formato) salvo 1 celda de la hoja 03 (WAPE de M3 entradas 0,3884279257131179 → …178, 2 ulp) por ruido de punto
flotante del pronóstico de M3 (diferencia relativa ≤ 4,8·10⁻¹⁵ en `predicciones`, código de pronóstico sin cambios);
hoja 06, `_schemas` y `silenciosos` idénticos byte a byte; los demás contratos iguales por modelo. Detalle en
`.agents/tasks/correcciones-v2/verificacion.md`.

## Archivos modificados (ALX no es repositorio git)

- `pipeline/conf/`: `alx.yml`, `costos.yml`, `export_anexo_d.yml`, `model_m3.yml`, `model_u6.yml`.
- `pipeline/src/daas/`: `costs/anexo_e.py`; `modules/funds_m6/dataset.py`, `simulator.py`;
  `modules/branches_m3/balance.py`, `policy.py`; `pipeline/run_u1_u2.py`, `run_u3.py`, `run_u6.py`;
  `publish/validate_xlsx.py`; `publish/anexo_d/masters.py`, `sheet_02_operational_plan.py`, `sheet_03_metrics.py`,
  `sheet_04_description.py`, `sheet_04_v2.py` (nuevo), `sheet_05_m6_funds.py`.
- `pipeline/docs/supuestos.md`; `tests_alx/test_correcciones_v2.py` (nuevo); `tests_alx/test_entrega_interruptores.py`.
- `entrega/POC_Efectivo_PRAGMA.xlsx`, `entrega/output_api/*` (v1 respaldada en `entrega/historico/v1_2026-10-21/`).

## Pendientes para el trabajo posterior

- ~~Publicación en S3 con el Excel y `output_api/` v2~~ y ~~ajustar el sha256 que exige `publicar.py`~~: hechos
  el 26-oct-2026, ver "Publicación en S3" al final.
- Actualizar el repo GitHub (`poc-bancolombia-repo`), `CONTEXTO_LLM.md` y `guia_supuestos.md` (incluida la
  corrección de que los Anexos B y C sí se recibieron).
- Comunicar a Andrés los cambios y que el registro propio es la versión final.
- Pedir al banco `Historico BANREP.xlsx` e `Historico Traslados.xlsx` (SUP-46).
- Decisión del usuario sobre la alternativa de SUP-44 (segunda atención consolidada en 8667/9311: 4 y 1 provisiones
  adicionales por 73.047.796 y 18.008.804 COP).
- Decisión sobre la alternativa de SUP-21 (INDIVIDUAL interurbano, +575.069 COP).
- Citar SUP-20 y SUP-29 en `supuesto_utilizado` de la hoja 05; tildes de los textos heredados de las hojas 02 y 05
  (las frases nuevas sí llevan tildes); salvedad de SUP-09 (reparto del pagado por gavetas).
- Riesgo residual de M3: 31 recolecciones menores de 1 M COP que sí superan su costo (la regla aprobada no las omite).
- Observaciones no bloqueantes de la revisión que siguen abiertas:
  - NB-1: "laboratorio" sin definir en la hoja 04.
  - NB-2: frases de variables y componentes de M4 y M5.
  - NB-3: grupos de equipos silenciosos de M1 sin separar entre RN-07 y RN-08.
  - NB-4: alternativa literal de RN-07 en SUP-06.
  - NB-5: cambio de denominación con BanRep en Cali, y atribución a RN-71A en lugar de SUP-13 o SUP-14 en días no
    hábiles.
  - NB-6 (comentario de `conf/costos.yml`) quedó corregida.
- La v2 de la iteración 1 (sha256 `8efab823…965a`, nunca entregada al banco) queda fuera de Drive, en
  `~/.cache/poc-daas/corrida_entrega_v2/B_v2/`.

## Cierre de la revisión final (26-oct-2026)

- La revisión final de la iteración 2 dejó resueltos B-1 (traslado con disponibilidad T+1, SUP-52) y B-2 (tarifa del traslado entre ciudades declarada, SUP-53), y abrió un único hallazgo, B-3: el texto de SUP-14 en el registro decía que las operaciones usadas eran solo traslado y venta, mientras la v2 también usa 4 `retiro_banrep` (CALI|TRANSPORTADORA_003, 1-sep).
- El Excel ya era correcto: la fila M6 de la hoja 04 declara `traslado_fondos` (198 filas), `venta_efectivo` (148) y `retiro_banrep` (4).
- B-3 se corrigió solo en el texto de SUP-14 (`ALX/pipeline/docs/supuestos.md`, "Qué asumimos" y "Efecto"), sin regenerar el Excel. El sha256 del Excel v2 sigue siendo `167a52e4…` después de la corrección.

## Publicación en S3 (26-oct-2026)

- Ruta: `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/` (carpeta nueva, perfil `alx-mx`). Misma
  estructura que `v0_provisional/`: `anexo_d/`, `api/`, `esquemas/`, `tablas/`, `validacion/` y `manifest.json`.
- Objetos: 249 (10.401.803 B, 9,9 MiB). `anexo_d/POC_Efectivo_PRAGMA_v2.xlsx` es este Excel (sha256 `167a52e4…`).
  Las tablas son copia fiel de `output_api/` v2: 2.547 alertas y 2.897 recomendaciones.
- Fecha: 26-oct-2026, 19:37 hora Colombia (2026-10-27T00:37:03Z). Revisión 1 de la v2.
- Puntero nuevo: `s3://poc-daas-bancolombia-777937796305/output/pronosticos/version_vigente.json`. Indica
  `version_vigente = v2`, su prefijo, el sha256 del manifest y del Excel, y la versión anterior (`v0_provisional`,
  entrega v1, Excel `52e7547f…`).
- `v0_provisional/` no se tocó: sigue con 249 objetos y los mismos ETag que antes de publicar.
- Verificación:
  - Se descargaron los 249 objetos. Los 248 del manifest coinciden en bytes y sha256 (`publicar.py verificar`).
  - El ChecksumSHA256 que guarda S3 coincide en los 249.
  - Claves iguales a `v0_provisional/`, salvo el Excel de `anexo_d/` (`_v2` en lugar de `_v1`).
  - La simulación recalculada reproduce las 2.523 recomendaciones y las 2.297 alertas de M1–M3.
  - Las métricas coinciden con la hoja 03.
  - Los contratos OpenAPI dan 0 errores de esquema en 1.176 instancias.
- Insumos: los de la corrida B2_v2 que generó esta entrega. No se mezclaron con los de la v1.
- Script y forma de republicar: `ALX/publicacion_s3/README.md`. `publicar.py --version v2|v0_provisional`; la
  opción `v0_provisional` reproduce la v1 con sha256 idéntico en los 247 archivos.
