# Contexto completo del proyecto para agentes LLM y personas que llegan sin contexto

**Qué es este archivo.** El contexto completo de lo hecho en el componente analítico de la PoC DaaS de Bancolombia (Pragma): qué se pidió, de dónde viene el código, qué datos hay y qué problemas tienen, qué modelos se probaron, cuáles se adoptaron y por qué, qué se descartó, cómo se publicó en S3, cómo se reproduce y qué queda pendiente. Está escrito para que un agente LLM (y la persona que lo usa) entienda el repositorio sin haber visto la conversación de trabajo ni la carpeta de trabajo original.

**Cómo se relaciona con el `README.md`.** El README es la guía práctica: instalar, correr, comparar. Este archivo explica el qué, el porqué, la historia, los hallazgos y el estado. Los comandos se citan del README tal cual; si alguna vez difieren, manda el README junto con el código.

**Fecha de corte de este documento:** 23-oct-2026. La entrega de la PoC es el 26-oct-2026.

**Actualizado el 25-oct-2026:** se incorporan el EDA Box-Jenkins v2 (`ALX/eda/03_eda_box_jenkins_v2.ipynb`, 24-oct), que pasa a ser el EDA vigente y deja superado al notebook 02 (§6.2), y el EDA dedicado de M5 (`ALX/eda/04_eda_m5.ipynb`, 25-oct; §6.5).

**Actualizado el 26-oct-2026 (entregable v2):** el Excel y los contratos de `entrega/` son la **v2** (sha256 `167a52e4…`; cambios en `entrega/CAMBIOS_v2.md`), el registro de supuestos `pipeline/docs/supuestos.md` (SUP-01..SUP-53) entra al repo como **versión final**, y se corrige la afirmación anterior de que los Anexos B y C no se recibieron (§1). La v2 se publicó en S3 el mismo día en `output/pronosticos/v2/`, con el puntero `output/pronosticos/version_vigente.json`; `v0_provisional/` queda como la v1 (§7). Se actualizaron §1, §2.3, §3.5, §4.6, §4.7, §5, §6.7, §7, §8, §9, §10, §11, §12 y §13. Las demás cifras (pronósticos, métricas predictivas, champions, bandas) no cambian en la v2.

**Convenciones.**
- Rutas de archivo sin prefijo (p. ej. `pipeline/conf/alx.yml`) = rutas **dentro de este repo** (existen; mapa completo en §10). Los prefijos de bucket (`raw/`, `interim/`, `output/api/`, …) se refieren a S3 o a la carpeta de trabajo de una corrida, no al repo.
- `ALX/...` = carpeta de trabajo original en el Google Drive del proyecto (`Mi unidad/PoC-Bancolombia/ALX/`). **No está en el repo.** Ahí está todo el material de soporte (experimentos, notebooks, informes). Si necesitas algo de ahí, pide acceso al Drive del proyecto.
- `CONTEXTO_CONVERSACION.md` = bitácora maestra del proyecto, en la raíz del mismo Drive (`Mi unidad/PoC-Bancolombia/CONTEXTO_CONVERSACION.md`), fuera del repo.
- `~/.cache/poc-daas/...` y `~/.mlflow/poc-daas/...` = carpetas en el equipo de quien hizo el trabajo; no son accesibles para ti.
- Cifras con coma decimal (0,2490). "pp" = puntos porcentuales de WAPE (0,01 de WAPE = 1 pp).
- Donde dos fuentes se contradicen se usa la más reciente y se anota con **[Contradicción resuelta]**.

## Índice

1. La PoC, el pliego y los entregables
2. Historia: repo de Andrés, repo de Santiago y el trabajo de ALX
3. Datos: buckets, capas, fuentes y hallazgos de calidad
4. Modelos M1–M6, métricas, champions, regla de adopción, bandas y M6
5. Supuestos SUP-xx vigentes
6. Experimentos y resultados, incluidos los no adoptados
7. Publicación en S3 (`v2` vigente, `v0_provisional` = v1)
8. Reproducibilidad: cómo correr de punta a punta y qué diferencias esperar
9. Acceso a AWS
10. Mapa del repo archivo por archivo
11. Pendientes, preguntas abiertas, riesgos y limitaciones
12. Glosario
13. Guía para el agente que lea esto

---

## 1. La PoC, el pliego y los entregables

**Qué es.** Bancolombia está eligiendo proveedor para una solución *Data as a Service* de **administración integral del efectivo**. Es la **segunda ronda** del proceso y Pragma es uno de los proveedores. Cada proveedor construye una prueba de concepto (PoC) funcional: modelos analíticos en Python, backend en Java, frontend en Angular con Power BI embebido, reglas de negocio y trazabilidad. Este repo cubre **solo el componente analítico** (pronósticos, recomendaciones y el Excel de entrega). Backend y frontend no están aquí: la bitácora los registra como no iniciados al 13-oct (`CONTEXTO_CONVERSACION.md` §2), como riesgo crítico vigente (`ALX/analisis_repo_santiago.md` §8, riesgo 1) y, al 22-oct, como responsabilidad de otro equipo (`ALX/resumen_avances_v2.md` §14).

**El problema de negocio.** El banco mueve billetes entre cajeros, sucursales, fondos de las transportadoras de valores (TDV) y el Banco de la República (BanRep). Si un cajero se queda sin efectivo, el cliente no puede retirar; si sobra efectivo quieto, se paga almacenamiento, transporte y costo de oportunidad. La PoC debe pronosticar la demanda y el ingreso de efectivo y **recomendar qué hacer, cuándo, cuánto y a qué costo**. Alcance geográfico: **Cali, Pasto e Ipiales**.

**El pliego** es `POC_DaaS.docx` (unas 3.500 palabras; está en la raíz del Drive del proyecto, no en el repo). Lo que más condiciona:

| Tema | Qué dice |
|---|---|
| Fechas | Corte de datos **31-ago-2026**. Pronóstico diario del **1 al 15-sep-2026** (prueba ciega: el banco guarda los reales y calcula las métricas oficiales). Bloque 1 = 1–7 sep, bloque 2 = 8–15 sep |
| Métricas (§8) | **WAPE** (principal), **MAE** y **Bias** para M1–M5; WAPE global, por ciudad y por bloque; MAE y Bias globales. Solo sobre observaciones con operación válida (se excluyen equipos desmontados o no operativos) |
| Saldo inicial simulado | El banco no entrega saldos de ATM ni sucursales: M1 arranca en min(cupo, 500 M); M2 en el cupo; M3 en `cupo_max_suc` vigente al 31-ago. M6 usa el último disponible ≤ 31-ago por fondo y denominación |
| M4 y M5 | Grano mínimo fondo-día; sin recomendación logística propia; son insumo de M6 |
| M6 (§7.1) | Balance por fondo, fecha y denominación (billetes de 100.000 a 2.000) para todos los días calendario; en días no hábiles no se recomiendan BanRep, ventas ni intercambios; cada recomendación con acción, fondo, fecha, monto, denominación, origen/destino, saldo antes y después, costo (Anexo E), criterio y explicación. M6 **no** se evalúa como pronóstico |
| Lo analítico (§10) | Estacionalidades (fines de mes, quincenas, festivos, eventos atípicos), tratamiento de faltantes, explicación de variables, validación temporal y métricas |
| Criterios de descarte (§13) | No presentar modelos funcionales; no separar analítico/backend/frontend; no explicar resultados o supuestos; no sustentar; **presentar como observado algo estimado sin declararlo**; **imputar como cero los días del Anexo C** o no documentar su tratamiento; no entregar el Excel de §9 |
| Pesos (§12) | Analítico 40 %, backend 20 %, frontend 15 %, calidad técnica 10 %, experiencia de usuario 10 %, sustentación 5 % |
| Sustentación (§14) | Presencial en Medellín, con líderes técnico, analítico y funcional |

**Anexos del pliego** (§9.1): A metadatos de insumos (`Anexo_A_Metadatos_Insumos.xlsx`), B reglas de negocio RN-xx (`Anexo_B_Reglas_de_Negocio.docx`), C observaciones de calidad, con los días sin registro y su tratamiento (`Anexo_C_Observaciones de calidad.docx`), **D plantilla del Excel de entrega**, **E parámetros de costos**. **[Contradicción resuelta]** Versiones anteriores de este documento decían que A, B y C nunca se recibieron. **Es falso: los cinco anexos sí se recibieron** y están en `~/Desktop/datos-anexo-poc-bancolombia/` del equipo de Alexander Peláez (lo encontró la auditoría del pliego del 26-oct, `Mi unidad/PoC-Bancolombia/.agents/tasks/auditoria-pliego/auditoria.md` §0). Hasta la v1 las RN-xx se reconstruyeron desde el código y la documentación de Santiago; la v2 se contrastó contra el texto literal de B y C, y el registro de supuestos cita ese texto. Lo que **no** se recibió son dos insumos que el Anexo A lista para M6: `Historico BANREP.xlsx` e `Historico Traslados.xlsx` (SUP-46). Los 27 días del Anexo C están en la configuración (`pipeline/conf/dq_rules.yml`). El repo versiona solo D y E porque la corrida no lee A, B ni C: los **originales de D y E** (entregados por el banco el 21-oct-2026) están en `datos/raiz/anexos/Anexos/` (sha256 del D `a247fae77dcf5779e6e36e732af447945faa32a670555a03c0962237992c20ec`, del E `caaa399cbd21459303d6b738f949b8f52b89801104ac5bb3a392a4fb77097c97`; SUP-40). No existen en S3.

**Indicación del banco sobre la información faltante:** lo que el banco no suministró debe suplirse con supuestos debidamente documentados. Por eso cada SUP del registro final declara qué no entregó el banco, qué se asume, por qué (con cita literal), su efecto, la alternativa y dónde se aplica (§5), y la sección "Preguntas abiertas" del registro pasó a "Preguntas convertidas en supuestos": no se esperan respuestas del banco.

**Entregable principal: el Excel `entrega/POC_Efectivo_PRAGMA.xlsx` v2**, sha256 **`167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461`** (929.096 bytes, generado el 26-oct-2026 sobre la plantilla original del Anexo D). Reemplaza a la v1 del 21-oct (sha256 `52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688`, 917.601 bytes), que queda en el historial de git (commit `955115d`) y en `ALX/entrega/historico/v1_2026-10-21/`. Qué cambió, por qué y cuánto: `entrega/CAMBIOS_v2.md`. **Los pronósticos (hoja 01) y las métricas predictivas (hoja 03) son los mismos de la v1**; cambian el plan operativo, M6, los costos y los textos. El pliego exige un único Excel `POC_Efectivo_<NOMBRE_PROVEEDOR>.xlsx` con 5 hojas obligatorias y conservar sin modificar las informativas. Contenido de las 6 hojas de la v2 (v1 entre paréntesis cuando cambia):

| Hoja | Filas | Contenido |
|---|---:|---|
| `01_Predicciones` | 9.690 | M1 435 × 15; M2 56 × 15 × 2 objetivos; M3 44 × 15 × 2; M4 5 × 15; M5 6 × 15. Del 1 al 15-sep, 0 nulos, 0 duplicados. Idéntica a la v1 |
| `02_Plan_Operativo` | 2.585 (2.592) | M1 1.349 provisiones + 53 sin acción; M2 28 provisiones + 719 recolecciones + 3 sin acción; M3 2 provisiones + 425 recolecciones (432; 7 omitidas por SUP-43) + 6 sin acción. Con cupo, saldo antes/después, ocupación y costo. `nivel_riesgo` medido antes de la acción (SUP-42): 1.098 alto, 1.216 medio, 271 bajo (v1: 2.592 bajo) |
| `03_Metricas_Desarrollo` | 105 | Métricas del **backtest propio 17–31 ago** (origen 16-ago): Global, Cali, Pasto, Ipiales, Semana 1 (17–23) y Semana 2 (24–31); de M6 solo métricas operativas y de costo. Las 91 predictivas iguales a la v1; cambian 4 valores de costo y los textos `comentarios` (49) y `metodologia_validacion` (105) |
| `04_Descripcion_Solucion` | 8 | Una fila por modelo × objetivo, con enfoque, variables, validación, limitaciones y supuestos SUP-xx citados por número y título. En la v2 las 80 celdas de texto se reescribieron para el evaluador (interruptor `hoja04_v2`) |
| `05_M6_Fondos` | 566 (565) | 6 fondos × 6 denominaciones × 15 días más filas de acciones: 198 de traslado (99 traslados), 148 ventas, 4 retiros BanRep, 216 sin acción; sin venta, BanRep ni intercambio en días no hábiles |
| `06_Diccionario_Campos` | 20 | Informativa, intacta |

`validate_xlsx.validate_anexo_d` da 0 errores (v1 y v2). **Salvedad:** el pliego menciona además las hojas informativas `00_Instrucciones`, `GUIA_Descripcion_Solucion` y `07_Catalogo_Ejemplos`, pero la plantilla recibida no las trae; no se crearon porque el pliego prohíbe hojas adicionales (pregunta abierta P25, SUP-40).

**Contratos de salida del entregable v2:** `entrega/output_api/` (6 parquet con su `_schemas/*.json`): `predicciones` 10.230 filas (9.690 PROYECTADO de M1–M5 + 540 SIMULADO de M6), `recomendaciones` 2.897 (v1 2.923), `alertas` 2.547 (v1 2.590; solo cambian las de M6, 293 → 250), `metricas` 50 (v1 46; nuevas `recoleccion_omitida_monto`, `cajeros_sucursal_mapeados`, `flujo_sin_fondo` y `costo_traslado_tarifa_destino`), `backtest` 15.804, `silenciosos` 15. `silenciosos` y los `_schemas` son idénticos byte a byte a la v1. Las bandas del 90 % solo están aquí (la plantilla no tiene columna para ellas).

**Entregable secundario:** la publicación en S3 con la forma de los contratos OpenAPI del arquitecto (§7). **Vigente: `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/`** (entrega v2, 26-oct-2026, 249 objetos), indicada por el puntero `output/pronosticos/version_vigente.json`. `output/pronosticos/v0_provisional/` (revisión 2 del 22-oct) es la publicación de la v1 y se conserva sin cambios.

---

## 2. Historia: repo de Andrés, repo de Santiago y el trabajo de ALX

Hay tres líneas de trabajo, en este orden. Este repo sale de la tercera.

### 2.1 Repo de Andrés Vergara: `poc-daas-bancolombia` (primer intento de Pragma)

- Remoto `git@github.com:andresvergara-cmd/poc-daas-bancolombia.git`, rama `main`, último commit **`562088f`** (sin cambios desde el 8-oct-2026). Paquete Python `daas` (Python 3.11) con capas `raw → interim → processed → features → output` (+ `quality`), contratos C-01..C-12, reglas de calidad V-01..V-12 y orquestadores `run_u0` … `run_u7`.
- Pronóstico: **un Prophet por serie, solo con estacionalidad semanal**, validado en una sola ventana (17–31 ago). WAPE de ese backtest: M1 0,3188; M2 0,3954 (solo `pagado`); M3 0,5253 / 0,5552; M4 0,4679; M5 0,7057.
- Documentación en la carpeta docs de ese repo (11 documentos: `arquitectura.md`, `documento-tecnico.md`, `supuestos.md` SUP-01..SUP-14 y SUP-M3-01/02, `metodologia.md` CRISP-DM + ASUM-DM, `modelo-datos.md`, `inventario-datos.md`, `plan-ejecucion.md`, `preguntas-cliente.md`, `onboarding-cientifico-datos.md`, `arquitectura-rfp.md`, `arquitectura-objetivo.md`). Su PDF de supuestos es `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf`.
- Una revisión del 8-oct-2026 (`CONTEXTO_CONVERSACION.md` §6) encontró, sobre ese commit, riesgos frente al pliego (nombre del Excel, saldo antes vacío en la hoja 02, M6 sin control de días hábiles, M3 sin costo, Prophet sin calendario de pagos, tarifa única de ATM) y errores de lógica (re-ejecutar U1/U2 borraba m3–m6, M6 no aplicaba sus propias acciones y prometía el mismo excedente a varios fondos, etc.). Esos hallazgos se refieren al código de Andrés; **no se re-verificaron uno por uno contra la base que usa este repo**. Varios no se observan en el entregable vigente (el Excel se llama `POC_Efectivo_PRAGMA.xlsx`, la hoja 02 trae saldo antes y después, M6 no recomienda BanRep/venta/intercambio en días no hábiles, M3 tiene costo y M6 aplica las acciones secuencialmente).
- **Qué tomó ALX de Andrés:** el entendimiento del pliego y de los datos (la revisión del repo y de los datos del bucket encontró los problemas de §3.5). No se tomó código de Andrés. Las tablas que hoy están en `output/api/` de los buckets son salidas de su pipeline (§7.3).

### 2.2 Repo de Santiago Higuita: `poc-daas-ds-dev` (base del código de este repo)

- Remoto `git@github.com:shiguitau0301/poc-daas-ds-dev.git`, último commit **`08a93bc`** (15-oct-2026), 325 archivos. No es un fork git del de Andrés (no comparten historia), pero comparte el paquete `daas`, los módulos M1–M6, los contratos C-01..C-12 y los SUP-xx: parte del código de Andrés reorganizado.
- Aportes: un **laboratorio de evaluación** (`lab/`) con un **arnés de backtest rodante** (16 orígenes de selección + 2 bloqueados + chequeo), una **regla de adopción** estadística, **bandas conformales** por tramo de horizonte, explicabilidad (permutación y SHAP), simuladores de políticas y una landing React (no Angular). Modelos adoptados por Santiago, que son la **referencia** contra la que se mide todo después: M1 y M2 `combo_gbm_prophetcal` (promedio de un boosting global con calendario + Prophet con calendario), M3 `gbm_cal` (boosting global con calendario), M4 y M5 `combo_perfil_gbml1` (perfil día de semana × factor del día del mes + boosting con pérdida L1).
- Ojo: el "LightGBM" del README de Santiago es en realidad `HistGradientBoostingRegressor` de scikit-learn (HGB). Y el campo `datos: "synthetic-data"` de sus registros **no significa datos sintéticos**: es el nombre de la carpeta raíz de datos; sus corridas son sobre datos reales (se comprobó con paridad exacta, §6.1).
- Su Excel (`ALX/entrega/referencia_santiago/POC_Efectivo_PRAGMA.xlsx`, sha256 `bc7d5189ebe0f15a670b5a03d23238ae6b0fc5b08f21b59aa29912e1dc8333f5`) es la referencia de comparación del entregable. WAPE de su hoja 03 (chequeo 17–31 ago): M1 0,2551; M2 `pagado` 0,3652; M2 `cash_in` 0,3868; M3 0,4219 / 0,4577; M4 0,3196; M5 0,5668.
- **Qué tomó ALX de Santiago:** todo el pipeline (`pipeline/`), el laboratorio (`lab/`), el arnés y su regla, el conformal, los supuestos SUP-01..SUP-23 y el registro de supuestos (hoy `pipeline/docs/supuestos.md` en este repo, que ALX continuó desde SUP-24), y sus modelos como referencia. Los cambios de ALX sobre el pipeline van **detrás de interruptores** (`pipeline/conf/alx.yml`): con todos apagados, el pipeline reproduce el Excel de Santiago celda a celda (105/105 filas de la hoja 03; §6.8).

### 2.3 El trabajo de ALX (Alexander Peláez, Pragma), 8 al 26-oct-2026

`ALX/` es una carpeta de trabajo en Google Drive (no es un repo git) que contiene una copia del repo de Santiago más todo lo nuevo. Los clones de los repos de Andrés (carpeta poc-daas-bancolombia del Drive) y de Santiago (carpeta repo-santiago del Drive) se mantuvieron **solo lectura**. Cronología:

| Fecha | Qué se hizo | Resultado |
|---|---|---|
| 8-oct | Revisión del repo de Andrés y de los datos del bucket réplica; cargadores `datos_poc.py`, notebook `01_series_de_tiempo.ipynb`, `guia_datos_bucket.md` | Problemas de datos de §3.5 (unidades de TDV_001, filas `TOTAL`, duplicado del 13-may, desinstalados, faltantes de fuentes) |
| 13-oct | Bitácora `CONTEXTO_CONVERSACION.md` | Traspaso entre sesiones |
| 18-oct (fase 1) | Análisis del repo de Santiago (`ALX/analisis_repo_santiago.md`), EDA por serie con Box-Jenkins, SARIMA de referencia, MLflow | SARIMA descartado; MLflow con importación del historial de Santiago |
| 18-oct (fase 2) | Mejora de los modelos de Santiago con ML: 146 candidatos, regla de adopción v1 declarada antes de medir | Champions nuevos en 6 de 7 series; M4 se queda con Santiago |
| 19–21-oct | Workflow de imputación: inventario de faltantes, 6 métodos, repetición del ML; correcciones de datos y medición (SUP-24..SUP-40); entregable nuevo | **Imputación no adoptada**; correcciones adoptadas; Excel `52e7547f…` |
| 22-oct | Publicación provisional en S3 (revisiones 1 y 2), preguntas al arquitecto, resumen de avances v2, diagnóstico y plan de M5, M5 v2 | `v0_provisional` r2 (248 objetos); M5 sin cambios en la entrega |
| 23-oct | Armado de este repo mínimo con una corrida auditada | 231 archivos (232 con este documento), sin commit |
| 24-oct | EDA Box-Jenkins v2 de M1–M6 (`ALX/eda/03_eda_box_jenkins_v2.ipynb`), solo identificación, sin estimar modelos | EDA vigente; supera al notebook 02 (§6.2) |
| 25-oct | EDA dedicado de M5 (`ALX/eda/04_eda_m5.ipynb`) | Causas del sesgo de M5 y recomendaciones P3–P6 sin implementar (§6.5) |
| 26-oct | Publicación de la v2 en `output/pronosticos/v2/` y puntero `version_vigente.json`; `publicar.py` parametrizado por versión | 249 objetos, manifest `967eac4b…`; `v0_provisional/` intacta |
| 26-oct | Auditoría del entregable contra el pliego y el texto literal de los Anexos B y C (`Mi unidad/PoC-Bancolombia/.agents/tasks/auditoria-pliego/auditoria.md`); correcciones v2 detrás de 10 interruptores (SUP-42..SUP-53 nuevos, SUP-12/14/21/22 y otros reescritos); registro propio como versión final de supuestos; actualización de este repo | **Excel v2 `167a52e4…`** (`entrega/CAMBIOS_v2.md`); pronósticos y métricas predictivas sin cambios |

### 2.4 Cómo se armó este repo (23-oct-2026)

El usuario pidió subir a `https://github.com/alexanderpj-ds/poc-bancolombia` (repo vacío creado para esto) **solo lo indispensable para reproducir los resultados vigentes** (el Excel y la publicación en S3), y un archivo de contexto para LLM (este). Decisiones que tomó el usuario:

1. "Correr el proyecto" = poder ejecutar todo el proceso y llegar a los mismos resultados del Excel y de S3. **Los notebooks de análisis no entran.**
2. Lo que no es necesario para generar los pronósticos no entra (pruebas, informes, resúmenes, landing, experimentos).
3. Los datos no son un riesgo (todo vive en cuentas empresariales de la compañía, incluido GitHub); el peso se maneja como mejor convenga: por eso `raw/` (110 MB) se descarga de S3 con un script y no se versiona; los anexos D y E (71 KB) sí se versionan porque no están en S3.
4. Entorno exacto con `uv` (`pyproject.toml` + `uv.lock`) para que cualquiera pueda replicar.
5. **No perder nada**: todo lo excluido (en especial la imputación, que no mejoró los modelos pero sirve para la sustentación y para mejoras) sigue en `ALX/` sin cambios y está inventariado en el README §12 y en §6 de este documento. **No se borró ni modificó nada de `ALX/`** (verificado contra un manifiesto sha256 de 740 archivos).
6. El repo queda listo con `git add` y **sin commit**: el commit y el push los hace el usuario.
7. Prioridad: tener el repo ya. Por eso **no se repitió la corrida completa desde el repo**; la evidencia de reproducibilidad es una corrida auditada sobre una copia de `ALX/` con el mismo script, datos y versiones (§8).

Cómo se decidió qué entra: se corrió el pipeline completo con un hook de auditoría (`sys.addaudithook`) que registró cada archivo abierto y cada módulo cargado (187 rutas de `ALX/` leídas). Entró lo que esa corrida leyó o importó, más `publicacion_s3/publicar.py` y lo que este lee. Quedaron fuera, por no usarse nunca, `ALX/pipeline/src/daas/modules/funds_m6/recommender.py`, `ALX/pipeline/src/daas/quality/schemas.py`, `ALX/pipeline/conf/aws.yml`, `ALX/pipeline/conf/contracts/C-01..C-12.yml` y `ALX/ml/conf/`. El layout replica las rutas relativas de `ALX/` porque `ml/__init__.py`, `lab/__init__.py`, `imputacion/__init__.py`, `pipeline/corrida_entrega.sh` y `publicacion_s3/publicar.py` localizan la raíz por posición relativa: **no muevas carpetas**. Por eso dentro del código la raíz del repo se llama `ALX` (variable `ALX` en `corrida_entrega.sh` y `publicar.py`). Ningún archivo de código se modificó al copiarlo (220/220 idénticos byte a byte a `ALX/`).

**Actualización v2 (26-oct-2026).** Se copiaron de `ALX/` los 19 archivos de código y configuración que tocaron las correcciones v2 (5 de `pipeline/conf/` y 14 de `pipeline/src/daas/`), el módulo nuevo `pipeline/src/daas/publish/anexo_d/sheet_04_v2.py`, el registro `pipeline/docs/supuestos.md` (lo citan el código, la configuración y la hoja 04; antes estaba solo en el Drive), el Excel y los contratos v2 y `entrega/CAMBIOS_v2.md`. Todos idénticos byte a byte a `ALX/`. No entraron: el respaldo v1 (`ALX/entrega/historico/`; git conserva la v1 en el commit `955115d`), `ALX/entrega/CONTEXTO_v2_para_Andres.md` (comunicación interna), las pruebas (`ALX/tests_alx/test_correcciones_v2.py`) ni los scripts de verificación de la v2 (`~/.cache/poc-daas/corrida_entrega_v2/scripts/`). El repo queda con 235 archivos versionados.

---

## 3. Datos: buckets, capas, fuentes y hallazgos de calidad

### 3.1 Los dos buckets (us-east-1)

| Bucket | Cuenta | Perfil AWS | Uso en este repo |
|---|---|---|---|
| `poc-daas-bancolombia-replica-903641686926` | 903641686926 | `alx-poc` | **Réplica, solo lectura.** Fuente de `raw/` (19 objetos, 110.501.133 bytes) que descarga `scripts/descargar_raw.sh`. 61 objetos el 8-oct, 63 el 18-oct |
| `poc-daas-bancolombia-777937796305` | 777937796305 | `alx-mx` | **Bucket destino** (el principal del proyecto; el de la configuración original de Andrés). Versionado Enabled, SSE AES256; 64 objetos antes de publicar. `raw/` idéntico a la réplica (19/19). Lo lee `publicacion_s3/publicar.py` (`interim/` y `processed/`) y aloja `output/pronosticos/v0_provisional/` |

Comparación réplica vs destino (22-oct): 62 objetos iguales (25 por ETag + 37 con ETag distinto por multipart pero sha256 idéntico), 2 solo en destino (`quality/reports/20261009T032853` y `T033058`), 1 solo en réplica (`output/anexo_d/POC_Efectivo_PRAGMA.xlsx`), 0 distintos. El bucket destino podría pasar a ser la fuente de datos (capas idénticas); **no se cambió ninguna configuración**: es decisión del usuario.

### 3.2 Capas

`raw/` (archivos del banco) → `interim/` (una tabla limpia por fuente) → `processed/` (una tabla por modelo, hasta el 31-ago, más `_holdout/` y `_dim/dim_fondo`) → `features/` (calendario y lags) → `output/` (contratos y Excel), más `quality/` (reportes de calidad). Cada tabla se nombra con una URI abstracta `daas://<capa>/<dataset>` que `pipeline/src/daas/io/storage.py` resuelve a disco local o S3 según `pipeline/conf/paths.yml`. **El pipeline de este repo trabaja sobre `raw/` y los anexos en disco local** (inventario de la corrida auditada): U0 regenera `interim/`, `processed/` y `features/`, no los baja de S3. Solo `publicacion_s3/publicar.py` lee capas derivadas del bucket.

El bucket trae un **holdout** parcial de septiembre (solo M6 y 26 filas de M5): **no se usa** para entrenar ni elegir (SUP-18).

### 3.3 Los 6 fondos (eje de todo)

Fondo = `CIUDAD|TRANSPORTADORA`: `CALI|TRANSPORTADORA_001`, `_002`, `_003`, `_004`, `PASTO|TRANSPORTADORA_001` e `IPIALES|TRANSPORTADORA_002`. M4 tiene 5 fondos porque `CALI|TRANSPORTADORA_004` no tiene CBR (y esa TDV solo existe desde el 8-may-2026). En las vistas `api/` de S3 se escriben `CIUDAD|TDV_00X`. Universo de datos (8-oct): 491 cajeros (435 dispensadores, 56 multifuncionales), 44 sucursales, 39 puntos CBR y 529 puntos de clientes.

### 3.4 Fuentes y contratos C-01..C-12

`pipeline/conf/sources.yml` mapea las 19 fuentes de `raw/` (más el Anexo E) a 12 contratos canónicos; cada uno tiene su lector en `pipeline/src/daas/ingest/readers/`.

| Contrato | Fuente | Filas | Grano y periodo | Uso |
|---|---|---:|---|---|
| C-01 `txn_cajeros` | `raw/txn_cajeros_train.csv` | 844.207 | cajero × día × código, 1-sep-2024 a 31-ago-2026 | M1, M2. `pagado` = `cdgtrn` 220, 420, 520; `cash_in` = 401, 501, 629 |
| C-02 `cp_historico` | `raw/cp_historico.xlsx` | 233.644 | 557 snapshots del maestro de cajeros, 2-ene-2023 a 8-sep-2026 | Cupo, administrador, ciudad; contexto "as of" (SUP-28) |
| C-03 `cp_desinstalados` | `raw/cp_desinstalados_enmascarados.xlsx` | 3.157 | código de cajero | RN-07 (SUP-01) |
| C-04 `txc_suc` | `raw/txc_suc_train.csv` | 31.974 | sucursal × día, 1-sep-2024 a 31-ago-2026 | M3 |
| C-05 `oficinas` | `raw/Oficinas.xlsm` | 44 | sucursal | Fondo y tipología (costo) |
| C-06 `maestro_sucursales` | `raw/maestro_sucursales_hist_enmascarado.xlsx` | 83.401 | snapshots 2019 a 24-sep-2026 | Maestro de sucursales |
| C-07 `cbr` | `raw/CLIENTES_Y_CBR.xlsx`, hoja `CBR` | 10.607 | un depósito por fila, 2-ene-2023 a 31-ago-2026 | M4 (se agrega a fondo-día) |
| C-08 `clientes` | `raw/CLIENTES_Y_CBR.xlsx`, hoja `Clientes` | 148.184 | un depósito por fila, 1-ene-2023 a 29-sep-2026 | M5 (lo posterior al 31-ago no se usa) |
| C-09 `disponibles` | 10 × `raw/TRANSPORTADORA_00X_disponibles_AAAA.csv` | 309.048 | fondo × día hábil × denominación × calidad × familia, 2-ene-2024 a 16 o 30-sep-2026 | M6: saldo inicial, mínimos, máximos, mezcla |
| C-10 `intercambios` | `raw/Historico_Intercambios.xlsx` | 9.523 | operación, 2-ene-2024 a 31-ago-2026 | M6 (solo habilita la operación) |
| C-11 `consolidado_ventas` | `raw/Consolidado_ventas.xlsx` | 1.769 | operación, 2-ene-2024 a 31-ago-2026 | M6 (habilita; tasa de venta SUP-23) |
| C-12 `costos_anexo_e` | `datos/raiz/anexos/Anexos/Anexo_E_Parametros costos.xlsx` | — | tarifas por servicio y TDV | Costos: `costo = fijo + monto / 10.000 × tarifa` |

Los sha256 de los 19 archivos `raw/` están en `scripts/raw.sha256`. Rango y volumen por serie (datos corregidos): M1 279.050 cajero-días con dato y 0 ceros (en cajeros un día sin uso **no llega como 0: no hay fila**); M3 10.163 ceros reales (domingos, festivos y sábados) y casi ninguna ausencia; M4 y M5 tienen historia desde enero de 2023 (M4 es la más incompleta); 21 series tienen menos de 90 días con dato (`ALX/resumen_avances_v2.md` §3.3).

**Anexo C:** 27 días sin registro en toda la red de cajeros: 6 a 17-abr; 10, 16 a 18, 20, 22 a 25 y 30-jun; 6 a 10-jul de 2026 (14.568 cajero-días). Solo afecta a M1 y M2. **Siempre quedan NaN, nunca 0** (`pipeline/src/daas/quality/anexo_c.py`, `mark_missing`). Ponerlos en 0 es criterio de descarte.

**Septiembre de 2026 no tiene festivos entre el 1 y el 15.** El 31-ago es lunes (pago de fin de mes, su efecto cae el 1-sep) y el 15-sep es martes (quincena): en la prueba ciega pesan los días de pago y los días 1–2 del mes.

### 3.5 Hallazgos de calidad y cómo se trató cada uno

Ninguna corrección inventa datos: se deduplica, se convierten unidades, se excluyen subtotales o se marca como faltante. Fuentes: `CONTEXTO_CONVERSACION.md` §9, `ALX/guia_datos_bucket.md` §8 (21 problemas), `ALX/resumen_avances_v2.md` §3.4, `pipeline/docs/supuestos.md` y, para las filas 18–21 (v2), la auditoría del pliego del 26-oct y `entrega/CAMBIOS_v2.md`.

| # | Hallazgo | Tratamiento vigente |
|---|---|---|
| 1 | **Anexo C** (27 días, 14.568 cajero-días) | NaN en entrenamiento, simulación y métricas (SUP-02). Imputación evaluada y no adoptada (SUP-36). En la v2 la hoja 04 declara además el efecto estimado del bloque de abril, como pide el Anexo C |
| 2 | **M6, TDV_001 con unidades mezcladas:** `valor` es cantidad de billetes hasta el 17-jul-2026 y pesos desde el 21-jul-2026 (`CALI\|` y `PASTO\|TRANSPORTADORA_001`). Sin corregir, el mínimo de M6 sale en miles de pesos y nunca detecta déficit | Se convierte a pesos lo que está en billetes, **detectado por datos** (un fondo-día está en billetes si menos del 50 % de sus filas distintas de 0 son múltiplo de la denominación): 49.212 filas. SUP-29 |
| 3 | **M6, filas `calidad = TOTAL`** en TDV_002 (hasta el 12-ago-2026) y TDV_003 (hasta el 29-jul-2026): subtotal que duplica el saldo y los mínimos/máximos | Se excluyen 16.423 filas (16.192 igualan exactamente la suma del resto). SUP-29 |
| 4 | **M6, 30 fondo-días con doble formato** (el `TOTAL` no iguala la suma; TDV_002 del 21 al 27-jul y 11–12-ago-2026; TDV_003 desde el 8-ene-2026) y **23 blancos** en `CALI\|TRANSPORTADORA_004\|50000` (9-jul a 11-ago-2026) | Salen de la ventana de mínimos y máximos (SUP-10) como faltantes. **Salvedad:** el reparto por denominación (SUP-09) todavía los usa (§11) |
| — | Efecto conjunto en M6 al 31-ago (36 fondo × denominación) | Saldo inicial igual en 36/36; estados de riesgo de 11 bajo mínimo / 7 sobre máximo a **4 / 6: cambian 10 de 36**. **[Contradicción resuelta]** El 8-oct, corrigiendo solo `TOTAL` y unidades, se contaban 5 / 5 y 8 cambios; la cifra vigente (con las tres correcciones) es 10 |
| 5 | **Sucursales: 13-may-2026 duplicado** (las 44 sucursales dos veces; entradas 111,0 → 55,5 mil M) | Se deduplica para entrenar y evaluar (SUP-35; interruptor `correcciones_datos`) |
| 6 | **Sucursales: 4 días sin dato** (6-dic-2024, 6-may-2025, 29 y 30-ago-2026) | Quedan NaN |
| 7 | **Cajeros desinstalados** 1120, 1121, 1122 y 5778 (3-ago-2026) | Pronóstico 0 los 15 días y fila `sin_accion` (regla de inactividad de Santiago). RN-07 saca de las métricas 25 cajeros de M1 y 4 de M2 (SUP-01). De 29 marcados RN-07, 23 son códigos reutilizados (SUP-06) |
| 8 | **Valores corruptos:** monto `884s0000` (cajero 6303, 25-jul-2026) y fecha `35/06/2026` | El monto deja el cajero-día como NaN; la fecha la descarta `processed` (SUP-35) |
| 9 | **Ceros de M3 en días hábiles de agosto de 2026:** 10-ago, 34 de 44 sucursales en 0; del 18 al 28-ago, 5 a 10 por día hábil (en julio, máximo 2) | Se conservan como cero real (dato entregado); como faltante solo se midió como sensibilidad (SUP-37). Bajan la cobertura de las bandas de M3. **Pendiente de confirmar con el banco** |
| 10 | **Maestro de cajeros "vigente" del 8-sep-2026**, posterior al corte (392 cajeros cambiaron de cupo y 144 de administrador; `estado` siempre `Produccion`) | Las variables de contexto usan el último snapshot ≤ cada origen ("as of", SUP-28): cambia algún atributo en el 20,4 % de los cajero-orígenes de M1. Los datos de referencia (cupo, administración, sucursal) usan el último snapshot de cada cajero, declarado en SUP-45 (v2): frente al del 23-jul cambian 2 cupos y 4 cajeros solo existen en el del 8-sep |
| 11 | **Menos cajeros reportando** del 10 al 25-ago-2026 (355–390 frente a unos 425) | Se deja como dato; explica buena parte de la distancia entre la lectura observada y la RN-08 |
| 12 | **SUP-02 no estaba implementado:** una entidad con todos sus reales en 0 en la ventana entraba al WAPE agregado | Sale solo del WAPE agregado; MAE, Bias y `n` la incluyen (SUP-27). En M3 baja el WAPE 3,1–4,9 pp **sin cambiar ningún pronóstico** (§4.4) |
| 13 | **Hueco de disponibles** del 31-jul al 9-sep-2024 (33 días hábiles) | No se imputa; no entra en ninguna ventana de M6 |
| 14 | **Clientes (M5):** 529 puntos frente a 344 esperados; ~217 activos en ago-2026; Pasto cae de 200–250 a 20–45 mil M/mes desde sep-2025; depósitos de hasta 203 mil M en un día; pocos "megapuntos" esporádicos dominan el sesgo | Se usan todos; diagnóstico en §6.5 |
| 15 | **CBR (M4):** de 39 puntos, solo 10 con movimiento en ago-2026; casi sin datos los domingos | Se modela tal cual |
| 16 | **Faltan fuentes para M6:** el Anexo A lista `Historico BANREP.xlsx` e `Historico Traslados.xlsx`, que no están entre los 19 archivos recibidos (SUP-46) | BanRep se habilita por tarifa y solo en Cali (SUP-13); traslados y ventas inferidos de `dim_fondo` y del histórico de ventas (SUP-08). Es lo único del Anexo A que no se recibió |
| 17 | **Linaje en el bucket:** sin manifiestos `.meta.json`; un solo reporte de calidad del 6-oct en la réplica | Informativo |
| 18 | **Cajeros administrados por sucursal fuera de M6 (v1):** el flujo de los 84 cajeros con `admon = SUC` no llegaba a ningún fondo (42,2 mil M de ingresos y 111,7 mil M de salidas en el horizonte) | v2: 82 se integran al fondo de su sucursal administradora (Oficinas); 9859 y 9860 quedan fuera y declarados (sucursal 787 ausente de Oficinas; 2.568.045.929 COP de pagado de M1). El 2691 figura en Pasto pero su sucursal 70 se atiende desde Cali y va a `CALI\|TRANSPORTADORA_002` (SUP-12) |
| 19 | **Tarifas y escalas (v1):** 5 MF de TDV fuera del municipio de la ciudad del fondo con tarifa urbana; la sucursal 70 con escala de la `Ubicación` (`INTERURBANO 3`) aunque `Escalas = 1` | v2: tarifa MF interurbano (SUP-21, +3,94 M COP en M2) y escala desde `Escalas` (SUP-22, −6,76 M COP en M3) |
| 20 | **`nivel_riesgo` de la hoja 02 en bajo en las 2.592 filas (v1)**, incluidos 2 MF (8667 y 9311) con cupo menor que su flujo neto de algunos días; recolecciones de M3 de pocos miles de COP | v2: riesgo antes de la acción (SUP-42), cupo insuficiente declarado (SUP-44) y monto mínimo de recolección en M3 (SUP-43, 7 omitidas por 548.282 COP) |
| 21 | **Fecha de disponibilidad de los traslados (v2 preliminar):** la nota del Anexo E dice que el traslado llega al destino al día siguiente | v2 final: el traslado se ordena el día anterior al faltante y sus dos filas llevan la fecha de ejecución (SUP-52); el costo entre ciudades usa la tarifa de la TDV del fondo origen (SUP-53) |

**`origen_dato` (SUP-24 a SUP-26).** Cada fila de los contratos de salida lleva su procedencia en un conjunto cerrado: `PROYECTADO` (pronósticos M1–M5), `SIMULADO` (balance M6), `ESTIMADO` (recomendaciones, alertas, métricas, backtest) y **nunca `REAL`** (el horizonte es posterior al corte). Es la defensa frente al criterio de descarte "presentar como observado algo estimado". El Excel no tiene esa columna; la procedencia se declara en la hoja 04.

**Maestro vigente vs as-of.** El pipeline de Santiago usa el maestro vigente (8-sep) para atributos operativos; ALX corrigió las **variables de contexto V4** del ML para usar el maestro "as of" en cada origen, con una guarda de fuga (alterar los snapshots posteriores al origen no cambia el pronóstico). En M3 el cupo es constante por sucursal, así que no cambia nada.

---

## 4. Modelos M1–M6, métricas, champions, regla de adopción, bandas y M6

### 4.1 Qué pronostica cada modelo

| Modelo | Canal | Variable(s) | Grano | Entidades | Salida operativa |
|---|---|---|---|---:|---|
| M1 | ATM dispensador | `pagado` (retiros) | cajero-día | 435 | Provisión hasta el cupo con costo; alerta de agotamiento |
| M2 | ATM multifuncional | `pagado` y `cash_in` (depósitos), por separado | cajero-día | 56 (× 2) | Provisión o recolección según saldo neto |
| M3 | Sucursal | `entradas` y `salidas` | sucursal-día | 44 (× 2) | Provisión o recolección con costo |
| M4 | Corresponsal bancario robusto (CBR) | `ingreso_efectivo_cbr` | fondo-día | 5 | Ninguna: insumo de M6 |
| M5 | Clientes corporativos | `ingreso_efectivo_clientes` | fondo-día | 6 | Ninguna: insumo de M6 |
| M6 | Fondos de las TDV | Ninguna: balance | fondo × denominación × día | 6 × 6 = 36 | Traslados, ventas y BanRep (v2: sin cambios de denominación ni intercambios dentro del fondo, SUP-14), con saldo antes/después y costo |

Total: 646 series pronosticadas y evaluadas (M1–M5) + 36 de balance (M6) = 682.

### 4.2 Métricas

Fórmulas oficiales sin cambios en `pipeline/src/daas/forecasting/metrics.py`:
- **WAPE** = Σ|Y − Ŷ| / Σ|Y| (principal; **micro**: se suman errores y reales de todas las entidades-día de la celda, no es un promedio por entidad).
- **MAE** = media de |Y − Ŷ| (COP).
- **Bias** = Σ(Ŷ − Y) / ΣY (negativo = subpronóstico).
- Pares con NaN se descartan; si Σ|Y| = 0 el resultado es NaN, nunca 0.

**Dos lecturas del real en cajeros.** *Observada*: un cajero-día sin registro es faltante (la usa el arnés y el entrenamiento). *RN-08*: si la red reportó ese día (y no es Anexo C), la ausencia vale 0; según el README de Santiago es la lectura con la que puntúa el banco, y es más exigente. M1 y M2 publican las dos (SUP-02); la hoja 04 v2 presenta primero la lectura RN-08 (M1 0,3145; M2 `pagado` 0,4488; M2 `cash_in` 0,4814). RN-08 está en el Anexo B, que sí se recibió, y el último párrafo del Anexo C confirma que la ausencia con la red operando vale 0 COP (auditoría del pliego, §0).

### 4.3 Validación: el arnés rodante y la regla de adopción

- **Arnés** (de Santiago, `ALX/lab/evaluation/harness.py`; no está en el repo): en cada fecha de corte simulada (origen) se entrena con datos ≤ origen y se pronostican 15 días. Tres grupos de orígenes: **selección** (16 fines de mes, de feb-2025 a jun-2026), **bloqueados** (31-ago-2025 y 31-jul-2026, abiertos una sola vez al final) y **chequeo** (16-ago-2026, backtest 17–31 ago, la ventana de la hoja 03; nunca decide sola). Paridad: `datos_poc.matriz_arnes` reproduce el cargador del arnés exactamente (650 celdas idénticas, |dif WAPE| máx 9,7e-16).
- **Regla de adopción v1** (`ALX/ml/conf/adopcion_ml.yml`, declarada el 18-oct-2026 17:18 antes de medir, **huella `623420f48f04`**, aplicada literal por `ALX/ml/adopcion.py`; SUP-30, SUP-31). Un candidato reemplaza a la referencia de Santiago si cumple las cinco:
  - **R1:** mejora pareada media en selección ḡ = WAPE_ref − WAPE_cand > k·EE (EE = sd/√n). k = 1 en general; **k = 2** para variantes de la referencia, afinados con Optuna y ensambles que los contienen (corrección por búsqueda múltiple).
  - **R2:** ninguna celda bloque × ciudad empeora más de 2 EE.
  - **R3:** en los 3 orígenes de confirmación (2 bloqueados + chequeo), WAPE medio ≤ el de la referencia y en ninguno lo supera por más de 0,02.
  - **R4:** |Bias medio| ≤ el de la referencia + 0,05.
  - **R5:** banda conformal del 90 % (`por_tramo`) con cobertura 0,90 ± 0,05 en cada bloque.
  - Desempate: menor WAPE medio; a menos de 1 EE, el más simple. Challenger = mejor candidato no adoptado.
- La regla v1 se mantuvo sin cambios durante todo el trabajo posterior (la huella se comprobó igual antes y después).

### 4.4 Champions adoptados (estado vigente, escenario S1)

Escenario **S1** = datos corregidos (SUP-35) + contexto V4 "as of" (SUP-28) + métrica con SUP-27, **sin imputación** (SUP-36). La regla v1 aplicada sobre S1 deja los mismos 7 champions que la fase 2 (`ALX/resumen_avances_v2.md` §8.5; `ALX/imputacion/resultados/ml/decision_final.csv`).

| Serie | Referencia (Santiago) | **Champion** | WAPE selección ref → champion | Mejora ± EE (k) | Confirmación ref → champion | Chequeo 17–31 ago: Santiago → entregado | Andrés (chequeo) |
|---|---|---|---|---|---|---|---:|
| M1 `pagado` | `combo_gbm_prophetcal` | **`ml_lgbm_v4_tw`** (LightGBM, V4, Tweedie) | 0,2394 → 0,2191 | +2,03 ± 1,11 pp (1) | 0,2483 → 0,2444 | 0,2551 → **0,2490** (RN-08: 0,3385 → 0,3145) | 0,3188 |
| M2 `pagado` | `combo_gbm_prophetcal` | **`ml_ens_pond_m2_pagado`** (ponderado congelado, V4) | 0,3825 → 0,3651 (mismos 10 orígenes) | +1,74 ± 0,76 pp (2) | 0,3827 → 0,3813 | 0,3652 → **0,3642** (RN-08: 0,5422 → 0,4488) | 0,3954 |
| M2 `cash_in` | `combo_gbm_prophetcal` | **`ml_ens_pond_m2_cash_in`** (ponderado, V3) | 0,3765 → 0,3638 (10) | +1,27 ± 0,41 pp (2) | 0,4062 → 0,4000 | 0,3868 → **0,3832** (RN-08: 0,5333 → 0,4814) | — |
| M3 `entradas` | `gbm_cal` | **`ml_ens_pond_m3_entradas`** (ponderado, V1) | 0,2249 → 0,2152 (10) | +0,97 ± 0,33 pp (2) | 0,3876 → 0,3772 | 0,4219 → **0,3884** con SUP-02 (0,4200 sin) | 0,5253 |
| M3 `salidas` | `gbm_cal` | **`ml_lgbm_v1_l1`** (LightGBM, V1, L1) | 0,2760 → 0,2583 | +1,77 ± 0,94 pp (1) | 0,3949 → 0,3876 | 0,4577 → **0,4166** con SUP-02 (0,4578 sin) | 0,5552 |
| M4 CBR | `combo_perfil_gbml1` | **`combo_perfil_gbml1`** (sin cambio: ningún candidato cumplió R1–R5) | 0,3351 | — | 0,3103 | 0,3196 → 0,3196 | 0,4679 |
| M5 clientes | `combo_perfil_gbml1` | **`ml_ens_media_top3_m5`** (media de 3 LightGBM L1) | 0,5990 → 0,5634 | +3,56 ± 1,02 pp (2) | 0,5942 → 0,5648 | 0,5668 → **0,5160** | 0,7057 |

Notas para leerla:
- Los ponderados (`pond`) solo se evalúan en 10 de los 16 orígenes de selección (los únicos con 6 orígenes previos cerrados para aprender pesos); la mejora se calcula pareada sobre esos 10.
- **[Contradicción resuelta]** La fase 2 (18-oct, escenario S0) publicó cifras de selección algo distintas (p. ej. M1 0,2196; M3 `entradas` 0,2206; M3 `salidas` 0,2633; `ALX/ml/resultados/adopcion.csv`, `ALX/resumen_avances_v1.md`). Las vigentes son las de S1 de la tabla; los champions son los mismos.
- **M3: la bajada del WAPE en la hoja 03 es casi toda medición (SUP-02/SUP-27), no modelo.** Con la misma medición que Santiago, el champion empata en el chequeo (0,4200 vs 0,4219; 0,4578 vs 0,4577); se adoptó por la media de selección y confirmación. La hoja 03 publica la cifra con SUP-02 y su comentario declara qué sucursales salen (82, 830 y 972 en `entradas`; 82, 813, 830 y 972 en `salidas`). Al presentar, dar siempre las dos lecturas.
- Lo que empeora queda a la vista: Bias de M3 `salidas` −0,019 → −0,104 (sobre todo en la semana 2); 9 de 45 celdas de WAPE por ciudad o semana empeoran (la mayor, M2 `cash_in` Pasto +1,51 pp).
- Hoja 03 del entregable, MAE / Bias: M1 22,04 M / −0,069; M2 `pagado` 15,04 M / −0,112; M2 `cash_in` 49,24 M / −0,083; M3 `entradas` 419,0 M / +0,021; M3 `salidas` 360,49 M / −0,104; M4 758,3 M / −0,063; M5 3.255,5 M / −0,430.
- Dos champions pasan R1 con menos de 2 EE (M1 1,82 EE y M3 `salidas` 1,89 EE en S1); con k = 2 para todos, en M1 quedaría Santiago.

**Cómo corren en el pipeline.** `pipeline/conf/model_u1_u2.yml`, `model_m3.yml` y `model_u4_u5.yml` tienen `forecaster.modelo` (receta de Santiago) y `forecaster.modelo_alx` (champion). Con el interruptor `campeones_ml: true` manda `modelo_alx`, que apunta a recetas `campeon_m1`, `campeon_m2_pagado`, `campeon_m2_cash_in`, `campeon_m3_entradas`, `campeon_m3_salidas` y `campeon_m5` de `pipeline/conf/pronosticadores.yml` (familia `ml_laboratorio`); M4 usa la receta nativa `combo_perfil_gbml1`. La familia `ml_laboratorio` (`pipeline/src/daas/forecasting/laboratorio.py`) llama a `ml.pronosticar.pronosticar`, que arma el modelo desde la receta congelada en `lab/conf/experimentos/<champion>.yml` vía `lab.forecasting.registry`. El contexto V4 lo arma `imputacion/contexto_asof.py` desde `raw/cp_historico.xlsx` de la raíz de datos local (es solo contexto: **no imputa**). Champion y challenger por serie también están en `lab/conf/bandas.yml` (claves `adoptado` y `retador`).

**Variables (V0–V4, acumulativas, motor `pipeline/src/daas/forecasting/global_ml.py`).** V0 = las de Santiago; V1 = calendario colombiano detallado (`pipeline/src/daas/forecasting/calendario_co.py`: día de pago 15 y fin de mes corridos al hábil anterior, días 1–3 después del pago, puentes, víspera y post-festivo hábiles, primas, Semana Santa, temporada decembrina, Feria de Cali, Carnaval de Pasto, festivos de Ecuador para Ipiales); V2 = rezagos y estacionalidad anual; V3 = perfil propio e intermitencia; V4 = contexto (cupo, ciudad y administración del maestro "as of", red de la ciudad y serie hermana). Conjunto elegido: V4 en M1 y M2 `pagado`; V3 en M2 `cash_in`; V1 en M3, M4 y M5. Estrategia directa con el horizonte como variable y objetivo relativo y(s+h)/nivel.

### 4.5 Bandas conformales y coberturas

Método de Santiago sin cambios (`pipeline/src/daas/forecasting/intervals.py`): banda del 90 % con residuos **fuera de muestra**, escala = nivel de 28 días, cuantiles por tramo (bloque 1 = h 1–7, bloque 2 = h 8–15), corrección de muestra finita, calibración rodante con al menos 6 orígenes previos (en el pipeline, los 8 previos; con menos cae a ± MAE con aviso). Cada modelo nuevo se recalibró con sus propios residuos (`ALX/ml/bandas_ml.py`). Coberturas del champion (S1, `ALX/imputacion/resultados/ml/bandas_oficial.csv`), bloque 1 / bloque 2:

| Serie | Selección | Chequeo 17–31 ago |
|---|---|---|
| M1 | 0,889 / 0,905 | 0,900 / **0,802** |
| M2 `pagado` | 0,891 / 0,919 | 0,931 / 0,868 |
| M2 `cash_in` | 0,913 / 0,888 | **0,847** / 0,921 |
| M3 `entradas` | 0,916 / 0,902 | **0,695 / 0,555** |
| M3 `salidas` | 0,885 / 0,912 | **0,718 / 0,551** |
| M4 | 0,911 / 0,852 | 0,920 / 0,943 |
| M5 | 0,909 / 0,898 | 0,892 / 0,933 |

Todos cumplen R5 en selección, con bandas más angostas que la referencia. En el chequeo, M3 cubre solo 0,55–0,72 con **cualquier** modelo (también el de Santiago) por los ceros de agosto: rompe la intercambiabilidad que da la garantía. Las garantías son marginales (no por entidad ni por día). CQR y conformal adaptativo (ACI) quedan propuestos, no implementados.

### 4.6 M1–M3: simulación de saldo y reglas de recomendación (base de Santiago)

- **M1:** saldo inicial min(cupo, 500 M); umbral de alerta 8 % del cupo (RN-34, SUP-04/SUP-19); política `umbral_pronostico_a_cupo` con margen 0: se provisiona el día en que el saldo menos lo pronosticado bajaría del 8 % y se llena hasta el cupo, tope 500 M por provisión (RN-10, RN-11); lead time 0 (SUP-16). En backtest deja 3,4 % de días agotados y un remanente medio de 24,6 % del cupo (RN-12 pide cerca de 0 % y ≤ 22 %: las dos metas se oponen; SUP-15).
- **M2:** misma familia con el saldo neto (`pagado` − `cash_in`); al cierre se recoge lo que pasa del cupo.
- **M3:** política por sucursal (RN-40, RN-41; SUP-M3-01): reserva = mín(50 % del cupo, máx(8 % del cupo, σ del flujo neto)); provisión hasta la reserva + 3 días de salidas medias; recolección de lo que pasa de la reserva + 15 días de salidas medias (los 15 días son elección de Pragma). Con menos de 30 días válidos, regla vigente del banco.
- Costos del Anexo E (`pipeline/conf/costos.yml`). M1: tabla urbana o interurbana según la tipología de facturación (SUP-21). M2 (v2): `MF INTERURBANO` cuando el municipio del MF de TDV no coincide con la ciudad del fondo (RN-04A, SUP-21; 1519, 7352, 7814, 9251 y 9650). M3 (v2): escala de la sucursal interurbana desde el campo `Escalas` de Oficinas (SUP-22; solo cambia la sucursal 70). Equipos y acciones de sucursal con costo 0 declarado (RN-04A). Costos Santiago → v1 → v2: M1 169,0 → 158,5 → 158,5 M; M2 73,5 → 71,4 → 75,3 M; M3 148,9 → 147,7 → 140,3 M COP.
- **v2, plan operativo:** `nivel_riesgo` de la hoja 02 medido con el saldo sin la acción (SUP-42); cupo insuficiente declarado en 8667 y 9311 (SUP-44: todas sus filas en alto, con días, neto máximo y demanda no atendida mínima); M3 no recomienda recolecciones de efectivo ocioso cuyo monto no supera el costo de la visita, nunca las de exceso sobre el cupo (SUP-43: 7 omitidas, 548.282 COP; el efectivo se encadena a la siguiente visita). M2 no omite ninguna (RN-35) y explica la única antieconómica (9251).
- Cajeros sin dato reciente se pronostican en 0 (RN-08 aplicada como pronóstico) y se listan en `silenciosos` (12 cajeros de M1 con 0 los 15 días: 4 desinstalados + 8 sin dato con la red operando; 3 de M2).

### 4.7 M6: cómo se calcula y reglas de recomendación

M6 **no entrena ni pronostica**: simula el balance por `fondo_id` × denominación a partir de los pronósticos de M1–M5 y recomienda acciones costeadas (`pipeline/src/daas/pipeline/run_u6.py`, `pipeline/src/daas/modules/funds_m6/`). Lo que sigue es la v2; los cambios frente a la v1 se marcan.
1. **Saldo inicial** = último disponible ≤ 31-ago por fondo y denominación, con disponibles corregidos (SUP-07, SUP-29).
2. **Efecto neto diario de M1–M5 por fondo** (signos en `efecto_m1_m5` de `pipeline/conf/model_u6.yml`: ingresos = `cash_in` de M2, `entradas` de M3, M4 y M5; egresos = `pagado` de M1 y M2, `salidas` de M3), imputado al fondo el día pronosticado, sin rezago (SUP-12). Cajeros de TDV: fondo `fondo` + `admon` del maestro CP; sucursales: `CIUDAD FONDO` + `TTADORA` de Oficinas. **v2, cajeros de sucursal** (`admon = SUC`, interruptor `m6_cajeros_sucursal`): su flujo va al fondo de su sucursal administradora (fila de Oficinas de su `codigo_sucursal`, el mismo puente que M3). Se integran 82 de 84; 9859 y 9860 quedan fuera porque su sucursal 787 no está en Oficinas (2.568.045.929 COP de pagado de M1, declarados en la hoja 04, en SUP-12 y en la métrica `flujo_sin_fondo`). El 2691 va a `CALI|TRANSPORTADORA_002` porque su sucursal 70 se atiende desde Cali (alternativa declarada: 1.360.258.526 COP a Pasto). Efecto en la hoja 05: ingresos 1.348,99 → 1.391,20 mil M COP; salidas 957,20 → 1.066,31 mil M COP; cuadre con los pronósticos ≤ 2 COP por fondo-día. En la v1 estos cajeros no llegaban a ningún fondo. El total de M5 se multiplica por un **factor de red móvil** 1/(1 + sesgo), medido en los 3 últimos orígenes cerrados y acotado a [0,67; 1,5] (SUP-20; M4 no se corrige). Hoy la razón medida supera el tope y se aplica 1,5. **[Contradicción resuelta]** El texto de SUP-20 cita razones 1,98 / 1,83 / 1,76 (corrida de Santiago); con el champion vigente son 1,90 / 1,72 / 1,75, media 1,79 (`ALX/plan_mejora_m5.md` §2.5). En los dos casos el factor aplicado es 1,5.
3. **Reparto por denominación** según la mezcla histórica de los disponibles del fondo en 180 días (SUP-09).
4. **Mínimo y máximo** = percentiles 10 y 90 del saldo diario en 180 días (SUP-10).
5. **Simulador secuencial** (`simulator.py`): día a día aplica el efecto, detecta faltantes y excedentes, elige **una** alternativa de menor costo por necesidad (RN-80) y la **aplica al saldo** (el saldo después de una acción es el antes de la siguiente). Primero faltantes (mayor monto), luego excedentes; un excedente se conserva si guardarlo cuesta menos que actuar (RN-79).
   - **Operaciones de RN-84 (v2, SUP-14, interruptor `m6_operaciones_rn84`):** se usan `traslado_fondos`, `venta_efectivo` y `retiro_banrep`; `consignacion_banrep` está habilitada en Cali pero no se eligió en ninguna necesidad. `cambio_denominacion` (que es con BanRep) e `intercambio_bancos` (con otras entidades) quedan deshabilitados dentro del fondo y la explicación lo dice. En la v1 también hubo 0 filas de esas dos operaciones; solo cambia el texto.
   - **Traslado al día siguiente (v2, SUP-52, interruptor `m6_traslado_t1`):** la nota del Anexo E dice que el efectivo sale del origen en la fecha de ejecución y llega al destino al día siguiente. El traslado se ordena el día T, anterior al faltante proyectado de T+1; sus dos filas (salida en el origen, entrada en el destino) llevan la fecha T, con el mismo monto y denominación (RN-74), y el destino lo recibe al cierre de T, que es su saldo inicial de T+1 (RN-71). Un faltante del mismo día no se cubre con traslado. La capacidad del origen es su saldo sobre el mínimo también después de sus flujos de T+1. Los traslados no tienen restricción de día hábil.
   - **Días no hábiles:** sábados, domingos y festivos no admiten BanRep, ventas ni intercambios (RN-71A). BanRep solo en Cali, por tarifa del Anexo E (SUP-13; el histórico BanRep del Anexo A no se recibió, SUP-46). La venta no tiene tarifa: su beneficio es la tasa histórica de ventas (SUP-23).
   - **Costos (Anexo E, hoja Fondos):** costo = fijo + monto / 10.000 × tarifa, registrado una sola vez en la fila de salida del origen (RN-74). Traslados entre fondos de la misma ciudad: costo 0 (nota del Anexo E). **Entre ciudades (v2, SUP-53):** tarifa de la transportadora del fondo origen; la alternativa (TDV del destino) se declara en la explicación y en la métrica `costo_traslado_tarifa_destino` (interruptor `m6_tarifa_traslado_declarada`, solo textos).

**Resultado en el entregable v2 (hoja 05, 566 filas):** 99 traslados (198 filas; 25 ordenados el día anterior al faltante), 148 ventas, **4 retiros BanRep** y 216 sin acción; 275 necesidades, 251 resueltas con una acción y 24 conservadas por costo, 0 parciales, 0 sin solución, 0 saldos negativos; alertas de M6 250. **Costo de M6: 1.441.530 COP** (v1: 0):
- 545.413 COP de 2 traslados `IPIALES|TRANSPORTADORA_002 → PASTO|TRANSPORTADORA_001` en la denominación 50.000, ejecutados el 4-sep (709.150.000 COP, costo 16.219 + 709.150.000 / 10.000 × 3,40 = 257.330) y el 5-sep (799.600.000 COP, costo 288.083), para los faltantes de Pasto del sábado 5 y el domingo 6. Con los cajeros de sucursal integrados, Pasto quedaría bajo su mínimo esos días; BanRep y venta no se permiten en no hábiles y el traslado desde Ipiales es la opción de menor costo (desde Cali costaba 1.486.729). Con la tarifa de la TDV del destino serían 938.560 COP (+393.147; SUP-53).
- 896.117 COP de 4 retiros BanRep del 1-sep en `CALI|TRANSPORTADORA_003` (denominaciones 2.000, 5.000, 10.000 y 20.000; 947.993.000 COP): faltantes del primer día que no admiten traslado, porque habría que ordenarlo antes del corte.

Por fondo (ventas / filas de traslado / retiros BanRep / costo, v1 → v2): CALI|001 35/69/0/0 → 28/70/0/0; CALI|002 47/0/0/0 → 41/2/0/0; CALI|003 0/57/0/0 → 0/48/4/896.117; CALI|004 0/74/0/0 → 0/74/0/0; IPIALES|002 59/0/0/0 → 59/2/0/545.413; PASTO|001 28/0/0/0 → 20/2/0/0. Almacenamiento: 43,37 M (v1) → 41,46 M COP (v2). La verificación independiente recalculó los 99 traslados y los 4 retiros contra el Anexo E con 0 diferencias.

**v1 (21-oct), como referencia:** 200 filas de traslado (100 traslados; 142 filas en días hábiles y 58 en no hábiles, todas entre fondos de Cali, a costo 0), 169 ventas, 0 BanRep, costo de M6 0 (frente a 253.905 COP de Santiago, por el traslado Pasto → Ipiales que desaparece al quitar las filas `TOTAL`: el mínimo de Ipiales baja de 2.535 M a 1.401 M), almacenamiento 52,3 → 43,4 M COP frente a Santiago. M6 no reporta WAPE (SUP-11).

---

## 5. Supuestos SUP-xx vigentes

**Registro final: `pipeline/docs/supuestos.md`** (versión v2, 26-oct-2026; en el repo desde la v2). **Decisión del usuario del 26-oct-2026: el registro propio es la versión final de los supuestos; los documentos de Andrés en `revision-andres/` (Drive) no se usan.** La indicación del banco es suplir con supuestos documentados toda información que no suministró: cada SUP tiene seis encabezados (No lo entregó el banco · Qué asumimos · Por qué, con texto literal del pliego o de los Anexos · Efecto cuantificado · Alternativa y su efecto · Dónde se aplica). La hoja 04 cita cada SUP por número y título. SUP-01 a SUP-23 y SUP-M3-01/02 vienen del registro de Santiago; SUP-24 a SUP-40 son de la v1 de ALX; **SUP-41 está reservado** (M5 v2, no adoptado); **SUP-42 a SUP-53 son nuevos de la v2**. Nada se renumeró. En la v2 se reescribieron SUP-01, 02, 03, 06, 08, 12, 13, 14, 16, 18, 21, 22, 27, 29, 36, 37, 40 y M3-01; "Preguntas abiertas" pasó a "Preguntas convertidas en supuestos" (no habrá respuestas del banco: cada duda la resuelve un SUP). **[Contradicción resuelta]** El PDF de Andrés (`ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf`) y su consolidación del 26-oct coinciden con este registro hasta SUP-14; desde SUP-15 los mismos números significan otra cosa (PDF SUP-15/16/17 = registro SUP-24/25/26; PDF SUP-18, MILP de fondos con ~798 M COP de BanRep, no tiene equivalente ni corresponde al Excel). Manda el registro, que es el que cita la hoja 04. Guía de lectura (escrita antes de la v2, cubre hasta SUP-41): `ALX/guia_supuestos.md`; variables de cada champion: `ALX/variables_por_modelo.md`.

| SUP | Significado (v2) |
|---|---|
| SUP-01 | RN-07: los cajeros activos en el maestro y presentes en desinstalados salen de WAPE, MAE y Bias en todos sus días (por cajero, no por entidad-día) y no calibran la banda; siguen en las salidas |
| SUP-02 | Un cero con la red operando es observación válida; los 27 días del Anexo C quedan nulos; entidad con denominador cero fuera del WAPE agregado; M1 y M2 publican lectura de entrenamiento y lectura RN-08 |
| SUP-03 | M1–M3 pronostican todos los días calendario del 1 al 15-sep (RN-02) |
| SUP-04 | Umbral de agotamiento de M1 = 8 % del cupo (RN-34) |
| SUP-05 | Cassette de depósitos de M2: sin efecto (el efectivo se recicla, RN-30) |
| SUP-06 | Código de cajero reutilizado = una sola serie (RN-06) |
| SUP-07 | Saldo inicial de M6 = último registro ≤ 31-ago por fondo y denominación |
| SUP-08 | Operaciones habilitadas por fondo, inferidas del histórico (`dim_fondo`, ventas) |
| SUP-09 | Reparto del efecto de M1–M5 por denominación según la mezcla de 180 días (salvedad abierta: aún sin las exclusiones de SUP-29) |
| SUP-10 | Mínimo/máximo de M6 = percentiles 10/90 del saldo en 180 días |
| SUP-11 | M6 sin WAPE: completitud y cobertura de recomendaciones |
| SUP-12 | **Reescrito (v2).** Flujo de M1–M3 al fondo, el día pronosticado: cajeros de TDV al fondo del maestro CP, sucursales al de Oficinas y **cajeros de sucursal al fondo de su sucursal administradora** (82 de 84; 9859 y 9860 fuera y declarados; 2691 a Cali). RN-70, RN-08A, pliego §7.1 |
| SUP-13 | BanRep habilitado por tarifa del Anexo E y solo en Cali (RN-75); v2: 4 retiros BanRep el 1-sep en CALI\|TRANSPORTADORA_003 |
| SUP-14 | **Reescrito (v2).** Sin intercambio ni cambio de denominación dentro del fondo (RN-84): las operaciones usadas son `traslado_fondos` (198 filas), `venta_efectivo` (148) y `retiro_banrep` (4); `consignacion_banrep` habilitada en Cali y no elegida |
| SUP-M3-01 | Saldo de la bóveda de M3 en [0, `cupo_max_suc`]; política por sucursal |
| SUP-M3-02 | `cupo_max_suc` vigente = último valor ≤ 31-ago |
| SUP-15 | No se le pone precio al agotamiento ni al efectivo quieto en cajeros y sucursales; frontera de márgenes m0/m25/m50 |
| SUP-16 | Lead time de provisión de M1 = 0 días (RN-11); los traslados de M6 siguen SUP-52 |
| SUP-17 | Entidades con poca historia: el modelo global les comparte lo aprendido; respaldos documentados |
| SUP-18 | Nada posterior al corte entra a entrenar ni a elegir (el holdout de septiembre no se lee) |
| SUP-19 | El 8 % es umbral de alerta; la política de M1 es la del pliego (margen 0) |
| SUP-20 | Factor de red móvil sobre el total de M5 que consume M6, acotado a [0,67; 1,5] |
| SUP-21 | **Reescrito (v2).** Tarifa urbana o interurbana (RN-04A): M1 por tipología de facturación; **M2 `MF INTERURBANO` si el municipio del MF de TDV no es la ciudad del fondo** (5 MF, +3.936.535 COP); alternativa declarada para 4 INDIVIDUAL de M1 (+575.069 COP) |
| SUP-22 | **Reescrito (v2).** Escala de la sucursal interurbana desde el campo `Escalas` de Oficinas (Anexo A); solo cambia la sucursal 70 (−6.757.937 COP) |
| SUP-23 | Tasa de venta de M6 desde `consolidado_ventas` (no contractual) |
| SUP-24 | Métricas marcadas `origen_dato = ESTIMADO` |
| SUP-25 | Recomendaciones y alertas marcadas ESTIMADO, no SIMULADO |
| SUP-26 | `REAL` no aparece en los contratos de salida |
| SUP-27 | Entidad con denominador cero fuera solo del WAPE agregado, también en el arnés (precisa SUP-02) |
| SUP-28 | Variables de contexto con el maestro "as of" (último snapshot de `cp_historico.xlsx` ≤ origen) |
| SUP-29 | Disponibles de M6 corregidos: sin `TOTAL`, TDV_001 en pesos, blancos y doble formato fuera de la ventana de SUP-10 |
| SUP-30 | Regla de adopción R1–R5 declarada antes de medir |
| SUP-31 | k = 2 en R1 por búsqueda múltiple |
| SUP-32 | Pesos congelados en los ensambles ponderados |
| SUP-33 | Contexto empaquetado en el modelo registrado (pyfunc de MLflow) |
| SUP-34 | Demanda censurada: se modela lo dispensado |
| SUP-35 | Duplicado del 13-may-2026 y valores corruptos: corrección de datos, no imputación |
| SUP-36 | Imputación de faltantes: evaluada y **no adoptada** |
| SUP-37 | Ceros de M3 en agosto de 2026 leídos como reales |
| SUP-38 | Repetición acotada del laboratorio a los finalistas (28 modelo-serie, decisión D1) |
| SUP-39 | Modelos finales del laboratorio en el pipeline del entregable (`forecaster.modelo_alx`, receta congelada) |
| SUP-40 | Plantilla del Anexo D y tarifas del Anexo E originales en la corrida del entregable |
| SUP-41 | **Reservado:** recomendación de M5 v2 (factor de SUP-20 por fondo encogido 50 % con tope 1,5), no aplicada (§6.5) |
| SUP-42 | **Nuevo (v2).** `nivel_riesgo` de la hoja 02 medido antes de la acción (alto si el saldo sin la acción se agota o supera el cupo; medio bajo el 8 % o en recolecciones de M2; bajo si es preventiva u ociosa) |
| SUP-43 | **Nuevo (v2).** Monto mínimo de recolección: M3 no recoge efectivo ocioso cuyo monto no supera el costo de la visita; nunca omite las de exceso sobre el cupo (7 omitidas, 548.282 COP) |
| SUP-44 | **Nuevo (v2).** Cupo insuficiente: 8667 y 9311 (MF de sucursal, cupo 85.502.000) con todas sus filas en alto y la demanda no atendida declarada; una atención diaria hasta el cupo |
| SUP-45 | **Nuevo (v2).** Datos de referencia de los cajeros del último snapshot del maestro CP (8-sep-2026); las variables de pronóstico usan el snapshot ≤ origen (SUP-28) |
| SUP-46 | **Nuevo (v2).** Insumos del Anexo A no recibidos: `Historico BANREP.xlsx` e `Historico Traslados.xlsx`; se suplen con SUP-08 y SUP-13 |
| SUP-47 | **Nuevo (v2).** `nivel_riesgo` de la hoja 05 = riesgo residual después de actuar |
| SUP-48 | **Nuevo (v2).** La columna de cumplimiento que la plantilla de la hoja 02 no trae no se agrega; el cumplimiento va en `regla_aplicada` y la explicación |
| SUP-49 | **Nuevo (v2).** Definiciones de calendario de RN-04: festivos (`holidays` CO), quincena (15) y fin de mes, corridos al hábil anterior |
| SUP-50 | **Nuevo (v2).** RN-08 como pronóstico 0 de equipos silenciosos (12 de M1) y listado en `silenciosos` |
| SUP-51 | **Nuevo (v2).** Variables de eventos y externas propias (primas, temporada, Semana Santa, Feria de Cali, Carnaval de Pasto, festivos de Ecuador) |
| SUP-52 | **Nuevo (v2).** Traslado disponible en el fondo destino al día siguiente (nota del Anexo E), ordenado el día anterior al faltante, con las dos filas en la fecha de ejecución (RN-74) |
| SUP-53 | **Nuevo (v2).** Tarifa del traslado entre ciudades = la de la transportadora del fondo origen (545.413 COP; con la del destino, 938.560) |

Decisiones del usuario del 20-oct que fijaron varios SUP: principio rector "toda decisión defendible ante Bancolombia; ninguna puede exponer a un criterio de descarte; ante dos opciones válidas, la más conservadora y trazable, declarada y medida"; D1 repetición acotada a finalistas (SUP-38); D2 SUP-02 en el arnés y V4 "as of" antes de repetir el ML (SUP-27, SUP-28, SUP-30 a SUP-34); D3 solo corregir los disponibles de M6 (SUP-29), el SUP-09 nuevo para después; D4 registro de Santiago como base, sin renumerar, lo nuevo desde SUP-24. Directriz general: si una decisión técnica choca con el pliego, gana el pliego y se documenta.

Decisiones del 26-oct-2026: (1) el registro propio es la versión final de los supuestos y los documentos de Andrés (`revision-andres/`) no se usan; (2) la información que el banco no suministró se suple con supuestos documentados (indicación del banco); (3) D-1, escala de sucursal desde `Escalas` (SUP-22), y D-2, textos limpios de la hoja 03, confirmadas. Quedan para decisión del usuario, sin aplicar: la alternativa de SUP-44 (segunda atención consolidada en 8667/9311: 4 y 1 provisiones adicionales por 73.047.796 y 18.008.804 COP) y la de SUP-21 (INDIVIDUAL interurbano, +575.069 COP).

---

## 6. Experimentos y resultados, incluidos los no adoptados

Regla general: casi todo el material experimental **no está en el repo** (no hace falta para generar los pronósticos) y sigue en `ALX/` sin cambios. Lo que sí está en el repo de cada experimento se indica en cada apartado. Tabla de ubicación al final (§6.9).

### 6.1 Paridad con Santiago (base de todas las comparaciones)

- `ALX/datos_poc.py` (`matriz_arnes`) lee los datos de S3 a memoria y replica exactamente el cargador del arnés de Santiago: recalculando 4 pronosticadores deterministas, 650 celdas con referencia en sus registros coinciden (mismo n, |dif WAPE| máx 9,7e-16). Ej.: M1 `naive_7` en el chequeo, n = 5.518, WAPE 0,47253283.
- `gbm_cal` y `gbm_cal_l1` difieren de los registros de Santiago en M1 (hasta 0,018) porque esas corridas son anteriores al orden determinista de filas que hoy tiene `global_gbm.py`; por eso **toda comparación usa la referencia recalculada en ALX en los dos lados**.
- La receta del pipeline recalculada en ALX reproduce la hoja 03 del Excel de Santiago en los 7 datasets (`ALX/ml/resultados/hoja03_vs_alx.csv`).

### 6.2 EDA con Box-Jenkins: v2 vigente (24-oct) y notebook 02 superado (18-oct) — análisis, no modelo

**EDA vigente: `ALX/eda/03_eda_box_jenkins_v2.ipynb` (24-oct-2026; módulo `ALX/eda/eda_bj.py`; 290 celdas, 93 figuras, 0 errores; revisión APPROVED en la iteración 3).** Hace solo la fase de identificación de Box-Jenkins como análisis exploratorio, **sin estimar modelos** (0 SARIMAX/ARIMA/AIC en el cuaderno y el módulo). Cifras de esta subsección: §9 y §10 del cuaderno (marcadores `concl:M1.final` … `concl:M6.final` y `concl:9.3`).

- **Método.** Cada modelo se analiza en el índice donde está su volumen: M1 y M2 en días calendario (s = 7, m = 30), M3 y M4 en lun–sáb (s = 6, m = 26), M5 y M6 en lun–vie (s = 5, m = 22). Escala log1p justificada con λ de Guerrero, rango-media y ρ media–desviación. ADF + KPSS en una tabla de cinco pasos; **D antes que d** (D = 1 solo si F_s ≥ 0,64, picos en s, 2s y 3s con ρ(3s)/ρ(s) ≥ 0,8 y sin sobrediferenciación; si esos criterios discrepan, la estacionalidad es determinista y se describe con perfiles y eventos). Correlogramas clásicos `plot_acf`/`plot_pacf` de statsmodels con banda del 95 % y lectura en texto; Ljung-Box sobre la serie estacionarizada z (no sobre residuos de un modelo); F_t/F_s (STL/MSTL, con componente anual donde cabe) y periodograma; estudio de eventos de calendario contado en días hábiles u operativos con consistencia entre años (pagos, primas, Semana Santa, diciembre, Feria de Cali, Carnaval de Pasto, festivos de Ecuador); intermitencia ADI/CV² (Syntetos-Boylan); heterogeneidad por entidad; CCF, Granger con corrección de Holm e identidad de flujos M1–M5 → M6; varianza explicada en escala común (§9.1) frente a importancias guardadas de permutación y SHAP de `ALX/ml/resultados/` (§9.2, sin reentrenar). Los días dudosos (ceros de red de M3 y M6, caídas de reporte de M1/M2) se apartan del análisis; no es imputación y los modelos entrenan con los datos tal cual.
- **Hallazgos comunes.** La estacionalidad semanal es fuerte y **determinista**: **D = d = 0 en casi todos los agregados**; solo M2 `cash_in` y M3 (`entradas` y `salidas`) dan **D = 1, d = 0**. Por entidad domina (0, 0) (M1 96 %, M2 98–100 %, M5 100 %). En las 8 series el **Ljung-Box de z en 2s da p < 0,001**: tras quitar la semana queda memoria que los rezagos propios aprovechan. **Lo que explica la serie coincide con lo que aporta al pronóstico** (la estacionalidad semanal llega al modelo por `dia_de_semana` y el calendario por `festivos`/`dia_del_mes_y_pago`) en todas las series con ML **salvo M4**, donde la primera fuente es la **estacionalidad anual** (rezago 312), que el modelo solo recibe de forma indirecta.
- **Por modelo (agregado de la red):**

  | Serie | (D, d) | Correlograma | Fuerza | Eventos de calendario principales | Qué explica la serie (§9.1) | Qué aporta al pronóstico (cuota de permutación, §9.2) |
  |---|---|---|---|---|---|---|
  | M1 | (0, 0) | ρ(1) = 0,28, ρ(s) = 0,36 | F_s(7) = 0,65, F_s(30) = 0,50, F_t = 0,30 | fin de mes (pago) +80,7 %, día 1 +69,6 %, prima de diciembre +61,3 %, día siguiente al pago +50,9 % | semana 43 %, mes 23 %, tendencia 10 % | `dia_del_mes_y_pago` 30 %, `dia_de_semana` 27 %, `festivo_detalle` 11 % |
  | M2 `pagado` | (0, 0) | ρ(1) = 0,20, ρ(s) = 0,55 | F_s(7) = 0,72 | fin de mes +66,1 % (p = 0,062), prima +53,8 %, festivo −52,2 % | semana 57 %, mes 12 %, calendario 11 % | `dia_de_semana` 35 %, `dia_del_mes_y_pago` 20 %, `festivo_detalle` 16 % |
  | M2 `cash_in` | (1, 0) | tras (1 − B^s): ρ(1) = 0,13, ρ(s) = −0,37 | F_s(7) = 0,78 | Carnaval de Pasto −65,0 % en Pasto y −61,3 % en Ipiales, festivo −53,2 % | semana 72 %, calendario 10 %, serie hermana 5 % | `dia_de_semana` 51 %, `festivos` 20 %, `perfil_entidad` 13 % |
  | M3 `entradas` | (1, 0) | tras (1 − B^s): ρ(1) = 0,42, ρ(s) = −0,22 | F_s(6) = 0,95, F_t = 0,53 | Carnaval de Pasto −28,9 % en Ipiales, Feria de Cali +26,4 % | semana 88 % | `festivos` 42 %, `dia_de_semana` 42 %, `festivo_detalle` 14 % |
  | M3 `salidas` | (1, 0) | tras (1 − B^s): ρ(1) = 0,37, ρ(s) = −0,26; PACF corta en 2 | F_s(6) = 0,94, F_t = 0,51 | Feria de Cali +43,3 %, Carnaval de Pasto −32,5 % en Ipiales, prima +29,6 % | semana 85 % | `dia_de_semana` 48 %, `festivos` 34 %, `festivo_detalle` 10 % |
  | M4 | (0, 0) | ρ(1) = 0,32, ρ(s) = 0,39; PACF corta en 1 | F_s(6) = 0,55, F_s(312) = 0,57 | Carnaval de Pasto −69,6 % en Ipiales y −48,8 % en Pasto, fin de mes −39,7 %, día 1 −34,1 % | **anual 31 %**, semana 31 %, mes 9 % (no explicado 22 %) | `dia_de_semana` 61 %, `nivel_y_tendencia` 25 %, `dia_del_mes_y_pago` 14 % (**no coinciden**) |
  | M5 | (0, 0) | ρ(1) = 0,13, ρ(s) = 0,36 | F_s(5) = 0,59, F_s(260) = 0,61, F_t = 0,34 | post-festivo +154,7 %, primer día tras un bloque +147,7 %, día 2 +85,0 %, Feria de Cali +54,1 %, festivo de Ecuador en Ipiales −51,8 % | semana 32 %, anual 30 %, tendencia 10 % (no explicado 19 %) | `festivos` 55 %, `dia_de_semana` 15 %, `festivo_detalle` 12 % |
  | M6 | (0, 0) | ρ(1) = 0,73, ρ(s) = 0,52; memoria persistente (semivida 8) | F_t = 0,66, F_s(5) = 0,28, F_s(22) = 0,31 | Δsaldo en % del saldo medio: fin de año −14,3 %, día 1 −9,5 %, fin de mes −9,3 % | tendencia 52 %, mes 12 %, semana 10 % | no pronostica con ML |

- **Relaciones multivariadas.** M2: CCF `cash_in` → `pagado` con pico en k = 0 (ρ = 0,79); Granger con Holm significativo en los dos sentidos. M3: CCF `entradas` → `salidas` en k = 0 (ρ = 0,76); en `entradas` la decisión de D depende de los ceros dudosos de red (con ellos (0, 0) y ρ(s) = 0,27; sin ellos (1, 0) y ρ(s) = 0,89). M1: correlación red de la ciudad ↔ cajero 0,52 en log1p. M4 y M5: casi no hay co-movimiento entre fondos (Spearman mediano 0,06 y 0,13). **M6: la identidad de flujos casi no explica el Δsaldo diario** (β entre 0,007 y 0,218 y **R² ≤ 0,013** en los 5 fondos que reporta la §10; Granger flujo → Δsaldo con p de Holm < 0,05 solo en CALI/TDV003).
- **Salvedad de las importancias** (§9.2): salen de los CSV de la fase 2 (escenario S0), no de S1; en M4 se explica un proxy (`ml_lgbm_v1_l1_opt_m4`) que no es miembro del champion `combo_perfil_gbml1`.
- **Qué supera al notebook 02** (§11 del cuaderno): correlogramas clásicos en vez de mapas de calor por entidad; índice propio por modelo en vez de calendario con s = 7 para todos; D antes que d con ADF + KPSS en vez de una etiqueta; transformación justificada por serie; ceros dudosos apartados con sensibilidad; estudio de eventos en días hábiles en vez de regresión en días calendario; periodograma, intermitencia por clase y análisis multivariado, que el 02 no tenía; conclusiones por modelo con cifras.

**Notebook 02 (18-oct, superado por el 03).** Las cifras siguientes son **del notebook 02** y se conservan como historia; no se comparan una a una con las del 03, que usa otro grano (agregado de la red frente a cada serie) y otro método de calendario. Para cualquier pregunta sobre los datos, usa el 03.

- 682 series al mismo grano del pronóstico (no agregado, por decisión del usuario), con datos corregidos y el Anexo C como NaN. Pruebas: intermitencia ADI-CV², atípicos por STL robusto, λ de Guerrero, ADF y KPSS, `ndiffs`/`nsdiffs`, ACF/PACF, fuerza de tendencia y estacionalidad (STL/MSTL, 7 y 30 días), Ljung-Box, efectos de calendario por OLS con errores HAC y órdenes SARIMA candidatos. 242 series con tramo contiguo, 412 con un tramo rellenado solo para la prueba, 28 sin base.
- Hallazgos que guiaron el modelado: en cajeros manda el **calendario de pagos**, no la semana (M1: +51 % el día de pago, significativo en el 91 % de los cajeros; +39 % el día siguiente; +21 % los días 1–2; −45 % en festivos; estacionalidad semanal débil, F_s7 mediana 0,37); sucursales con estacionalidad semanal fuerte (0,81–0,82) e intermitencia por calendario; M4 errático con la peor cobertura (79 %); M5 errático (CV² 3,94) con cambio de régimen en la mitad de los fondos; M6 casi un paseo aleatorio con tendencia. Ljung-Box rechaza ruido blanco en el rezago 7 en el 78–100 % de las series.
- Dónde está el 03 (vigente): `ALX/eda/03_eda_box_jenkins_v2.ipynb` (10,1 MB, ejecutado) y su módulo `ALX/eda/eda_bj.py`; revisión y verificación en la raíz del Drive, `Mi unidad/PoC-Bancolombia/.agents/tasks/eda-box-jenkins-v2/` (`review-eda.md`, `verificacion-eda.md`).
- Dónde está el 02 (superado): `ALX/eda/` (`box_jenkins.py`, `calcular_indicadores.py`, `graficos_bj.py`, `construir_notebook_02.py`, notebook `02_eda_series_box_jenkins.ipynb` con 17 secciones y 67 figuras, `resultados/` con `indicadores_series.{parquet,csv}` de 682 × 114, `acf_pacf.parquet`, `efectos_calendario.parquet`, `cobertura_grano.csv`, `efecto_correcciones.csv`, `rangos_series.csv`, `ceros_recientes.csv`). El EDA agregado inicial del 8-oct es `ALX/01_series_de_tiempo.ipynb` (con `ALX/graficos_poc.py`). **Nada de esto está en el repo** (el usuario excluyó los notebooks de análisis).

### 6.3 SARIMA de referencia (18-oct) — descartado

- SARIMAX de statsmodels sobre log1p, s = 7, ventana de 730 días, d y D del EDA en cada corte, 15 combinaciones por AIC; variante `sarimax_cal` con calendario; respaldo `media_dow_4s`. Mismo arnés (chequeo, bloqueados y 8 orígenes de selección); 133,5 min; 196 runs en MLflow.
- WAPE del chequeo 17–31 ago:

  | Dataset | `media_dow_4s` | `sarima_ref` | `sarimax_cal` | Santiago | Andrés |
  |---|---:|---:|---:|---:|---:|
  | M1 | 0,3340 | 0,3376 | 0,3826 | **0,2551** | 0,3188 |
  | M2 `pagado` | 0,4183 | 0,4457 | 0,4911 | **0,3652** | 0,3954 |
  | M2 `cash_in` | 0,4457 | 0,4702 | 0,4803 | **0,3868** | — |
  | M3 `entradas` | 0,5005 | 0,7686 | 0,5798 | **0,4219** | 0,5253 |
  | M3 `salidas` | 0,5204 | 0,8064 | 0,6638 | **0,4577** | 0,5552 |
  | M4 | 0,4377 | 0,3926 | 0,4360 | **0,3196** | 0,4679 |
  | M5 | 0,6276 | 0,6681 | 0,5742 | **0,5668** | 0,7057 |

- Santiago gana en todos. Por qué pierde: SARIMA solo ve los rezagos de cada serie; el error está en el calendario de pagos y en la información compartida entre entidades, que solo aprende un modelo global. Anomalía sin investigar: `sarimax_cal` sale peor que `sarima_ref` en M1, M2 y M4. **Decisión del usuario (18-oct): "ya sabemos que no es un candidato"**; SARIMA queda solo como referencia documentada.
- Dónde está: `ALX/sarima/` (`paridad_arnes.py`, `sarima_referencia.py`, `correr_sarima.py`, `comparar.py`, notebook `03_sarima_referencia.ipynb`, `resultados/` con `comparacion_chequeo.csv`, `comparacion_arnes.csv`, `corridas_sarima.jsonl` de 3.956 filas y diagnósticos). Nada en el repo.

### 6.4 Fase 2: mejora de los modelos de Santiago con ML (18-oct) — adoptado en 6 de 7 series

- **Diseño:** motor ML global único (`pipeline/src/daas/forecasting/global_ml.py`; con V0 + motor `hgb` reproduce `gbm_cal` a 1e-9) con LightGBM 4.7.0, XGBoost 3.2.0, CatBoost 1.2.10, RandomForest y ExtraTrees (scikit-learn 1.9.1) y HGB; conjuntos V0–V4; pérdidas L2, L1 y Tweedie; Optuna (TPE, semilla 0, 20 ensayos; 10 en M1); ensambles (media de los 3 mejores, referencia + mejor ML, ponderado fuera de muestra, stacking, ponderado con corrección de sesgo en M4/M5). Etapas E1–E6. **146 candidatos**, 37.829 filas en `ALX/ml/resultados/corridas_ml.jsonl`, unas 2 h 40 min de cómputo. Sin fuga: estrategia directa, toda variable con datos ≤ origen, guarda `test_no_future_leak`, pesos de ensamble solo con orígenes cerrados, bloqueados abiertos una sola vez con finalistas congelados.
- **Hallazgos:** la mejora viene de las **variables y la pérdida, no del motor** (con V0 solo 3 de 35 combinaciones motor × dataset superan a la referencia; V1 baja el WAPE en las 7 series); L1 gana en 6 de 7 (en M1 Tweedie), porque el WAPE se minimiza con la mediana; LightGBM es el mejor motor individual en 6 de 7 (en M2 `pagado` CatBoost por muy poco); Optuna aporta a lo sumo 0,14 pp y en 5 de 7 queda peor; los modelos de Santiago reciben entre 0 % y 40 % del peso en los ensambles y Prophet con calendario conserva 11–14 % en M1 y M2; en importancias (permutación y SHAP), el día del mes y el pago mandan en M1, el día de la semana en M2, M3 `salidas` y M4, los festivos en M3 `entradas` y M5.
- **Correcciones de la revisión (3 vueltas antes de aprobar):** el desempate "por pares en orígenes comunes" se escribió después de ver la confirmación, así que dejó de decidir y quedó como sensibilidad (cambió los champions de M2 `cash_in` y M3 `entradas`); k = 2 para ensambles con un miembro afinado (el champion de M1 pasó de `ml_ens_media_top3_m1` a `ml_lgbm_v4_tw`); el modelo registrado debe reproducir lo evaluado, así que el contexto V4 viaja dentro del modelo de MLflow (sin contexto el champion de M2 `pagado` no cumpliría R3: 0,3842 vs 0,3827). En M3 `entradas` el ponderado se adopta por la letra de la regla aunque `ml_lgbm_v1_l1` es mejor en los mismos 10 orígenes (0,2181 vs 0,2206).
- **En M4 no se adoptó nada:** el mejor (`ml_ens_campeon_ml_m4`, WAPE 0,3278, cumple k = 2) no fue finalista; queda como revisión pendiente.
- **Qué hay en el repo:** las 80 recetas `lab/conf/experimentos/*.yml` (19 de Santiago + 61 `ml_*` de ALX; el registro las carga todas aunque solo se usen las de los champions), `ml/pronosticar.py`, `global_ml.py` y `calendario_co.py`. **En `ALX/ml/`** (fuera del repo): `adopcion.py` (y `huella_regla()`), `conf/adopcion_ml.yml`, `conf/ensambles/`, `correr_ml.py`, `correr_ensambles.py`, `ensambles.py`, `etapas.py`, `optuna_ml.py`, `decision.py`, `bandas_ml.py`, `explicar_ml.py`, `registrar_mlflow.py`, `verificar_registro.py`, `medir_sin_contexto.py`, el notebook `04_mejora_modelos_ml.ipynb` y `resultados/` (`adopcion.csv` con los 146 candidatos y su decisión, `comparacion_*.csv`, `bandas_ml.csv`, `cribado.csv`, `pesos_ensambles.csv`, `optuna_<ds>.csv`, `importancias_permutacion.csv`, `shap_resumen.csv`, `reproduccion_santiago.csv`, `verificacion_registro.csv`, `figuras/`).

### 6.5 M5: sesgo estructural, diagnóstico y M5 v2 (22-oct) — no adoptado; EDA de M5 (25-oct)

- **Problema:** el champion de M5 subestima en 17 de 19 orígenes (Bias medio −20,9 % en selección, −24,7 % en bloqueados, −43,0 % en el chequeo; Santiago tiene el mismo patrón, −43,2 % en el chequeo). Empeora en 2026.
- **Diagnóstico** (`ALX/plan_mejora_m5.md`): el modelo acierta la mediana (P(y > ŷ) = 0,494) pero la suma real es 1,32 veces la pronosticada: cola derecha enorme. El 10 % de los días con mayor depósito explica el 143 % del sesgo; unos pocos "megapuntos" esporádicos (punto 220 de `CALI|TRANSPORTADORA_001`, mediana de 87 mil M por depósito; 276 y 27 de Pasto; 69 de Ipiales, 68,8 % del volumen histórico de ese fondo) explican cerca de la mitad. En el chequeo, un solo día (27-ago, 78,6 mil M del punto 220) explica el 35 %. Ninguna transformación del pronóstico mejora a la vez WAPE y Bias (frontera: f = 1,155 lleva el Bias a −8,7 % pero sube el WAPE 2,49 ± 0,97 pp): **elegir es una decisión de política, no de modelo**. La regla v1 rechaza por construcción toda corrección de sesgo. Plan priorizado P1–P9 (regla v2, corrección de sesgo móvil, variables de estado de los puntos, recencia, cuantiles, etc.), con preguntas al banco sobre esos clientes.
- **M5 v2** (`ALX/m5_mejora/`, regla v2 `conf/adopcion_m5_v2.yml` huella `688ae78b095e`, 17 orígenes frescos de días 15): **ningún candidato cumple**; el mejor (`cs50`, factor global encogido 50 %) baja el |Bias| de 20,9 % a 12,2 % pero cuesta +2,01 ± 1,09 pp de WAPE en selección. Recomendación del informe: dejar M5 sin cambios y ajustar solo SUP-20 a un factor por fondo encogido 50 % con tope 1,5 (sería SUP-41); para la corrida de septiembre da 1,5 en los 6 fondos, así que el Excel no cambiaría. **No se aplicó: la decisión es del usuario.** El Excel siguió en `52e7547f…`, y la v2 del 26-oct tampoco cambia M5 (SUP-41 queda reservado).
- **EDA dedicado de M5** (`ALX/eda/04_eda_m5.ipynb`, 25-oct-2026; módulo `ALX/eda/eda_m5.py`; 71 celdas, 46 figuras, 0 errores; revisión APPROVED en la iteración 2; Box-Jenkins sin estimar modelos). Resumen con cifras en `Mi unidad/PoC-Bancolombia/.agents/tasks/eda-m5/final_report.md`. Confirma y cuantifica el diagnóstico anterior:
  - **Concentración:** 547 pares fondo-punto; **Gini 0,90**; el **top 1 % de pares lleva el 47,3 % del volumen** (top 10 %: 85,6 %). La variabilidad del log del fondo la explica el **tamaño del depósito (84,8 %)**, casi nada la **frecuencia (3,3 %)**. Por punto la demanda es intermitente (ADI mediano 4,55).
  - **Colas pesadas:** a nivel par-día **Hill α̂ ≈ 1** (1,01: media al límite, varianza infinita); a nivel fondo-día α̂ ≈ 2,62. 12 megapuntos esporádicos llevan el 11,4 % del volumen y 2 grandes recurrentes el 19,1 %; ninguno tiene un ritmo operable.
  - **Identificación:** ADF y KPSS se contradicen; D = 0, d = 0. ρ(1) = 0,13, ρ(s = 5) = 0,36; F_s(5) = 0,59, F_t = 0,34. Ipiales (66 cambios de nivel) y Pasto (32) no son estacionarias en nivel: su persistencia viene de esos cambios, no de una estructura ARMA.
  - **Calendario:** post-festivo **+155 %** [IC +93; +226], debido al tamaño del depósito (+144 %) y no a la frecuencia (+4,7 %); se debilita (2024 +174 %, 2025 +111 %, 2026 +72 %).
  - **Cambio en 2026:** el Bias medio de selección pasa de **−14,4 % (2025) a −31,8 % (2026)**; el nivel de la red baja **−0,31 en log** (frecuencia −0,08, tamaño −0,24). En Pasto el Bias propio pasa de +2 % a −80 %. CALI/TDV004 existe desde mayo de 2026, pesa 0,42 % del volumen y tiene WAPE 156,8 %.
  - **Causas del sesgo (chequeo, igual a la hoja 03: WAPE 51,60 %, Bias −42,97 %):** los megapuntos esporádicos explican el **49,2 %** del sesgo (sin ellos el Bias queda en −13,5 %) y **CALI/TDV001 concentra el 63,6 %**. Cascada del Bias: **−42,97 %** completo → −33,19 % sin el 27-ago → −29,10 % sin además el 18-ago → **−8,57 % en días normales**. El pronóstico no tiene ninguna variable sobre el estado de los puntos (importancias: festivos 55 %, día de semana 15 %, `festivo_detalle` 12 %).
  - **Recomendaciones (sin implementar):** P3 variables de estado de los puntos (231 pares callados); P4 nivel reciente robusto; P5 pérdida cuantil o expectil con bandas asimétricas; P6 megapuntos como componente aparte, sobre todo como insumo de M6. Además, SUP-17 (perfil propio de CALI/TDV004 encogido al de la ciudad) y SUP-20 con factor por fondo encogido, porque el sesgo está en TDV001. El EDA respalda dejar M5 en la mediana y corregir en M6; lo que falta es información de los puntos.
- Nada de esto está en el repo.

### 6.6 Imputación de faltantes (19–21-oct) — evaluada y no adoptada

El usuario pidió explícitamente **no perder este material**: no mejoró los modelos, pero sirve para la sustentación (el pliego evalúa el "tratamiento de datos faltantes" y descarta a quien no lo documente) y para mejoras.

- **Inventario** (`ALX/imputacion/inventario.py`): cada entidad-día de las 682 series recibe un código con datos ≤ 31-ago. Seis tipos: (a) faltante de la fuente (Anexo C, 4 días de sucursales, hueco de disponibles de 2024), (b) estructural o cero real, (c) entidad que no reporta, (d) corruptos, (e) duplicados, (f) ceros dudosos de M3. **25.203 entidad-días imputables** (del Anexo C, 13.642 de 14.568). Silencios largos, finales, desinstalados y huecos de red de más de 12 días no se imputan.
- **Métodos comparados** (`ALX/imputacion/metodos.py`): 1) lineal (piso), 2) perfil propio (mediana en días comparables, escalada al nivel reciente), 3) STL, 4) Kalman, 5) Kalman con calendario, 6) LightGBM global. **[Contradicción resuelta]** El plan hablaba de "5 métodos" porque Kalman y Kalman con calendario son la misma familia; en el código y las tablas son 6.
- **Simulación:** se ocultan días que sí tienen dato (sueltos, rachas de 2–5 días y bloques de 12 días, de red o de entidad), cada método corta la historia después del hueco a una distancia aleatoria (sin fuga) y se mide el WAPE y el Bias de reconstrucción. Regla de elección E1–E4 declarada antes de medir (`ALX/imputacion/conf/regla_imputacion.yml`, 20-oct 17:44, huella `3361fa6b1e16`; elección congelada `cfe36eddd5ba`). Resultado: el lineal se queda en 18 de 40 celdas (todas las de M6); en el bloque de 12 días (caso Anexo C) gana el perfil propio en M1 y M2; en silencios de un día gana LightGBM global (la red sí opera ese día).
- **Reglas del pliego aplicadas:** se imputa solo para entrenar, dentro del pronosticador y con datos ≤ origen; **nunca para evaluar** (el arnés aborta si el real viene marcado; S1 y S2 se evalúan con el mismo `n` en 5.904 celdas); el Anexo C nunca queda en 0; todo valor imputado lleva marca (`imputado`, `origen_dato = ESTIMADO`, `metodo_imputacion`).
- **Repetición del ML** con escenarios declarados antes de correr (`ALX/imputacion/conf/decision_ml.yml`, huella `0ee298cb749e`): S0 fase 2; S0' = S0 re-puntuado con SUP-02; **S1** = correcciones + V4 "as of", sin imputar (vigente); S2 = S1 + imputación; S2b = sensibilidad de ceros dudosos. 28 modelo-serie (champion, challenger, finalistas y referencia) en 19 orígenes (SUP-38). Guardas extra para variantes con imputación: G1 mejora media ≥ 0, G2 ninguna celda peor > 2 EE, G3 confirmación no peor.
- **Resultado:** **la imputación no se adopta en ningún champion**: efecto S2 − S1 entre **−0,27 y +1,01 pp** de WAPE, dentro de 2 EE en todos (T0 = T1 = T2 en `ALX/imputacion/resultados/ml/decision_final.csv`). **[Contradicción resuelta]** La bitácora del 20-oct decía "entre −0,62 y +0,27 pp"; la cifra corregida del 21-oct es −0,27 a +1,01. Los challengers de 5 series son variantes con imputación (informativos; no van al Excel).
- **En el repo:** solo `imputacion/__init__.py`, `imputacion/contexto_asof.py` (contexto V4 "as of", que no imputa) e `imputacion/datos.py` (los importa la corrida). El interruptor `imputacion: false` de `pipeline/conf/alx.yml` no tiene código detrás: encenderlo **aborta la corrida** (`laboratorio.py`). **En `ALX/imputacion/`** (29 MB, fuera del repo): `inventario.py`, `metodos.py`, `simulacion.py`, `eleccion.py`, `aplicar.py`, `repeticion_ml.py`, `decidir_ml.py`, `correcciones_arnes.py`, `m6_efecto.py`, `sup02.py`, `origen_dato_s3.py`, `mlflow_imputacion.py`, `conf/` (reglas y elección congelada), el notebook ejecutado `05_imputacion_faltantes.ipynb` y `resultados/` (`inventario_resumen.md`, `comparacion_metodos.md`, `eleccion_por_celda.csv`, `ml_repeticion.md`, `correcciones_arnes.md`, `correcciones_m6_origen.md`, `resultados/ml/decision_final.csv`, `resultados/ml/bandas_oficial.csv`, `resultados/ml/verificacion_registro.csv`, `entrega_cumplimiento_pliego.md`, `entrega_comparacion_santiago.md`/`.csv`, `entrega_verificacion_i_chequeo.csv`, `entrega_verificacion_ii_hoja03.csv`, `m6/`, `arnes/`, `inventario/`, `metodos/`).

### 6.7 Correcciones adoptadas, cada una medida por separado

| Corrección | Efecto medido | Interruptor (`pipeline/conf/alx.yml`) |
|---|---|---|
| SUP-02 / SUP-27 (medición) | M3: salen 3 sucursales en `entradas` y 4 en `salidas` en el chequeo; el WAPE baja 3,1–4,9 pp sin cambiar pronósticos; en selección no cambia; ninguna decisión de adopción distinta | `sup02_denominador_cero` |
| SUP-28 (V4 "as of") | M1 −0,05 ± 0,09 pp, M2 `pagado` +0,07 ± 0,06 pp en selección: el maestro vigente no inflaba las cifras; guarda de fuga sin diferencias | `contexto_asof` |
| SUP-35 (dedup 13-may, corruptos a NaN) | M3 `entradas` −0,54 ± 0,52 pp y `salidas` −0,51 ± 0,37 pp en selección | `correcciones_datos` |
| SUP-29 (disponibles de M6) | 10 de 36 estados de riesgo cambian; costo de traslados 253.905 → 0 | `correccion_m6` (+ `correccion_disponibles.aplicar` en `model_u6.yml`) |
| SUP-24 a SUP-26 (`origen_dato`) | No cambia cifras; 0 filas REAL | `origen_dato` |
| Champions ML (SUP-39) | §4.4 | `campeones_ml` |
| Textos de la hoja 04 (SUP-24 a SUP-40) | — | `supuestos_alx` |
| **v2:** cajeros de sucursal en M6 (SUP-12) | Ingresos de la hoja 05 +42,21 mil M y salidas +109,11 mil M COP; ventas 169 → 148 | `m6_cajeros_sucursal` |
| **v2:** tarifa MF interurbano (SUP-21) | M2 +3.936.535 COP (61 acciones de 5 MF) | `m2_tarifa_interurbana` |
| **v2:** escala desde `Escalas` (SUP-22) | M3 −6.757.937 COP (sucursal 70) | `m3_escala_anexo_a` |
| **v2:** riesgo antes de la acción y cupo insuficiente (SUP-42, SUP-44) | Hoja 02: 1.098 alto, 1.216 medio, 271 bajo (v1 todo bajo) | `nivel_riesgo_previo` |
| **v2:** monto mínimo de recolección (SUP-43) | M3: 432 → 425 recolecciones; costo de M3 147,65 → 140,26 M COP (con SUP-22) | `monto_minimo_recoleccion` |
| **v2:** operaciones de RN-84 (SUP-14) | Solo textos: 0 cambios de denominación o intercambio en v1 y v2 | `m6_operaciones_rn84` |
| **v2:** traslado al día siguiente (SUP-52) | Traslados 105 → 99 frente a la v2 preliminar; 4 retiros BanRep; costo de M6 545.413 → 1.441.530 COP | `m6_traslado_t1` |
| **v2:** tarifa de traslado declarada (SUP-53) | Solo textos y la métrica `costo_traslado_tarifa_destino` (938.560 COP) | `m6_tarifa_traslado_declarada` |
| **v2:** hoja 04 y textos de la hoja 03 | 80 celdas de la hoja 04 reescritas; 49 `comentarios` y 105 `metodologia_validacion` de la hoja 03; ningún valor predictivo cambia | `hoja04_v2`, `hoja03_textos_v2` |

### 6.8 MLflow y cadena de verificación hasta el Excel

- Store local en el equipo original (no en el repo): `sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db` y artefactos en `/Users/alexanderpelaez/.mlflow/poc-daas/artifacts`. Experimentos: 1 `poc-daas/lab-santiago-historico` (2.574 runs importados de los registros de Santiago), 2 `poc-daas/demo-autolog`, 3 `poc-daas/sarima-referencia` (196), 4–10 `poc-daas/ml/<serie>` (fase 2, 363–515 runs por serie, tag `adopcion_huella = 623420f48f04`), 11–17 `poc-daas/imputacion/<serie>`, más `poc-daas/ml/m5-v2`.
- Model Registry `poc-daas-ml-<serie>` con alias `@champion` (v5, salvo m3_salidas y m5 en v4) y `@challenger`; clase `ml.pronosticar.PronosticadorEscenario`. Las versiones de la fase 2 quedan con tag `estado = obsoleta`. También 7 SARIMA `poc-daas-sarima-<serie>@referencia`.
- **Cadena verificada:** (i) registro = arnés S1 en 28/28 comparaciones (≤ 1e-6); (ii) pipeline = arnés S1 en el chequeo (diferencia relativa 0 en seis datasets y 4·10⁻¹⁸ en M3 `entradas`); (iii) pipeline con todos los interruptores apagados = Excel de Santiago (105/105 filas de la hoja 03; hojas 01, 02, 04, 05 y 06 iguales celda a celda). Toda diferencia con Santiago la causa un interruptor de ALX.
- **El pipeline de este repo no usa MLflow** para pronosticar: corre las recetas congeladas (SUP-39). `lab/tracking/mlflow_tracking.py` está en el repo solo porque `ml/pronosticar.py` importa de él `PronosticadorPanel` y `a_matriz` (requiere el paquete `mlflow`, pero no levanta servidor ni escribe store).
- Pruebas: no están en el repo (decisión del usuario). En `ALX/`: `ALX/pipeline/tests` 325 en verde, `ALX/tests_alx` + `ALX/lab/tests` 260 (21-oct). Con la v2 (26-oct): `ALX/pipeline/tests` 326 y `ALX/tests_alx` + `ALX/lab/tests` 301, todas en verde (incluye `ALX/tests_alx/test_correcciones_v2.py`, que valida los interruptores y el registro de supuestos). **[Contradicción resuelta]** Hubo conteos inconsistentes del pipeline (339 / 323 / 344); el correcto al 21-oct es 325 (344 fue una invocación conjunta con `tests_alx`; 339 no tiene evidencia).

### 6.9 Dónde está cada material (fuera del repo, en `ALX/`)

| Material | Ruta en el Drive | Estado |
|---|---|---|
| EDA agregado (8-oct) | `ALX/01_series_de_tiempo.ipynb`, `ALX/graficos_poc.py` | Análisis |
| EDA Box-Jenkins v2 de M1–M6 (24-oct): identificación sin estimar modelos, conclusiones por modelo (§10) y qué variables importan (§9) | `ALX/eda/03_eda_box_jenkins_v2.ipynb`, `ALX/eda/eda_bj.py` | Análisis, **vigente** (§6.2) |
| EDA dedicado de M5 (25-oct): concentración, colas, megapuntos, cambio de 2026 y descomposición del sesgo | `ALX/eda/04_eda_m5.ipynb`, `ALX/eda/eda_m5.py`; resumen en `Mi unidad/PoC-Bancolombia/.agents/tasks/eda-m5/final_report.md` | Análisis (§6.5) |
| EDA por serie (18-oct) | `ALX/eda/02_eda_series_box_jenkins.ipynb` y sus módulos (`box_jenkins.py`, `calcular_indicadores.py`, `graficos_bj.py`, `construir_notebook_02.py`, `resultados/`) | Análisis, **superado por el 03** |
| SARIMA | `ALX/sarima/` | Descartado |
| Fase 2 ML (entrenamiento, adopción, MLflow) | `ALX/ml/` | Adoptado (en el repo solo `ml/pronosticar.py` y `ml/__init__.py`) |
| Imputación | `ALX/imputacion/` | No adoptada (en el repo solo `contexto_asof.py`, `datos.py`, `__init__.py`) |
| M5: diagnóstico y v2 | `ALX/plan_mejora_m5.md`, `ALX/m5_mejora/` | No adoptado |
| Laboratorio de Santiago (arnés, conformal, simuladores, explicabilidad, handoff, pruebas, conf) | `ALX/lab/` | En el repo solo `lab/forecasting/`, `lab/tracking/mlflow_tracking.py`, `lab/conf/experimentos/`, `lab/conf/bandas.yml` |
| Registros del laboratorio de Santiago | `ALX/resultados/*.jsonl` | Histórico |
| Supuestos completos | **En el repo** desde la v2: `pipeline/docs/supuestos.md` (copia idéntica de `ALX/pipeline/docs/supuestos.md`). Guía de lectura `ALX/guia_supuestos.md` (pre-v2) | Vigente, versión final |
| Supuestos de Andrés | `Mi unidad/PoC-Bancolombia/revision-andres/`, `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf` | **No se usan** (decisión del 26-oct) |
| Variables por modelo | `ALX/variables_por_modelo.md` | Consulta (champions vigentes, sin cambios en v2) |
| Auditoría del pliego (26-oct) | `Mi unidad/PoC-Bancolombia/.agents/tasks/auditoria-pliego/auditoria.md` | Origen de las correcciones v2 |
| Correcciones v2: plan, verificación, revisión y evidencia | `Mi unidad/PoC-Bancolombia/.agents/tasks/correcciones-v2/`; corridas A2/B2 y scripts `verificar_v2.py`, `verificar_t1.py`, `comparar_v2.py` en `~/.cache/poc-daas/corrida_entrega_v2/` | Evidencia |
| Respaldo de la v1 | `ALX/entrega/historico/v1_2026-10-21/` (y commit `955115d` de este repo) | Histórico |
| Contexto de la v2 para Andrés | `ALX/entrega/CONTEXTO_v2_para_Andres.md` | Comunicación interna; no entra al repo |
| Anexos A, B y C originales | `~/Desktop/datos-anexo-poc-bancolombia/` (equipo original) | Recibidos; la corrida no los lee |
| Resto del pipeline (pruebas, `corrida_local.sh` de Santiago, `conf/aws.yml`, `conf/contracts/`, lock antiguo, `recommender.py`, `schemas.py`) | `ALX/pipeline/` | No usado por la corrida |
| Publicación S3 (README, inventario del bucket, pruebas, revisiones r1/r2 y VersionId) | `ALX/publicacion_s3/` | En el repo solo `publicar.py` |
| HUs y handoff del arquitecto | `ALX/consumo-pronosticos/` | En el repo solo los 4 OpenAPI |
| Documentos | `ALX/analisis_repo_santiago.md` (documento técnico base), `ALX/resumen_avances_v1.md` (18-oct), `ALX/resumen_avances_v2.md` (22-oct, el más completo), `ALX/resumen_trabajo_y_consumo.md`, `ALX/guia_datos_bucket.md`, `ALX/preguntas_arquitecto.md`, `ALX/estructura_pronosticos_s3.md`, `ALX/docs/metodologia-valor.md` (reglas anti-fuga de Santiago), `ALX/README.md` (README de Santiago, **no describe este repo**) | Soporte |
| Excel de Santiago | `ALX/entrega/referencia_santiago/POC_Efectivo_PRAGMA.xlsx` | Referencia |
| Pruebas de ALX | `ALX/tests_alx/` (17 archivos) | — |
| Landing web de Santiago | `ALX/landing/` | No usada |
| Planes, verificaciones y revisiones de los workflows de agentes | `ALX/.agents/tasks/` (p. ej. `ALX/.agents/tasks/imputacion/verificacion-entrega.md` documenta la corrida del entregable) | Evidencia |
| Corrida oficial del entregable (raíz de datos y salidas) | `~/.cache/poc-daas/corrida_entrega/` (equipo original) | Evidencia |

---

## 7. Publicación en S3 (`v2` vigente, `v0_provisional` = v1)

### 7.1 Qué hay publicado

Dos prefijos en el bucket destino (perfil `alx-mx`), uno por entrega, y un puntero (`Mi unidad/PoC-Bancolombia/.agents/tasks/publicacion-s3-v2/reporte.md`; `ALX/publicacion_s3/README.md`; `ALX/estructura_pronosticos_s3.md`):

| Prefijo / clave | Entrega | Estado |
|---|---|---|
| `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/` | v2 (Excel `167a52e4…`) | **Vigente.** Revisión 1, publicada el 26-oct-2026 19:37 (hora Colombia): 249 objetos, 10.401.803 B; `manifest.json` sha256 `967eac4b8f99b9cf406494c5b09d522a1e5acdf707f4c326a6300b6327a12bf1` |
| `s3://poc-daas-bancolombia-777937796305/output/pronosticos/version_vigente.json` | — | Puntero (1.210 B, VersionId `5YGrpL.w3gjBS8xPLTBDWnUbaij4NqqD`): `version_vigente = v2`, prefijo, manifest y su sha256, `n_objetos` 249, sha256 y copia del Excel, y `version_anterior` (`v0_provisional`, entrega v1, Excel `52e7547f…`). Los consumidores deben leer este puntero y luego el `manifest.json` del prefijo |
| `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/` | v1 (Excel `52e7547f…`) | Anterior, conservada sin cambios: revisión 2 del 22-oct (248 objetos del manifest) más `anexo_d/POC_Efectivo_PRAGMA_v1.xlsx` subido aparte el 24-oct = 249 objetos; mismos ETag antes y después de publicar la v2 |

Los dos prefijos tienen la misma estructura y las mismas 249 claves relativas salvo el Excel de `anexo_d/` (`_v1` frente a `_v2`). En la v2 el Excel sí está en el manifest (248 archivos listados); en `v0_provisional` no (247).

**Cómo se genera.** `publicacion_s3/publicar.py` está parametrizado por versión (`--version` o `PUBLICAR_VERSION`; por defecto `v2`):
- `generar <salida> --version v2`: fuente `entrega/output_api` + Excel `entrega/POC_Efectivo_PRAGMA.xlsx` (exige el sha256 completo `167a52e4…`); insumos (`interim/`, `processed/`) de la corrida local B2 que generó la v2 (`~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`, `DAAS_CONF=B2_v2/conf`, `DAAS_SCHEME=local`; **no lee S3**); copia el Excel a `anexo_d/POC_Efectivo_PRAGMA_v2.xlsx`; el manifest guarda `insumos_locales` y `conf` con sus sha256.
- `generar <salida> --version v0_provisional`: reproduce la publicación de la v1 (247/247 archivos con el mismo sha256) desde el respaldo `entrega/historico/v1_2026-10-21/`, insumos de S3 y el `alx.yml` v1 (`~/.cache/poc-daas/corrida_entrega_v2/A2_v1/conf`). Esas rutas **no están en el repo**.
- `verificar <descarga>`: compara bytes y sha256 contra el manifest.
- `subir <salida> [--dry-run]` (boto3): solo escribe claves bajo `output/pronosticos/v2/` y la clave `output/pronosticos/version_vigente.json`; exige que ambos destinos estén vacíos (sin objetos, versiones ni delete markers), que la salida coincida con su manifest y que sea de la versión; sube con `ChecksumSHA256`; nunca borra; se niega con `--version v0_provisional`. Como la v2 ya está publicada, hoy se detiene sin escribir.
- La simulación M1–M3 recalculada incluye el monto mínimo de recolección de M3 (SUP-43) cuando el interruptor está encendido.

Verificación de la publicación v2 (reporte): 249/249 objetos descargados con el sha256 esperado (también el `ChecksumSHA256` de S3); `fuente.archivos` = sha256 de los 6 parquet de `entrega/output_api`; Excel de `anexo_d/` = `167a52e4…`; la simulación recalculada reproduce las 2.523 recomendaciones y las 2.297 alertas de M1–M3; métricas = hoja 03 (35/35 ciudad × bloque y 21/21 globales); 1.176 instancias OpenAPI con 0 errores de esquema. Desde la copia limpia de este repo, `generar --version v2` reproduce 248/248 archivos con el sha256 publicado (README §9.3).

**Revisión 2 de `v0_provisional` (v1, 22-oct), como referencia histórica.** La generó la versión anterior de `publicar.py` a partir de `entrega/output_api/` y del Excel v1; abortaba si el sha256 del Excel no empezaba por `52e7547fce59105a`, si la simulación recalculada no reproducía recomendaciones y alertas o si el disponible no coincidía con el saldo inicial de M6. Leía a memoria del bucket destino `interim/cp_historico`, `interim/oficinas`, `interim/cp_desinstalados`, `processed/m1_atm_dispensador`, `processed/m2_atm_multifuncional`, `processed/m3_sucursales`, `processed/m6_fondos` y `processed/_dim/dim_fondo`, e importaba lógica de `daas` sin reentrenar. Estructura (la de `v2/` es igual, más `anexo_d/` en el manifest):

```text
v0_provisional/
  manifest.json                    versión, revisión 2, fecha, fuente (sha256 de output_api y del Excel 52e7547f…),
                                   champions, convenciones, decisiones, discrepancias, filas por tabla, sha256 por archivo
  tablas/<tabla>/modelo=mX/[fecha=AAAA-MM-DD/]part-0.parquet   (Hive; copia fiel de entrega/output_api)
  esquemas/<tabla>.schema.json
  api/flujo_b/forecast_series/, forecast_metrics/, simulated_balance/   (por modelo)
  api/flujo_c/simulated_balance_plan/
  api/flujo_d/funds_map.json
  api/flujo_e/alerts.json
  validacion/validacion_openapi.json, verificaciones.json
```

- `tablas/` de `v0_provisional`: predicciones 10.230 filas, alertas 2.590, recomendaciones 2.923, metricas 46, backtest 15.804, silenciosos 15 (las de la v1, commit `955115d`). En `v2/`: alertas 2.547, recomendaciones 2.897, metricas 50, el resto igual. Las tablas son reparticionadas (Hive): su sha256 no es el de los parquet fuente; la correspondencia se prueba con `fuente.archivos` del manifest.
- `api/`: JSON con la forma del payload (`data`) de los contratos OpenAPI del arquitecto (`consumo-pronosticos/contratos/*.yaml`, flujos B, C, D y E), sin la envoltura `statusCode/...`. 1.176 instancias validan con **0 errores de esquema**. 646 series, 520 entidades con saldo simulado (423 cajeros, 53 multifuncionales, 44 sucursales), 6 fondos, 2.590 alertas.
- La revisión 2 tomó los contratos del arquitecto como especificación dominante y cerró las brechas de la r1 (ciudad en M1–M3, `disponibleObservado` de M6 36/36 = saldo inicial, saldo diario simulado, métricas por ciudad × bloque 35/35 y 21/21 iguales a la hoja 03, `diaCruce`/`servicioSugerido` 520/520, `fondoId` como `CIUDAD|TDV_00X` incluida TDV_004, criticidad del catálogo A-101…A-108, `tipoDato` SIMULADO). Se subió con `aws s3 sync --delete` **solo a ese prefijo** y se verificó por sha256.
- **Es una estructura PROVISIONAL** hasta que el arquitecto entregue la especificación de almacenamiento (formato, particionado, envoltura, nombre de versión, valor real de `corrida`, hoy `"0007"`). Política de versiones aplicada desde la v2: un prefijo por entrega (`v0_provisional` = v1, `v2`), las versiones anteriores no se borran ni se sobrescriben y `version_vigente.json` dice cuál es la vigente.
- Volver a la revisión 1: el bucket tiene versionado; el VersionId del `manifest.json` de r1 es `Fz0ZPux6iCZu6ZHNywyI8SiXcT8ZpvHL` (r2: `nvqHItw6rn3_bbH8b3MTU11o8ZxWeczZ`) y las 242 VersionId de r1 están en `ALX/publicacion_s3/revision/r2/versiones_revision1.tsv`. **[Contradicción resuelta]** La r1 tenía 242 objetos; la r2, 248 (247 archivos listados en el manifest + el manifest), y hoy `v0_provisional/` tiene 249 por el Excel v1 que se subió aparte el 24-oct.

### 7.2 Discrepancias declaradas y preguntas al arquitecto

Nueve discrepancias semánticas declaradas (DS-1 a DS-9) y 11 preguntas con opciones A/B en `ALX/preguntas_arquitecto.md`: (1) layout, versión y `corrida`; (2) `DESBALANCE_DENOMINACION` no se genera (requiere banda del total del fondo); (3) `EXCEDENTE_NO_EVACUABLE` no se genera (no hay regla); (4) `CALI|TDV_004` incluida y nomenclatura `TDV_00X`; (5) mapeo de criticidad (884 CRITICA + 1.214 MEDIA en ALERTA_PROVISION, 199 MEDIA SUCURSAL_EXCESO, 26 CRITICA FALTANTE_FONDO, 267 MODERADA EXCEDENTE_FONDO); (6) asignación de `tipoDato`; (7) solo nivel POINT en series (no OVERVIEW/MODEL); (8) observado solo en la ventana 17–31 ago (47 de 646 series sin observado, nunca cero); (9) `reconstruido = false` en los 6 fondos; (10) MAE/Bias por celda calculados por nosotros; (11) días sin acción con saldoAntes = saldoDespues = cierre. Documento para el arquitecto sobre la estructura: `ALX/estructura_pronosticos_s3.md`.

### 7.3 `output/api/` y `output/anexo_d/` de los buckets NO son lo vigente

En **ambos** buckets, `output/api/` (predicciones, recomendaciones, alertas, metricas, esquemas, `optimizacion_m6.json` y `output/api/anexo_d/POC_Efectivo_PRAGMA.xlsx`) es la salida del **9-oct-2026 del pipeline de Andrés**; su Excel tiene sha256 **`6e781aaaab841de43e6adcfd9bf57204b29f3caf2741e2f7021c603a14a73a78`** (ETag `135e26638e9d3c419b45490adda97a68`, 561.969 B). `output/anexo_d/POC_Efectivo_PRAGMA.xlsx` de la réplica es del 8-oct (sha256 `515ab9d9…`). Ninguno es el entregable (ni la v1 `52e7547f…` ni la v2 `167a52e4…`). Una verificación anterior que comparó el md5 local contra ese ETag dio una falsa alarma por eso. **No consumas `output/api/` como pronóstico vigente**: la publicación vigente es `output/pronosticos/v2/` (ver `output/pronosticos/version_vigente.json`); `v0_provisional/` es la v1.

---

## 8. Reproducibilidad: cómo correr de punta a punta y qué diferencias esperar

### 8.1 Requisitos

macOS arm64 (única plataforma probada: `uv.lock` está restringido a ella porque la resolución universal falla con `shap==0.51.0`), `uv` ≥ 0.12 (se usó 0.12.21), Python 3.11.16 (`.python-version`; uv lo instala), AWS CLI v2 (se usó 2.37.10), ~2 GB de disco y ~15 min de CPU. `pyproject.toml` fija 23 dependencias directas con `==` y el freeze completo del venv que generó el entregable (182 paquetes) como `constraint-dependencies`; `[tool.uv] package = false`: `daas` no se instala, corre por `PYTHONPATH`. El `ALX/pipeline/uv.lock` original de Santiago **no** reproduce el entorno (difiere en 158 paquetes y no trae lightgbm 4.7.0, catboost 1.2.10 ni mlflow 3.17.1), por eso no se incluyó. Quedaron fuera del entorno, por no usarse en la corrida: xgboost, statsforecast, statsmodels, pulp, sagemaker, pytest y jupyter.

### 8.2 Los pasos (comandos exactos en el README §6)

Clona el repo **fuera** de Google Drive u otras carpetas sincronizadas. Ningún paso escribe en S3. Estas son líneas tal como aparecen en el README §6:

```zsh
uv sync --frozen
sh scripts/descargar_raw.sh
TRABAJO=$HOME/.cache/poc-daas/repo_corrida
cd /tmp && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 MKL_NUM_THREADS=1 MLFLOW_DISABLE_AGENT_HINT=1 \
  sh "$REPO/pipeline/corrida_entrega.sh" "$REPO/datos/raiz" "$TRABAJO" "$REPO/.venv/bin/python"
cd /tmp && PYTHONDONTWRITEBYTECODE=1 "$REPO/.venv/bin/python" "$REPO/scripts/comparar_salidas.py" \
  "$REPO/entrega/output_api" "$REPO/entrega/POC_Efectivo_PRAGMA.xlsx" \
  "$TRABAJO/data/output/api" "$TRABAJO/data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx"
cd /tmp && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO:$REPO/pipeline/src" \
  "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" generar "$HOME/.cache/poc-daas/repo_pub_v2" --version v2
```

Qué hace cada uno:
1. `uv sync --frozen` (desde la raíz del repo; luego `REPO=$PWD`): crea `.venv` con las versiones exactas.
2. `scripts/descargar_raw.sh`: `aws s3 cp` recursivo de `s3://poc-daas-bancolombia-replica-903641686926/raw/` a datos/raiz/raw (carpeta ignorada por git) con el perfil `alx-poc` (variable `AWS_PROFILE_RAW` para otro perfil, `AWS_BIN` para otro binario) y luego, desde `datos/raiz`, verifica los 19 archivos con `shasum -a 256 -c` contra `scripts/raw.sha256`.
3. `pipeline/corrida_entrega.sh <raiz> <trabajo> [python]`: corre U0 → U7 (`python -m daas.pipeline.run_u0` … `run_u7`). **Borra `"$TRABAJO/data"` y `"$TRABAJO/conf"` al iniciar** (usa una carpeta dedicada), copia la raíz y `pipeline/conf`, reescribe `paths.yml` a `default_scheme: local`, exporta `DAAS_SCHEME=local`, quita `DAAS_S3_BUCKET` y, antes de cada unidad, aborta si alguna ruta de salida no resuelve a `file://` (registro en `$TRABAJO/rutas.log`). Variables: `UNIDADES` (subconjunto), `REANUDAR=1` (no borra), `CONF_ALX=<otro alx.yml>` (p. ej. todos en `false` = pipeline de Santiago). Unos 15 min (la corrida oficial tardó 898 s). Salidas: `data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx`, `data/output/api/` (6 parquet + `*.meta.json` + `_schemas/`), `data/output/explicabilidad/importancias.parquet`, `interim/`, `processed/`, `features/`, `quality/reports/` y logs `u0.log` … `u7.log`.
4. `scripts/comparar_salidas.py <ref_api> <ref_xlsx> <nuevo_api> <nuevo_xlsx>`: compara por contenido (parquet y celdas del Excel). Con las rutas del README compara contra la v2 de `entrega/`. Para reproducir la v1 con el código actual: `CONF_ALX` = el `alx.yml` del commit `955115d` (sha256 `e841aca2…6832`) y referencia = `entrega/` de ese commit.
5. `publicacion_s3/publicar.py generar <carpeta> --version v2`: arma la publicación v2 en local con los insumos de `~/.cache/poc-daas/corrida_entrega_v2/B2_v2/` (sin S3). En un equipo sin esa carpeta, corre el paso 3 con `TRABAJO=$HOME/.cache/poc-daas/corrida_entrega_v2/B2_v2` (borra `data/` y `conf/` ahí). Publica **el Excel del repo**, no uno regenerado, y exige su sha256 completo. `publicar.py verificar <carpeta>` comprueba una descarga contra su manifest. `publicar.py subir` **no forma parte del flujo de reproducción** y no debe ejecutarse para verificar (la v2 ya está publicada; ver §7.1).

Unidades del pipeline: U0 ingesta raw → interim, calidad, curado → processed, features y costos del Anexo E; U1/U2 M1 y M2 (pronóstico, simulación de saldo, provisiones, recolecciones, alertas); U3 M3; U4/U5 M4 y M5; U6 M6; U7 contratos `output/api/*`, Excel del Anexo D y `validate_xlsx`.

### 8.3 Qué diferencias esperar

Una corrida nueva **no** reproduce el sha256 del Excel: el xlsx guarda la fecha de generación (`docProps/core.xml`) y los floats llevan ruido de ~1e-7 por sumas paralelas (Prophet/joblib) y orden de reducción (LightGBM/numpy). Criterio de equivalencia (README §8, el mismo de `ALX/ml/verificar_registro.py`): mismas hojas, filas, columnas y esquema arrow; celdas de texto y fecha idénticas; en numéricas Σ|dif| / Σ|ref| ≤ 1e-6 por columna. Solo `silenciosos.parquet` y los `_schemas/*.json` pueden coincidir byte a byte. `run_id` usa `git rev-parse --short HEAD`; sin commit queda `nogit` (solo afecta a `*.meta.json`).

**Evidencia de la v2 (26-oct-2026).** Corrida B2 (la del Excel v2, `~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`, unos 19 min) con el venv original y la misma raíz de datos de la v1 (19/19 sha256): `validate_anexo_d` 0 errores; frente a la v1, hojas 01 y 06 idénticas y 91 métricas predictivas iguales (rtol 1e-12). Corrida A2 (código v2 con el `alx.yml` de la v1): 6 hojas iguales a la v1 salvo `03!F21` (2 ulp). Corrida desde la copia limpia de este repo: README §9.3.

**Evidencia de la v1 (corrida auditada del 23-oct-2026, 12:28–12:43, 14 min)** sobre una copia de `ALX/` en `/tmp`, con el venv original (mismas versiones que `uv.lock`), los mismos raw y anexos, y `corrida_entrega.sh` con el hook de auditoría:

| Salida | Resultado frente a `entrega/` |
|---|---|
| Excel | sha256 `3450ff60…` vs `52e7547f…`; 6 hojas con las mismas dimensiones; **1 celda distinta: `03_Metricas_Desarrollo!F23`** (Bias de M3 `entradas`), 0.02064426798851951 vs 0.02064426798851952 (1 ulp). En el zip difieren `docProps/core.xml` (fecha) y `xl/worksheets/sheet3.xml` (esa celda) |
| `silenciosos.parquet` y los 6 `_schemas/*.json` | Idénticos byte a byte |
| alertas, backtest, metricas, predicciones, recomendaciones | Mismas filas, columnas y esquema; diferencias ≤ 9,5e-7 COP absolutas y ≤ 2,8e-18 relativas (máx. `predicciones.band_high`) |

Conclusión: equivalente; la causa es punto flotante y la marca de tiempo, no modelo ni datos.

**Verificación rápida desde una copia limpia del índice del repo** (23-oct): `uv sync --frozen` OK (122 paquetes, subconjunto exacto del freeze); importación de los 107 módulos de `daas`, `ml`, `lab`, `imputacion` y `datos_poc` OK (`MODELS` del registro = 85); descarga de raw 19/19 sha256 OK; **arranque U0** (`UNIDADES="u0"`) en 29 s con `rutas.log` en ok y **los 32 parquet de `interim/`, `processed/` y `features/` iguales (`DataFrame.equals`) 32/32** a los de la corrida oficial; `publicar.py` importa y sus rutas existen.

**No se repitió desde el repo** (por la prioridad del usuario): el pipeline completo U1–U7, `comparar_salidas.py` y `publicar.py generar`. Las tablas de `publicar.py` son copia de `entrega/output_api` y deberían coincidir byte a byte con S3, pero eso no se verificó desde el repo.

### 8.4 Cómo se regeneró el entregable original

La corrida oficial del 21-oct usó el mismo `corrida_entrega.sh` con la raíz `~/.cache/poc-daas/corrida_entrega/raiz/` (raw copiado del bucket en solo lectura + anexos originales) y escribió en `~/.cache/poc-daas/corrida_entrega/completa/`; luego el Excel y `data/output/api/` se copiaron a `ALX/entrega/`, se validó con `daas.publish.validate_xlsx.validate_anexo_d` y se registró el sha256. Si cambia algo (p. ej. respuestas del banco) y se regenera, el sha256 cambiará y `publicar.py` exigirá actualizar el sha256 esperado (en la versión del 23-oct, `EXCEL_SHA_PREFIJO`; hoy, `excel_sha256` de `PUBLICACIONES`): eso es un cambio de código y de entregable que requiere acuerdo del usuario.

La v2 del 26-oct se generó igual (corrida B2 con `ALX/pipeline/corrida_entrega.sh`, raíz `~/.cache/poc-daas/corrida_entrega_v2/raiz/`, idéntica a la de la v1), se copió a `ALX/entrega/` tras respaldar la v1 en `ALX/entrega/historico/v1_2026-10-21/`, se validó con `validate_anexo_d` y se registró el sha256 `167a52e4…`. Para publicarla, `publicar.py` pasó a parametrizarse por versión (`PUBLICACIONES`, con el sha256 completo de cada Excel) y la v2 se subió a `output/pronosticos/v2/` (§7.1).

---

## 9. Acceso a AWS

- **Sesión SSO `poc-bancolombia`** (definida en `~/.aws/config`, junto con el start URL del portal; no está en el repo). Sobre ella hay dos perfiles del AWS CLI que comparten la sesión, así que basta un login:

  | Perfil | Cuenta | Rol | Uso |
  |---|---|---|---|
  | `alx-poc` | 903641686926 | `AWSBedrockFullAccess` | Réplica en **solo lectura** (descarga de `raw/`; también `datos_poc.py`) |
  | `alx-mx` | 777937796305 | `Ps-HackatonAgentic-Mexico` | Bucket destino: aloja `output/pronosticos/v2/` (vigente), `version_vigente.json` y `v0_provisional/` (v1); lo lee `publicar.py --version v0_provisional` |

  (En la bitácora aparece también un perfil `alx-dev`, misma cuenta y rol que `alx-poc`; el repo no lo usa.) Si en tu equipo los perfiles se llaman distinto, usa `AWS_PROFILE_RAW=<perfil>` para `descargar_raw.sh` y `AWS_PROFILE=<perfil>` para `publicar.py`. Permisos mínimos: `s3:ListBucket` y `s3:GetObject` en ambos buckets.
- **Incidencia conocida: dos identidades en el mismo portal.** El dueño del trabajo tiene un usuario del portal para la herramienta de IA (Kiro) y otro, con acceso a las cuentas de datos. El navegador guarda una sola sesión del portal: si el login de la terminal se completa en el navegador donde está la otra identidad, queda con el usuario equivocado (`ForbiddenException ... No access`); y cerrar sesión para cambiar invalida los tokens de la otra herramienta (así se cayó un workflow el 20-oct con `No valid token found`). Procedimiento que funcionó (20-oct y 23-oct), lo ejecuta **la persona, nunca un agente** (comandos del README §5.2):

```zsh
aws sso login --profile alx-poc --use-device-code
aws sts get-caller-identity --profile alx-poc   # Account 903641686926
aws sts get-caller-identity --profile alx-mx    # Account 777937796305 (misma sesión, sin otro login)
```

- Abrir la URL y el código del device flow en una **ventana privada o un perfil de Chrome separado** con la identidad de datos.
- **Nunca ejecutar `aws sso logout`**: revoca la sesión en el servidor e invalida los tokens de otras herramientas. Cuando la sesión venza, repetir solo el login.
- **Para agentes:** no ejecutes `aws sso login`, `aws sso logout` ni `aws configure sso`. Si las credenciales vencen, pausa y pide a la persona que renueve la sesión (README §5.2).
- **S3 es solo lectura** para todo el flujo del repo (`ls`, `head-object`, `cp` S3 → local). Las únicas escrituras que se hicieron en S3 fueron la publicación de `v0_provisional` del 22-oct (con el Excel v1 agregado el 24-oct) y la de `v2/` + `version_vigente.json` del 26-oct (con `publicar.py subir`, aprobada por el usuario), todas con `alx-mx`.

---

## 10. Mapa del repo archivo por archivo

235 archivos versionados (los 231 iniciales + este + 3 de la v2: `pipeline/docs/supuestos.md`, `pipeline/src/daas/publish/anexo_d/sheet_04_v2.py` y `entrega/CAMBIOS_v2.md`). Toda ruta entre comillas invertidas de esta sección es un archivo versionado (existe en `git ls-files`); lo que no está versionado (carpetas generadas o ignoradas) se escribe sin comillas invertidas. La raíz del repo equivale a la raíz de la carpeta ALX (no muevas carpetas: varios módulos localizan la raíz por posición relativa).

### 10.1 Raíz, entorno y scripts

| Ruta | Rol |
|---|---|
| `CONTEXTO_LLM.md` | Este documento: contexto completo para agentes y personas |
| `README.md` | Guía práctica: propósito, arquitectura, mapa, requisitos, comandos, salidas, criterio de comparación, evidencia, supuestos, decisiones, material no incluido y limitaciones |
| `AGENTS.md` | Reglas para agentes (leer primero este documento; S3 solo lectura; sin login/logout SSO; correr fuera de Drive; no tocar recetas congeladas sin acuerdo) |
| `pyproject.toml` | Proyecto `poc-bancolombia` 0.1.0: Python `==3.11.*`, 23 dependencias `==`, `package = false`, `environments` restringido a macOS arm64, `constraint-dependencies` con el freeze completo (182 paquetes) |
| `uv.lock` | Lock de uv (123 paquetes resueltos) para `uv sync --frozen` |
| `.python-version` | `3.11.16` |
| `.gitignore` | Ignora el entorno .venv, cachés de Python, mlruns, mlflow.db, catboost_info, la carpeta datos/raiz/raw (raw descargado), salidas, logs, .env y .aws |
| `datos_poc.py` | Cargadores de series desde la réplica S3 a memoria (perfil `alx-poc`; `matriz_arnes`, `matriz_eda`, constantes del proyecto). En el repo lo importa `imputacion/datos.py` |
| `scripts/descargar_raw.sh` | Descarga los 19 archivos de raw de la réplica (solo lectura) a datos/raiz/raw (no versionada) y verifica sus sha256 |
| `scripts/raw.sha256` | sha256 de los 19 archivos de raw (rutas relativas raw/&lt;archivo&gt;) |
| `scripts/comparar_salidas.py` | Compara una corrida con `entrega/` por contenido (parquet y celdas del Excel) |

### 10.2 Datos y referencias versionadas

| Ruta | Rol |
|---|---|
| `datos/raiz/anexos/Anexos/Anexo_D_Plantilla_entrega_proveedor_POC.xlsx` | Plantilla original del Anexo D (sha256 `a247fae7…`); la usa U7 |
| `datos/raiz/anexos/Anexos/Anexo_E_Parametros costos.xlsx` | Parámetros de costos originales del Anexo E (sha256 `caaa399c…`; nombre con espacio); lo lee U0 (contrato C-12) |
| `entrega/POC_Efectivo_PRAGMA.xlsx` | Excel entregado v2 (sha256 `167a52e4…9461`). Referencia de comparación. Entrada de `publicacion_s3/publicar.py --version v2`, que exige su sha256 completo `167a52e4…` |
| `entrega/CAMBIOS_v2.md` | Cambios v1 → v2: interruptores, cifras por fondo, costos, reproducción de la v1 y pendientes |
| `entrega/output_api/predicciones.parquet` | 10.230 filas: pronóstico por entidad-día con `band_low`/`band_high` y `origen_dato` |
| `entrega/output_api/recomendaciones.parquet` | 2.897 filas: acciones de M1–M3 y M6 con monto, costo y saldos |
| `entrega/output_api/alertas.parquet` | 2.547 alertas (M1 1.349, M2 749, M3 199, M6 250) |
| `entrega/output_api/metricas.parquet` | 50 filas de métricas (incluye lecturas RN-08, bloque `sesgo_red_origen` y, desde la v2, `recoleccion_omitida_monto`, `cajeros_sucursal_mapeados`, `flujo_sin_fondo` y `costo_traslado_tarifa_destino`) |
| `entrega/output_api/backtest.parquet` | 15.804 filas del backtest 17–31 ago |
| `entrega/output_api/silenciosos.parquet` | 15 entidades sin dato reciente y su tratamiento |
| `entrega/output_api/_schemas/predicciones.json`, `entrega/output_api/_schemas/recomendaciones.json`, `entrega/output_api/_schemas/alertas.json`, `entrega/output_api/_schemas/metricas.json`, `entrega/output_api/_schemas/backtest.json`, `entrega/output_api/_schemas/silenciosos.json` | Esquemas versionados de cada contrato |

La carpeta datos/raiz/raw no está versionada: la llena `scripts/descargar_raw.sh`.

### 10.3 Configuración del pipeline (`pipeline/conf/`) y punto de entrada

| Ruta | Rol |
|---|---|
| `pipeline/corrida_entrega.sh` | **Punto de entrada** U0 → U7 en modo local (ver §8.2) |
| `pipeline/conf/alx.yml` | Interruptores de ALX: los 7 de la v1 y los 10 de la v2 en `true`, `imputacion: false` (README §3) |
| `pipeline/docs/supuestos.md` | Registro final de supuestos SUP-01..SUP-53 (v2); lo citan el código, la configuración y la hoja 04 |
| `pipeline/conf/paths.yml` | Capas y raíz de datos (`pipeline/corrida_entrega.sh` lo reescribe a `default_scheme: local`) |
| `pipeline/conf/sources.yml` | Mapa de las 19 fuentes de raw + Anexo E a los contratos C-01..C-12 |
| `pipeline/conf/dq_rules.yml` | Reglas de calidad, los 27 días del Anexo C y el corte |
| `pipeline/conf/calendario_co.yml` | Calendario de Colombia |
| `pipeline/conf/costos.yml` | Reglas de costos del Anexo E (tipologías de cajero y sucursal; MF interurbano y escala de sucursal de la v2) |
| `pipeline/conf/entity_id_map.yml` | Mapa de identificadores de entidades |
| `pipeline/conf/export_anexo_d.yml` | Configuración y validación del Excel del Anexo D (textos de la hoja 04 y, en la v2, `hoja_04_v2`, `hoja_03_v2`, `textos_v2` y `nivel_riesgo_previo`) |
| `pipeline/conf/model_u1_u2.yml` | M1 y M2: `forecaster.modelo` (Santiago) y `forecaster.modelo_alx` (champions), política, inactividad, métricas |
| `pipeline/conf/model_m3.yml` | M3: recetas (`modelo_alx: {entradas: campeon_m3_entradas, salidas: campeon_m3_salidas}`) y política por sucursal |
| `pipeline/conf/model_u4_u5.yml` | M4 y M5: `modelo_alx: {m4: combo_perfil_gbml1, m5: campeon_m5}` |
| `pipeline/conf/model_u6.yml` | M6: saldo inicial, mezcla, mínimos/máximos, factor de M5 (`correccion_total`), `correccion_disponibles`, operaciones (incluidos `rn84` y `traslado.tarifa_por: origen`), decisión (`traslado_disponible_t1`, `riesgo_residual`) y costos |
| `pipeline/conf/pronosticadores.yml` | Recetas de pronóstico (incluidas `campeon_*` de la familia `ml_laboratorio`), bandas conformales y textos de enfoque por modelo |

### 10.4 Paquete `daas` (`pipeline/src/daas/`, 95 módulos)

| Ruta | Rol |
|---|---|
| `pipeline/src/daas/__init__.py` | Paquete `daas` (componente analítico) |
| `pipeline/src/daas/alx.py` | Lee los interruptores de `pipeline/conf/alx.yml` (`interruptor(nombre)`; ausente = `false`) |
| `pipeline/src/daas/pipeline/__init__.py` | Subpaquete de orquestación |
| `pipeline/src/daas/pipeline/run_u0.py` | U0: ingesta → calidad → fondo → curado → features y costos |
| `pipeline/src/daas/pipeline/run_u1_u2.py` | U1/U2: M1 y M2 (pronóstico, backtest, banda, saldo, acciones, alertas) |
| `pipeline/src/daas/pipeline/run_u3.py` | U3: M3 |
| `pipeline/src/daas/pipeline/run_u4_u5.py` | U4/U5: M4 y M5 (ingreso por fondo) |
| `pipeline/src/daas/pipeline/run_u6.py` | U6: balance prescriptivo de M6 |
| `pipeline/src/daas/pipeline/run_u7.py` | U7: Excel del Anexo D y su validación |
| `pipeline/src/daas/ingest/__init__.py` | Subpaquete de ingesta |
| `pipeline/src/daas/ingest/normalize.py` | Normalización raw → interim (tipos, fechas, un snapshot por entidad, `fondo_id`) |
| `pipeline/src/daas/ingest/readers/__init__.py` | Lectores por contrato C-01..C-12 |
| `pipeline/src/daas/ingest/readers/_sources.py` | Carga de `pipeline/conf/sources.yml` para los lectores |
| `pipeline/src/daas/ingest/readers/_points.py` | Lectura compartida de las hojas `CBR` y `Clientes` |
| `pipeline/src/daas/ingest/readers/atm_transactions.py` | C-01 `txn_cajeros` |
| `pipeline/src/daas/ingest/readers/cp_history.py` | C-02 `cp_historico` |
| `pipeline/src/daas/ingest/readers/cp_uninstalled.py` | C-03 `cp_desinstalados` (RN-07) |
| `pipeline/src/daas/ingest/readers/txc_suc.py` | C-04 `txc_suc` |
| `pipeline/src/daas/ingest/readers/offices.py` | C-05 `oficinas` |
| `pipeline/src/daas/ingest/readers/branch_master.py` | C-06 `maestro_sucursales` |
| `pipeline/src/daas/ingest/readers/cbr.py` | C-07 `cbr` |
| `pipeline/src/daas/ingest/readers/customers.py` | C-08 `clientes` |
| `pipeline/src/daas/ingest/readers/available_cash.py` | C-09 `disponibles` (10 CSV) |
| `pipeline/src/daas/ingest/readers/exchanges.py` | C-10 `intercambios` |
| `pipeline/src/daas/ingest/readers/sales_summary.py` | C-11 `consolidado_ventas` |
| `pipeline/src/daas/ingest/readers/anexo_e_costs.py` | C-12 `costos_anexo_e` |
| `pipeline/src/daas/quality/__init__.py` | Subpaquete de calidad |
| `pipeline/src/daas/quality/checks.py` | Validaciones V-01..V-12 |
| `pipeline/src/daas/quality/anexo_c.py` | Densifica el calendario y marca el Anexo C como faltante (`mark_missing`), nunca cero |
| `pipeline/src/daas/quality/report.py` | Reporte de calidad (json + md) |
| `pipeline/src/daas/fondo/__init__.py` | Subpaquete de fondo |
| `pipeline/src/daas/fondo/build_fund.py` | `fondo_id = CIUDAD\|TRANSPORTADORA` y dimensión de fondos |
| `pipeline/src/daas/curate/__init__.py` | Subpaquete de curado |
| `pipeline/src/daas/curate/build_processed.py` | interim → processed por modelo, corte de entrenamiento y holdout |
| `pipeline/src/daas/features/__init__.py` | Subpaquete de features |
| `pipeline/src/daas/features/calendar.py` | `dim_calendario` de Colombia (festivos con `holidays`) |
| `pipeline/src/daas/features/ts_features.py` | Lags y medias móviles por entidad (capa features) |
| `pipeline/src/daas/costs/__init__.py` | Subpaquete de costos |
| `pipeline/src/daas/costs/anexo_e.py` | Motor de costos: costo = fijo + monto / 10.000 × tarifa |
| `pipeline/src/daas/forecasting/__init__.py` | Subpaquete de pronóstico |
| `pipeline/src/daas/forecasting/forecast.py` | Camino único de pronóstico de una unidad: horizonte, backtest y banda |
| `pipeline/src/daas/forecasting/forecasters.py` | Pronosticadores seleccionables por configuración (recetas) |
| `pipeline/src/daas/forecasting/forecaster.py` | Prophet (portado de la primera ronda) |
| `pipeline/src/daas/forecasting/global_gbm.py` | Boosting global de Santiago (HGB) |
| `pipeline/src/daas/forecasting/global_ml.py` | Motor ML global de ALX (LightGBM, XGBoost, CatBoost, RF, ET, HGB; V0–V4) |
| `pipeline/src/daas/forecasting/calendario_co.py` | Calendario colombiano detallado (V1) |
| `pipeline/src/daas/forecasting/laboratorio.py` | Familia `ml_laboratorio`: corre los champions del laboratorio dentro del pipeline (SUP-39) y arma el contexto "as of" |
| `pipeline/src/daas/forecasting/intervals.py` | Bandas conformales |
| `pipeline/src/daas/forecasting/metrics.py` | WAPE, MAE y Bias oficiales |
| `pipeline/src/daas/forecasting/explain.py` | Explicabilidad fuera de muestra (alimenta la hoja 04) |
| `pipeline/src/daas/decision/__init__.py` | Subpaquete de decisión |
| `pipeline/src/daas/decision/alerts.py` | Alertas de severidad (RN-34) |
| `pipeline/src/daas/decision/optimizer.py` | Optimizador (portado de la primera ronda) |
| `pipeline/src/daas/decision/policies.py` | Políticas de provisión |
| `pipeline/src/daas/modules/__init__.py` | Subpaquete de módulos por modelo |
| `pipeline/src/daas/modules/atm_m1_m2/__init__.py` | Núcleo M1/M2 |
| `pipeline/src/daas/modules/atm_m1_m2/balance.py` | Simulación de saldo de M1 y M2 |
| `pipeline/src/daas/modules/atm_m1_m2/config.py` | Carga de `pipeline/conf/model_u1_u2.yml` |
| `pipeline/src/daas/modules/atm_m1_m2/dataset.py` | Objetivos `pagado` y `cash_in`; lectura RN-08 |
| `pipeline/src/daas/modules/atm_m1_m2/inactivity.py` | Equipos inactivos o desmontados: pronóstico cero (RN-07, RN-08) |
| `pipeline/src/daas/modules/branches_m3/__init__.py` | Subpaquete M3 |
| `pipeline/src/daas/modules/branches_m3/balance.py` | Simulación de saldo de la bóveda de sucursal |
| `pipeline/src/daas/modules/branches_m3/config.py` | Carga de `pipeline/conf/model_m3.yml` |
| `pipeline/src/daas/modules/branches_m3/dataset.py` | Series de M3 (incluye la deduplicación de SUP-35) |
| `pipeline/src/daas/modules/branches_m3/policy.py` | Política diferenciada por sucursal (RN-37..RN-44) |
| `pipeline/src/daas/modules/funds_inflows_m4_m5/__init__.py` | Subpaquete M4/M5 |
| `pipeline/src/daas/modules/funds_inflows_m4_m5/config.py` | Carga de `pipeline/conf/model_u4_u5.yml` |
| `pipeline/src/daas/modules/funds_inflows_m4_m5/dataset.py` | Series fondo-día de M4 y M5 |
| `pipeline/src/daas/modules/funds_m6/__init__.py` | Subpaquete M6 |
| `pipeline/src/daas/modules/funds_m6/balance.py` | Balance por fondo y denominación |
| `pipeline/src/daas/modules/funds_m6/config.py` | Carga de `pipeline/conf/model_u6.yml` |
| `pipeline/src/daas/modules/funds_m6/correccion_disponibles.py` | Corrección de disponibles detectada en datos (SUP-29) |
| `pipeline/src/daas/modules/funds_m6/dataset.py` | Insumos de M6 (disponibles, mezcla, mínimos/máximos, factor de M5; v2: cajeros de sucursal al fondo, `enabled_operations_matrix`) |
| `pipeline/src/daas/modules/funds_m6/simulator.py` | Simulador secuencial de balance y decisiones de M6 (v2: traslado T+1 `_anticipate`, tarifa del origen, RN-84) |
| `pipeline/src/daas/io/__init__.py` | Subpaquete de E/S |
| `pipeline/src/daas/io/storage.py` | Resolución de URIs daas://&lt;capa&gt;/&lt;dataset&gt; a local o S3 |
| `pipeline/src/daas/lineage/__init__.py` | Subpaquete de linaje |
| `pipeline/src/daas/lineage/manifest.py` | `run_id` (`<fecha>_<git sha>` o `nogit`) y manifiestos .meta.json |
| `pipeline/src/daas/publish/__init__.py` | Subpaquete de publicación |
| `pipeline/src/daas/publish/contracts.py` | Contratos output/api/* + _schemas; conjunto cerrado `origen_dato` |
| `pipeline/src/daas/publish/explainability.py` | Artefacto de explicabilidad (output/explicabilidad/importancias.parquet de la corrida) |
| `pipeline/src/daas/publish/validate_xlsx.py` | Validación del Excel ya generado (`validate_anexo_d`) |
| `pipeline/src/daas/publish/anexo_d/__init__.py` | Generación del Anexo D sobre la plantilla |
| `pipeline/src/daas/publish/anexo_d/cell_values.py` | Conversión de valores de celda |
| `pipeline/src/daas/publish/anexo_d/config.py` | Carga de `pipeline/conf/export_anexo_d.yml` y de la plantilla |
| `pipeline/src/daas/publish/anexo_d/constants.py` | Proveedor, hojas obligatorias, encabezados y fórmulas |
| `pipeline/src/daas/publish/anexo_d/generate.py` | Orquesta las 5 hojas |
| `pipeline/src/daas/publish/anexo_d/masters.py` | Maestros, capacidades y fondos que alimentan las hojas |
| `pipeline/src/daas/publish/anexo_d/sheet_01_predictions.py` | Hoja 01 |
| `pipeline/src/daas/publish/anexo_d/sheet_02_operational_plan.py` | Hoja 02 |
| `pipeline/src/daas/publish/anexo_d/sheet_03_metrics.py` | Hoja 03 |
| `pipeline/src/daas/publish/anexo_d/sheet_04_description.py` | Hoja 04 (con `hoja04_v2` delega en `sheet_04_v2.py`) |
| `pipeline/src/daas/publish/anexo_d/sheet_04_v2.py` | Hoja 04 v2: textos para el evaluador desde `export_anexo_d.yml` y su validación; exige `supuestos_alx` |
| `pipeline/src/daas/publish/anexo_d/sheet_05_m6_funds.py` | Hoja 05 |
| `pipeline/src/daas/publish/anexo_d/workbook.py` | Escritura y validación sobre la plantilla |

### 10.5 Laboratorio, ML e imputación (solo lo que usa la corrida)

| Ruta | Rol |
|---|---|
| `lab/__init__.py` | Hace importable `daas` desde pipeline/src |
| `lab/forecasting/__init__.py` | Subpaquete de pronosticadores del laboratorio |
| `lab/forecasting/registry.py` | Registro `MODELS` (85 al importar) con el contrato `forecast(history, dates)`; carga todo `lab/conf/experimentos/` |
| `lab/forecasting/challengers.py` | Retadores y combinaciones (con pesos opcionales, para los ponderados) |
| `lab/forecasting/gbm.py` | Boosting global directo y contrastes (ridge, CatBoost) |
| `lab/tracking/__init__.py` | Subpaquete de MLflow |
| `lab/tracking/mlflow_tracking.py` | Helpers de MLflow; `ml/pronosticar.py` importa `PronosticadorPanel` y `a_matriz` |
| `lab/conf/bandas.yml` | Champion (`adoptado`) y challenger (`retador`) por serie; lo lee `publicacion_s3/publicar.py` para el manifest |
| `lab/conf/experimentos/` (80 yml) | Recetas congeladas. De Santiago: `cat_cal.yml`, `cat_cal_ctrl.yml`, `combo3_ets.yml`, `combo3_mstl.yml`, `combo3_theta.yml`, `combo_gbm_lineal.yml`, `combo_gbm_perfil.yml`, `combo_gbm_prophetcal.yml`, `combo_perfil_gbml1.yml`, `ets_auto.yml`, `gbm_base.yml`, `gbm_cal.yml`, `gbm_cal_l1.yml`, `lineal_cal.yml`, `mstl_7_30.yml`, `perfil_cal_100.yml`, `perfil_cal_50.yml`, `prophet_cal.yml`, `theta_opt.yml`. De ALX (fase 2): `ml_cat_v1.yml`, `ml_cat_v1_l1.yml`, `ml_cat_v3.yml`, `ml_cat_v4.yml`, `ml_ens_campeon_ml_m1.yml`, `ml_ens_campeon_ml_m2_cash_in.yml`, `ml_ens_campeon_ml_m2_pagado.yml`, `ml_ens_campeon_ml_m3_entradas.yml`, `ml_ens_campeon_ml_m3_salidas.yml`, `ml_ens_campeon_ml_m4.yml`, `ml_ens_campeon_ml_m5.yml`, `ml_ens_media_top3_m1.yml`, `ml_ens_media_top3_m2_cash_in.yml`, `ml_ens_media_top3_m2_pagado.yml`, `ml_ens_media_top3_m3_entradas.yml`, `ml_ens_media_top3_m3_salidas.yml`, `ml_ens_media_top3_m4.yml`, `ml_ens_media_top3_m5.yml`, `ml_ens_pond_m1.yml`, `ml_ens_pond_m2_cash_in.yml`, `ml_ens_pond_m2_pagado.yml`, `ml_ens_pond_m3_entradas.yml`, `ml_ens_pond_m3_salidas.yml`, `ml_ens_pond_m4.yml`, `ml_ens_pond_m5.yml`, `ml_et_v0.yml`, `ml_et_v1.yml`, `ml_et_v3.yml`, `ml_et_v4.yml`, `ml_hgb_v1.yml`, `ml_hgb_v1_l1.yml`, `ml_lgbm_v0.yml`, `ml_lgbm_v0_l1.yml`, `ml_lgbm_v1.yml`, `ml_lgbm_v1_l1.yml`, `ml_lgbm_v1_l1_opt_m4.yml`, `ml_lgbm_v1_l1_opt_m5.yml`, `ml_lgbm_v1_opt_m3_entradas.yml`, `ml_lgbm_v1_opt_m3_salidas.yml`, `ml_lgbm_v1_tw.yml`, `ml_lgbm_v2.yml`, `ml_lgbm_v2_l1.yml`, `ml_lgbm_v3.yml`, `ml_lgbm_v3_l1.yml`, `ml_lgbm_v3_opt_m2_cash_in.yml`, `ml_lgbm_v3_tw.yml`, `ml_lgbm_v4.yml`, `ml_lgbm_v4_l1.yml`, `ml_lgbm_v4_opt_m1.yml`, `ml_lgbm_v4_opt_m2_pagado.yml`, `ml_lgbm_v4_tw.yml`, `ml_rf_v0.yml`, `ml_rf_v1.yml`, `ml_rf_v3.yml`, `ml_rf_v4.yml`, `ml_xgb_v0.yml`, `ml_xgb_v0_l1.yml`, `ml_xgb_v1.yml`, `ml_xgb_v1_l1.yml`, `ml_xgb_v3.yml`, `ml_xgb_v4.yml`. Las de los champions: `ml_lgbm_v4_tw.yml`, `ml_ens_pond_m2_pagado.yml`, `ml_ens_pond_m2_cash_in.yml`, `ml_ens_pond_m3_entradas.yml`, `ml_lgbm_v1_l1.yml`, `combo_perfil_gbml1.yml`, `ml_ens_media_top3_m5.yml` (y las de sus miembros) |
| `ml/__init__.py` | Hace importables `lab` y `daas` |
| `ml/pronosticar.py` | `pronosticar(history, dates, ...)`: arma y ajusta la receta del champion; lo llaman `pipeline/src/daas/forecasting/laboratorio.py` y `pipeline/src/daas/forecasting/explain.py`; también envuelve el modelo registrado (`PronosticadorEscenario`) |
| `imputacion/__init__.py` | Hace importables `lab`, `ml`, `datos_poc` y `daas` |
| `imputacion/contexto_asof.py` | Contexto V4 "as of" (SUP-28): último snapshot del maestro ≤ origen. **No imputa** |
| `imputacion/datos.py` | Matrices corregidas (dedup, corruptos, desinstalados); lo importa `imputacion/contexto_asof.py` |

### 10.6 Publicación y contratos del arquitecto

| Ruta | Rol |
|---|---|
| `publicacion_s3/publicar.py` | Parametrizado por versión (`--version v2` por defecto, o `v0_provisional`). `generar <carpeta>`: arma la publicación en local; `verificar <carpeta>`: comprueba una descarga contra su manifest; `subir <carpeta> [--dry-run]`: publica solo en `output/pronosticos/v2/` y `version_vigente.json`, con destino vacío y sin borrar. Perfil `alx-mx` |
| `consumo-pronosticos/contratos/openapi-datos-flujo-b.yaml` | OpenAPI del flujo B (series, métricas, saldo simulado) |
| `consumo-pronosticos/contratos/openapi-datos-plan-flujo-c.yaml` | OpenAPI del flujo C (plan de saldo simulado) |
| `consumo-pronosticos/contratos/openapi-datos-fondos-flujo-d.yaml` | OpenAPI del flujo D (mapa de fondos) |
| `consumo-pronosticos/contratos/openapi-datos-alertas-flujo-e.yaml` | OpenAPI del flujo E (alertas) |

---

## 11. Pendientes, preguntas abiertas, riesgos y limitaciones

### 11.1 Pendientes inmediatos

1. **Commit y push de la actualización v2 de este repo** a `https://github.com/alexanderpj-ds/poc-bancolombia.git` (rama `main`): los hace el usuario. Todo queda staged y sin commit.
2. ~~Publicar la v2 en S3~~: **hecho** el 26-oct-2026 en `output/pronosticos/v2/` con el puntero `version_vigente.json` (§7.1). Queda pendiente que el arquitecto confirme la estructura definitiva de almacenamiento.
3. Sustentación presencial en Medellín (la entrega era el **26-oct-2026**).
4. Backend Java y frontend Angular + Power BI: fuera de este repo (§1).
5. Respuesta del arquitecto a las 11 preguntas (§7.2) y especificación definitiva de almacenamiento.
6. Decisiones del usuario abiertas por la v2: alternativa de SUP-44 (segunda atención consolidada en 8667/9311: 4 y 1 provisiones adicionales por 73.047.796 y 18.008.804 COP) y alternativa de SUP-21 (INDIVIDUAL interurbano, +575.069 COP).
7. Pendientes de texto de la v2 (`entrega/CAMBIOS_v2.md`): citar SUP-20 y SUP-29 en `supuesto_utilizado` de la hoja 05; tildes de los textos heredados de las hojas 02 y 05; salvedad de SUP-09; observaciones no bloqueantes NB-1 a NB-5 de la revisión. Riesgo residual de M3: 31 recolecciones menores de 1 M COP que sí superan su costo.
8. Pedir al banco `Historico BANREP.xlsx` e `Historico Traslados.xlsx` del Anexo A (SUP-46); con ellos la habilitación de BanRep y traslados se tomaría del histórico real.
9. Decidir si el bucket destino `777937796305` pasa a ser la fuente de datos (hoy la réplica lo es para `raw/`).
10. Decidir sobre M5: aplicar o no la recomendación de M5 v2 (SUP-41 reservado; no cambia el Excel de septiembre) o alguna opción del plan de M5.
11. Actualizar `ALX/guia_supuestos.md` a la v2 (cubre hasta SUP-41).

### 11.2 Preguntas al banco convertidas en supuestos

Con la indicación del banco de suplir con supuestos documentados la información no suministrada, el registro final ya no tiene "Preguntas abiertas": cada duda quedó resuelta por un SUP con su texto literal de respaldo (tabla "Preguntas convertidas en supuestos" de `pipeline/docs/supuestos.md`). Las que antes figuraban aquí quedan así: ceros de sucursales de agosto → SUP-37; entidad con reales en 0 → SUP-27; RN-08 → resuelta por el texto de los Anexos B y C (SUP-02, SUP-50); unidades de la TDV_001, `TOTAL`, blancos de la TDV_004 y doble formato → SUP-29; hojas informativas que la plantilla no trae → SUP-40; fondo de los cajeros de sucursal → SUP-12; MF urbano o interurbano → SUP-21; escala de sucursal → SUP-22; 8667 y 9311 → SUP-44; operaciones de RN-84 → SUP-14; archivos BanRep y Traslados → SUP-46; maestro CP posterior al corte → SUP-45; fecha del traslado → SUP-52; tarifa entre ciudades → SUP-53.

Siguen como temas de conversación con el banco (no bloquean el entregable): los megapuntos de M5 (puntos 220 de Cali, 276 y 27 de Pasto, 69 de Ipiales) y si prefiere un M5 centrado aunque suba el WAPE; si la evaluación de septiembre incluye depósitos extraordinarios de clientes; si `CALI|TRANSPORTADORA_004` es nueva desde may-2026; la caída de cajeros que reportan del 10 al 25-ago y la vigencia del universo de clientes (529 frente a 344).

### 11.3 Riesgos

- **M5 subpronostica de forma estructural** (Bias −43,0 % en el chequeo; −20,9 % en selección); el total pronosticado de septiembre (354,4 mil M) está por debajo de los últimos cuatro totales reales de 15 días (364, 465, 423 y 517 mil M). M6 lo corrige solo en parte (tope 1,5 de SUP-20).
- **M3:** ceros de agosto sin confirmar; cobertura de la banda 0,55–0,72 en el chequeo; Bias de `salidas` −0,104; la mejora publicada en la hoja 03 es casi toda medición (SUP-02).
- **El banco puede medir distinto:** lectura RN-08 vs observada (en el chequeo la distancia va de 6,5 a 17,7 pp), denominador cero (SUP-27), exclusión por cajero vs por entidad-día (SUP-01), ceros de M3 (SUP-37).
- **Evidencia limitada:** un solo origen de chequeo; los bloqueados ya se usaron (no quedan orígenes fuera de muestra para una decisión nueva hasta tener datos de sep–oct); dos champions pasan R1 con menos de 2 EE; los pesos congelados de los ponderados usan meses posteriores al bloqueado 31-ago-2025; la repetición con imputación fue acotada a 28 modelo-serie.
- **SUP-09 sin las exclusiones de SUP-29:** el reparto por denominación aún suma los 30 fondo-días con doble formato y cuenta como 0 los blancos de la TDV_004 (la mezcla corregida se mueve hasta 8,3 pp en `PASTO|TRANSPORTADORA_001`). Declarado en la hoja 04.
- **Riesgos operativos del modelo de Santiago aún vigentes:** visitas sin tope (RN-15: 1.349 provisiones de M1 en 15 días); tensión RN-12 (agotamiento cerca de 0 % vs remanente ≤ 22 %).
- **Discrepancias README de Santiago vs código** (LightGBM = HGB, etc.): riesgo en la sustentación si el banco revisa el código.

### 11.4 Limitaciones del repo

- `uv.lock` solo probado y restringido a macOS arm64.
- `publicar.py --version v2` depende de los insumos locales de la corrida B2 (`~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`, ruta fija en el script); `--version v0_provisional` depende del respaldo v1 (`entrega/historico/`, fuera del repo) y de `interim/`/`processed/` del bucket destino (sesión `alx-mx` vigente).
- No hay pruebas automatizadas en el repo (están en `ALX/`).
- La corrida completa del pipeline v2 y `publicar.py generar --version v2` desde una copia limpia del repo están en el README §9.3; `subir` no se probó desde el repo (la v2 ya está publicada).
- El repo no trae el laboratorio completo: no se puede re-elegir modelos ni recalibrar bandas desde aquí (eso vive en `ALX/lab/` y `ALX/ml/`).

### 11.5 Mejoras para después de la entrega

SUP-09 nuevo (reparto de `pagado` de M1/M2 por gavetas y el resto por mezcla de movimientos); regla de adopción v2 en orígenes nuevos (sep–oct 2026); repetición completa del ML con imputación; CQR o conformal adaptativo (ACI), sobre todo para M3; variables de estado de los puntos para M5 (P3) y demás del plan de M5; revisar M4 con `ml_ens_campeon_ml_m4`; variable de silencios RN-08.

---

## 12. Glosario

| Término | Significado |
|---|---|
| **ALX** | Carpeta de trabajo de Alexander Peláez en el Drive del proyecto; copia del repo de Santiago más todo el trabajo nuevo. En el código, nombre de la raíz del repo |
| **Anexo A–E** | Anexos del pliego, todos recibidos: A metadatos de insumos, B reglas de negocio RN-xx, C observaciones de calidad (días sin registro), D plantilla del Excel, E costos. Del Anexo A no llegaron `Historico BANREP.xlsx` ni `Historico Traslados.xlsx` (SUP-46) |
| **Anexo C (días)** | 27 días de 2026 sin registro en toda la red de cajeros; siempre NaN, nunca 0 |
| **Arnés** | Backtest rodante de Santiago (`ALX/lab/evaluation/harness.py`) |
| **"As of"** | Con la información disponible en la fecha del origen (último snapshot del maestro ≤ origen) |
| **ATM dispensador / multifuncional** | Cajero que solo entrega billetes (M1) / que además recibe depósitos (M2) |
| **Backtest** | Repetir la prueba ciega sobre la historia |
| **Banda conformal** | Intervalo del 90 % calibrado con residuos fuera de muestra, sin suponer distribución |
| **BanRep** | Banco de la República: los fondos consignan excedentes, retiran efectivo y cambian denominaciones; no opera en días no hábiles; en la PoC solo habilitado en Cali (SUP-13) |
| **Bias** | Σ(ŷ − y) / Σy; negativo = subpronóstico |
| **Bloque 1 / 2** | Días 1–7 y 8–15 del horizonte; en la hoja 03, "Semana 1" (17–23 ago) y "Semana 2" (24–31 ago) |
| **Bloqueados** | Orígenes 31-ago-2025 y 31-jul-2026, reservados para confirmar una sola vez |
| **Calidad / familia** | Atributos de los disponibles: estado o destino del billete (incluye la fila `TOTAL`, que es un subtotal) / serie nueva o antigua |
| **Cambio de denominación / intercambio** | Canje entre denominaciones dentro del fondo / canje de efectivo con otras entidades |
| **`cash_in`** | Depósitos en multifuncionales (`cdgtrn` 401, 501, 629) |
| **CBR** | Corresponsal bancario robusto: comercio que recibe efectivo para el banco (M4) |
| **Champion / challenger** | Modelo adoptado por serie / mejor candidato no adoptado (alias `@champion` y `@challenger` en MLflow) |
| **Chequeo** | Origen 16-ago-2026 (backtest 17–31 ago): la ventana de la hoja 03; nunca decide solo |
| **Cobertura** | Fracción de reales dentro de la banda |
| **Corte** | 31-ago-2026: último día con datos que se puede usar |
| **Cupo / `cupo_max_suc`** | Capacidad máxima de efectivo de un cajero / de la bóveda de una sucursal |
| **Denominación** | Billete de 100.000, 50.000, 20.000, 10.000, 5.000 o 2.000 COP (grano de M6) |
| **Denominador cero** | Entidad con Σ\|y\| = 0 en la ventana; sale solo del WAPE agregado (SUP-27) |
| **Disponible** | Saldo de un fondo por denominación, calidad y familia al cierre de un día hábil (C-09) |
| **EE** | Error estándar de la diferencia pareada entre orígenes (sd/√n) |
| **Entradas / salidas** | Efectivo que entra o sale de la bóveda de una sucursal por la operación con clientes (M3) |
| **Escenarios S0, S0', S1, S2, S2b** | Fase 2; fase 2 re-puntuada con SUP-02; correcciones sin imputar (**vigente**); con imputación; sensibilidad de ceros dudosos |
| **Fondo** | Bóveda de una TDV en una ciudad; id `CIUDAD\|TRANSPORTADORA` (6 fondos); grano de M4, M5 y M6 |
| **G1–G3** | Guardas extra para variantes con imputación |
| **HGB** | `HistGradientBoostingRegressor` de scikit-learn; el "LightGBM" del README de Santiago |
| **Holdout** | Datos posteriores al corte que trae el bucket; no se usan (SUP-18) |
| **Horizonte (h)** | Días desde el origen, 1 a 15 |
| **Huella** | Primeros 12 caracteres del sha256 de un archivo de reglas; prueba que la regla no cambió después de medir (`623420f48f04` adopción v1; `3361fa6b1e16` imputación; `0ee298cb749e` decisión con imputación; `688ae78b095e` M5 v2) |
| **Interruptor** | Clave de `pipeline/conf/alx.yml` que activa un cambio de ALX sobre el pipeline de Santiago |
| **k** | Múltiplo del EE exigido en R1 (1 o 2) |
| **L1 / L2 / Tweedie** | Pérdidas: absoluta (mediana), cuadrática (media) y Tweedie (media con varianza creciente) |
| **MAE** | Error absoluto medio en COP |
| **Megapunto** | Cliente de M5 con depósitos muy grandes y esporádicos (p. ej. punto 220 de Cali) |
| **`ml_laboratorio`** | Familia de recetas del pipeline que corre los champions del laboratorio |
| **Nivel** | Media reciente de la entidad (56 días en el motor ML, 28 en las bandas) |
| **Origen** | Fecha de corte simulada del backtest |
| **`origen_dato`** | Procedencia de cada fila de salida: PROYECTADO, SIMULADO, ESTIMADO; nunca REAL |
| **`pagado`** | Retiros de efectivo en cajeros (`cdgtrn` 220, 420, 520) |
| **Pliego** | `POC_DaaS.docx`, documento oficial de la PoC |
| **pp** | Puntos porcentuales de WAPE |
| **Provisión / recolección** | Llevar efectivo a un punto / retirarlo (servicio de la TDV) |
| **R1–R5** | Regla de adopción (mejora > k·EE, ninguna celda peor, confirmación, Bias, cobertura) |
| **RN-xx** | Reglas de negocio del Anexo B; el registro de supuestos v2 cita su texto literal (RN-07 desinstalados; RN-08 ausencia con red operando = 0; RN-34 umbral 8 %; RN-71A sin BanRep/venta/cambio en no hábiles; RN-74 traslados pareados; RN-75 BanRep) |
| **Saldo simulado** | Saldo que evoluciona solo con el pronóstico y las acciones propuestas; no es real |
| **Selección** | 16 fines de mes (feb-2025 a jun-2026) donde se elige el modelo |
| **Snapshot** | Copia del maestro en una fecha (`ingestion_year/month/day`) |
| **SUP-xx** | Supuesto declarado en el registro final `pipeline/docs/supuestos.md` (SUP-01..SUP-53; SUP-41 reservado) |
| **TDV** | Transportadora de valores (TRANSPORTADORA_001 a 004; en `api/` de S3, TDV_001 a TDV_004): custodia los fondos y hace provisiones y recolecciones |
| **Traslado** | Movimiento de efectivo entre fondos (dos filas pareadas con la misma fecha de ejecución: origen y destino); llega al destino al día siguiente (SUP-52) y entre ciudades se cobra con la tarifa de la TDV del origen (SUP-53) |
| **U0–U7** | Unidades del pipeline (§8.2) |
| **V0–V4** | Conjuntos de variables del motor ML global (§4.4) |
| **Venta de efectivo** | Bancolombia vende billetes a empresas; su beneficio es la tasa histórica (`TASA` por cada 10.000 COP), no un costo del Anexo E |
| **WAPE** | Σ\|y − ŷ\| / Σ\|y\|, micro; métrica principal del pliego |
| **Winkler** | Puntaje de una banda que castiga a la vez su ancho y los reales que caen fuera |

---

## 13. Guía para el agente que lea esto

### 13.1 Qué abrir primero según la pregunta

| Pregunta | Abre primero |
|---|---|
| ¿Cómo instalo y corro todo? | `README.md` §5 y §6; luego `pipeline/corrida_entrega.sh` y `scripts/descargar_raw.sh` |
| ¿Qué modelo usa cada serie y por qué? | §4.4 de este documento; `pipeline/conf/model_u1_u2.yml`, `pipeline/conf/model_m3.yml`, `pipeline/conf/model_u4_u5.yml` (`modelo_alx`), `pipeline/conf/pronosticadores.yml` (`campeon_*`), `lab/conf/bandas.yml`, y la receta en `lab/conf/experimentos/<champion>.yml` |
| ¿Cómo entra un champion al pipeline? | `pipeline/src/daas/forecasting/laboratorio.py` → `ml/pronosticar.py` → `lab/forecasting/registry.py` |
| ¿Qué cambió ALX respecto de Santiago? | `pipeline/conf/alx.yml` (cada interruptor) y `pipeline/src/daas/alx.py`; §6.7 |
| ¿Cómo se calculan las métricas? | `pipeline/src/daas/forecasting/metrics.py`; §4.2 |
| ¿Cómo se trata el Anexo C? | `pipeline/conf/dq_rules.yml` y `pipeline/src/daas/quality/anexo_c.py` |
| ¿Cómo se corrige M6? | `pipeline/src/daas/modules/funds_m6/correccion_disponibles.py`, `simulator.py`, `pipeline/conf/model_u6.yml`; §4.7 |
| ¿Qué contiene el Excel o los contratos? | `entrega/POC_Efectivo_PRAGMA.xlsx` (v2), `entrega/output_api/`; los generadores en `pipeline/src/daas/publish/` |
| ¿Cómo se arma la publicación de S3 y cuál es la vigente? | `publicacion_s3/publicar.py` y `consumo-pronosticos/contratos/`; §7 (`v2/` vigente, `version_vigente.json`) |
| ¿Mi corrida coincide con la entregada? | `scripts/comparar_salidas.py` y el criterio del README §8; §8.3 |
| ¿Qué pasó con la imputación, SARIMA, el EDA o M5? | §6 de este documento; el detalle está en `ALX/` (Drive), empezando por `ALX/resumen_avances_v2.md` |
| ¿Cómo son las series (estacionariedad, estacionalidad, autocorrelación, calendario, relaciones)? | §6.2 de este documento; detalle en `ALX/eda/03_eda_box_jenkins_v2.ipynb` (Drive): §2–§7 un modelo por sección, §10 conclusiones por modelo |
| ¿Qué variables explican la serie y cuáles aportan al pronóstico? | §6.2 (tabla por modelo); `ALX/eda/03_eda_box_jenkins_v2.ipynb` §9 |
| ¿Por qué M5 subestima y qué se podría hacer? | §6.5; `Mi unidad/PoC-Bancolombia/.agents/tasks/eda-m5/final_report.md` y `ALX/eda/04_eda_m5.ipynb` (Drive); `ALX/plan_mejora_m5.md` |
| ¿Qué supuesto aplica? | §5 de este documento; texto completo en `pipeline/docs/supuestos.md` (registro final) |
| ¿Qué cambió en la v2 y por qué? | `entrega/CAMBIOS_v2.md`; §4.6, §4.7 y §5 de este documento; los interruptores v2 en `pipeline/conf/alx.yml` |
| ¿Cómo funciona M6 en la v2 (cajeros de sucursal, traslado T+1, operaciones, costo)? | §4.7; `pipeline/src/daas/modules/funds_m6/dataset.py` y `simulator.py`; SUP-12, SUP-14, SUP-52, SUP-53 |

### 13.2 Qué no asumir

- **No asumas que `output/api/` del bucket es el resultado vigente.** Es la salida del 9-oct del pipeline de Andrés (Excel `6e781aaa…`). Lo vigente es `entrega/` (v2) y `output/pronosticos/v2/` (ver `version_vigente.json`).
- **No asumas que una corrida nueva reproduce el sha256 del Excel.** Compara por contenido; la diferencia esperada son 1–2 ulp en alguna celda predictiva de M3 en la hoja 03 (F21 o F23) y la fecha de `docProps/core.xml`.
- **No asumas que las métricas de la hoja 03 son de la prueba ciega.** Son del backtest propio 17–31 ago; las de septiembre las calcula el banco.
- **No asumas que la mejora de M3 en la hoja 03 es del modelo.** Es casi toda SUP-02 (medición).
- **No asumas que la imputación está activa.** No se adoptó; `imputacion: false` y encenderlo aborta la corrida. `imputacion/contexto_asof.py` construye contexto, no imputa.
- **No asumas que `synthetic-data` en registros de Santiago significa datos sintéticos**, ni que su "LightGBM" es LightGBM (es HGB). Los champions de ALX sí usan LightGBM real (4.7.0).
- **No asumas que M6 es un pronóstico** ni que tiene WAPE.
- **No asumas que los Anexos A, B y C no se recibieron.** Se recibieron (están en `~/Desktop/datos-anexo-poc-bancolombia/` del equipo original, no en el repo); versiones anteriores de este documento decían lo contrario. Lo no recibido son `Historico BANREP.xlsx` e `Historico Traslados.xlsx` del Anexo A (SUP-46).
- **No asumas que el Excel de `entrega/` es el `52e7547f…`.** Es la v2 `167a52e4…`; la v1 está en el commit `955115d`. Y no asumas que `v0_provisional/` es lo vigente en S3: es la v1 conservada; la v2 está en `output/pronosticos/v2/`.
- **No uses los supuestos de Andrés** (`revision-andres/`, PDF de supuestos): desde el 26-oct manda el registro propio, que usa otra numeración desde SUP-15.
- **No asumas que M6 cuesta 0 ni que solo traslada y vende.** En la v2 cuesta 1.441.530 COP e incluye 4 retiros BanRep (§4.7).
- **No asumas que los perfiles `alx-poc`/`alx-mx` existen en tu equipo** ni que tienes permisos en esos buckets; pide acceso y usa `AWS_PROFILE_RAW`/`AWS_PROFILE` si tus perfiles se llaman distinto.
- **No asumas otra plataforma que macOS arm64** para `uv.lock`.
- **No asumas que `ALX/README.md` describe este repo** (es el README de Santiago, con comandos de `corrida_local.sh`, la landing y pruebas que aquí no están).
- **No asumas que las cifras de la fase 2 (18-oct) son las vigentes:** mandan las del escenario S1 (§4.4). Ante conflicto entre fuentes, manda la más reciente; en `CONTEXTO_CONVERSACION.md`, §20 y §21 mandan sobre las anteriores.
- **No asumas que hay pruebas automatizadas en el repo.**
- **No asumas que el notebook 02 (`02_eda_series_box_jenkins.ipynb`) es el EDA vigente.** Lo vigente es `03_eda_box_jenkins_v2.ipynb` (§6.2), y para M5 además `04_eda_m5.ipynb` (§6.5). Ninguno de los dos está en el repo.

### 13.3 Qué no hacer

- No escribir en S3 (ningún `aws s3 sync`, `cp` local → S3 ni `rm`), salvo pedido explícito de la persona.
- No ejecutar `aws sso login`, `aws sso logout` ni `aws configure sso`: pedir a la persona que renueve la sesión.
- No usar como `TRABAJO` una carpeta con contenido valioso: `corrida_entrega.sh` borra `data/` y `conf/` dentro de ella.
- No correr dentro de Google Drive ni dejar `.venv`, `__pycache__`, `mlruns/` o cachés en carpetas sincronizadas.
- No mover carpetas del repo ni cambiar `lab/conf/experimentos/`, `pipeline/conf/` (incluidos los interruptores v2 de `alx.yml`) o el Excel de `entrega/` sin acuerdo explícito: cambian el entregable.
- No ejecutar `publicacion_s3/publicar.py subir` ni cambiar sus salvaguardas o `PUBLICACIONES` sin pedido explícito; nunca borrar ni sobrescribir `v0_provisional/` ni `v2/`.
- No poner en 0 los días del Anexo C ni presentar como observado algo estimado (criterios de descarte del pliego).
