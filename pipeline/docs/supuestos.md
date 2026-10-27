# Supuestos analíticos de la PoC

Registro final de supuestos de la solución (versión v2, 26-oct-2026). El banco indicó que la información que no
suministró debe suplirse con supuestos debidamente documentados: cada supuesto de este registro dice qué información
no entregó el banco, qué asumimos, por qué (con el texto literal del pliego o de los Anexos cuando existe), su efecto
cuantificado, la alternativa y su efecto, y dónde se aplica. La hoja `04_Descripcion_Solucion` del Anexo D cita cada
supuesto por su número y su título.

**Fuentes.** Pliego `POC_DaaS.docx` y Anexos originales del banco: A (metadatos de insumos), B (reglas de negocio
RN-xx), C (observaciones de calidad), D (plantilla de entrega) y E (parámetros de costos), en
`~/Desktop/datos-anexo-poc-bancolombia/`. Las citas entre comillas son texto literal de esos documentos. Las cifras
salen de los datos reales de la corrida del entregable; las rutas de evidencia son relativas a la carpeta de trabajo.

**Numeración.** No se renumeró ningún supuesto. SUP-41 está reservado para la propuesta de M5 v2, no adoptada
(`m5_mejora/resultados_m5_v2.md`). Los supuestos nuevos van de SUP-42 a SUP-53. Las cifras marcadas "(v2)" son las de
la corrida del entregable v2 (`entrega/CAMBIOS_v2.md`).

**Interruptores.** Las correcciones del entregable v2 están detrás de interruptores de `pipeline/conf/alx.yml`
(valor por defecto `false`; con todos en `false` la corrida reproduce el entregable v1): `m6_cajeros_sucursal`
(SUP-12), `m2_tarifa_interurbana` (SUP-21), `m3_escala_anexo_a` (SUP-22), `nivel_riesgo_previo` (SUP-42, SUP-44),
`monto_minimo_recoleccion` (SUP-43), `m6_operaciones_rn84` (SUP-14), `m6_traslado_t1` (SUP-52),
`m6_tarifa_traslado_declarada` (SUP-53), `hoja04_v2` y `hoja03_textos_v2`.

---

## SUP-01 · Exclusión de métricas por cajero, no por entidad-día

**No lo entregó el banco.** El estado operativo diario de cada cajero: el maestro trae el estado vigente y la lista
de desinstalados trae una fecha de baja, pero no qué días estuvo fuera de operación.

**Qué asumimos.** Los 29 cajeros en conflicto RN-07 (activos en el maestro y presentes en la lista de desinstalados;
25 de M1 y 4 de M2) se excluyen de WAPE, MAE y sesgo en todos sus días, y tampoco calibran la banda. Siguen en los
contratos de salida y en la hoja 01 por completitud.

**Por qué.** El pliego (§8): "Se excluirán del cálculo las entidades-día correspondientes a equipos desmontados,
retirados o no operativos según el maestro. La obligación de reportar la fila con valor cero se mantiene para efectos
de completitud, no de evaluación." RN-07: "los equipos desmontados, retirados o inactivos se reportarán con valor
pronosticado cero a partir de la fecha de su cambio de estado". Sin estado diario, la exclusión por entidad-día no se
puede construir; la del cajero entero es la que se sostiene con el maestro.

**Efecto.** 29 cajeros fuera de las métricas internas de M1 y M2 (columna `__rn07_conflicto`). No cambia ningún
pronóstico publicado.

**Alternativa.** Excluir por entidad-día desde la fecha de baja de la lista de desinstalados; las observaciones de
frontera podrían no coincidir con las del banco. Con un estado operativo diario se cambia la granularidad sin tocar
código.

**Dónde.** `metricas.excluir_rn07_por_cajero` en `pipeline/conf/model_u1_u2.yml`; `modules/atm_m1_m2/dataset.py`
(`exclude_rn07_by_atm`).

---

## SUP-02 · Ceros reales, faltantes y lectura RN-08 en el WAPE

**No lo entregó el banco.** El detalle del cálculo oficial del WAPE para el cero operativo y para una entidad con
denominador cero.

**Qué asumimos.** Un cero en un día con la red operando es una observación válida. Los 27 días del Anexo C (sin dato
en toda la red) quedan como faltantes: no se imputan, no entran a las métricas y los rezagos, medias y perfiles se
calculan solo con los días con dato. Una entidad con denominador cero en la ventana sale del WAPE agregado (SUP-27).
Para M1 y M2 se publican dos lecturas del backtest: primero la que corresponde a RN-08 y al último párrafo del Anexo C
(la ausencia de registro con la red operando vale 0 COP), que es la que usa el banco para puntuar, y la de
entrenamiento (la ausencia de registro es faltante).

**Por qué.** RN-08: "Cuando el resto de la red registre operación en una fecha, la ausencia de registros de un equipo
corresponde a inactividad real y equivale a 0 COP [...] Cuando la fecha corresponda a los días de indisponibilidad
de la fuente declarados en el Anexo C, la ausencia deberá tratarse como dato faltante y en ningún caso como valor
cero." Anexo C: "Los 27 días deberán tratarse como datos faltantes y nunca como valores observados iguales a cero" y
"Estos días deberán excluirse del cálculo de cualquier métrica de validación interna".

**Efecto.** WAPE del backtest con la lectura RN-08 frente a la de entrenamiento: M1 0,3145 frente a 0,2490; M2 pagado
0,4488 frente a 0,3642; M2 cash-in 0,4814 frente a 0,3832. Efecto estimado del bloque de abril sobre el pronóstico:
en la hoja 04 y en SUP-36 (medido entrenando con los faltantes imputados; dentro de 2 errores estándar).

**Alternativa.** Si el WAPE oficial tratara el cero operativo de otra forma, la cifra del banco puede diferir con el
mismo modelo; las dos lecturas publicadas acotan esa diferencia.

**Dónde.** `quality/anexo_c.py` (ventana del Anexo C); `publish/contracts.py` (lecturas `RN-08:` de `metricas`);
interruptor `sup02_denominador_cero` (`pipeline/conf/alx.yml`); hoja 03 y hoja 04.

---

## SUP-03 · Días calendario en M1–M3

**No lo entregó el banco.** Nada: el calendario del periodo lo fijan el pliego y RN-02; se registra para trazabilidad.

**Qué asumimos.** M1–M3 pronostican y reportan todos los días calendario del 1 al 15 de septiembre de 2026, incluidos
sábados, domingos y festivos. El saldo simulado evoluciona igual en días no hábiles.

**Por qué.** RN-02: "La hoja 01_Predicciones deberá contener una fila por cada combinación de entidad, variable
objetivo y fecha del periodo de evaluación [...] No se admitirán omisiones de filas como mecanismo para representar
ausencia de pronóstico." Pliego §9: "Todos los entregables deberán corresponder [...] al periodo de evaluación
comprendido entre el 1 y el 15 de septiembre de 2026, con granularidad diaria."

**Efecto.** 15 filas por entidad y variable en la hoja 01 (9.690 filas).

**Alternativa.** Reportar solo días hábiles rompería RN-02 (omisión de filas).

**Dónde.** `horizonte` en `conf/model_u1_u2.yml`, `conf/model_m3.yml` y `conf/export_anexo_d.yml`;
`publish/validate_xlsx.py` (`_validate_rn02`).

---

## SUP-04 · Umbral de agotamiento de M1 = 8 % del cupo (RN-34)

**No lo entregó el banco.** Nada: lo fija RN-34 ("el umbral de riesgo de desabastecimiento se fija en 8 % del cupo
aplicable"); se registra para trazabilidad.

**Qué asumimos.** El umbral de agotamiento es 8 % del cupo operativo de RN-09. Su papel en la política está en SUP-19.

**Por qué.** RN-34: "En M1, el proveedor define la fecha de provisión según su política, pero la trayectoria simulada
no deberá descender por debajo del 8 % del cupo operativo sin una provisión programada."

**Efecto.** Define las alertas de M1 (855 críticas y 494 de alerta en las provisiones del horizonte) y el nivel de
riesgo de la hoja 02 (SUP-42).

**Alternativa.** Si el banco ajustara el umbral, es un cambio de parámetro.

**Dónde.** `m1.umbral_agotamiento` en `conf/model_u1_u2.yml`.

---

## SUP-05 · Cassette de depósitos de M2 (sin efecto)

**No lo entregó el banco.** La capacidad del cassette de depósitos de los multifuncionales.

**Qué asumimos.** M2 no modela un cassette separado: el efectivo recibido se recicla y el saldo es neto de pagado y
cash-in. El número se conserva para no renumerar.

**Por qué.** RN-30: "el efectivo recibido no se mantiene separado del efectivo disponible para retiro"; RN-23: "Se
asume que la totalidad del efectivo recibido es reutilizable por el equipo."

**Efecto.** Ninguno: el saldo de M2 sigue RN-19 y RN-30.

**Alternativa.** No aplica mientras rijan RN-23 y RN-30.

**Dónde.** `modules/atm_m1_m2/balance.py` (`simulate_balance_m2`).

---

## SUP-06 · Código de cajero reutilizado: una serie por código (RN-06)

**No lo entregó el banco.** Un criterio o una marca que identifique cuándo un código de cajero pasó a otro equipo.

**Qué asumimos.** Cada código es una sola serie, con sus atributos vigentes (SUP-45), salvo que la validación contra
el maestro muestre un cambio de identidad. Criterio declarado de cambio de identidad: cambio de `disp_mf`, de
municipio real o de fondo, o un corte de transacciones en la fecha del cambio de atributos (dato en los 30 días
previos y ninguno en los 30 siguientes). Un cambio de administración (TDV a TDV o TDV a sucursal) con transacciones
continuas es el mismo equipo con otro operador. Los 25 códigos de la lista de desinstalados (bajas de 2005 a 2022) que
figuran en "Produccion" en el maestro y transan hasta el 29 o el 31 de agosto se tratan como código reutilizado: se
pronostican, porque RN-07 se aplica sobre su estado vigente.

**Por qué.** RN-06: "El código del equipo no constituye un identificador único permanente. Bancolombia podrá haber
reutilizado un mismo código en equipos con nombre, ubicación o condiciones operativas diferentes. El proveedor deberá
validar la consistencia del código contra los atributos del maestro y tratar como series independientes los casos en
que se evidencie un cambio de identidad." RN-27: la diferencia entre tipos de administración "se limita al mecanismo
de atención, la frecuencia operativa y el costo del servicio". RN-07: "Los equipos activos deberán contar con
predicción para la totalidad del periodo de evaluación".

**Efecto.** Validación sobre los 491 códigos y los snapshots de `raw/cp_historico.xlsx`
(`.agents/tasks/correcciones-v2/evidencia/rn06_cambios.csv`): nombre y coordenadas cambian en casi todos los códigos
por el enmascaramiento (nombre en el 92,6 % de los 462 códigos fuera del conflicto RN-07 y en el 58,6 % de los 29 en
conflicto; latitud en el 98,1 % y el 82,8 %), por lo que no sirven como señal de identidad. `disp_mf`, `fondo` y
`estado`: 0 cambios. Municipio: 2 códigos (4350 y 4568, `VALLE` ↔ `YUMBO`: el departamento en lugar del municipio,
error de dato). Administración: 4 códigos del grupo en conflicto cambian entre transportadoras (117, 1302, 2381, 9368)
con transacciones continuas; 8 códigos fuera de él cambian entre TDV y sucursal (1160, 1161, 1162, 5767, 6823, 7368,
7864, 8396). Con el criterio declarado: 0 cambios de identidad. Pronóstico positivo para los 25 de M1 y 4 de M2 en
conflicto (salen de las métricas por SUP-01).

**Alternativa.** Cortar la serie en cada cambio de administración: cambiaría la hoja 01 de esos códigos sin evidencia
de otro equipo.

**Dónde.** Serie por `cod_cajero` en `modules/atm_m1_m2/dataset.py`; verificación con
`~/.cache/poc-daas/corrida_entrega_v2/scripts/rn06_atributos.py`.

---

## SUP-07 · Saldo inicial de M6 = último registro ≤ 31-ago por fondo y denominación

**No lo entregó el banco.** Un saldo al cierre del 31 de agosto para los fondos y denominaciones sin registro ese
día.

**Qué asumimos.** El saldo inicial de cada fondo y denominación es su último registro de disponibles con fecha ≤
2026-08-31. Una combinación sin registro arranca en 0 con aviso.

**Por qué.** Pliego §5: "El proveedor deberá utilizar el último disponible por fondo y denominación registrado hasta el
31 de agosto de 2026"; RN-71A: "Los disponibles históricos solo existen para días hábiles."

**Efecto.** 36 de 36 combinaciones con saldo inicial mayor que 0; saldo de la red al corte 212.331.636.000 COP.

**Alternativa.** Otra regla para fondos sin registro ese día cambiaría el saldo de arranque (hoy no aplica: ninguna
combinación queda en 0).

**Dónde.** `saldo_inicial` en `conf/model_u6.yml`; `modules/funds_m6/dataset.py`
(`initial_balance_by_fund_denomination`).

---

## SUP-08 · Operaciones habilitadas por fondo, inferidas del histórico (M6)

**No lo entregó el banco.** La matriz de operaciones permitidas por fondo y el `Historico Traslados.xlsx` que lista el
Anexo A (SUP-46).

**Qué asumimos.** La venta se habilita en un fondo si aparece en su histórico de ventas; el traslado entre fondos de
`dim_fondo` siempre está habilitado; BanRep sigue SUP-13; el intercambio y el cambio de denominación no se recomiendan
dentro del fondo (SUP-14).

**Por qué.** RN-75: "debe considerar los fondos que están habilitados para realizar dichas operaciones, de acuerdo con
el histórico compartido". RN-82: "Las recomendaciones se limitan a los fondos, ciudades y operaciones incluidos en los
datos entregados."

**Efecto.** Venta habilitada en los fondos con histórico de ventas; v2: 148 filas de venta, 198 de traslado (99
traslados) y 4 de retiro BanRep en el horizonte (SUP-52).

**Alternativa.** Con la matriz oficial se cambia la fuente en `operaciones` de `conf/model_u6.yml`; una operación
permitida sin uso histórico queda hoy fuera.

**Dónde.** `modules/funds_m6/dataset.py` (`enabled_operations_matrix`); `operaciones` en `conf/model_u6.yml`.

---

## SUP-09 · Reparto del efecto de M1–M5 por denominación (M6)

**No lo entregó el banco.** La composición por denominación de los flujos de los canales.

**Qué asumimos.** El efecto neto de M1–M5 por fondo y día se reparte entre denominaciones en proporción a la mezcla
histórica del valor en disponibles del fondo, en los 180 días que terminan en el corte, calculada con los disponibles
corregidos (SUP-29). Sin histórico, reparto uniforme con aviso. No se corrige el perfilado por denominación ni el
desbalance persistente entre fondos.

**Por qué.** Pliego §7.1: "Cuando esta información no esté disponible por denominación, el proveedor podrá
distribuirla con una metodología explícita y declararla como estimada."

**Efecto.** Con los disponibles corregidos la mezcla cambia hasta 8,3 pp en `PASTO|TRANSPORTADORA_001` (50.000: 47,7 %
→ 56,0 %), hasta 2,7 pp en `CALI|TRANSPORTADORA_001` y 1,2 pp o menos en los demás fondos
(`imputacion/resultados/m6/efecto_mezcla.csv`).

**Alternativa.** Repartir el pagado de M1/M2 por gavetas y el resto por la mezcla de movimientos del fondo, validando en
cortes anteriores; no está implementada. El pagado de los cajeros se carga en pocas denominaciones y su flujo no tiene
por qué parecerse al stock de la bóveda.

**Dónde.** `mezcla_denominacion` en `conf/model_u6.yml`; `modules/funds_m6/dataset.py` (`denomination_mix_by_fund`).

---

## SUP-10 · Mínimos y máximos operativos de M6

**No lo entregó el banco.** Mínimos y máximos oficiales por fondo y denominación.

**Qué asumimos.** Mínimo = percentil 10 y máximo = percentil 90 del saldo diario por fondo y denominación en los 180
días que terminan en el corte, con los disponibles corregidos (SUP-29). Sin histórico, mínimo 0 y máximo 3 × saldo
inicial, con aviso.

**Por qué.** RN-72 pide identificar faltante ("cuando el efectivo disponible no sea suficiente para atender las
salidas esperadas") y excedente ("cuando el fondo mantenga efectivo superior al requerido"); sin niveles oficiales, el
rango observado es el dato disponible.

**Efecto.** Por construcción, el saldo histórico queda fuera del rango en cerca del 20 % de los días, y eso fija
cuántas acciones emite M6 (v2: 275 necesidades, 251 resueltas por una acción y 24 conservadas por costo).

**Alternativa.** Con los niveles oficiales se reemplazan por configuración.

**Dónde.** `minmax` en `conf/model_u6.yml`; `modules/funds_m6/balance.py` (`operational_minmax`).

---

## SUP-11 · Métrica de M6 sin WAPE

**No lo entregó el banco.** Nada: el pliego fija que M6 no reporta métricas predictivas; se registra para
trazabilidad.

**Qué asumimos.** M6 reporta la completitud del saldo inicial y la cobertura de las necesidades, y la identidad de
RN-71 en la hoja 03; no reporta WAPE sobre el saldo.

**Por qué.** Pliego §9: "M6 Fondos no deberá reportar métricas predictivas." RN-68: "M6 no es un modelo predictivo
independiente ni tiene una variable objetivo."

**Efecto.** Hoja 03: completitud 100 %, cobertura de necesidades y consistencia de RN-71 con diferencia máxima 0 COP.

**Alternativa.** Si el banco definiera una métrica para M6, se agrega como bloque adicional.

**Dónde.** `pipeline/run_u6.py` (`_metrics_block`); `publish/anexo_d/sheet_03_metrics.py`.

---

## SUP-12 · Flujo de M1–M3 al fondo, con los cajeros de sucursal (M6, RN-70)

**No lo entregó el banco.** La asignación cajero → fondo de los cajeros administrados por sucursal (`admon = SUC`): el
campo `fondo` del maestro CP dice "Fondo-Ciudad desde donde la TDV atiende el cajero", y estos cajeros no los atiende
una TDV.

**Qué asumimos.** El flujo de cada cajero de TDV va al fondo `fondo` + `admon` del maestro CP; el de cada sucursal (M3),
al fondo `CIUDAD FONDO` + `TTADORA` de Oficinas; y el de cada cajero administrado por sucursal (pagado de M1; pagado y
cash-in de M2), al fondo de su sucursal administradora: la fila de Oficinas cuyo código es su `codigo_sucursal`. Un
cajero cuya sucursal no está en Oficinas no recibe un fondo arbitrario: queda fuera y se declara con su cifra. El flujo
se imputa el día pronosticado, sin rezago logístico. Las entradas y salidas de M3 no incluyen el abastecimiento de los
cajeros que la sucursal administra (no hay doble conteo).

**Por qué.** Pliego §7.1: "Las proyecciones de M1 a M5 deberán utilizarse para calcular los ingresos y las salidas de
efectivo esperados en cada fondo: pagado de M1 y M2, cash_in de M2, entradas y salidas de M3". RN-08A: "en los demás
casos es administrado por la sucursal indicada en codigo_sucursal". Anexo A, Oficinas: "CIUDAD FONDO | Ciudad fondo
desde donde se atiende la sucursal" y "TTADORA | Transportadora que atiende actualmente la sucursal". RN-36 (variables
de M3 de la "operación propia de la sucursal") y RN-43 ("Los flujos de ATM deberán mantenerse diferenciados de las
entradas y salidas propias de la sucursal").

**Efecto.** 82 de los 84 cajeros de sucursal se integran (v2). Quedan fuera 9859 y 9860 (sucursal 787 ausente de
Oficinas): 2.568.045.929 COP de pagado de M1. El flujo integrado suma 42,21 mil M COP de ingresos (cash-in de M2) y
109,11 mil M COP de salidas (pagado de M1 y M2) en la hoja 05; por fondo, las salidas suben 15,15 mil M en
`CALI|TRANSPORTADORA_001`, 67,67 en `CALI|TRANSPORTADORA_002`, 11,35 en `CALI|TRANSPORTADORA_003`, 2,63 en
`IPIALES|TRANSPORTADORA_002` y 12,31 en `PASTO|TRANSPORTADORA_001`. M6 recomienda 148 ventas (169 en v1) y 99
traslados (100 en v1), con el traslado disponible al día siguiente (SUP-52). El cajero 2691 figura en Pasto en el maestro, en la hoja 01 y en el conteo del §3, pero su
sucursal (70, El Bordo) se atiende desde Cali: su flujo va a `CALI|TRANSPORTADORA_002`, el mismo fondo de su sucursal
en M3.

**Alternativa.** (a) Asignar 2691 al único fondo de Pasto: 1.360.258.526 COP de pagado de M1 irían a
`PASTO|TRANSPORTADORA_001` en lugar de `CALI|TRANSPORTADORA_002`. (b) Dejar fuera los 84 cajeros de sucursal
(entregable v1): 42,2 mil M de ingresos y 111,7 mil M de salidas no llegarían a ningún fondo. (c) Si las entradas y
salidas de M3 incluyeran el abastecimiento de esos cajeros, el flujo neto de los 82 (≈ −66,9 mil M COP en el
horizonte) estaría contado dos veces; los datos no permiten verificarlo.

**Dónde.** Interruptor `m6_cajeros_sucursal` (`pipeline/conf/alx.yml`); `modules/funds_m6/dataset.py`
(`_atm_code_to_fund_map_suc`, `net_effect_m1_m5_by_fund_day`); filas `cajeros_sucursal_mapeados` y `flujo_sin_fondo`
de `metricas`; `supuesto_utilizado` de la hoja 05.

---

## SUP-13 · BanRep: habilitación por tarifa y restricción a Cali (M6, RN-75)

**No lo entregó el banco.** El `Historico BANREP.xlsx` que lista el Anexo A (hojas Consignaciones República, Cambios
República y Consignaciones apto de baja; SUP-46) ni el listado de fondos autorizados.

**Qué asumimos.** Consignación y retiro BanRep se habilitan si la transportadora del fondo tiene tarifa BanRep en el
Anexo E y el fondo está en Cali.

**Por qué.** RN-75: "debe considerar los fondos que están habilitados para realizar dichas operaciones, de acuerdo con
el histórico compartido. Por ejemplo, para consignación y retiro de alta, solo están habilitados los fondos de Cali."

**Efecto.** BanRep habilitado en los 4 fondos de Cali; se evalúa en cada necesidad de esos fondos. En v2 se eligen 4
retiros BanRep (CALI|TRANSPORTADORA_003, 1 de septiembre, 947.993.000 COP, costo 896.117 COP): son faltantes del
primer día, que no admiten traslado (SUP-52). No hay consignaciones: en cada caso hubo otra alternativa de menor
costo o el día no era hábil (RN-71A).

**Alternativa.** Con el listado de fondos autorizados se cambia la lista de ciudades sin tocar código; sin la
restricción a Cali, BanRep quedaría habilitado en los 6 fondos por tarifa.

**Dónde.** `operaciones.banrep.ciudades_habilitadas` y `operaciones.banrep_desde_anexo_e` en `conf/model_u6.yml`.

---

## SUP-14 · Sin intercambio ni cambio de denominación dentro del fondo (M6, RN-84)

**No lo entregó el banco.** Un procedimiento o tarifa para rebalancear denominaciones dentro de un mismo fondo.

**Qué asumimos.** M6 no recomienda `cambio_denominacion` ni `intercambio_bancos` dentro del fondo: quedan
deshabilitados en los 6 fondos y la explicación de cada necesidad lo dice. Las operaciones usadas en el horizonte son
`traslado_fondos`, `venta_efectivo` y `retiro_banrep` (SUP-08, SUP-13, SUP-52); `consignacion_banrep` queda habilitada
en Cali (SUP-13) y no se eligió en ninguna necesidad.

**Por qué.** RN-84: "Podrán recomendarse: traslado_fondos, venta_efectivo, consignacion_banrep, retiro_banrep,
cambio_denominacion (cambios con Banco de la República), intercambio_bancos y otra_accion_justificada. El proveedor
deberá indicar cuáles utilizó." El cambio de denominación es con el Banco de la República y el intercambio con otras
entidades (pliego §7.1: "intercambios con otras entidades"); ninguno es un movimiento interno del fondo.

**Efecto.** 0 filas de cambio de denominación o intercambio en v1 y en v2; cambia el texto del descarte en las
explicaciones de la hoja 05. En v2 la hoja 05 usa `traslado_fondos` (198 filas, 99 traslados), `venta_efectivo`
(148 filas) y `retiro_banrep` (4 filas, CALI|TRANSPORTADORA_003, 1-sep), como declara la fila M6 de la hoja 04.

**Alternativa.** Emitirlos dentro del fondo con el concepto `Costo intercambio` del Anexo E (comportamiento previo,
con el interruptor apagado): contrario a la lectura literal de RN-84.

**Dónde.** Interruptor `m6_operaciones_rn84` (`pipeline/conf/alx.yml`); `operaciones.rn84.texto_descartada` en
`conf/model_u6.yml`; `modules/funds_m6/dataset.py` (`enabled_operations_matrix`) y `simulator.py` (`_is_allowed`).

---

## SUP-M3-01 · Saldo de la bóveda de M3 en [0, cupo_max_suc]

**No lo entregó el banco.** Una política de provisión y recolección por sucursal ni un máximo físico distinto del
cupo.

**Qué asumimos.** El saldo simulado se mantiene entre 0 y `cupo_max_suc`. Dentro del rango, la política diferenciada
por sucursal: reserva = mín(50 % del cupo, máx(8 % del cupo, σ del flujo neto)); provisión cuando el saldo previsto
baja de la reserva, hasta la reserva más 3 días de salidas medias; recolección de lo que pasa del techo (reserva más 15
días de salidas medias) o del cupo. El techo de 15 días se eligió entre 6, 10 y 15 con un criterio escrito antes de
medir: mantiene los días agotados de la regla vigente, reduce el efectivo ocioso y es el de menor costo en la ventana.
Una sucursal con menos de 30 días válidos de historia aplica la regla vigente del banco (apertura bajo el umbral →
cupo; recoge solo sobre el cupo), sin pronóstico.

**Por qué.** RN-38: "El saldo simulado no podrá ser negativo ni superar dicho cupo. No se asumirá una regla general de
llenado completo de bóveda ni un porcentaje único de recolección." RN-41: "El proveedor deberá proponer una política
diferenciada y sustentada en el comportamiento histórico". RN-16 y RN-52 para la historia corta. RN-44: "Los umbrales
preventivos por sucursal son parametrizables".

**Efecto.** v2: 2 provisiones y 425 recolecciones de M3 (216 por exceso sobre el cupo y 209 de efectivo ocioso); 0
saldos fuera de [0, cupo].

**Alternativa.** Techo de 6 o 10 días (más recolecciones de ocioso); regla única de llenado al cupo (prohibida por
RN-38).

**Dónde.** `politica` y `saldo.cap_superior` en `conf/model_m3.yml`; `modules/branches_m3/policy.py` y `balance.py`.

---

## SUP-M3-02 · cupo_max_suc vigente por sucursal

**No lo entregó el banco.** Nada: el pliego fija el cupo vigente; se registra para trazabilidad.

**Qué asumimos.** El cupo vigente es el último valor con fecha ≤ 2026-08-31; sin ninguno, el máximo observado con
aviso. En el laboratorio, el contexto toma el cupo vigente en cada origen (SUP-28).

**Por qué.** Pliego §5: "M3: cupo_max_suc vigente según el último registro disponible hasta el 31 de agosto de 2026."
RN-38: "El cupo_max_suc vigente al 31 de agosto de 2026 constituye la restricción de capacidad."

**Efecto.** 44 sucursales con cupo vigente; el cupo es constante por sucursal en el periodo, así que el contexto "as
of" no cambia nada en M3.

**Alternativa.** Ninguna con base en el pliego.

**Dónde.** `publish/anexo_d/masters.py` (`capacity_m3`); `modules/branches_m3/dataset.py`.

---

## SUP-15 · Nivel de servicio y costo del agotamiento (M1, M2)

**No lo entregó el banco.** Un costo de agotamiento ni una tasa de costo de oportunidad del efectivo quieto en cajeros
y sucursales (el banco lo confirmó por escrito).

**Qué asumimos.** El nivel de servicio lo fija el Anexo B: RN-12 pide una tasa de agotamiento "cercana a 0 %" y un
remanente antes de la provisión de hasta 22 % del cupo; RN-34 dispara la provisión al 8 %; RN-10 topa la provisión de
M1 en 500 M. No se le pone precio al agotamiento ni al efectivo quieto; la política se elige con la frontera entre
servicio y remanente.

**Por qué.** El único costo sobre efectivo quieto del Anexo E es el almacenamiento en fondos (M6). El pliego controla
el agotamiento con la meta de servicio, no con un costo.

**Efecto.** Con plan fijo, la política deja 3,4 % de días agotados (IC 95 %: 2,0–5,3 %; 13 episodios, lead time 0)
frente a 12,9 % de la regla anterior; ninguna variante llega a cerca de 0 % sin pasar el 22 % de remanente.

**Alternativa.** Un costo de agotamiento basado en el ingreso por transacción (lucro cesante), declarado como supuesto
del proveedor; hoy no se usa.

**Dónde.** `m1.politica` en `conf/model_u1_u2.yml`; filas de backtest de la política en la hoja 03.

---

## SUP-16 · Lead time de la provisión (M1)

**No lo entregó el banco.** Un lead time general ni por ciudad o transportadora (confirmado por el banco).

**Qué asumimos.** Lead time de 0 días: la provisión se aplica antes del pagado del mismo día. Un día queda como
sensibilidad. Este lead time es solo de la provisión de M1; los traslados entre fondos de M6 siguen la nota del
Anexo E (disponibles en el fondo destino al día siguiente, SUP-52).

**Por qué.** RN-11: "la provisión se aplica antes del pagado del día".

**Efecto.** Con el plan rehecho cada día, la política deja 0,41 % de días agotados con lead time 0, 2,63 % con 1 día y
8,70 % con 2; el costo por episodio pasa de 137,8 M a 139,5 M COP.

**Alternativa.** Lead time de 1 día (sensibilidad medida); se cambia en la configuración.

**Dónde.** `m1.lead_time_dias` en `conf/model_u1_u2.yml`.

---

## SUP-17 · Entidades con poca historia

**No lo entregó el banco.** Nada específico; RN-16 deja la estrategia al proveedor ("podrá usar equipos comparables,
modelos jerárquicos o agregación por zona o segmento, y deberá documentar la estrategia y sus limitaciones en la hoja
04_Descripcion_Solucion").

**Qué asumimos.** No hay un modelo aparte para entidades nuevas: el modelo global comparte con ellas lo aprendido en
toda la red; los modelos por serie caen a su respaldo estacional bajo el mínimo de observaciones; sin ningún ejemplo
de entrenamiento, el pronóstico es la media de los últimos 28 días, con aviso.

**Por qué.** RN-16, citada arriba; el modelo global es la forma de "equipos comparables" que admite la regla.

**Efecto.** Las entidades con menos de 90 días son el segmento con más error, pero pesan 0,5–0,9 % del volumen.

**Alternativa.** Agregación por zona o segmento; no se midió que mejorara.

**Dónde.** `forecaster.min_obs` de `conf/model_*.yml`; hoja 04 (bloque de poca historia).

---

## SUP-18 · Nada posterior al corte entra a entrenar ni a elegir

**No lo entregó el banco.** Nada: el corte lo fija el pliego (§6); se registra para trazabilidad.

**Qué asumimos.** Los holdouts del 1 al 15 de septiembre no se leen. Todo pronóstico usado para medir, calibrar la
banda, estimar el sesgo de red o explicar el modelo se hace con datos hasta su origen. Las 44 filas del crudo de
clientes posteriores al corte (`CALI|TRANSPORTADORA_004`, 1 al 29 de septiembre, 42,9 mil M COP) se excluyen. El
maestro CP vigente es dato de referencia, no información del objetivo (SUP-45).

**Por qué.** Pliego §9: "Todos los entregables deberán corresponder a la fecha de corte del 31 de agosto de 2026".

**Efecto.** 0 filas posteriores al corte en entrenamiento y métricas (guarda `no_futuro` del laboratorio).

**Alternativa.** Ninguna.

**Dónde.** `curate/build_processed.py` (holdouts), `lab/` (guarda `no_futuro`).

---

## SUP-19 · El 8 % de RN-34 es umbral de alerta; la política de M1 es la del pliego

**No lo entregó el banco.** Una política de provisión de M1 (RN-34: "el proveedor define la fecha de provisión según
su política").

**Qué asumimos.** El 8 % marca el riesgo y las alertas. La política vigente pide provisión el día en que el saldo
proyectado con el pronóstico baja del umbral y llena al cupo operativo en la fecha indicada, con margen 0 (RN-09,
RN-11, RN-34). Los montos fijos se miden solo como sensibilidad.

**Por qué.** RN-11: "monto de provisión = cupo operativo − saldo antes de provisión; saldo después de provisión = cupo
operativo". Una política con margen de 50 % incumplía RN-11, RN-12 y RN-34.

**Efecto.** Con plan fijo y lead time 0, remanente antes de la provisión de 24,6 % contra el saldo real (IC 95 %:
20,5–29,2 %), 22,3 % sobre su propio pronóstico y 21,5 % en el plan publicado (hoja 03).

**Alternativa.** Margen de 25 % o 50 %: el remanente sube a 30,9 % y 37,4 % y los agotados bajan a 2,1 % y 1,4 %.

**Dónde.** `m1.politica` en `conf/model_u1_u2.yml`.

---

## SUP-20 · Corrección del total de M5 que consume M6

**No lo entregó el banco.** Nada específico; el pliego pide que M6 use las proyecciones de M4 y M5.

**Qué asumimos.** M6 multiplica los ingresos pronosticados de M5 por un factor de red móvil `1 / (1 + sesgo)`, con el
sesgo del total medido fuera de muestra en los 3 últimos orígenes cerrados antes del origen de la corrida, acotado a
[0,67; 1,5]. Lo que M5 publica no cambia. M4 no se corrige.

**Por qué.** El pronóstico que gana en WAPE apunta a la mediana y subestima el total; M6 suma esos ingresos. En M5 el
sesgo es negativo en todos los orígenes medidos; en M4 cambia de signo.

**Efecto.** Razones por origen 1,90 / 1,72 / 1,75 (crudo 1,79): se aplica el tope 1,5 y el sesgo no se corrige entero.

**Alternativa.** Factor por fondo encogido (propuesta de M5 v2, SUP-41 reservado, no adoptada) o un tope de 1,8;
sobreestimar el ingreso haría que M6 venda o traslade de más.

**Dónde.** `correccion_total` en `conf/model_u6.yml`; filas `factor_red_*` de `metricas`.

---

## SUP-21 · Tarifa urbana o interurbana de los cajeros (RN-04A)

**No lo entregó el banco.** Un campo urbano/interurbano para los cajeros dispensadores (M1).

**Qué asumimos.** M1: la tabla urbana o interurbana sale de la tipología de facturación (`tipo_facturacion`): ELITE,
VIP, ALTO, MEDIO, BAJO e INDIVIDUAL con la tabla urbana; INTERURBANO COMBO con la interurbana. M2 (multifuncional de
TDV): `MF URBANO` cuando el municipio del equipo coincide con la ciudad del fondo y `MF INTERURBANO` en los demás casos.
Los equipos administrados por sucursal tienen costo 0 declarado.

**Por qué.** RN-04A: M1 "Hoja ATM: ATM L-S o D-F PROGRAMADO + categoría | tipo_facturacion y admon del maestro CP";
M2 "MF URBANO o INTERURBANO PROGRAMADO L-S o D-F | admon del maestro CP. Urbano cuando el municipio del equipo coincide
con la ciudad del fondo; interurbano en los demás casos"; "Equipos administrados por sucursal (M1 y M2) | Sin tarifa
TDV | Costo 0; el proveedor lo declara en la explicación funcional". Para M1 RN-04A no da el criterio de municipio, y
ELITE a BAJO solo existen en la tabla urbana.

**Efecto.** v2: 5 MF de TDV fuera del municipio de la ciudad del fondo (1519 y 7352 en Palmira, 7814 en Tuluá, 9251 en
Pradera y 9650 en Yumbo, todos con fondo Cali); sus 61 acciones (59 recolecciones y 2 provisiones) pasan de 9.888.680
a 13.825.215 COP (+3.936.535) y el costo total de M2 de 71.404.981 a 75.341.516 COP.

**Alternativa.** Los 4 dispensadores INDIVIDUAL con municipio distinto de la ciudad del fondo (8416 Chachagüí/Pasto,
3568 Riofrío, 3781 Ginebra y 4458 San Pedro/Cali) usan la tarifa urbana: 14 provisiones, 2.360.392 COP; con la
interurbana serían 2.935.460 COP (+575.068).

**Dónde.** Interruptor `m2_tarifa_interurbana` (`pipeline/conf/alx.yml`); `cajero` en `conf/costos.yml`;
`costs/anexo_e.py` (`mf_es_interurbano`); `pipeline/run_u1_u2.py` (`_m2_interurban_typology`); frase de la hoja 02.

---

## SUP-22 · Escala de la sucursal para el costo (Escalas de Oficinas)

**No lo entregó el banco.** Una aclaración para las sucursales en que la `Ubicación` y el campo `Escalas` no coinciden
(`INTERURBANO 3` con `Escalas = 1`).

**Qué asumimos.** La tipología (urbana, interurbana o aérea) sale de la `Ubicación` de Oficinas y, en las interurbanas,
la escala sale del campo `Escalas` cuando es un entero ≥ 1 (si no, del número de la `Ubicación`, con aviso). Sin
prefijo, la sucursal es urbana.

**Por qué.** Anexo A, Oficinas: "Escalas | Escala de transporte para sucursales interurbanas (tarifa INTERURBANA PR
ESCALA del Anexo E)" y "Ubicación y Escalas determinan la tarifa de sucursales del Anexo E". RN-04A: M3 "Hoja
Sucursales: PROGRAMADO URBANO, INTERURBANA PR ESCALA o AÉREO | Ubicación, Escalas y TTADORA del listado de oficinas."

**Efecto.** v2: solo cambia la sucursal 70 (`INTERURBANO 3`, `Escalas = 1`): sus recolecciones pasan de la escala 3 a la
1 (≈ −6,76 M COP en el costo de M3).

**Alternativa.** Escala del número de la `Ubicación` (entregable v1, interruptor apagado): +6,76 M COP en la sucursal
70.

**Dónde.** Interruptor `m3_escala_anexo_a` (`pipeline/conf/alx.yml`); `sucursal` en `conf/costos.yml`;
`costs/anexo_e.py` (`branch_concept`); `pipeline/run_u3.py`.

---

## SUP-23 · Tasa de venta de M6

**No lo entregó el banco.** Una tasa contractual de venta de efectivo.

**Qué asumimos.** El beneficio de vender efectivo usa la tasa mediana observada en el consolidado de ventas del fondo
(COP por cada 10.000 vendidos). La venta no tiene costo en el Anexo E.

**Por qué.** RN-76: "El campo TASA del histórico de ventas corresponde a la comisión recibida por el banco por cada
10.000 COP vendidos y podrá utilizarse como referencia".

**Efecto.** El beneficio se reporta aparte del costo del Anexo E; v2: 148 filas de venta.

**Alternativa.** Una tasa contractual distinta cambiaría el beneficio, no el costo.

**Dónde.** `decision.venta` en `conf/model_u6.yml`; `modules/funds_m6/dataset.py` (`sales_rate_by_fund`).

---

## Supuestos agregados (oct-2026)

---

## SUP-24 · Métricas marcadas origen_dato = ESTIMADO

**No lo entregó el banco.** Una taxonomía de procedencia para las métricas y los pares del backtest.

**Qué asumimos.** Cada fila de los contratos de salida lleva `origen_dato` (REAL / PROYECTADO / SIMULADO / ESTIMADO). Las
filas de `metricas` y `backtest` son ESTIMADO: son estadísticos y pares de evaluación.

**Por qué.** Pliego §7.1: las proyecciones "no podrán presentarse como saldos observados, certificaciones oficiales ni
movimientos efectivamente realizados"; ante la duda, ESTIMADO es la etiqueta conservadora.

**Efecto.** Ninguna cifra cambia; en la réplica publicada coinciden las 20 combinaciones contrato × modelo
(`imputacion/resultados/origen_dato_s3.csv`).

**Alternativa.** Otra taxonomía se cambia en el mapa por contrato, sin tocar la lógica.

**Dónde.** `publish/contracts.py` (`ORIGEN_DATO_POR_CONTRATO`, `asignar_origen_dato`); interruptor `origen_dato`;
`tests_alx/test_origen_dato.py`.

---

## SUP-25 · Recomendaciones y alertas marcadas ESTIMADO, no SIMULADO

**No lo entregó el banco.** La procedencia esperada de las recomendaciones.

**Qué asumimos.** `recomendaciones`, `alertas` y `silenciosos` son ESTIMADO (resultado de aplicar reglas sobre el
pronóstico o el saldo simulado); `predicciones` es PROYECTADO en M1–M5 y SIMULADO en M6.

**Por qué.** La acción es un paso más allá del dato simulado; ESTIMADO no afirma más de lo que es.

**Efecto.** Todas las recomendaciones y alertas, ESTIMADO; las 540 filas de M6 en `predicciones`, SIMULADO.

**Alternativa.** Heredar la procedencia del insumo (SIMULADO en M6): una entrada del mapa.

**Dónde.** `publish/contracts.py`.

---

## SUP-26 · REAL no aparece en los contratos de salida

**No lo entregó el banco.** Nada: el horizonte es posterior al corte; se registra para trazabilidad.

**Qué asumimos.** Ninguna fila publicada es REAL. Los 27 días del Anexo C siguen como faltantes, nunca en cero.

**Por qué.** No hay dato observado del 1 al 15 de septiembre: una fila REAL sería un dato inventado.

**Efecto.** 0 filas REAL en los 6 contratos; una fila REAL hace fallar la publicación.

**Alternativa.** Ninguna.

**Dónde.** `publish/contracts.py`; `tests_alx/test_origen_dato.py`.

---

## SUP-27 · Entidad con denominador cero fuera del WAPE agregado

**No lo entregó el banco.** El tratamiento de una entidad con todos sus reales en cero en la ventana (el WAPE queda
indefinido para ella).

**Qué asumimos.** Una entidad cuyo Σ|y| es 0 en la ventana sale solo del WAPE agregado; MAE, sesgo y `n` la incluyen.
La hoja 03 publica el WAPE con esa exclusión y la hoja 04 da también el de la fórmula literal del §8.

**Por qué.** Pliego §8: "WAPE = Σ |Yt − Ŷt| / Σ |Yt|"; la entidad con denominador cero no aporta denominador y su error
domina el agregado sin poder normalizarse.

**Efecto.** En M3, 3 sucursales en entradas y 4 en salidas (39 y 51 entidades-día): WAPE de entradas 0,3884 con la
exclusión frente a 0,4200 con la fórmula literal; de salidas 0,4166 frente a 0,4578. En M1, M2, M4 y M5 no cambia.

**Alternativa.** Publicar la fórmula literal en la hoja 03 (0,4200 y 0,4578 en M3).

**Dónde.** Interruptor `sup02_denominador_cero`; `forecasting/metrics.py` (`wape_aggregate`, `sup02_note`);
`lab/evaluation/harness.py`.

---

## SUP-28 · Variables de contexto con el maestro vigente en cada origen

**No lo entregó el banco.** Un maestro CP fechado por día: los snapshots tienen fechas irregulares y el último es del
8 de septiembre, posterior al corte.

**Qué asumimos.** El grupo `contexto` toma, en cada origen de backtest y en el pronóstico, el último snapshot de
`raw/cp_historico.xlsx` con fecha ≤ origen (cupo, administrador, tipo de equipo, ciudad), nunca uno posterior. Un
cajero sin snapshot hasta ese origen queda sin contexto (faltante). En M3, `cupo_max_suc` es el último valor ≤ origen.

**Por qué.** Pliego §9 (corte del 31 de agosto) y SUP-18: el maestro vigente es posterior a todos los orígenes.

**Efecto.** Cambia alguna variable en 1.662 de 8.131 cajero-orígenes de M1 (20,4 %) y en 681 de 1.038 de M2 pagado; 0
en M3, M4 y M5. Si se alteran los snapshots posteriores al origen, el pronóstico sale idéntico. Efecto en el WAPE de M1
−0,05 ± 0,09 pp en selección y de M2 pagado +0,07 ± 0,06 pp (`imputacion/resultados/ml/efectos_resumen.csv`).

**Alternativa.** Usar el maestro vigente en todos los orígenes: fuga leve de información posterior.

**Dónde.** Interruptor `contexto_asof`; `imputacion/contexto_asof.py`; `forecasting/laboratorio.py`.

---

## SUP-29 · Corrección de los disponibles de M6: sin TOTAL y TDV_001 en pesos

**No lo entregó el banco.** Las unidades de `valor` de la TRANSPORTADORA_001, el significado de la calidad `TOTAL`, el
significado de 23 filas en blanco de la TRANSPORTADORA_004 y cuál de los dos formatos de reporte es el oficial en 30
fondo-días.

**Qué asumimos.** Al cargar los disponibles: (1) se excluyen las filas `calidad = TOTAL` (subtotal de las demás
calidades; solo las traen la TRANSPORTADORA_002 hasta el 12-ago-2026 y la 003 hasta el 29-jul-2026); (2) en la
TRANSPORTADORA_001, los días en que `valor` viene en cantidad de billetes (hasta el 17-jul-2026) se multiplican por la
denominación; el cambio se detecta por datos (un fondo-día está en billetes si menos del 50 % de sus filas con valor
distinto de 0 son múltiplo de la denominación); (3) los días con algún valor en blanco (23 días de
`CALI|TRANSPORTADORA_004|50000`) y los días con dos formatos de reporte (30 fondo-días de la 002 y la 003) salen de la
ventana de mínimos y máximos como faltantes, nunca como cero ni sumando dos reportes.

**Por qué.** Anexo A: "valor | Valor en efectivo del disponible"; "En M6 se consolidan todas las calidades" (pliego
§7.1: "dentro de cada denominación se consolidan todas las calidades y familias"): sumar `TOTAL` con las demás duplica
el saldo (16.192 de las 16.423 celdas `TOTAL` igualan la suma del resto). RN-83: el proveedor deberá perfilar la
información de fondos "identificando cobertura temporal, días faltantes, duplicados, inconsistencias entre fuentes" y
"documentar los ajustes". Anexo A: "Los registros con valor igual a cero corresponden a existencias observadas iguales
a cero": un blanco no es un cero.

**Efecto.** Detección de billetes del 2-ene-2024 al 17-jul-2026 en los dos fondos de la TDV_001 (49.212 filas
convertidas); 16.423 filas `TOTAL` excluidas; saldo inicial igual en las 36 combinaciones; mínimos de la TDV_001 de
miles de pesos a miles de millones; estado de riesgo al 31-ago distinto en 10 de 36 combinaciones frente a no
corregir (`imputacion/resultados/m6/`).

**Alternativa.** Sin corregir: mínimos de la TDV_001 en miles de pesos (M6 nunca vería un déficit ahí) y los de la 002 y
003 al doble. La mezcla por denominación (SUP-09) suma los dos formatos en los 30 fondo-días y cuenta los blancos como 0.

**Dónde.** Interruptor `correccion_m6` y `correccion_disponibles` en `conf/model_u6.yml`;
`modules/funds_m6/correccion_disponibles.py`; `tests_alx/test_disponibles_m6.py`.

---

## SUP-30 · Regla de adopción R1–R5 declarada antes de medir

**No lo entregó el banco.** Nada: la elección del modelo es del proveedor (pliego §7 y §8); se registra para
trazabilidad del criterio.

**Qué asumimos.** Un modelo reemplaza a la referencia solo si cumple las cinco condiciones declaradas el 18-oct-2026
antes de cualquier corrida: R1 mejora pareada de WAPE en 16 orígenes de selección mayor que k errores estándar; R2
ninguna celda bloque × ciudad empeora más de 2 EE; R3 confirmación en 3 orígenes no usados para elegir; R4 sesgo no peor
que el de la referencia más 0,05; R5 cobertura conformal del 90 % ± 5 pp por tramo.

**Por qué.** Es la garantía contra elegir con los mismos datos con los que se mide (pliego §8: validación temporal).

**Efecto.** Cambia el modelo en 6 de 7 series; M4 se queda con la referencia porque ningún candidato cumplió R1–R5.

**Alternativa.** Elegir por el WAPE de selección sin confirmación: riesgo de sobreajuste a los cortes.

**Dónde.** `ml/conf/adopcion_ml.yml`; `ml/adopcion.py`; `ml/resultados/adopcion.csv`.

---

## SUP-31 · k = 2 en R1 por búsqueda múltiple

**No lo entregó el banco.** Nada: criterio estadístico del proveedor.

**Qué asumimos.** A las variantes, afinados y ensambles que contienen a la referencia se les exige una mejora mayor que
2 EE en R1; a los candidatos nuevos, 1 EE. R2 usa siempre k = 2.

**Por qué.** Con 146 candidato-dataset alguno gana por azar; k = 2 corrige la búsqueda múltiple donde la selección reusa
información.

**Efecto.** 45 de 146 candidato-dataset con k = 2. Dos modelos publicados pasan R1 con menos de 2 EE (M1, 1,72 EE; M3
salidas, 1,83 EE) y cumplieron R3 en los 3 orígenes de confirmación.

**Alternativa.** k = 2 para todos: M1 y M3 salidas se quedarían con la referencia.

**Dónde.** `ml/conf/adopcion_ml.yml`.

---

## SUP-32 · Pesos congelados en los ensambles ponderados

**No lo entregó el banco.** Nada: criterio del proveedor.

**Qué asumimos.** En selección, los ponderados se evalúan con pesos recalculados en cada origen con orígenes
anteriores; para confirmar y publicar, los pesos se congelan una vez con los 16 orígenes de selección.

**Por qué.** Lo publicado es exactamente lo confirmado; recalcular con datos de confirmación sería fuga.

**Efecto.** Ponderados publicados en M2 pagado, M2 cash-in y M3 entradas (pesos en la hoja 04).

**Alternativa.** Pesos iguales: otro modelo, no evaluado como publicado.

**Dónde.** `ml/correr_ensambles.py`; `pipeline/conf/pronosticadores.yml`; `ml/resultados/pesos_ensambles.csv`.

---

## SUP-33 · Contexto empaquetado en el modelo registrado

**No lo entregó el banco.** Nada: criterio de reproducibilidad del proveedor.

**Qué asumimos.** Los modelos con el grupo `contexto` se registran con su contexto como artefactos, de modo que el
modelo registrado reproduce lo evaluado.

**Por qué.** Sin el contexto, el modelo registrado correría una variante distinta de la evaluada.

**Efecto.** 28 de 28 comparaciones del modelo registrado contra lo evaluado dentro de 1e-6.

**Alternativa.** Registrar sin contexto: el modelo de M2 pagado no cumpliría R3.

**Dónde.** `ml/registrar_mlflow.py`; `ml/pronosticar.py`; `imputacion/resultados/ml/verificacion_registro.csv`.

---

## SUP-34 · Demanda censurada: se modela lo dispensado

**No lo entregó el banco.** El saldo diario observado de los cajeros (pliego §5: "Bancolombia no entregará saldos de
efectivo por punto").

**Qué asumimos.** El objetivo de M1 y M2 es lo entregado (`pagado`); cuando el cajero se agota, la demanda queda
censurada y no se reconstruye.

**Por qué.** Reconstruir la demanda sin dato de saldo sería inventar; el pliego evalúa contra lo observado.

**Efecto.** No medible sin saldo diario. Proxy en el grupo de intermitencia (fracción de días cerca del máximo).

**Alternativa.** Con el saldo diario del banco se podría corregir.

**Dónde.** `forecasting/global_ml.py` (grupo `intermitencia`).

---

## SUP-35 · Duplicado del 13-may-2026 y valores corruptos: corrección de datos, no imputación

**No lo entregó el banco.** Una versión corregida de las 44 filas duplicadas de sucursales del 13-may-2026 y del monto
corrupto `884s0000` (cajero 6303, 25-jul-2026).

**Qué asumimos.** El duplicado exacto se deduplica; el cajero-día con monto corrupto pasa a faltante, nunca a 0.

**Por qué.** Un duplicado exacto duplica el real con el que se mide; un día incompleto no es una observación válida.

**Efecto.** 44 celdas corregidas en M3 entradas y 44 en salidas; 1 cajero-día en M1. WAPE de selección de M3 entradas
−0,54 ± 0,52 pp y de salidas −0,51 ± 0,37 pp.

**Alternativa.** No deduplicar (comportamiento con el interruptor apagado): el corte del 30-abr se mediría contra el
real duplicado.

**Dónde.** Interruptor `correcciones_datos`; `modules/atm_m1_m2/dataset.py`, `modules/branches_m3/dataset.py`.

---

## SUP-36 · Imputación de faltantes: evaluada y no adoptada

**No lo entregó el banco.** El dato de los 27 días del Anexo C ("La información correspondiente no puede recuperarse").

**Qué asumimos.** Los faltantes no se imputan: el entrenamiento los maneja como faltantes, las métricas los excluyen y
nunca valen cero. La imputación (método elegido por celda) se evaluó con una regla de decisión declarada antes de
medir y no se adoptó en ningún modelo.

**Por qué.** Anexo C: "Para el entrenamiento de los modelos, el proveedor deberá imputar o manejar explícitamente estos
días mediante el método que considere técnicamente apropiado" y "La descripción deberá incluir la técnica utilizada, su
justificación, el tratamiento dado al bloque de 12 días consecutivos de abril y el efecto estimado sobre el
pronóstico". Manejarlos como faltantes es la opción que no reconstruye datos.

**Efecto.** Diferencia de WAPE con imputación menos sin imputación (positivo = peor): media por dataset entre −0,27 pp
y +1,01 pp, dentro de 2 EE en los 7 datasets. En los modelos publicados de M1 y M2, cortes del 30-abr y 31-may-2026
(los que contienen el bloque de abril y ningún otro día del Anexo C): M1 +0,15 y −0,15 pp; M2 pagado −0,64 y −0,02; M2
cash-in −0,12 y +0,12; medias de selección +0,10 ± 0,11 (M1, 16 cortes), −0,06 ± 0,10 y +0,11 ± 0,11 (M2, 10 cortes).
La medición imputa también silencios cortos (en el corte del 30-abr, 4.755 de 9.721 celdas imputadas de M1 son del
Anexo C). En el entregable el efecto es 0 porque no se imputa.

**Alternativa.** Adoptar la imputación en los datasets donde pasa G1–G3: no le gana a la referencia en R3.

**Dónde.** Interruptor `imputacion: false`; `forecasting/laboratorio.py`; `imputacion/resultados/ml/`
(`efecto_imputacion.csv`, `efectos_resumen.csv`, `decision_final.csv`).

---

## SUP-37 · Ceros de M3 en agosto de 2026 leídos como reales

**No lo entregó el banco.** Una confirmación de los ceros de sucursales en días hábiles de agosto de 2026 (p. ej.
10-ago: 34 de 44 sucursales en 0).

**Qué asumimos.** Son ceros reales, que es el dato entregado; la lectura como faltante solo se usa como sensibilidad
para entrenar.

**Por qué.** Anexo A, M3: `entradas` y `salidas` son el "total transacciones" del día: un cero es el dato entregado.
RN-08 y el Anexo C hablan de cajeros, no de sucursales. Anexo A: "Los registros con valor igual a cero corresponden a
existencias observadas iguales a cero".

**Efecto.** Sensibilidad (ceros como faltante solo para entrenar): el WAPE del chequeo del 16-ago cambia entre −1,27 y
+0,59 pp. La cobertura conformal de M3 en el chequeo baja a 0,55–0,72 por tramo.

**Alternativa.** Tratarlos como faltantes también en la evaluación: cambiaría las métricas de M3 sin respaldo del
banco.

**Dónde.** `imputacion/resultados/inventario/ceros_dudosos.csv`; `imputacion/resultados/ml/sensibilidad_S2b.csv`.

---

## SUP-38 · Repetición acotada del laboratorio a los finalistas

**No lo entregó el banco.** Nada: decisión de alcance del proveedor por tiempo de entrega (20-oct-2026).

**Qué asumimos.** La repetición con datos corregidos o imputados cubre a los finalistas de cada dataset y a la
referencia, con la misma regla; no se repite el cribado de motores ni de conjuntos.

**Por qué.** Tiempo de entrega; los finalistas son los que pueden cambiar la decisión.

**Efecto.** 28 modelo-dataset en dos escenarios con 19 orígenes; el modelo elegido es el mismo en los 7 datasets.

**Alternativa.** Repetir todo el cribado: un modelo no finalista podría beneficiarse de la corrección.

**Dónde.** `ml/conf/adopcion_ml.yml` (finalistas); `imputacion/resultados/ml/alcance_d1.csv`.

---

## SUP-39 · Modelos finales del laboratorio en el pipeline del entregable

**No lo entregó el banco.** Nada: la elección es del proveedor; se registra para trazabilidad.

**Qué asumimos.** El entregable se genera con los modelos elegidos por la regla de adopción (SUP-30), con datos
corregidos (SUP-35), contexto con el maestro vigente en cada origen (SUP-28) y sin imputación (SUP-36): M1 LightGBM
global con pérdida Tweedie; M2 pagado, M2 cash-in y M3 entradas promedios ponderados con pesos congelados; M3 salidas
LightGBM global con pérdida L1; M4 el promedio simple de un perfil y un boosting global (ningún candidato cumplió la
regla); M5 promedio de tres LightGBM globales. El pipeline llama a la misma función que envuelve el modelo registrado.

**Por qué.** Pliego §7 y §8: pronósticos funcionales y validación temporal; usar la misma función garantiza que lo
publicado es lo evaluado.

**Efecto.** WAPE del backtest del 17 al 31-ago (hoja 03): M1 0,2490; M2 pagado 0,3642; M2 cash-in 0,3832; M3 entradas
0,3884 y salidas 0,4166 (con SUP-27); M4 0,3196; M5 0,5160. El pronóstico del pipeline es igual al evaluado
(diferencia relativa ≤ 4·10⁻¹⁸).

**Alternativa.** La referencia previa (modelos combinados del pipeline base): M1 0,2551; M2 pagado 0,3652; M2 cash-in
0,3868; M3 entradas 0,4219 y salidas 0,4577; M5 0,5668.

**Dónde.** Interruptor `campeones_ml`; `forecaster.modelo_alx` de `conf/model_*.yml`; `forecasting/laboratorio.py`.

---

## SUP-40 · Plantilla del Anexo D y tarifas del Anexo E de la corrida

**No lo entregó el banco.** Las hojas informativas 00_Instrucciones, GUIA_Descripcion_Solucion y 07_Catalogo_Ejemplos que
menciona el pliego: la plantilla recibida no las trae.

**Qué asumimos.** La corrida usa los originales del banco sin modificar: `Anexo_D_Plantilla_entrega_proveedor_POC.xlsx`
(sha256 `a247fae77dcf5779e6e36e732af447945faa32a670555a03c0962237992c20ec`, 6 hojas: 01 a 05 y 06_Diccionario_Campos) y
`Anexo_E_Parametros costos.xlsx` (sha256 `caaa399cbd21459303d6b738f949b8f52b89801104ac5bb3a392a4fb77097c97`). No se crean
las hojas informativas ausentes.

**Por qué.** Pliego §9: las hojas informativas "deberán conservarse sin diligenciar ni modificar. No se aceptarán
archivos CSV independientes, otras hojas adicionales ni columnas renombradas, agregadas o eliminadas en las hojas
obligatorias." Crear hojas que la plantilla no trae sería agregar hojas.

**Efecto.** El Excel conserva las 6 hojas de la plantilla, con la 06 idéntica.

**Alternativa.** Crear las tres hojas: riesgo de incumplir "otras hojas adicionales".

**Dónde.** `plantilla` en `conf/export_anexo_d.yml`; `publish/anexo_d/workbook.py`; `publish/validate_xlsx.py`.

---

## SUP-42 · Nivel de riesgo antes de la acción (hoja 02)

**No lo entregó el banco.** Bandas o reglas para el `nivel_riesgo` de la hoja 02 (la plantilla solo trae la lista alto,
medio, bajo).

**Qué asumimos.** El nivel se mide con el saldo del día sin la acción. Provisión de M1 y M2: alto si el saldo sin la
provisión se agota (≤ 0); medio si queda por debajo del 8 % del cupo (el borde exacto del 8 % queda fuera, igual que las
alertas); bajo si la provisión es preventiva. Provisión de M3: alto si el saldo se agota; medio en el resto, porque toda
provisión de M3 nace de un saldo previsto bajo la reserva preventiva de la sucursal (nunca bajo). Recolección de M2:
medio (saldo al cierre sobre el cupo). Recolección de M3: alto si el saldo superaría el cupo; bajo si es efectivo
ocioso. Cada fila agrega una frase con el nivel y su motivo. Cupo insuficiente prevalece (SUP-44).

**Por qué.** RN-03: toda recomendación deberá contener "el nivel de riesgo"; pliego §10: "priorización de riesgos".
RN-12 (agotamiento "cercano a 0 %"), RN-21 y RN-34 (8 % del cupo), RN-35 (saldo sobre el cupo), RN-38 (la bóveda no
puede superar el cupo), RN-40 ("efectivo ocioso de forma injustificada") y RN-44 (umbrales preventivos).

**Efecto.** v2 frente a v1 (2.592 filas en bajo): M1, 855 provisiones en alto y 494 en medio, iguales a las alertas
crítico y alerta del mismo día; M2, 27 provisiones en alto (26 de 8667 y 9311 por SUP-44) y 1 en medio, 719
recolecciones en medio; M3, 2 provisiones en medio, 216 recolecciones en alto (exceso sobre el cupo) y 209 en bajo; las
filas sin acción conservan la peor severidad de las alertas.

**Alternativa.** Riesgo residual después de la acción (entregable v1): 2.592 de 2.592 filas en bajo, porque la acción
lleva el saldo al rango operativo.

**Dónde.** Interruptor `nivel_riesgo_previo`; `nivel_riesgo_previo` y `textos_v2.motivo_riesgo` en
`conf/export_anexo_d.yml`; `publish/anexo_d/sheet_02_operational_plan.py` (`nivel_riesgo_previo`).

---

## SUP-43 · Monto mínimo de recolección

**No lo entregó el banco.** Un monto mínimo de recolección ni un criterio de cuándo una visita no se justifica.

**Qué asumimos.** En M3 no se recomienda una recolección de efectivo ocioso (saldo al cierre ≤ cupo) cuyo monto no supera
su costo de la visita del Anexo E (`fijo + monto/10.000 × tarifa`, factor 1,0). Es una restricción dura que nunca
omite una recolección necesaria: la de exceso sobre el cupo siempre se mantiene, aunque sea antieconómica, y su
explicación lo dice. El efectivo omitido queda en la bóveda, el saldo se encadena (RN-39) y la siguiente recolección lo
incluye. Las sucursales con regla vigente (historia corta) solo recogen por exceso y nunca omiten. En M2 toda
recolección es necesaria (solo existe sobre el cupo): ninguna se omite, y las antieconómicas lo dicen en la
explicación.

**Por qué.** RN-40: recolección "cuando indique riesgo de exceder el cupo o de mantener efectivo ocioso de forma
injustificada"; RN-44: evaluación por "costo estimado [...] y capacidad de reducir efectivo ocioso sin generar riesgo de
faltante"; pliego §8: "consistencia del monto recomendado con el saldo, el cupo y la regla aplicada, costo estimado".
RN-38 (el saldo no puede superar el cupo), RN-22 y RN-35 (M2 recoge lo que pasa del cupo).

**Efecto.** v2: 7 recolecciones de M3 omitidas por 548.282 COP en 4 sucursales (824, 869, 871, 997); 0 recolecciones de
efectivo ocioso con monto ≤ costo (8 en v1; la menor, 2.787 COP con costo 16.221); 0 omitidas con saldo sobre el cupo;
M2 mantiene 1 recolección antieconómica (9251) por RN-35. Siguen recolecciones de M3 menores de 1 M COP cuyo monto sí
supera su costo (riesgo residual en `entrega/CAMBIOS_v2.md`).

**Alternativa.** Sin monto mínimo (entregable v1): 8 recolecciones que cuestan más de lo que recogen. Factor mayor
que 1 (p. ej. 2): más omisiones.

**Dónde.** Interruptor `monto_minimo_recoleccion`; `politica.monto_minimo_recoleccion` en `conf/model_m3.yml`;
`modules/branches_m3/balance.py` (`simulate_balance_m3`), `pipeline/run_u3.py`; fila `recoleccion_omitida_monto` de
`metricas`; frase `textos_v2.m2_antieconomica` de la hoja 02.

---

## SUP-44 · Cupo insuficiente (M1–M3)

**No lo entregó el banco.** Un cupo alternativo ni una regla para el equipo cuyo flujo neto de salida de un día supera
su cupo.

**Qué asumimos.** Una entidad tiene cupo insuficiente si en algún día el flujo neto de salida pronosticado supera su
cupo aplicable (M1: pagado frente al cupo operativo; M2: pagado − cash-in frente al cupo; M3: salidas − entradas frente
a `cupo_max_suc`). Todas sus filas de la hoja 02 quedan en alto y la explicación lo declara con los días, el neto
máximo, el cupo y la demanda no atendida mínima. Se programa una atención diaria que completa hasta el cupo; no se
programan atenciones adicionales.

**Por qué.** RN-18: el cupo "El proveedor deberá tomarlo como dato dado y no deberá recalcularlo, estimarlo ni
sustituirlo". RN-19A: "el monto de provisión deberá ser el necesario para completar el saldo hasta el cupo del equipo";
RN-24: "Las provisiones deberán completar el saldo hasta el cupo". RN-21: evitar "saldos negativos o superiores al cupo
al cierre del día". RN-28 (multifuncionales de sucursal): "Cuando el proveedor determine que se requieren varias
atenciones del mismo tipo en una fecha, deberá consolidarlas en una única acción diaria": permite consolidar, y con
una sola provisión hasta el cupo no hay atenciones adicionales que consolidar.

**Efecto.** v2: solo los MF de sucursal 8667 (4 días con neto > cupo; demanda no atendida mínima 73.047.796 COP) y 9311 (1
día; 18.008.804 COP), con cupo de 85.502.000 COP; sus 26 filas en alto. Ninguna entidad de M1 ni de M3.

**Alternativa.** Una segunda atención consolidada cuando el neto supera el cupo (lectura amplia de RN-28): cubriría la
demanda de esos días con provisiones adicionales; requiere aprobación (pendiente en `entrega/CAMBIOS_v2.md`).

**Dónde.** Interruptor `nivel_riesgo_previo`; `publish/anexo_d/sheet_02_operational_plan.py`
(`entidades_cupo_insuficiente`); `textos_v2.cupo_insuficiente` en `conf/export_anexo_d.yml`.

---

## SUP-45 · Maestro CP vigente (snapshot del 8-sep-2026)

**No lo entregó el banco.** Un maestro CP cerrado al 31 de agosto: el archivo trae snapshots y el último de 487 de los
491 cajeros es del 8 de septiembre de 2026.

**Qué asumimos.** Los datos de referencia de los cajeros (cupo, administración, tipología de facturación, municipio,
sucursal y ciudad del fondo) son los del último snapshot de cada cajero; las variables de pronóstico usan el snapshot ≤
origen (SUP-28).

**Por qué.** Pliego §3: "El universo de ATM y sucursales corresponde a los maestros entregados"; RN-05: "El proveedor
deberá utilizar exclusivamente los equipos contenidos en los maestros suministrados"; pliego §5: "M1: menor valor entre
el cupo registrado en el maestro CP y 500.000.000 COP" y "M2: cupo registrado en el maestro CP" (para M3 el pliego
sí fija "el último registro disponible hasta el 31 de agosto de 2026"). El maestro es dato de referencia entregado por
el banco, no información del objetivo; el corte aplica al entrenamiento y a las decisiones (SUP-18).

**Efecto.** Frente al último snapshot ≤ 31-ago (23-jul-2026): 2 cupos distintos (1505 y 7441: 67.850.000 frente a
68.850.000) y 4 cajeros que solo están en el snapshot del 8-sep (1049, 1050, 1085 y 1086; 6 acciones por
2.447.303.123 COP en v1). Administración, estado, municipio, sucursal, tipología y ciudad del fondo: 0 diferencias.
Pronóstico: sin datos posteriores al corte (`.agents/tasks/correcciones-v2/evidencia/sup45_uso_cp.md`).

**Alternativa.** Usar el snapshot del 23-jul-2026: cambiarían 2 cupos y 4 cajeros quedarían sin maestro (contrario a
RN-05).

**Dónde.** `interim/cp_historico` (último snapshot por cajero); `modules/atm_m1_m2/dataset.py`,
`publish/anexo_d/masters.py`, `modules/funds_m6/dataset.py`.

---

## SUP-46 · Insumos del Anexo A no recibidos

**No lo entregó el banco.** `Historico BANREP.xlsx` (hojas Consignaciones República, Cambios República y Consignaciones
apto de baja) e `Historico Traslados.xlsx`, que el Anexo A lista como insumos de M6: no están entre los 19 archivos de
datos recibidos (lista del 21-oct-2026).

**Qué asumimos.** La habilitación de BanRep se suple con la tarifa del Anexo E y el ejemplo de RN-75 (SUP-13); la de
traslados y venta, con `dim_fondo` y el histórico de ventas (SUP-08).

**Por qué.** RN-75: "de acuerdo con el histórico compartido. Por ejemplo, para consignación y retiro de alta, solo
están habilitados los fondos de Cali." El banco indicó que la información no suministrada se suple con supuestos
documentados.

**Efecto.** Los de SUP-08 y SUP-13. El estado actual del repositorio de datos no se verificó en este trabajo.

**Alternativa.** Con los archivos, la habilitación se tomaría del histórico real.

**Dónde.** `operaciones` en `conf/model_u6.yml`.

---

## SUP-47 · Nivel de riesgo residual de la hoja 05

**No lo entregó el banco.** Bandas para el `nivel_riesgo` de la hoja 05.

**Qué asumimos.** El nivel de la hoja 05 es el residual después de actuar: alto si el saldo queda bajo el 50 % del
mínimo, medio si se conserva un excedente sobre el máximo porque moverlo cuesta más (RN-79), bajo en el resto. Las
alertas de M6 miden el riesgo antes de actuar.

**Por qué.** RN-77 (suficiencia: "garantizar efectivo suficiente para operar") y RN-78 (exceso); la acción de M6 lleva
el saldo al rango y el residual muestra lo que queda sin resolver.

**Efecto.** Se declara en la hoja 04 (fila M6); no cambia en v2.

**Alternativa.** Riesgo antes de la acción, como la hoja 02 (SUP-42); no se adoptó en M6.

**Dónde.** `decision.riesgo_residual` en `conf/model_u6.yml`.

---

## SUP-48 · Columna de cumplimiento ausente en la plantilla

**No lo entregó el banco.** La columna de cumplimiento de la regla en la plantilla de la hoja 02 (RN-02 y el pliego §9
la mencionan y el diccionario 06 define `cumple_regla_saldo_objetivo`, pero la hoja 02 de la plantilla no la trae).

**Qué asumimos.** No se agrega la columna; el cumplimiento se declara en `regla_aplicada` y en la explicación funcional
de cada fila.

**Por qué.** Pliego §9: "No se aceptarán [...] columnas renombradas, agregadas o eliminadas en las hojas obligatorias."

**Efecto.** Hoja 02 con las 16 columnas de la plantilla.

**Alternativa.** Agregar la columna: riesgo de incumplir la estructura.

**Dónde.** `publish/anexo_d/constants.py` (`HEADERS`); `publish/validate_xlsx.py`.

---

## SUP-49 · Definiciones de calendario de RN-04

**No lo entregó el banco.** Las variables de calendario (RN-04: "Bancolombia no suministrará variables de calendario
derivadas").

**Qué asumimos.** Festivo = festivo nacional de Colombia según la librería `holidays` 0.106 (país CO) más los ajustes de
`conf/calendario_co.yml` (hoy ninguno); quincena = día 15 de cada mes; fin de mes = último día calendario del mes. Si la
quincena o el fin de mes caen en sábado, domingo o festivo, la fecha de pago se corre al día hábil anterior. Se
incorporan como variables del modelo (día de pago, días hábiles desde y hasta el pago, día del mes, días al fin de mes,
festivo, víspera y día siguiente hábil, puentes y largo del bloque no hábil).

**Por qué.** RN-04: "El proveedor deberá construir los indicadores de festivos en Colombia, quincenas y fines de mes, y
documentar su definición, fuente y forma de incorporación en la hoja 04_Descripcion_Solucion."

**Efecto.** El grupo "día del mes y pago" es el más importante de M1 (6,2 puntos de WAPE al barajarlo).

**Alternativa.** Pago en la fecha calendario sin corrimiento: no se midió que mejorara.

**Dónde.** `features/calendar.py`, `forecasting/global_gbm.py` (`calendar`), `forecasting/calendario_co.py`;
`conf/calendario_co.yml`.

---

## SUP-50 · RN-08 como pronóstico cero de equipos silenciosos

**No lo entregó el banco.** El estado de los equipos que dejan de reportar con la red operando.

**Qué asumimos.** Un equipo sin dato en los últimos 15 días con la red operando se pronostica en 0 (RN-08), y uno
desinstalado en 0 desde su baja (RN-07); se listan en el contrato informativo `silenciosos` y la hoja 04 muestra su
tratamiento.

**Por qué.** RN-08: la ausencia de registros con la red operando "corresponde a inactividad real y equivale a 0 COP";
tras 15 días de red sin dato, un equipo reporta en los 15 siguientes solo el 13 % de los días en M1 (53 de 75 episodios
sin ningún dato) y el 39 % en M2. RN-07 pide una predicción y 0 lo es.

**Efecto.** 12 equipos de M1 con pronóstico 0 (v2 igual a v1).

**Alternativa.** Pronosticar con el modelo: el banco puntúa su ausencia como 0.

**Dónde.** `inactividad.rn08` en `conf/model_u1_u2.yml`; `modules/atm_m1_m2/inactivity.py`.

---

## SUP-51 · Variables de eventos y externas (RN-04, §5)

**No lo entregó el banco.** Variables de eventos comerciales o externas.

**Qué asumimos.** Se usan variables propias definidas por fecha: primas (15 al 30 de junio y 15 al 24 de diciembre),
temporada decembrina, fin e inicio de año, Semana Santa, feria de Cali (25 al 30 de diciembre) y carnaval de Pasto (2
al 7 de enero); y festivos de Ecuador (librería `holidays`, país EC) por la frontera de Ipiales. Origen: definición
propia y la librería; uso: indicadores del día pronosticado; tratamiento: ninguno adicional.

**Por qué.** RN-04: "El uso de eventos comerciales u otras variables externas será opcional y deberá cumplir las
condiciones definidas en el Anexo POC para variables adicionales." Pliego §5: "El proveedor podrá incorporar variables
adicionales, propias o externas, siempre que documente su origen, uso, tratamiento y aporte esperado al desempeño de
la solución."

**Efecto.** Aporte medido en el backtest: el grupo de festivos pesa 1,2 puntos de WAPE en M1, 14,3 en M3 entradas y 14,0
en M5; las variables de temporada no se midieron por separado.

**Alternativa.** Quitar las variables de temporada: no se midió.

**Dónde.** `forecasting/calendario_co.py` (grupos `festivo_detalle` y `temporada`); `forecasting/global_ml.py`.

---

## SUP-52 · Traslado disponible en el fondo destino al día siguiente (M6, Anexo E y RN-74)

**No lo entregó el banco.** Cómo se concilian dos textos: RN-74 pide que el traslado tenga dos filas "con el mismo
monto, fecha y denominación", y la nota del Anexo E dice que el efectivo llega al destino al día siguiente. El banco no
dice qué fecha llevan las filas ni cómo entra el traslado al balance del destino.

**Qué asumimos.** Se cumplen los dos textos así. El traslado se ejecuta el día T. Sus dos filas llevan la fecha T
(RN-74). El destino lo recibe al cierre de T, y ese cierre es su saldo inicial de T+1 (RN-71). Entonces un traslado
solo cubre el faltante proyectado para el día siguiente. Al cierre de cada día se proyecta el saldo de T+1 con los
flujos de M1–M5. Si queda bajo el mínimo, se compara el traslado de hoy con las operaciones de T+1 (retiro BanRep si
el día es hábil y el fondo lo tiene habilitado) y se elige la de menor costo (RN-80). Un faltante del mismo día no se
cubre con traslado, sino con las demás operaciones de ese día. La capacidad del fondo origen es su saldo sobre el
mínimo, también después de sus flujos de T+1, para que el traslado no le cree un faltante.

**Por qué.** Anexo E, hoja Fondos, nota *: "El efectivo sale del fondo origen en la fecha de ejecución y se encuentra
disponible en el fondo destino al día siguiente." RN-74: "Cada traslado deberá reportarse mediante una fila de salida
en el fondo origen y una fila de entrada en el fondo destino, con el mismo monto, fecha y denominación." RN-71: "El
saldo final de una fecha será el saldo inicial de la fecha siguiente." Los traslados no tienen restricción de día
hábil (RN-71A solo excluye BanRep, ventas e intercambios).

**Efecto.** En v2, frente a la v2 con traslado el mismo día: 99 traslados en vez de 105 (198 filas en vez de 210). 25 se
ordenan el día anterior al faltante. Los 4 faltantes del 1 de septiembre en CALI|TRANSPORTADORA_003 (denominaciones
2.000, 5.000, 10.000 y 20.000) no admiten traslado, porque habría que ordenarlo antes del corte. Se cubren con 4
retiros BanRep por 947.993.000 COP, con costo de 896.117 COP. Las ventas pasan de 146 a 148 filas y la hoja 05 de 569 a
566 filas. El costo de M6 sube de 545.413 a 1.441.530 COP, y el de almacenamiento de 41.381.630 a 41.460.623 COP. Las
275 necesidades del horizonte siguen resueltas (251 con una acción y 24 conservadas por costo), sin necesidades
parciales ni sin solución. Pasto: los dos traslados desde IPIALES|TRANSPORTADORA_002 en 50.000 (709.150.000 y
799.600.000 COP) pasan del 5 y 6 al 4 y 5 de septiembre, con el mismo costo, y PASTO|TRANSPORTADORA_001 no queda bajo
su mínimo ningún día.

**Alternativa.** (a) Traslado el mismo día, como en el entregable v1: cubre faltantes del día con efectivo que, según
el Anexo E, aún no ha llegado. (b) Filas con fechas T y T+1: contradice la "misma fecha" de RN-74. Las dos se
descartan.

**Dónde.** Interruptor `m6_traslado_t1` de `conf/alx.yml`, que pasa a `decision.traslado_disponible_t1`;
`modules/funds_m6/simulator.py` (`_anticipate` y `_shortfall_candidates`); `pipeline/run_u6.py`.

---

## SUP-53 · Tarifa del traslado entre ciudades: la de la transportadora del fondo origen (M6)

**No lo entregó el banco.** Qué transportadora opera y cobra un traslado entre ciudades cuando los fondos son de
transportadoras distintas. El Anexo E trae la tarifa de cada ruta por transportadora. Por ejemplo, "Traslado
Ipiales-Pasto": TRANSPORTADORA_001 43.058 + 5,65 por cada 10.000 COP, y TRANSPORTADORA_002 16.219 + 3,40. No dice cuál
se aplica.

**Qué asumimos.** Se usa la tarifa de la transportadora del fondo origen. Esa transportadora entrega el efectivo desde
su bóveda, y en su fila se registra el costo. La ruta debe tener tarifa para esa transportadora: si figura como "No
Disponible", el traslado no se recomienda. Entre fondos de la misma ciudad, el costo es 0.

**Por qué.** RN-74: "El costo se registrará una sola vez, en la fila del fondo origen" y "las rutas marcadas como 'No
disponible' en el Anexo E no podrán recomendarse con esa transportadora". Anexo E, nota *: "El efectivo sale del fondo
origen en la fecha de ejecución" y "Los traslados entre fondos de distintas transportadoras de una misma ciudad no
tienen coste." Anexo E, nota ***: "Cualquier otro movimiento o costo que el proveedor visualice podrá suponerlo."

**Efecto.** En v2 hay 2 traslados con costo, los dos de IPIALES|TRANSPORTADORA_002 a PASTO|TRANSPORTADORA_001: 257.330 y
288.083 COP, 545.413 COP en total. Los demás traslados son entre fondos de Cali y tienen costo 0. La explicación de esas
2 filas de la hoja 05 declara la tarifa usada y la alternativa. La métrica informativa `costo_traslado_tarifa_destino`
la repite.

**Alternativa.** Tarifa de la transportadora del fondo destino (TRANSPORTADORA_001): 443.728 + 494.832 = 938.560 COP,
es decir 393.147 COP más. Esa regla también cambiaría qué rutas están disponibles: por ejemplo, la ruta Cali-Pasto
solo tiene tarifa para la TRANSPORTADORA_001.

**Dónde.** `operaciones.traslado.tarifa_por: origen` en `conf/model_u6.yml`; `modules/funds_m6/simulator.py`
(`transportadora` = la del fondo origen y `_tariff_sentence`); `pipeline/run_u6.py`
(`_transfer_tariff_row`); interruptor `m6_tarifa_traslado_declarada` de `conf/alx.yml`, que solo agrega los textos y
la métrica.

---

## Preguntas convertidas en supuestos

No habrá respuestas a preguntas abiertas: cada duda queda resuelta por un supuesto declarado.

| Pregunta | Supuesto | Texto literal que lo respalda |
|---|---|---|
| ¿`valor` de la TRANSPORTADORA_001 está en billetes hasta el 17-jul-2026? | SUP-29 (2) | Anexo A: "valor \| Valor en efectivo del disponible" |
| ¿`TOTAL` es el subtotal de las demás calidades? | SUP-29 (1) | Pliego §7.1: "dentro de cada denominación se consolidan todas las calidades y familias" |
| ¿Qué significan las 23 filas en blanco de la TRANSPORTADORA_004? | SUP-29 (3) | Anexo A: "Los registros con valor igual a cero corresponden a existencias observadas iguales a cero" |
| ¿Cuál formato es el oficial en los 30 fondo-días con dos reportes? | SUP-29 (3) | RN-83: "documentar los ajustes" |
| ¿Los ceros de sucursales de agosto de 2026 son reales? | SUP-37 | Anexo A: `entradas`/`salidas` "total transacciones" |
| ¿La plantilla debe traer las hojas informativas que no llegaron? | SUP-40 | Pliego §9: "No se aceptarán [...] otras hojas adicionales" |
| ¿RN-07 se aplica por entidad o por entidad-día? | SUP-01 | Pliego §8: "Se excluirán del cálculo las entidades-día [...] según el maestro" |
| ¿Entidad con real cero en toda la ventana de M3? | SUP-27 | Pliego §8: "WAPE = Σ \|Yt − Ŷt\| / Σ \|Yt\|" |
| ¿Días calendario o hábiles en M1–M3? | SUP-03 | RN-02: "una fila por cada combinación de entidad, variable objetivo y fecha del periodo de evaluación" |
| ¿Unidades de los disponibles y filas TOTAL de M6? | SUP-29 | Anexo A: "valor \| Valor en efectivo del disponible" |
| ¿Un cero de M3 es observado? | SUP-37 | Anexo A: "total transacciones" |
| ¿Fondo de los cajeros administrados por sucursal? | SUP-12 | RN-08A: "administrado por la sucursal indicada en codigo_sucursal" |
| ¿MF urbano o interurbano? | SUP-21 | RN-04A: "Urbano cuando el municipio del equipo coincide con la ciudad del fondo" |
| ¿Escala de la sucursal: `Ubicación` o `Escalas`? | SUP-22 | Anexo A: "Ubicación y Escalas determinan la tarifa de sucursales" |
| ¿Qué hacer con 8667 y 9311 (cupo menor que el flujo)? | SUP-44 | RN-18: "tomarlo como dato dado" |
| ¿Qué operaciones de RN-84 se usan? | SUP-14 | RN-84: "El proveedor deberá indicar cuáles utilizó" |
| ¿Archivos BanRep y Traslados del Anexo A? | SUP-46 | RN-75: "de acuerdo con el histórico compartido" |
| ¿Maestro CP posterior al corte? | SUP-45 | Pliego §3: "El universo de ATM y sucursales corresponde a los maestros entregados" |
| ¿Columna de cumplimiento de la hoja 02? | SUP-48 | Pliego §9: "columnas renombradas, agregadas o eliminadas" |
| ¿Fecha de las filas del traslado y cuándo llega al destino? | SUP-52 | Anexo E: "se encuentra disponible en el fondo destino al día siguiente"; RN-74: "con el mismo monto, fecha y denominación" |
| ¿Qué transportadora cobra el traslado entre ciudades? | SUP-53 | RN-74: "El costo se registrará una sola vez, en la fila del fondo origen" |

Fuera del alcance de este registro analítico: la separación de capas (backend y frontend) la documenta el componente
técnico de la solución.
