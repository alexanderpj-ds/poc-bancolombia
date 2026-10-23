# Contexto completo del proyecto para agentes LLM y personas que llegan sin contexto

**Qué es este archivo.** El contexto completo de lo hecho en el componente analítico de la PoC DaaS de Bancolombia (Pragma): qué se pidió, de dónde viene el código, qué datos hay y qué problemas tienen, qué modelos se probaron, cuáles se adoptaron y por qué, qué se descartó, cómo se publicó en S3, cómo se reproduce y qué queda pendiente. Está escrito para que un agente LLM (y la persona que lo usa) entienda el repositorio sin haber visto la conversación de trabajo ni la carpeta de trabajo original.

**Cómo se relaciona con el `README.md`.** El README es la guía práctica: instalar, correr, comparar. Este archivo explica el qué, el porqué, la historia, los hallazgos y el estado. Los comandos se citan del README tal cual; si alguna vez difieren, manda el README junto con el código.

**Fecha de corte de este documento:** 23-oct-2026. La entrega de la PoC es el 26-oct-2026.

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
7. Publicación en S3 (`v0_provisional`)
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

**Anexos del pliego** (§9.1): A metadatos de insumos, B reglas de negocio RN-xx (Word), C días sin registro y su tratamiento (Word), **D plantilla del Excel de entrega**, **E parámetros de costos**. **Nunca se recibieron A, B ni C**: las reglas RN-xx se conocen por el código y la documentación; los 27 días del Anexo C están en la configuración (`pipeline/conf/dq_rules.yml`). Los **originales de D y E** los entregó el banco el 21-oct-2026 y están versionados en `datos/raiz/anexos/Anexos/` (sha256 del D `a247fae77dcf5779e6e36e732af447945faa32a670555a03c0962237992c20ec`, del E `caaa399cbd21459303d6b738f949b8f52b89801104ac5bb3a392a4fb77097c97`; SUP-40). No existen en S3.

**Entregable principal: el Excel `entrega/POC_Efectivo_PRAGMA.xlsx`**, sha256 **`52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688`** (917.601 bytes, generado el 21-oct-2026 sobre la plantilla original del Anexo D). El pliego exige un único Excel `POC_Efectivo_<NOMBRE_PROVEEDOR>.xlsx` con 5 hojas obligatorias y conservar sin modificar las informativas. Contenido de las 6 hojas de este archivo (`ALX/analisis_repo_santiago.md` §12.4):

| Hoja | Filas | Contenido |
|---|---:|---|
| `01_Predicciones` | 9.690 | M1 435 × 15; M2 56 × 15 × 2 objetivos; M3 44 × 15 × 2; M4 5 × 15; M5 6 × 15. Del 1 al 15-sep, 0 nulos, 0 duplicados |
| `02_Plan_Operativo` | 2.592 | M1 1.349 provisiones + 53 sin acción; M2 28 provisiones + 719 recolecciones + 3 sin acción; M3 2 provisiones + 432 recolecciones + 6 sin acción. Con cupo, saldo antes/después, ocupación y costo |
| `03_Metricas_Desarrollo` | 105 | Métricas del **backtest propio 17–31 ago** (origen 16-ago): Global, Cali, Pasto, Ipiales, Semana 1 (17–23) y Semana 2 (24–31); de M6 solo métricas operativas y de costo |
| `04_Descripcion_Solucion` | 8 | Una fila por modelo × objetivo, con enfoque, variables, validación, limitaciones y supuestos SUP-xx |
| `05_M6_Fondos` | 565 | 6 fondos × 6 denominaciones × 15 días más filas extra de acciones; sin venta, BanRep ni intercambio en días no hábiles |
| `06_Diccionario_Campos` | 20 | Informativa, intacta |

`validate_xlsx.validate_anexo_d` da 0 errores. **Salvedad:** el pliego menciona además las hojas informativas `00_Instrucciones`, `GUIA_Descripcion_Solucion` y `07_Catalogo_Ejemplos`, pero la plantilla recibida no las trae; no se crearon porque el pliego prohíbe hojas adicionales (pregunta abierta P25, SUP-40).

**Contratos de salida del entregable:** `entrega/output_api/` (6 parquet con su `_schemas/*.json`): `predicciones` 10.230 filas (9.690 PROYECTADO de M1–M5 + 540 SIMULADO de M6), `recomendaciones` 2.923, `alertas` 2.590, `metricas` 46, `backtest` 15.804, `silenciosos` 15. Las bandas del 90 % solo están aquí (la plantilla no tiene columna para ellas).

**Entregable secundario:** la publicación provisional en S3 `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/` (revisión 2, 248 objetos), con la forma de los contratos OpenAPI del arquitecto (§7).

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
- **Qué tomó ALX de Santiago:** todo el pipeline (`pipeline/`), el laboratorio (`lab/`), el arnés y su regla, el conformal, los supuestos SUP-01..SUP-23 y el registro `ALX/pipeline/docs/supuestos.md` (que ALX continuó desde SUP-24), y sus modelos como referencia. Los cambios de ALX sobre el pipeline van **detrás de interruptores** (`pipeline/conf/alx.yml`): con todos apagados, el pipeline reproduce el Excel de Santiago celda a celda (105/105 filas de la hoja 03; §6.8).

### 2.3 El trabajo de ALX (Alexander Peláez, Pragma), 8 al 23-oct-2026

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

Ninguna corrección inventa datos: se deduplica, se convierten unidades, se excluyen subtotales o se marca como faltante. Fuentes: `CONTEXTO_CONVERSACION.md` §9, `ALX/guia_datos_bucket.md` §8 (21 problemas), `ALX/resumen_avances_v2.md` §3.4 y `ALX/pipeline/docs/supuestos.md`.

| # | Hallazgo | Tratamiento vigente |
|---|---|---|
| 1 | **Anexo C** (27 días, 14.568 cajero-días) | NaN en entrenamiento, simulación y métricas (SUP-02). Imputación evaluada y no adoptada (SUP-36) |
| 2 | **M6, TDV_001 con unidades mezcladas:** `valor` es cantidad de billetes hasta el 17-jul-2026 y pesos desde el 21-jul-2026 (`CALI\|` y `PASTO\|TRANSPORTADORA_001`). Sin corregir, el mínimo de M6 sale en miles de pesos y nunca detecta déficit | Se convierte a pesos lo que está en billetes, **detectado por datos** (un fondo-día está en billetes si menos del 50 % de sus filas distintas de 0 son múltiplo de la denominación): 49.212 filas. SUP-29 |
| 3 | **M6, filas `calidad = TOTAL`** en TDV_002 (hasta el 12-ago-2026) y TDV_003 (hasta el 29-jul-2026): subtotal que duplica el saldo y los mínimos/máximos | Se excluyen 16.423 filas (16.192 igualan exactamente la suma del resto). SUP-29 |
| 4 | **M6, 30 fondo-días con doble formato** (el `TOTAL` no iguala la suma; TDV_002 del 21 al 27-jul y 11–12-ago-2026; TDV_003 desde el 8-ene-2026) y **23 blancos** en `CALI\|TRANSPORTADORA_004\|50000` (9-jul a 11-ago-2026) | Salen de la ventana de mínimos y máximos (SUP-10) como faltantes. **Salvedad:** el reparto por denominación (SUP-09) todavía los usa (§11) |
| — | Efecto conjunto en M6 al 31-ago (36 fondo × denominación) | Saldo inicial igual en 36/36; estados de riesgo de 11 bajo mínimo / 7 sobre máximo a **4 / 6: cambian 10 de 36**. **[Contradicción resuelta]** El 8-oct, corrigiendo solo `TOTAL` y unidades, se contaban 5 / 5 y 8 cambios; la cifra vigente (con las tres correcciones) es 10 |
| 5 | **Sucursales: 13-may-2026 duplicado** (las 44 sucursales dos veces; entradas 111,0 → 55,5 mil M) | Se deduplica para entrenar y evaluar (SUP-35; interruptor `correcciones_datos`) |
| 6 | **Sucursales: 4 días sin dato** (6-dic-2024, 6-may-2025, 29 y 30-ago-2026) | Quedan NaN |
| 7 | **Cajeros desinstalados** 1120, 1121, 1122 y 5778 (3-ago-2026) | Pronóstico 0 los 15 días y fila `sin_accion` (regla de inactividad de Santiago). RN-07 saca de las métricas 25 cajeros de M1 y 4 de M2 (SUP-01). De 29 marcados RN-07, 23 son códigos reutilizados (SUP-06) |
| 8 | **Valores corruptos:** monto `884s0000` (cajero 6303, 25-jul-2026) y fecha `35/06/2026` | El monto deja el cajero-día como NaN; la fecha la descarta `processed` (SUP-35) |
| 9 | **Ceros de M3 en días hábiles de agosto de 2026:** 10-ago, 34 de 44 sucursales en 0; del 18 al 28-ago, 5 a 10 por día hábil (en julio, máximo 2) | Se conservan como cero real (dato entregado); como faltante solo se midió como sensibilidad (SUP-37). Bajan la cobertura de las bandas de M3. **Pendiente de confirmar con el banco** |
| 10 | **Maestro de cajeros "vigente" del 8-sep-2026**, posterior al corte (392 cajeros cambiaron de cupo y 144 de administrador; `estado` siempre `Produccion`) | Las variables de contexto usan el último snapshot ≤ cada origen ("as of", SUP-28): cambia algún atributo en el 20,4 % de los cajero-orígenes de M1 |
| 11 | **Menos cajeros reportando** del 10 al 25-ago-2026 (355–390 frente a unos 425) | Se deja como dato; explica buena parte de la distancia entre la lectura observada y la RN-08 |
| 12 | **SUP-02 no estaba implementado:** una entidad con todos sus reales en 0 en la ventana entraba al WAPE agregado | Sale solo del WAPE agregado; MAE, Bias y `n` la incluyen (SUP-27). En M3 baja el WAPE 3,1–4,9 pp **sin cambiar ningún pronóstico** (§4.4) |
| 13 | **Hueco de disponibles** del 31-jul al 9-sep-2024 (33 días hábiles) | No se imputa; no entra en ninguna ventana de M6 |
| 14 | **Clientes (M5):** 529 puntos frente a 344 esperados; ~217 activos en ago-2026; Pasto cae de 200–250 a 20–45 mil M/mes desde sep-2025; depósitos de hasta 203 mil M en un día; pocos "megapuntos" esporádicos dominan el sesgo | Se usan todos; diagnóstico en §6.5 |
| 15 | **CBR (M4):** de 39 puntos, solo 10 con movimiento en ago-2026; casi sin datos los domingos | Se modela tal cual |
| 16 | **Faltan fuentes para M6:** no hay histórico de traslados entre fondos ni de movimientos con BanRep (el pliego dice que el balance se construye con ellos) | BanRep se habilita por tarifa y solo en Cali (SUP-13); operaciones inferidas del histórico (SUP-08) |
| 17 | **Linaje en el bucket:** sin manifiestos `.meta.json`; un solo reporte de calidad del 6-oct en la réplica | Informativo |

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
| M6 | Fondos de las TDV | Ninguna: balance | fondo × denominación × día | 6 × 6 = 36 | Traslados, ventas, BanRep, cambios de denominación, con saldo antes/después y costo |

Total: 646 series pronosticadas y evaluadas (M1–M5) + 36 de balance (M6) = 682.

### 4.2 Métricas

Fórmulas oficiales sin cambios en `pipeline/src/daas/forecasting/metrics.py`:
- **WAPE** = Σ|Y − Ŷ| / Σ|Y| (principal; **micro**: se suman errores y reales de todas las entidades-día de la celda, no es un promedio por entidad).
- **MAE** = media de |Y − Ŷ| (COP).
- **Bias** = Σ(Ŷ − Y) / ΣY (negativo = subpronóstico).
- Pares con NaN se descartan; si Σ|Y| = 0 el resultado es NaN, nunca 0.

**Dos lecturas del real en cajeros.** *Observada*: un cajero-día sin registro es faltante (la usa el arnés y el entrenamiento). *RN-08*: si la red reportó ese día (y no es Anexo C), la ausencia vale 0; según el README de Santiago es la lectura con la que puntúa el banco, y es más exigente. M1 y M2 publican las dos (SUP-02). El Anexo B (donde está RN-08) nunca se recibió.

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
- Costos del Anexo E (`pipeline/conf/costos.yml`); cajero interurbano solo si su tipología lo dice (SUP-21); escala de sucursal desde `ubicacion` (SUP-22); acción de sucursal que se abastece a sí misma con costo 0 declarado (RN-04A). Costos del entregable vs Santiago: M1 169,0 → 158,5 M; M2 73,5 → 71,4 M; M3 148,9 → 147,7 M COP.
- Cajeros sin dato reciente se pronostican en 0 (RN-08 aplicada como pronóstico) y se listan en `silenciosos` (12 cajeros de M1 con 0 los 15 días: 4 desinstalados + 8 sin dato con la red operando; 3 de M2).

### 4.7 M6: cómo se calcula y reglas de recomendación

M6 **no entrena ni pronostica**: simula el balance por `fondo_id` × denominación a partir de los pronósticos de M1–M5 y recomienda acciones costeadas (`pipeline/src/daas/pipeline/run_u6.py`, `pipeline/src/daas/modules/funds_m6/`):
1. **Saldo inicial** = último disponible ≤ 31-ago por fondo y denominación, con disponibles corregidos (SUP-07, SUP-29).
2. **Efecto neto diario de M1–M5 por fondo** (signos en `efecto_m1_m5` de `pipeline/conf/model_u6.yml`: ingresos = `cash_in` de M2, `entradas` de M3, M4 y M5; egresos = `pagado` de M1 y M2, `salidas` de M3), con el flujo de cada cajero/sucursal imputado al fondo de los maestros, sin rezago (SUP-12). El total de M5 se multiplica por un **factor de red móvil** 1/(1 + sesgo), medido en los 3 últimos orígenes cerrados y acotado a [0,67; 1,5] (SUP-20; M4 no se corrige). Hoy la razón medida supera el tope y se aplica 1,5. **[Contradicción resuelta]** El texto de SUP-20 cita razones 1,98 / 1,83 / 1,76 (corrida de Santiago); con el champion vigente son 1,90 / 1,72 / 1,75, media 1,79 (`ALX/plan_mejora_m5.md` §2.5). En los dos casos el factor aplicado es 1,5.
3. **Reparto por denominación** según la mezcla histórica de los disponibles del fondo en 180 días (SUP-09).
4. **Mínimo y máximo** = percentiles 10 y 90 del saldo diario en 180 días (SUP-10).
5. **Simulador secuencial** (`simulator.py`): día a día aplica el efecto, detecta faltantes y excedentes, elige **una** alternativa de bajo costo por necesidad (traslado entre fondos, venta, BanRep, cambio de denominación o conservar) y la **aplica al saldo** (el saldo después de una acción es el antes de la siguiente). Traslados y cambios de denominación van en dos filas pareadas (RN-74). Sábados, domingos y festivos no admiten BanRep, ventas ni cambios de denominación (RN-71A). BanRep solo en Cali (SUP-13). La venta no tiene tarifa: su beneficio es la tasa histórica de ventas (SUP-23). Un excedente se conserva si guardarlo cuesta menos que actuar. Primero faltantes (mayor monto), luego excedentes.

Resultado en el entregable (hoja 05): 142 traslados en días hábiles + 58 en no hábiles (todos entre fondos de Cali, que el Anexo E no tarifa), 169 ventas, costo de traslados **253.905 → 0 COP** frente a Santiago (desaparece el único traslado con costo, Pasto → Ipiales, porque sin las filas `TOTAL` el mínimo de Ipiales baja de 2.535 M a 1.401 M), almacenamiento 52,3 → 43,4 M COP. M6 no reporta WAPE (SUP-11).

---

## 5. Supuestos SUP-xx vigentes

Texto completo (qué se asume, por qué, salvedad, evidencia y efecto) en `ALX/pipeline/docs/supuestos.md` (no está en el repo); la hoja 04 los cita por número. SUP-01 a SUP-23 y SUP-M3-01/02 vienen del registro de Santiago; SUP-24 a SUP-40 son de ALX. **[Contradicción resuelta]** El PDF de Andrés (`ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf`) coincide con este registro hasta SUP-14; desde SUP-15 los mismos números significan otra cosa (PDF SUP-15/16/17 = registro SUP-24/25/26; PDF SUP-18, MILP de fondos, no tiene equivalente). Manda el registro, que es el que cita la hoja 04.

| SUP | Significado |
|---|---|
| SUP-01 | RN-07: los cajeros activos en el maestro y presentes en desinstalados salen de WAPE, MAE y Bias en todos sus días (por cajero, no por entidad-día) y no calibran la banda; siguen en las salidas |
| SUP-02 | Un cero con la red operando es observación válida; los 27 días del Anexo C quedan nulos; entidad con denominador cero fuera del WAPE agregado; M1 y M2 publican lectura de entrenamiento y lectura RN-08 |
| SUP-03 | M1–M3 pronostican todos los días calendario del 1 al 15-sep |
| SUP-04 | Umbral de agotamiento de M1 = 8 % del cupo (RN-34) |
| SUP-05 | Cassette de depósitos de M2: sin efecto (el efectivo se recicla, RN-30) |
| SUP-06 | Código de cajero reutilizado = una sola serie (RN-06) |
| SUP-07 | Saldo inicial de M6 = último registro ≤ 31-ago por fondo y denominación |
| SUP-08 | Venta e intercambio habilitados por fondo según su histórico |
| SUP-09 | Reparto del efecto de M1–M5 por denominación según la mezcla de 180 días (salvedad abierta: aún sin las exclusiones de SUP-29) |
| SUP-10 | Mínimo/máximo de M6 = percentiles 10/90 del saldo en 180 días |
| SUP-11 | M6 sin WAPE: completitud y cobertura de recomendaciones |
| SUP-12 | Flujo de M1–M3 imputado al fondo de los maestros, el mismo día (RN-70) |
| SUP-13 | BanRep habilitado por tarifa del Anexo E y solo en Cali (RN-75) |
| SUP-14 | Intercambio y cambio de denominación dentro del fondo, regla determinista, no en días no hábiles |
| SUP-M3-01 | Saldo de la bóveda de M3 en [0, `cupo_max_suc`]; política por sucursal |
| SUP-M3-02 | `cupo_max_suc` vigente = último valor ≤ 31-ago |
| SUP-15 | No se le pone precio al agotamiento ni al efectivo quieto en cajeros y sucursales; frontera de márgenes m0/m25/m50 |
| SUP-16 | Lead time de provisión de M1 = 0 días (RN-11) |
| SUP-17 | Entidades con poca historia: el modelo global les comparte lo aprendido; respaldos documentados |
| SUP-18 | Nada posterior al corte entra a entrenar ni a elegir (el holdout de septiembre no se lee) |
| SUP-19 | El 8 % es umbral de alerta; la política de M1 es la del pliego (margen 0) |
| SUP-20 | Factor de red móvil sobre el total de M5 que consume M6, acotado a [0,67; 1,5] |
| SUP-21 | Cajero interurbano solo si su tipología de facturación lo dice |
| SUP-22 | Escala de la sucursal para el costo desde `ubicacion` |
| SUP-23 | Tasa de venta de M6 desde `consolidado_ventas` (no contractual) |
| SUP-24 | Métricas marcadas `origen_dato = ESTIMADO` |
| SUP-25 | Recomendaciones y alertas marcadas ESTIMADO, no SIMULADO |
| SUP-26 | `REAL` no aparece en `output/api/*` |
| SUP-27 | Entidad con denominador cero fuera solo del WAPE agregado, también en el arnés (precisa SUP-02) |
| SUP-28 | Variables V4 con el maestro "as of" (último snapshot de `cp_historico.xlsx` ≤ origen) |
| SUP-29 | Disponibles de M6 corregidos: sin `TOTAL`, TDV_001 en pesos, blancos y doble formato fuera de la ventana de SUP-10 |
| SUP-30 | Regla de adopción R1–R5 declarada antes de medir |
| SUP-31 | k = 2 en R1 por búsqueda múltiple |
| SUP-32 | Pesos congelados en los ensambles ponderados |
| SUP-33 | Contexto empaquetado en el modelo registrado (pyfunc de MLflow) |
| SUP-34 | Demanda censurada: se modela lo dispensado |
| SUP-35 | Duplicado del 13-may-2026 y valores corruptos: corrección de datos, no imputación |
| SUP-36 | Imputación de faltantes: evaluada y **no adoptada** |
| SUP-37 | Ceros dudosos de M3 en agosto de 2026 se leen como cero real |
| SUP-38 | Repetición acotada del ML con imputación (28 modelo-serie, decisión D1) |
| SUP-39 | Champions del laboratorio en el pipeline del entregable (`forecaster.modelo_alx`, receta congelada) |
| SUP-40 | Plantilla del Anexo D y tarifas del Anexo E originales en la corrida del entregable |

**SUP-41 no existe todavía:** es la recomendación de M5 v2 (factor de SUP-20 por fondo encogido 50 % con tope 1,5) que **no se aplicó** y espera decisión del usuario (§6.5).

Decisiones del usuario del 20-oct que fijaron varios SUP: principio rector "toda decisión defendible ante Bancolombia; ninguna puede exponer a un criterio de descarte; ante dos opciones válidas, la más conservadora y trazable, declarada y medida"; D1 repetición acotada a finalistas (SUP-38); D2 SUP-02 en el arnés y V4 "as of" antes de repetir el ML (SUP-27, SUP-28, SUP-30 a SUP-34); D3 solo corregir los disponibles de M6 (SUP-29), el SUP-09 nuevo para después; D4 registro de Santiago como base, sin renumerar, lo nuevo desde SUP-24. Directriz general: si una decisión técnica choca con el pliego, gana el pliego y se documenta.

---

## 6. Experimentos y resultados, incluidos los no adoptados

Regla general: casi todo el material experimental **no está en el repo** (no hace falta para generar los pronósticos) y sigue en `ALX/` sin cambios. Lo que sí está en el repo de cada experimento se indica en cada apartado. Tabla de ubicación al final (§6.9).

### 6.1 Paridad con Santiago (base de todas las comparaciones)

- `ALX/datos_poc.py` (`matriz_arnes`) lee los datos de S3 a memoria y replica exactamente el cargador del arnés de Santiago: recalculando 4 pronosticadores deterministas, 650 celdas con referencia en sus registros coinciden (mismo n, |dif WAPE| máx 9,7e-16). Ej.: M1 `naive_7` en el chequeo, n = 5.518, WAPE 0,47253283.
- `gbm_cal` y `gbm_cal_l1` difieren de los registros de Santiago en M1 (hasta 0,018) porque esas corridas son anteriores al orden determinista de filas que hoy tiene `global_gbm.py`; por eso **toda comparación usa la referencia recalculada en ALX en los dos lados**.
- La receta del pipeline recalculada en ALX reproduce la hoja 03 del Excel de Santiago en los 7 datasets (`ALX/ml/resultados/hoja03_vs_alx.csv`).

### 6.2 EDA por serie con Box-Jenkins (18-oct) — análisis, no modelo

- 682 series al mismo grano del pronóstico (no agregado, por decisión del usuario), con datos corregidos y el Anexo C como NaN. Pruebas: intermitencia ADI-CV², atípicos por STL robusto, λ de Guerrero, ADF y KPSS, `ndiffs`/`nsdiffs`, ACF/PACF, fuerza de tendencia y estacionalidad (STL/MSTL, 7 y 30 días), Ljung-Box, efectos de calendario por OLS con errores HAC y órdenes SARIMA candidatos. 242 series con tramo contiguo, 412 con un tramo rellenado solo para la prueba, 28 sin base.
- Hallazgos que guiaron el modelado: en cajeros manda el **calendario de pagos**, no la semana (M1: +51 % el día de pago, significativo en el 91 % de los cajeros; +39 % el día siguiente; +21 % los días 1–2; −45 % en festivos; estacionalidad semanal débil, F_s7 mediana 0,37); sucursales con estacionalidad semanal fuerte (0,81–0,82) e intermitencia por calendario; M4 errático con la peor cobertura (79 %); M5 errático (CV² 3,94) con cambio de régimen en la mitad de los fondos; M6 casi un paseo aleatorio con tendencia. Ljung-Box rechaza ruido blanco en el rezago 7 en el 78–100 % de las series.
- Dónde está: `ALX/eda/` (`box_jenkins.py`, `calcular_indicadores.py`, `graficos_bj.py`, `construir_notebook_02.py`, notebook `02_eda_series_box_jenkins.ipynb` con 17 secciones y 67 figuras, `resultados/` con `indicadores_series.{parquet,csv}` de 682 × 114, `acf_pacf.parquet`, `efectos_calendario.parquet`, `cobertura_grano.csv`, `efecto_correcciones.csv`, `rangos_series.csv`, `ceros_recientes.csv`). El EDA agregado inicial del 8-oct es `ALX/01_series_de_tiempo.ipynb` (con `ALX/graficos_poc.py`). **Nada de esto está en el repo** (el usuario excluyó los notebooks de análisis).

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

### 6.5 M5: sesgo estructural, diagnóstico y M5 v2 (22-oct) — no adoptado

- **Problema:** el champion de M5 subestima en 17 de 19 orígenes (Bias medio −20,9 % en selección, −24,7 % en bloqueados, −43,0 % en el chequeo; Santiago tiene el mismo patrón, −43,2 % en el chequeo). Empeora en 2026.
- **Diagnóstico** (`ALX/plan_mejora_m5.md`): el modelo acierta la mediana (P(y > ŷ) = 0,494) pero la suma real es 1,32 veces la pronosticada: cola derecha enorme. El 10 % de los días con mayor depósito explica el 143 % del sesgo; unos pocos "megapuntos" esporádicos (punto 220 de `CALI|TRANSPORTADORA_001`, mediana de 87 mil M por depósito; 276 y 27 de Pasto; 69 de Ipiales, 68,8 % del volumen histórico de ese fondo) explican cerca de la mitad. En el chequeo, un solo día (27-ago, 78,6 mil M del punto 220) explica el 35 %. Ninguna transformación del pronóstico mejora a la vez WAPE y Bias (frontera: f = 1,155 lleva el Bias a −8,7 % pero sube el WAPE 2,49 ± 0,97 pp): **elegir es una decisión de política, no de modelo**. La regla v1 rechaza por construcción toda corrección de sesgo. Plan priorizado P1–P9 (regla v2, corrección de sesgo móvil, variables de estado de los puntos, recencia, cuantiles, etc.), con preguntas al banco sobre esos clientes.
- **M5 v2** (`ALX/m5_mejora/`, regla v2 `conf/adopcion_m5_v2.yml` huella `688ae78b095e`, 17 orígenes frescos de días 15): **ningún candidato cumple**; el mejor (`cs50`, factor global encogido 50 %) baja el |Bias| de 20,9 % a 12,2 % pero cuesta +2,01 ± 1,09 pp de WAPE en selección. Recomendación del informe: dejar M5 sin cambios y ajustar solo SUP-20 a un factor por fondo encogido 50 % con tope 1,5 (sería SUP-41); para la corrida de septiembre da 1,5 en los 6 fondos, así que el Excel no cambiaría. **No se aplicó: la decisión es del usuario.** El Excel siguió en `52e7547f…`.
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

### 6.8 MLflow y cadena de verificación hasta el Excel

- Store local en el equipo original (no en el repo): `sqlite:////Users/alexanderpelaez/.mlflow/poc-daas/mlflow.db` y artefactos en `/Users/alexanderpelaez/.mlflow/poc-daas/artifacts`. Experimentos: 1 `poc-daas/lab-santiago-historico` (2.574 runs importados de los registros de Santiago), 2 `poc-daas/demo-autolog`, 3 `poc-daas/sarima-referencia` (196), 4–10 `poc-daas/ml/<serie>` (fase 2, 363–515 runs por serie, tag `adopcion_huella = 623420f48f04`), 11–17 `poc-daas/imputacion/<serie>`, más `poc-daas/ml/m5-v2`.
- Model Registry `poc-daas-ml-<serie>` con alias `@champion` (v5, salvo m3_salidas y m5 en v4) y `@challenger`; clase `ml.pronosticar.PronosticadorEscenario`. Las versiones de la fase 2 quedan con tag `estado = obsoleta`. También 7 SARIMA `poc-daas-sarima-<serie>@referencia`.
- **Cadena verificada:** (i) registro = arnés S1 en 28/28 comparaciones (≤ 1e-6); (ii) pipeline = arnés S1 en el chequeo (diferencia relativa 0 en seis datasets y 4·10⁻¹⁸ en M3 `entradas`); (iii) pipeline con todos los interruptores apagados = Excel de Santiago (105/105 filas de la hoja 03; hojas 01, 02, 04, 05 y 06 iguales celda a celda). Toda diferencia con Santiago la causa un interruptor de ALX.
- **El pipeline de este repo no usa MLflow** para pronosticar: corre las recetas congeladas (SUP-39). `lab/tracking/mlflow_tracking.py` está en el repo solo porque `ml/pronosticar.py` importa de él `PronosticadorPanel` y `a_matriz` (requiere el paquete `mlflow`, pero no levanta servidor ni escribe store).
- Pruebas: no están en el repo (decisión del usuario). En `ALX/`: `ALX/pipeline/tests` 325 en verde, `ALX/tests_alx` + `ALX/lab/tests` 260. **[Contradicción resuelta]** Hubo conteos inconsistentes del pipeline (339 / 323 / 344); el correcto al 21-oct es 325 (344 fue una invocación conjunta con `tests_alx`; 339 no tiene evidencia).

### 6.9 Dónde está cada material (fuera del repo, en `ALX/`)

| Material | Ruta en el Drive | Estado |
|---|---|---|
| EDA agregado (8-oct) y EDA por serie | `ALX/01_series_de_tiempo.ipynb`, `ALX/graficos_poc.py`, `ALX/eda/` | Análisis |
| SARIMA | `ALX/sarima/` | Descartado |
| Fase 2 ML (entrenamiento, adopción, MLflow) | `ALX/ml/` | Adoptado (en el repo solo `ml/pronosticar.py` y `ml/__init__.py`) |
| Imputación | `ALX/imputacion/` | No adoptada (en el repo solo `contexto_asof.py`, `datos.py`, `__init__.py`) |
| M5: diagnóstico y v2 | `ALX/plan_mejora_m5.md`, `ALX/m5_mejora/` | No adoptado |
| Laboratorio de Santiago (arnés, conformal, simuladores, explicabilidad, handoff, pruebas, conf) | `ALX/lab/` | En el repo solo `lab/forecasting/`, `lab/tracking/mlflow_tracking.py`, `lab/conf/experimentos/`, `lab/conf/bandas.yml` |
| Registros del laboratorio de Santiago | `ALX/resultados/*.jsonl` | Histórico |
| Supuestos completos | `ALX/pipeline/docs/supuestos.md`, `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf` | Vigente (registro) |
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

## 7. Publicación en S3 (`v0_provisional`)

### 7.1 Qué hay publicado

`s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/` (perfil `alx-mx`), **revisión 2 del 22-oct-2026**, 248 objetos, 9,6 MB. La genera `publicacion_s3/publicar.py generar <carpeta local>` a partir de `entrega/output_api/` y del Excel de `entrega/`; el script aborta si el sha256 del Excel no empieza por `52e7547fce59105a`, si la simulación recalculada no reproduce recomendaciones y alertas o si el disponible no coincide con el saldo inicial de M6. Lee a memoria del bucket destino `interim/cp_historico`, `interim/oficinas`, `interim/cp_desinstalados`, `processed/m1_atm_dispensador`, `processed/m2_atm_multifuncional`, `processed/m3_sucursales`, `processed/m6_fondos` y `processed/_dim/dim_fondo`, e importa lógica de `daas` sin reentrenar.

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

- `tablas/`: predicciones 10.230 filas, alertas 2.590, recomendaciones 2.923, metricas 46, backtest 15.804, silenciosos 15. Sus sha256 coinciden 6/6 con `entrega/output_api/`.
- `api/`: JSON con la forma del payload (`data`) de los contratos OpenAPI del arquitecto (`consumo-pronosticos/contratos/*.yaml`, flujos B, C, D y E), sin la envoltura `statusCode/...`. 1.176 instancias validan con **0 errores de esquema**. 646 series, 520 entidades con saldo simulado (423 cajeros, 53 multifuncionales, 44 sucursales), 6 fondos, 2.590 alertas.
- La revisión 2 tomó los contratos del arquitecto como especificación dominante y cerró las brechas de la r1 (ciudad en M1–M3, `disponibleObservado` de M6 36/36 = saldo inicial, saldo diario simulado, métricas por ciudad × bloque 35/35 y 21/21 iguales a la hoja 03, `diaCruce`/`servicioSugerido` 520/520, `fondoId` como `CIUDAD|TDV_00X` incluida TDV_004, criticidad del catálogo A-101…A-108, `tipoDato` SIMULADO). Se subió con `aws s3 sync --delete` **solo a ese prefijo** y se verificó por sha256.
- **Es una estructura PROVISIONAL** hasta que el arquitecto entregue la especificación de almacenamiento (formato, particionado, envoltura, nombre de versión, valor real de `corrida`, hoy `"0007"`). Política de versiones propuesta: prefijo por versión (`v0_provisional` → `v1`…), cada revisión sobrescribe la anterior y el versionado del bucket conserva el historial.
- Volver a la revisión 1: el bucket tiene versionado; el VersionId del `manifest.json` de r1 es `Fz0ZPux6iCZu6ZHNywyI8SiXcT8ZpvHL` (r2: `nvqHItw6rn3_bbH8b3MTU11o8ZxWeczZ`) y las 242 VersionId de r1 están en `ALX/publicacion_s3/revision/r2/versiones_revision1.tsv`. **[Contradicción resuelta]** La r1 tenía 242 objetos; la vigente (r2) 248 (247 archivos listados en el manifest + el manifest).

### 7.2 Discrepancias declaradas y preguntas al arquitecto

Nueve discrepancias semánticas declaradas (DS-1 a DS-9) y 11 preguntas con opciones A/B en `ALX/preguntas_arquitecto.md`: (1) layout, versión y `corrida`; (2) `DESBALANCE_DENOMINACION` no se genera (requiere banda del total del fondo); (3) `EXCEDENTE_NO_EVACUABLE` no se genera (no hay regla); (4) `CALI|TDV_004` incluida y nomenclatura `TDV_00X`; (5) mapeo de criticidad (884 CRITICA + 1.214 MEDIA en ALERTA_PROVISION, 199 MEDIA SUCURSAL_EXCESO, 26 CRITICA FALTANTE_FONDO, 267 MODERADA EXCEDENTE_FONDO); (6) asignación de `tipoDato`; (7) solo nivel POINT en series (no OVERVIEW/MODEL); (8) observado solo en la ventana 17–31 ago (47 de 646 series sin observado, nunca cero); (9) `reconstruido = false` en los 6 fondos; (10) MAE/Bias por celda calculados por nosotros; (11) días sin acción con saldoAntes = saldoDespues = cierre. Documento para el arquitecto sobre la estructura: `ALX/estructura_pronosticos_s3.md`.

### 7.3 `output/api/` y `output/anexo_d/` de los buckets NO son lo vigente

En **ambos** buckets, `output/api/` (predicciones, recomendaciones, alertas, metricas, esquemas, `optimizacion_m6.json` y `output/api/anexo_d/POC_Efectivo_PRAGMA.xlsx`) es la salida del **9-oct-2026 del pipeline de Andrés**; su Excel tiene sha256 **`6e781aaaab841de43e6adcfd9bf57204b29f3caf2741e2f7021c603a14a73a78`** (ETag `135e26638e9d3c419b45490adda97a68`, 561.969 B). `output/anexo_d/POC_Efectivo_PRAGMA.xlsx` de la réplica es del 8-oct (sha256 `515ab9d9…`). Ninguno es el entregable `52e7547f…`. Una verificación anterior que comparó el md5 local contra ese ETag dio una falsa alarma por eso. **No consumas `output/api/` como pronóstico vigente**: la publicación vigente es `output/pronosticos/v0_provisional/`.

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
cd /tmp && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO:$REPO/pipeline/src" AWS_PROFILE=alx-mx \
  "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" generar "$HOME/.cache/poc-daas/repo_v0_provisional"
```

Qué hace cada uno:
1. `uv sync --frozen` (desde la raíz del repo; luego `REPO=$PWD`): crea `.venv` con las versiones exactas.
2. `scripts/descargar_raw.sh`: `aws s3 cp` recursivo de `s3://poc-daas-bancolombia-replica-903641686926/raw/` a datos/raiz/raw (carpeta ignorada por git) con el perfil `alx-poc` (variable `AWS_PROFILE_RAW` para otro perfil, `AWS_BIN` para otro binario) y luego, desde `datos/raiz`, verifica los 19 archivos con `shasum -a 256 -c` contra `scripts/raw.sha256`.
3. `pipeline/corrida_entrega.sh <raiz> <trabajo> [python]`: corre U0 → U7 (`python -m daas.pipeline.run_u0` … `run_u7`). **Borra `"$TRABAJO/data"` y `"$TRABAJO/conf"` al iniciar** (usa una carpeta dedicada), copia la raíz y `pipeline/conf`, reescribe `paths.yml` a `default_scheme: local`, exporta `DAAS_SCHEME=local`, quita `DAAS_S3_BUCKET` y, antes de cada unidad, aborta si alguna ruta de salida no resuelve a `file://` (registro en `$TRABAJO/rutas.log`). Variables: `UNIDADES` (subconjunto), `REANUDAR=1` (no borra), `CONF_ALX=<otro alx.yml>` (p. ej. todos en `false` = pipeline de Santiago). Unos 15 min (la corrida oficial tardó 898 s). Salidas: `data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx`, `data/output/api/` (6 parquet + `*.meta.json` + `_schemas/`), `data/output/explicabilidad/importancias.parquet`, `interim/`, `processed/`, `features/`, `quality/reports/` y logs `u0.log` … `u7.log`.
4. `scripts/comparar_salidas.py <ref_api> <ref_xlsx> <nuevo_api> <nuevo_xlsx>`: compara por contenido (parquet y celdas del Excel).
5. `publicacion_s3/publicar.py generar <carpeta>`: arma `v0_provisional` en local (lee S3 con `alx-mx`; `AWS_PROFILE` lo cambia). Publica **el Excel del repo**, no uno regenerado. `publicar.py verificar <carpeta>` comprueba una descarga contra su manifest. La subida (`aws s3 sync`) **no forma parte del flujo** del repo y no debe ejecutarse para verificar.

Unidades del pipeline: U0 ingesta raw → interim, calidad, curado → processed, features y costos del Anexo E; U1/U2 M1 y M2 (pronóstico, simulación de saldo, provisiones, recolecciones, alertas); U3 M3; U4/U5 M4 y M5; U6 M6; U7 contratos `output/api/*`, Excel del Anexo D y `validate_xlsx`.

### 8.3 Qué diferencias esperar

Una corrida nueva **no** reproduce el sha256 del Excel: el xlsx guarda la fecha de generación (`docProps/core.xml`) y los floats llevan ruido de ~1e-7 por sumas paralelas (Prophet/joblib) y orden de reducción (LightGBM/numpy). Criterio de equivalencia (README §8, el mismo de `ALX/ml/verificar_registro.py`): mismas hojas, filas, columnas y esquema arrow; celdas de texto y fecha idénticas; en numéricas Σ|dif| / Σ|ref| ≤ 1e-6 por columna. Solo `silenciosos.parquet` y los `_schemas/*.json` pueden coincidir byte a byte. `run_id` usa `git rev-parse --short HEAD`; sin commit queda `nogit` (solo afecta a `*.meta.json`).

**Evidencia (corrida auditada del 23-oct-2026, 12:28–12:43, 14 min)** sobre una copia de `ALX/` en `/tmp`, con el venv original (mismas versiones que `uv.lock`), los mismos raw y anexos, y `corrida_entrega.sh` con el hook de auditoría:

| Salida | Resultado frente a `entrega/` |
|---|---|
| Excel | sha256 `3450ff60…` vs `52e7547f…`; 6 hojas con las mismas dimensiones; **1 celda distinta: `03_Metricas_Desarrollo!F23`** (Bias de M3 `entradas`), 0.02064426798851951 vs 0.02064426798851952 (1 ulp). En el zip difieren `docProps/core.xml` (fecha) y `xl/worksheets/sheet3.xml` (esa celda) |
| `silenciosos.parquet` y los 6 `_schemas/*.json` | Idénticos byte a byte |
| alertas, backtest, metricas, predicciones, recomendaciones | Mismas filas, columnas y esquema; diferencias ≤ 9,5e-7 COP absolutas y ≤ 2,8e-18 relativas (máx. `predicciones.band_high`) |

Conclusión: equivalente; la causa es punto flotante y la marca de tiempo, no modelo ni datos.

**Verificación rápida desde una copia limpia del índice del repo** (23-oct): `uv sync --frozen` OK (122 paquetes, subconjunto exacto del freeze); importación de los 107 módulos de `daas`, `ml`, `lab`, `imputacion` y `datos_poc` OK (`MODELS` del registro = 85); descarga de raw 19/19 sha256 OK; **arranque U0** (`UNIDADES="u0"`) en 29 s con `rutas.log` en ok y **los 32 parquet de `interim/`, `processed/` y `features/` iguales (`DataFrame.equals`) 32/32** a los de la corrida oficial; `publicar.py` importa y sus rutas existen.

**No se repitió desde el repo** (por la prioridad del usuario): el pipeline completo U1–U7, `comparar_salidas.py` y `publicar.py generar`. Las tablas de `publicar.py` son copia de `entrega/output_api` y deberían coincidir byte a byte con S3, pero eso no se verificó desde el repo.

### 8.4 Cómo se regeneró el entregable original

La corrida oficial del 21-oct usó el mismo `corrida_entrega.sh` con la raíz `~/.cache/poc-daas/corrida_entrega/raiz/` (raw copiado del bucket en solo lectura + anexos originales) y escribió en `~/.cache/poc-daas/corrida_entrega/completa/`; luego el Excel y `data/output/api/` se copiaron a `ALX/entrega/`, se validó con `daas.publish.validate_xlsx.validate_anexo_d` y se registró el sha256. Si cambia algo (p. ej. respuestas del banco) y se regenera, el sha256 cambiará y `publicar.py` exigirá actualizar `EXCEL_SHA_PREFIJO`: eso es un cambio de código y de entregable que requiere acuerdo del usuario.

---

## 9. Acceso a AWS

- **Sesión SSO `poc-bancolombia`** (definida en `~/.aws/config`, junto con el start URL del portal; no está en el repo). Sobre ella hay dos perfiles del AWS CLI que comparten la sesión, así que basta un login:

  | Perfil | Cuenta | Rol | Uso |
  |---|---|---|---|
  | `alx-poc` | 903641686926 | `AWSBedrockFullAccess` | Réplica en **solo lectura** (descarga de `raw/`; también `datos_poc.py`) |
  | `alx-mx` | 777937796305 | `Ps-HackatonAgentic-Mexico` | Bucket destino: lo lee `publicar.py`; ahí está `v0_provisional` |

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
- **S3 es solo lectura** para todo el flujo del repo (`ls`, `head-object`, `cp` S3 → local). La única escritura que se hizo en S3 fue la publicación de `v0_provisional` del 22-oct (manual, con `alx-mx`, solo a ese prefijo).

---

## 10. Mapa del repo archivo por archivo

232 archivos versionados (los 231 iniciales + este). Toda ruta entre comillas invertidas de esta sección es un archivo versionado (existe en `git ls-files`); lo que no está versionado (carpetas generadas o ignoradas) se escribe sin comillas invertidas. La raíz del repo equivale a la raíz de la carpeta ALX (no muevas carpetas: varios módulos localizan la raíz por posición relativa).

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
| `entrega/POC_Efectivo_PRAGMA.xlsx` | Excel entregado (sha256 `52e7547f…4688`). Referencia de comparación y entrada obligatoria de `publicacion_s3/publicar.py` |
| `entrega/output_api/predicciones.parquet` | 10.230 filas: pronóstico por entidad-día con `band_low`/`band_high` y `origen_dato` |
| `entrega/output_api/recomendaciones.parquet` | 2.923 filas: acciones de M1–M3 y M6 con monto, costo y saldos |
| `entrega/output_api/alertas.parquet` | 2.590 alertas |
| `entrega/output_api/metricas.parquet` | 46 filas de métricas (incluye lecturas RN-08 y bloque `sesgo_red_origen`) |
| `entrega/output_api/backtest.parquet` | 15.804 filas del backtest 17–31 ago |
| `entrega/output_api/silenciosos.parquet` | 15 entidades sin dato reciente y su tratamiento |
| `entrega/output_api/_schemas/predicciones.json`, `entrega/output_api/_schemas/recomendaciones.json`, `entrega/output_api/_schemas/alertas.json`, `entrega/output_api/_schemas/metricas.json`, `entrega/output_api/_schemas/backtest.json`, `entrega/output_api/_schemas/silenciosos.json` | Esquemas versionados de cada contrato |

La carpeta datos/raiz/raw no está versionada: la llena `scripts/descargar_raw.sh`.

### 10.3 Configuración del pipeline (`pipeline/conf/`) y punto de entrada

| Ruta | Rol |
|---|---|
| `pipeline/corrida_entrega.sh` | **Punto de entrada** U0 → U7 en modo local (ver §8.2) |
| `pipeline/conf/alx.yml` | Interruptores de ALX (todos `true` salvo `imputacion: false`) |
| `pipeline/conf/paths.yml` | Capas y raíz de datos (`pipeline/corrida_entrega.sh` lo reescribe a `default_scheme: local`) |
| `pipeline/conf/sources.yml` | Mapa de las 19 fuentes de raw + Anexo E a los contratos C-01..C-12 |
| `pipeline/conf/dq_rules.yml` | Reglas de calidad, los 27 días del Anexo C y el corte |
| `pipeline/conf/calendario_co.yml` | Calendario de Colombia |
| `pipeline/conf/costos.yml` | Reglas de costos del Anexo E (tipologías de cajero y sucursal) |
| `pipeline/conf/entity_id_map.yml` | Mapa de identificadores de entidades |
| `pipeline/conf/export_anexo_d.yml` | Configuración y validación del Excel del Anexo D (textos de la hoja 04, bandas de `nivel_riesgo`) |
| `pipeline/conf/model_u1_u2.yml` | M1 y M2: `forecaster.modelo` (Santiago) y `forecaster.modelo_alx` (champions), política, inactividad, métricas |
| `pipeline/conf/model_m3.yml` | M3: recetas (`modelo_alx: {entradas: campeon_m3_entradas, salidas: campeon_m3_salidas}`) y política por sucursal |
| `pipeline/conf/model_u4_u5.yml` | M4 y M5: `modelo_alx: {m4: combo_perfil_gbml1, m5: campeon_m5}` |
| `pipeline/conf/model_u6.yml` | M6: saldo inicial, mezcla, mínimos/máximos, factor de M5 (`correccion_total`), `correccion_disponibles`, operaciones, decisión y costos |
| `pipeline/conf/pronosticadores.yml` | Recetas de pronóstico (incluidas `campeon_*` de la familia `ml_laboratorio`), bandas conformales y textos de enfoque por modelo |

### 10.4 Paquete `daas` (`pipeline/src/daas/`, 94 módulos)

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
| `pipeline/src/daas/modules/funds_m6/dataset.py` | Insumos de M6 (disponibles, mezcla, mínimos/máximos, factor de M5) |
| `pipeline/src/daas/modules/funds_m6/simulator.py` | Simulador secuencial de balance y decisiones de M6 |
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
| `pipeline/src/daas/publish/anexo_d/sheet_04_description.py` | Hoja 04 |
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
| `publicacion_s3/publicar.py` | `generar <carpeta>`: arma `v0_provisional` en local (r2); `verificar <carpeta>`: comprueba una descarga contra su manifest. Perfil por defecto `alx-mx` |
| `consumo-pronosticos/contratos/openapi-datos-flujo-b.yaml` | OpenAPI del flujo B (series, métricas, saldo simulado) |
| `consumo-pronosticos/contratos/openapi-datos-plan-flujo-c.yaml` | OpenAPI del flujo C (plan de saldo simulado) |
| `consumo-pronosticos/contratos/openapi-datos-fondos-flujo-d.yaml` | OpenAPI del flujo D (mapa de fondos) |
| `consumo-pronosticos/contratos/openapi-datos-alertas-flujo-e.yaml` | OpenAPI del flujo E (alertas) |

---

## 11. Pendientes, preguntas abiertas, riesgos y limitaciones

### 11.1 Pendientes inmediatos

1. **Commit y push de este repo** a `https://github.com/alexanderpj-ds/poc-bancolombia.git` (rama `main`): los hace el usuario. Hoy todo está staged y sin commit.
2. Entrega de la PoC el **26-oct-2026**; sustentación presencial en Medellín.
3. Backend Java y frontend Angular + Power BI: fuera de este repo (§1).
4. Respuesta del arquitecto a las 11 preguntas (§7.2) y especificación definitiva de almacenamiento; luego, pasar de `v0_provisional` a `v1`.
5. Decidir si el bucket destino `777937796305` pasa a ser la fuente de datos (hoy la réplica lo es para `raw/`).
6. Decidir sobre M5: aplicar o no la recomendación SUP-41 de M5 v2 (no cambia el Excel de septiembre) o alguna opción del plan de M5.
7. Decidir si la hoja 03 publica también el WAPE de M3 sin SUP-02 (hoy está en el comentario y en los documentos; exige regenerar el Excel).

### 11.2 Preguntas abiertas al banco

(`ALX/resumen_avances_v2.md` §15.7; `ALX/pipeline/docs/supuestos.md`, "Preguntas abiertas"; `ALX/plan_mejora_m5.md` §6)
1. ¿Los ceros de sucursales en días hábiles de agosto de 2026 son cierres reales o falta de reporte? (SUP-37)
2. ¿Cómo trata la métrica oficial una entidad con todos sus reales en 0 en la ventana? (SUP-27)
3. ¿Cuál es la regla exacta de RN-08? ¿Se puede compartir el Anexo B?
4. ¿Los disponibles de la TDV_001 están en billetes hasta el 17-jul-2026 y en pesos desde el 21-jul? (SUP-29)
5. ¿`TOTAL` de la TDV_002 y TDV_003 es el subtotal de las demás calidades? (SUP-29)
6. ¿Qué son los 23 blancos de `CALI|TRANSPORTADORA_004|50000`? (SUP-29)
7. En los 30 fondo-días con doble formato, ¿cuál es el oficial? (SUP-29, SUP-09)
8. ¿Hay que incluir `00_Instrucciones`, `GUIA_Descripcion_Solucion` y `07_Catalogo_Ejemplos`, que la plantilla no trae? (P25, SUP-40)
9. Puntos 220 (Cali), 276 y 27 (Pasto) y 69 (Ipiales) de M5: ¿depósitos programados? ¿El banco conoce su fecha o monto?
10. Como M5 alimenta M6, ¿prefiere un M5 centrado (Bias ≈ 0) aunque suba el WAPE?
11. ¿La evaluación de septiembre incluye los depósitos extraordinarios de clientes?
12. ¿`CALI|TRANSPORTADORA_004` es una transportadora nueva desde may-2026?

También vigentes de la revisión de datos del 8-oct: la caída de cajeros que reportan del 10 al 25-ago, la vigencia del universo de clientes (529 frente a 344) y la falta de histórico de traslados y de movimientos con BanRep.

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
- `publicar.py` exige el Excel `52e7547f…` y depende de `interim/` y `processed/` del bucket destino (sesión `alx-mx` vigente).
- No hay pruebas automatizadas en el repo (están en `ALX/`).
- No se repitió desde el repo la corrida completa ni `publicar.py generar` (§8.3).
- El repo no trae el laboratorio completo: no se puede re-elegir modelos ni recalibrar bandas desde aquí (eso vive en `ALX/lab/` y `ALX/ml/`).

### 11.5 Mejoras para después de la entrega

SUP-09 nuevo (reparto de `pagado` de M1/M2 por gavetas y el resto por mezcla de movimientos); regla de adopción v2 en orígenes nuevos (sep–oct 2026); repetición completa del ML con imputación; CQR o conformal adaptativo (ACI), sobre todo para M3; variables de estado de los puntos para M5 (P3) y demás del plan de M5; revisar M4 con `ml_ens_campeon_ml_m4`; variable de silencios RN-08.

---

## 12. Glosario

| Término | Significado |
|---|---|
| **ALX** | Carpeta de trabajo de Alexander Peláez en el Drive del proyecto; copia del repo de Santiago más todo el trabajo nuevo. En el código, nombre de la raíz del repo |
| **Anexo A–E** | Anexos del pliego: A metadatos, B reglas de negocio RN-xx (no recibido), C días sin registro (no recibido como documento), D plantilla del Excel, E costos |
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
| **RN-xx** | Reglas de negocio del Anexo B, conocidas por el código y la documentación (RN-07 desinstalados; RN-08 ausencia con red operando = 0; RN-34 umbral 8 %; RN-71A sin BanRep/venta/cambio en no hábiles; RN-74 traslados pareados; RN-75 BanRep) |
| **Saldo simulado** | Saldo que evoluciona solo con el pronóstico y las acciones propuestas; no es real |
| **Selección** | 16 fines de mes (feb-2025 a jun-2026) donde se elige el modelo |
| **Snapshot** | Copia del maestro en una fecha (`ingestion_year/month/day`) |
| **SUP-xx** | Supuesto declarado en el registro (`ALX/pipeline/docs/supuestos.md`) |
| **TDV** | Transportadora de valores (TRANSPORTADORA_001 a 004; en `api/` de S3, TDV_001 a TDV_004): custodia los fondos y hace provisiones y recolecciones |
| **Traslado** | Movimiento de efectivo entre fondos (dos filas pareadas: origen y destino) |
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
| ¿Qué contiene el Excel o los contratos? | `entrega/POC_Efectivo_PRAGMA.xlsx`, `entrega/output_api/`; los generadores en `pipeline/src/daas/publish/` |
| ¿Cómo se arma la publicación de S3? | `publicacion_s3/publicar.py` y `consumo-pronosticos/contratos/`; §7 |
| ¿Mi corrida coincide con la entregada? | `scripts/comparar_salidas.py` y el criterio del README §8; §8.3 |
| ¿Qué pasó con la imputación, SARIMA, el EDA o M5? | §6 de este documento; el detalle está en `ALX/` (Drive), empezando por `ALX/resumen_avances_v2.md` |
| ¿Qué supuesto aplica? | §5 de este documento; texto completo en `ALX/pipeline/docs/supuestos.md` |

### 13.2 Qué no asumir

- **No asumas que `output/api/` del bucket es el resultado vigente.** Es la salida del 9-oct del pipeline de Andrés (Excel `6e781aaa…`). Lo vigente es `entrega/` y `output/pronosticos/v0_provisional/`.
- **No asumas que una corrida nueva reproduce el sha256 del Excel.** Compara por contenido; la diferencia esperada es 1 celda en el último decimal (F23 de la hoja 03).
- **No asumas que las métricas de la hoja 03 son de la prueba ciega.** Son del backtest propio 17–31 ago; las de septiembre las calcula el banco.
- **No asumas que la mejora de M3 en la hoja 03 es del modelo.** Es casi toda SUP-02 (medición).
- **No asumas que la imputación está activa.** No se adoptó; `imputacion: false` y encenderlo aborta la corrida. `imputacion/contexto_asof.py` construye contexto, no imputa.
- **No asumas que `synthetic-data` en registros de Santiago significa datos sintéticos**, ni que su "LightGBM" es LightGBM (es HGB). Los champions de ALX sí usan LightGBM real (4.7.0).
- **No asumas que M6 es un pronóstico** ni que tiene WAPE.
- **No asumas que existen los Anexos A, B y C** ni que conoces RN-xx con certeza: se infieren del código y la documentación.
- **No asumas que los perfiles `alx-poc`/`alx-mx` existen en tu equipo** ni que tienes permisos en esos buckets; pide acceso y usa `AWS_PROFILE_RAW`/`AWS_PROFILE` si tus perfiles se llaman distinto.
- **No asumas otra plataforma que macOS arm64** para `uv.lock`.
- **No asumas que `ALX/README.md` describe este repo** (es el README de Santiago, con comandos de `corrida_local.sh`, la landing y pruebas que aquí no están).
- **No asumas que las cifras de la fase 2 (18-oct) son las vigentes:** mandan las del escenario S1 (§4.4). Ante conflicto entre fuentes, manda la más reciente; en `CONTEXTO_CONVERSACION.md`, §20 y §21 mandan sobre las anteriores.
- **No asumas que hay pruebas automatizadas en el repo.**

### 13.3 Qué no hacer

- No escribir en S3 (ningún `aws s3 sync`, `cp` local → S3 ni `rm`), salvo pedido explícito de la persona.
- No ejecutar `aws sso login`, `aws sso logout` ni `aws configure sso`: pedir a la persona que renueve la sesión.
- No usar como `TRABAJO` una carpeta con contenido valioso: `corrida_entrega.sh` borra `data/` y `conf/` dentro de ella.
- No correr dentro de Google Drive ni dejar `.venv`, `__pycache__`, `mlruns/` o cachés en carpetas sincronizadas.
- No mover carpetas del repo ni cambiar `lab/conf/experimentos/`, `pipeline/conf/` o el Excel de `entrega/` sin acuerdo explícito: cambian el entregable y rompen `publicar.py`.
- No poner en 0 los días del Anexo C ni presentar como observado algo estimado (criterios de descarte del pliego).
