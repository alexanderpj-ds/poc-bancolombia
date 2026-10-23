# PoC DaaS Bancolombia: pronósticos de efectivo (Pragma)

Guía para personas y agentes LLM. Este repo contiene **solo** lo indispensable para reproducir los dos resultados vigentes de la PoC:

1. El Excel del Anexo D `entrega/POC_Efectivo_PRAGMA.xlsx` (sha256 `52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688`).
2. La publicación provisional en S3 `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/` (revisión 2, 248 objetos).

Qué entró y qué no se decidió con una corrida auditada que registró cada archivo abierto y cada módulo cargado (§9). Todo lo demás (imputación, EDA, SARIMA, mejora de M5, notebooks, revisiones, resúmenes) quedó fuera del repo y sigue en la carpeta `ALX/` del Google Drive del proyecto (§12).

**Contexto completo del proyecto:** [`CONTEXTO_LLM.md`](CONTEXTO_LLM.md). Léelo primero si vas a analizar el repo (o pídele a tu agente que lo haga): explica la historia, los datos, los modelos y su adopción, los supuestos, los experimentos no adoptados, la publicación en S3, los pendientes y qué no asumir. Las reglas para agentes están en [`AGENTS.md`](AGENTS.md).

## Índice

1. Propósito
2. Modelos y grano
3. Arquitectura y flujo de datos
4. Mapa del repo
5. Requisitos y acceso a AWS
6. Ejecutar todo el proceso
7. Salidas y dónde quedan
8. Comparación con la referencia y criterio de equivalencia
9. Evidencia de reproducibilidad
10. Supuestos (SUP-xx)
11. Decisiones adoptadas y descartadas
12. Material no incluido en el repo
13. Limitaciones

## 1. Propósito

PoC de *Data as a Service* para la administración del efectivo de Bancolombia (segunda ronda, Pragma). Con corte al **31-ago-2026** se pronostica el horizonte **1 al 15-sep-2026** de cajeros, multifuncionales, sucursales y fondos, y se generan el plan operativo (provisiones, recolecciones, traslados), las alertas y las métricas del backtest (17–31 ago). El entregable formal es el Anexo D (Excel de 6 hojas). La misma información se publica en S3 con la forma de los contratos OpenAPI del arquitecto (flujos B, C, D y E).

La base es el pipeline de Santiago Higuita (`pipeline/`; las salidas antiguas de `output/api/` en los buckets son del pipeline de Andrés Vergara). ALX agregó, detrás de interruptores (`pipeline/conf/alx.yml`), los champions de ML del laboratorio, el contexto "as of", correcciones de datos y supuestos nuevos.

## 2. Modelos y grano

| Modelo | Entidad × tiempo | Variable(s) | Entidades | Champion (backtest 17–31 ago) |
|---|---|---|---|---|
| M1 | cajero dispensador × día | `pagado` | 435 | `ml_lgbm_v4_tw` (LightGBM, V4, Tweedie) |
| M2 | multifuncional × día | `pagado`, `cash_in` | 56 | `ml_ens_pond_m2_pagado`, `ml_ens_pond_m2_cash_in` (ensambles ponderados congelados) |
| M3 | sucursal × día | `entradas`, `salidas` | 44 | `ml_ens_pond_m3_entradas`, `ml_lgbm_v1_l1` |
| M4 | fondo (CIUDAD\|TRANSPORTADORA) × día | ingreso CBR (corresponsales) | 5 | `combo_perfil_gbml1` (receta de Santiago; ningún candidato cumplió R1–R5) |
| M5 | fondo × día | ingreso de clientes | 6 | `ml_ens_media_top3_m5` (media de 3 LightGBM) |
| M6 | fondo × denominación × día | saldo proyectado + traslados, ventas y BanRep | 6 × 6 | balance determinista (no es un modelo estadístico) |

Las recetas de cada champion están en `lab/conf/experimentos/*.yml` y se eligen en `pipeline/conf/model_*.yml` (`forecaster.modelo_alx`).

WAPE global del backtest 17–31 ago (Santiago → entregable): M1 0,2551 → 0,2490; M2 pagado 0,3652 → 0,3642; M2 cash-in 0,3868 → 0,3832; M3 entradas 0,4219 → 0,3884; M3 salidas 0,4577 → 0,4166; M4 0,3196 → 0,3196; M5 0,5668 → 0,5160. En M3, SUP-02 excluye del WAPE 3 sucursales en entradas y 4 en salidas.

## 3. Arquitectura y flujo de datos

Capas (medallion, `pipeline/conf/paths.yml`): **raw → interim → processed → features → output** (+ `quality`). Cada dataset se nombra con una URI abstracta `daas://<capa>/<dataset>`, que `daas.io.storage` resuelve a `file://<root>/<capa>/<dataset>.parquet` (local) o `s3://<bucket>/<capa>/<dataset>.parquet`.

| Unidad | Módulo | Qué hace |
|---|---|---|
| U0 | `daas.pipeline.run_u0` | Ingesta de raw → interim, calidad (DQ), curado → processed, features, costos del Anexo E |
| U1/U2 | `daas.pipeline.run_u1_u2` | Pronóstico y plan de M1 y M2 (simulación de saldo, provisiones, recolecciones, alertas) |
| U3 | `daas.pipeline.run_u3` | Pronóstico y plan de M3 |
| U4/U5 | `daas.pipeline.run_u4_u5` | Pronóstico de M4 y M5 |
| U6 | `daas.pipeline.run_u6` | Balance de M6 por denominación y traslados |
| U7 | `daas.pipeline.run_u7` | Contratos `output/api/*`, Excel del Anexo D y `validate_xlsx` |

Cómo entran los champions de ML: `daas/forecasting/laboratorio.py` (familia `ml_laboratorio`) llama a `ml.pronosticar.pronosticar`, que usa `lab.forecasting.registry` (`MODELS`) con las recetas congeladas de `lab/conf/experimentos/`. El contexto V4 "as of" lo construye `imputacion.contexto_asof` (solo contexto: **no imputa**; SUP-28).

Interruptores de `pipeline/conf/alx.yml`: `campeones_ml`, `contexto_asof`, `correcciones_datos`, `correccion_m6`, `sup02_denominador_cero`, `origen_dato` y `supuestos_alx` en `true`; `imputacion: false` (encenderlo aborta la corrida, SUP-36). Con todos en `false` el pipeline se comporta como el de Santiago.

Después del pipeline, `publicacion_s3/publicar.py` toma `entrega/output_api/` y el Excel de `entrega/`, lee a memoria maestros e insumos de `interim/` y `processed/` del bucket 777937796305 (`INSUMOS_S3`) e importa funciones de `daas` (simulación M1–M3, corrección de disponibles M6, métricas) para armar `v0_provisional` en una carpeta local.

Buckets (us-east-1):

| Bucket | Cuenta | Perfil | Uso |
|---|---|---|---|
| `poc-daas-bancolombia-replica-903641686926` | 903641686926 | `alx-poc` | Réplica, **solo lectura**. Fuente de `raw/` (19 objetos, 110.501.133 bytes) |
| `poc-daas-bancolombia-777937796305` | 777937796305 | `alx-mx` | Bucket destino. `raw/` idéntico (19/19). Lo lee `publicar.py`; aloja `output/pronosticos/v0_provisional/` |

Ojo: `output/api/` y `output/anexo_d/` de ambos buckets son salidas del 8–9-oct del pipeline de Andrés, **no** el entregable vigente (el Excel del bucket tiene sha256 `6e781aaa…`). La publicación vigente de ALX es `output/pronosticos/v0_provisional/`.

## 4. Mapa del repo

El layout replica las rutas relativas de la carpeta `ALX/` original: `ml/__init__.py`, `lab/__init__.py` e `imputacion/__init__.py` agregan la raíz y `pipeline/src` a `sys.path` por posición relativa, `corrida_entrega.sh` usa su carpeta padre como raíz y `publicar.py` usa `parents[1]`. **No muevas carpetas.**

| Ruta | Qué es |
|---|---|
| `README.md`, `AGENTS.md` | Esta guía y las reglas para agentes |
| `CONTEXTO_LLM.md` | Contexto completo del proyecto para personas y agentes LLM (leer primero) |
| `pyproject.toml`, `uv.lock`, `.python-version` | Entorno exacto (Python 3.11.16, versiones del venv que generó el entregable). `package = false`: `daas` corre por PYTHONPATH |
| `.gitignore` | Ignora `.venv/`, cachés, `mlruns/`, `datos/raiz/raw/`, `salidas/`, logs y `.env` |
| `pipeline/corrida_entrega.sh` | **Punto de entrada** del pipeline U0→U7 en modo local (ver §6) |
| `pipeline/conf/*.yml` (13) | Configuración del pipeline: `alx` (interruptores), `calendario_co`, `costos`, `dq_rules`, `entity_id_map`, `export_anexo_d`, `model_m3`, `model_u1_u2`, `model_u4_u5`, `model_u6`, `paths`, `pronosticadores`, `sources` |
| `pipeline/src/daas/` | Paquete del pipeline (94 módulos) |
| `  pipeline/` | `run_u0` … `run_u7`: una unidad por módulo |
| `  ingest/`, `ingest/readers/` | Lectores de cada fuente raw y normalización a interim |
| `  quality/` | Reglas DQ y reportes (`quality/reports`) |
| `  curate/`, `features/`, `fondo/`, `costs/` | processed por modelo, features de series y calendario, dimensión de fondos, costos del Anexo E |
| `  forecasting/` | Pronosticadores (Prophet, GBM, globales ML), intervalos, métricas, calendario CO, `laboratorio.py` (puente a `ml/`) y `explain.py` |
| `  modules/` | Lógica por modelo: `atm_m1_m2`, `branches_m3`, `funds_inflows_m4_m5`, `funds_m6` (balance, simulador, corrección de disponibles) |
| `  decision/` | Políticas, optimizador y alertas |
| `  publish/`, `publish/anexo_d/` | Contratos `output/api`, explicabilidad, generación y validación del Anexo D (una clase por hoja) |
| `  io/storage.py`, `lineage/`, `alx.py` | Resolución `daas://`, manifiesto de linaje, lectura de interruptores |
| `ml/__init__.py`, `ml/pronosticar.py` | `pronosticar()`: arma y ajusta la receta del champion (lo llama `laboratorio.py`) |
| `lab/__init__.py`, `lab/forecasting/{registry,challengers,gbm}.py` | Registro `MODELS` y modelos del laboratorio que usan las recetas |
| `lab/tracking/mlflow_tracking.py` | `PronosticadorPanel` y `a_matriz` (los importa `ml/pronosticar.py`; no levanta servidor MLflow) |
| `lab/conf/experimentos/*.yml` (80) | Recetas congeladas; `registry` carga el directorio completo |
| `lab/conf/bandas.yml` | Bandas conformales; `publicar.py` lo lee para los champions del manifest |
| `imputacion/{__init__,contexto_asof,datos}.py` | Contexto V4 "as of" (SUP-28). El resto del experimento de imputación no está aquí (§12) |
| `datos_poc.py` | Carga de series; lo importa `imputacion/datos.py` |
| `publicacion_s3/publicar.py` | Genera `v0_provisional` en local (`generar`) y verifica una descarga (`verificar`) |
| `consumo-pronosticos/contratos/*.yaml` (4) | OpenAPI de los flujos B, C, D y E del arquitecto; `publicar.py` valida contra ellos |
| `entrega/POC_Efectivo_PRAGMA.xlsx` | Anexo D entregado (referencia y entrada obligatoria de `publicar.py`) |
| `entrega/output_api/*.parquet` + `_schemas/*.json` | Contratos del entregable: `alertas`, `backtest`, `metricas`, `predicciones`, `recomendaciones`, `silenciosos` |
| `datos/raiz/anexos/Anexos/` | Plantilla Anexo D (sha256 `a247fae7…`) y parámetros de costos Anexo E (`caaa399c…`); no existen en S3 |
| `datos/raiz/raw/` | Ignorado por git; lo llena `scripts/descargar_raw.sh` |
| `scripts/descargar_raw.sh` | Descarga raw de la réplica (solo lectura) y verifica sha256 |
| `scripts/raw.sha256` | sha256 de los 19 archivos raw |
| `scripts/comparar_salidas.py` | Compara una corrida con `entrega/` por contenido (parquet y celdas del Excel) |

## 5. Requisitos y acceso a AWS

### 5.1 Software

- macOS arm64 (es la única plataforma probada; el lock está restringido a ella, §13).
- [uv](https://docs.astral.sh/uv/) ≥ 0.12 (se usó 0.12.21). uv instala Python 3.11.16 si no lo tienes.
- AWS CLI v2 (se usó 2.37.10).
- ~2 GB de disco libre y ~15 min de CPU para el pipeline completo.

### 5.2 Login SSO (dos identidades en el mismo portal)

Los datos se leen con el usuario `alexander.pelaez` del portal `pragmaaws.awsapps.com`, a través de dos perfiles que comparten la sesión SSO `poc-bancolombia`:

| Perfil | Cuenta | Para qué |
|---|---|---|
| `alx-poc` | 903641686926 | Réplica, **solo lectura**: descarga de `raw/` |
| `alx-mx` | 777937796305 (rol `Ps-HackatonAgentic-Mexico`) | Bucket destino: lo lee `publicar.py` |

Procedimiento (lo ejecuta la persona, nunca un agente):

```zsh
aws sso login --profile alx-poc --use-device-code
aws sts get-caller-identity --profile alx-poc   # Account 903641686926
aws sts get-caller-identity --profile alx-mx    # Account 777937796305 (misma sesión, sin otro login)
```

- Abre la URL y el código en una **ventana privada o un perfil de Chrome separado** si en el navegador normal tienes otra sesión del portal (por ejemplo, la cuenta que usa Kiro). El navegador guarda una sola sesión del portal; mezclar usuarios da `ForbiddenException ... No access`.
- **No ejecutes `aws sso logout`**: revoca la sesión en el servidor e invalida los tokens de otras herramientas. Cuando la sesión venza, repite solo el login.
- Permisos necesarios: `s3:ListBucket` y `s3:GetObject` en ambos buckets.

## 6. Ejecutar todo el proceso

Clona el repo **fuera** de Google Drive u otras carpetas sincronizadas. Ningún paso escribe en S3.

```zsh
# 0. Entorno
cd poc-bancolombia
uv sync --frozen
REPO=$PWD

# 1. Insumos raw: S3 (solo lectura, perfil alx-poc) -> datos/raiz/raw/ y chequeo sha256 de los 19 archivos
sh scripts/descargar_raw.sh

# 2. Pipeline U0 -> U7 (~15 min). Escribe SOLO en $TRABAJO.
#    ATENCION: el script BORRA "$TRABAJO/data" y "$TRABAJO/conf" al iniciar. Usa una carpeta dedicada.
TRABAJO=$HOME/.cache/poc-daas/repo_corrida
cd /tmp && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 MKL_NUM_THREADS=1 MLFLOW_DISABLE_AGENT_HINT=1 \
  sh "$REPO/pipeline/corrida_entrega.sh" "$REPO/datos/raiz" "$TRABAJO" "$REPO/.venv/bin/python"

# 3. Comparar con la referencia de entrega/ (criterio §8)
cd /tmp && PYTHONDONTWRITEBYTECODE=1 "$REPO/.venv/bin/python" "$REPO/scripts/comparar_salidas.py" \
  "$REPO/entrega/output_api" "$REPO/entrega/POC_Efectivo_PRAGMA.xlsx" \
  "$TRABAJO/data/output/api" "$TRABAJO/data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx"

# 4. Publicación v0_provisional en local (lee S3 con alx-mx; escribe solo en la carpeta indicada)
cd /tmp && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO:$REPO/pipeline/src" AWS_PROFILE=alx-mx \
  "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" generar "$HOME/.cache/poc-daas/repo_v0_provisional"

# 5. (Opcional) verificar una descarga de S3 contra su manifest
#    aws s3 cp s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/ /tmp/v0_s3/ --recursive --profile alx-mx
#    cd /tmp && PYTHONPATH="$REPO:$REPO/pipeline/src" "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" verificar /tmp/v0_s3
```

Notas:

- `corrida_entrega.sh` acepta `UNIDADES="u0 u1_u2 ..."` (subconjunto de unidades), `REANUDAR=1` (no borra el trabajo) y `CONF_ALX=<otro alx.yml>` (por ejemplo, todos los interruptores en `false` = pipeline de Santiago). Fuerza `DAAS_SCHEME=local`, quita `DAAS_S3_BUCKET` y, antes de cada unidad, aborta si alguna ruta de salida no resuelve a `file://` (registro en `$TRABAJO/rutas.log`).
- Las variables `*_NUM_THREADS=1` reducen el ruido de punto flotante entre corridas.
- `publicar.py` aborta si el sha256 de `entrega/POC_Efectivo_PRAGMA.xlsx` no empieza por `52e7547fce59105a`. Publica el Excel del repo, no el regenerado en el paso 2.
- La subida a S3 (un `aws s3 sync` manual de la carpeta del paso 4 a `output/pronosticos/v0_provisional/`) **no forma parte del flujo** y no debe ejecutarse para verificar. Se menciona solo como referencia histórica.

## 7. Salidas y dónde quedan

Pipeline (paso 2), dentro de `$TRABAJO`:

- `data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx`: Anexo D (hojas 01_Predicciones 9.690 filas, 02_Plan_Operativo 2.592, 03_Metricas_Desarrollo 105, 04_Descripcion_Solucion 8, 05_M6_Fondos 565, 06_Diccionario_Campos 20).
- `data/output/api/`: `predicciones` (10.230), `recomendaciones` (2.923), `alertas` (2.590), `metricas` (46), `backtest` (15.804), `silenciosos` (15) en parquet, con `*.meta.json` y `_schemas/`.
- `data/output/explicabilidad/importancias.parquet`.
- `data/interim/`, `data/processed/`, `data/features/`, `data/quality/reports/`.
- Logs: `u0.log` … `u7.log` y `rutas.log`.

Publicación (paso 4), en la carpeta indicada: `manifest.json` (versión, revisión 2, fuente, champions, decisiones, discrepancias, sha256 por archivo) más 247 archivos en `tablas/<tabla>/modelo=mX[/fecha=AAAA-MM-DD]/part-0.parquet`, `esquemas/`, `api/flujo_{b,c,d,e}/` y `validacion/`. Es lo mismo que está publicado en `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v0_provisional/` (248 objetos con el manifest). La estructura es **provisional** hasta que el arquitecto entregue la especificación de almacenamiento. La revisión 1 sigue recuperable por versiones de S3 (manifest r1 VersionId `Fz0ZPux6iCZu6ZHNywyI8SiXcT8ZpvHL`).

Referencias versionadas en el repo: `entrega/POC_Efectivo_PRAGMA.xlsx` (sha256 `52e7547fce59105a24b0b0714aed9b0a18979804cec4fa9f1d03dc3cabde4688`, 917.601 B) y `entrega/output_api/` (sus sha256 coinciden 6/6 con los parquet del manifest publicado).

## 8. Comparación con la referencia y criterio de equivalencia

Una corrida nueva **no** reproduce el sha256 del Excel: el xlsx guarda la fecha de generación (`docProps/core.xml`) y los floats llevan ruido de 1e-7 por sumas paralelas (Prophet/joblib) y el orden de reducción en LightGBM/numpy. Criterio de equivalencia (el mismo de `ml/verificar_registro.py` en ALX):

- mismas hojas, filas y columnas, y mismo esquema arrow;
- celdas de texto y fecha idénticas;
- en columnas numéricas, Σ|dif| / Σ|ref| ≤ 1e-6 por columna.

Solo `silenciosos.parquet` y los `_schemas/*.json` pueden coincidir byte a byte. `run_id` usa `git rev-parse --short HEAD` sobre `pipeline/` y solo afecta a `*.meta.json`.

## 9. Evidencia de reproducibilidad

Corrida auditada del 23-oct-2026 (12:28–12:43, 14 min) sobre una copia de ALX en `/tmp`, con el venv original (`~/.venvs/poc-daas`, mismas versiones que `uv.lock`), los mismos raw (sha256 de `scripts/raw.sha256`) y los mismos anexos. Se ejecutó `corrida_entrega.sh` con un hook de auditoría (`sys.addaudithook`) que registró 187 archivos leídos de ALX; con eso se decidió el contenido del repo. Resultado frente a `entrega/` con `scripts/comparar_salidas.py`:

| Salida | Resultado |
|---|---|
| Excel | 6 hojas, mismas dimensiones. **1 celda distinta**: `03_Metricas_Desarrollo!F23` (Bias de M3 entradas), 0.02064426798851951 frente a 0.02064426798851952 (1 ulp). En el zip difieren `docProps/core.xml` (fecha) y `xl/worksheets/sheet3.xml` (esa celda) |
| `silenciosos.parquet` y los 6 `_schemas/*.json` | Idénticos byte a byte |
| `alertas`, `backtest`, `metricas`, `predicciones`, `recomendaciones` | Mismas filas, columnas y esquema; diferencias ≤ 9,5e-7 COP absolutas y ≤ 2,8e-18 relativas (máx. `predicciones.band_high`) |

Conclusión: equivalente según §8. La causa es ruido de punto flotante y la marca de tiempo del xlsx, no cambios de modelo ni de datos.

Lo que **no** se volvió a correr desde este repo: el pipeline completo (pasos 2–3) ni `publicar.py generar` (paso 4); se priorizó tener el repo disponible. Desde una copia limpia del repo sí se comprobaron `uv sync --frozen`, la importación de todos los módulos, el arranque del punto de entrada y la existencia de todas las rutas referenciadas. Las tablas de `publicar.py` son copia de `entrega/output_api` y deberían coincidir byte a byte con S3, pero esto no se verificó.

## 10. Supuestos (SUP-xx)

El texto completo está en `ALX/pipeline/docs/supuestos.md` (no incluido, §12) y el resumen va en la hoja 04 del Excel.

| SUP | Resumen |
|---|---|
| SUP-01 | Exclusión de métricas por cajero, no por entidad-día |
| SUP-02 | Ceros reales, faltantes y lectura RN-08 en el WAPE (entidad con denominador cero fuera del WAPE agregado) |
| SUP-03 | Días calendario en M1–M3 |
| SUP-04 | Umbral de agotamiento de M1 = 8 % del cupo (RN-34) |
| SUP-05 | Cassette de depósitos de M2 (sin efecto) |
| SUP-06 | Código de cajero reutilizado: una serie por código (RN-06) |
| SUP-07 | Saldo inicial de M6 = último registro ≤ 31-ago por fondo y denominación |
| SUP-08 | Operaciones habilitadas por fondo, inferidas del histórico (M6) |
| SUP-09 | Reparto del efecto de M1–M5 por denominación (M6) |
| SUP-10 | Mínimos y máximos operativos de M6 |
| SUP-11 | Métrica de M6 sin WAPE |
| SUP-12 | Imputación del flujo de M1–M3 al fondo (M6, RN-70) |
| SUP-13 | BanRep: habilitación por tarifa y restricción a Cali (M6, RN-75) |
| SUP-14 | Intercambio y cambio de denominación dentro del fondo (M6) |
| SUP-M3-01 | Saldo de la bóveda de M3 en [0, `cupo_max_suc`] |
| SUP-M3-02 | `cupo_max_suc` vigente por sucursal |
| SUP-15 | Nivel de servicio y costo del agotamiento (M1, M2) |
| SUP-16 | Lead time de la provisión (M1) |
| SUP-17 | Entidades con poca historia |
| SUP-18 | Nada posterior al corte entra a entrenar ni a elegir |
| SUP-19 | El 8 % de RN-34 es umbral de alerta; la política de M1 es la del pliego |
| SUP-20 | Corrección del total de M5 que consume M6 |
| SUP-21 | Cajero urbano o interurbano para el costo |
| SUP-22 | Escala de la sucursal para el costo |
| SUP-23 | Tasa de venta de M6 |
| SUP-24 | Métricas marcadas `origen_dato = ESTIMADO` |
| SUP-25 | Recomendaciones y alertas marcadas ESTIMADO, no SIMULADO |
| SUP-26 | REAL no aparece en `output/api/*` |
| SUP-27 | Entidad con denominador cero fuera del WAPE agregado, también en el arnés (precisa SUP-02) |
| SUP-28 | Variables V4 con el maestro vigente en cada origen ("as of": último snapshot de `cp_historico.xlsx` ≤ origen) |
| SUP-29 | Corrección de los disponibles de M6: sin `TOTAL` y TDV_001 en pesos |
| SUP-30 | Regla de adopción R1–R5 declarada antes de medir |
| SUP-31 | k = 2 en R1 por búsqueda múltiple |
| SUP-32 | Pesos congelados en los ensambles ponderados |
| SUP-33 | Contexto empaquetado en el modelo registrado (pyfunc) |
| SUP-34 | Demanda censurada: se modela lo dispensado |
| SUP-35 | Duplicado de sucursales del 13-may-2026 y valores corruptos: corrección de datos, no imputación |
| SUP-36 | Imputación de faltantes: evaluada y no adoptada |
| SUP-37 | Ceros dudosos de M3 en agosto de 2026 |
| SUP-38 | Repetición acotada del ML (decisión D1) |
| SUP-39 | Champions finales del laboratorio en el pipeline del entregable (`forecaster.modelo_alx`) |
| SUP-40 | Plantilla del Anexo D y tarifas del Anexo E de la corrida del entregable (originales, sha256 en §4) |

Detalle de los que más pesan en el resultado:

- **SUP-02 / SUP-27**: una entidad cuyo valor real suma cero en la ventana sale solo del WAPE agregado (métricas y hoja 03). Interruptor `sup02_denominador_cero`.
- **SUP-28**: las variables de contexto V4 usan el maestro vigente en cada origen, construido por `imputacion/contexto_asof.py`. Lo exigen los champions de M1, M2 pagado y M5. Interruptor `contexto_asof`.
- **SUP-29**: los disponibles de M6 se corrigen (se excluye la fila `TOTAL`, TDV_001 pasa de piezas a pesos, se descartan días con blancos o doble formato). Interruptor `correccion_m6` y `correccion_disponibles.aplicar` en `model_u6.yml`.
- **SUP-35**: se deduplica el duplicado exacto de sucursales del 13-may-2026 y los cajero-días con monto corrupto pasan a faltante (NaN). Es corrección, no imputación. Interruptor `correcciones_datos`.
- **SUP-36**: la imputación se evaluó y no se adoptó (§11).
- **SUP-39**: los champions de §2 corren dentro del pipeline por la familia `ml_laboratorio`, con la receta congelada (no el pyfunc de MLflow) para que el contexto "as of" se construya desde la raíz de datos de la corrida.
- **SUP-40**: se usaron la plantilla del Anexo D y el Anexo E originales del banco (los de `datos/raiz/anexos/Anexos/`).

## 11. Decisiones adoptadas y descartadas

Adoptadas:

- **Regla de adopción R1–R5 con k = 2** (SUP-30, SUP-31), declarada antes de medir. Un candidato reemplaza a la receta de Santiago solo si la cumple. La huella de la regla se calcula con `ml.adopcion.huella_regla()` sobre `ml/conf/adopcion_ml.yml` y vale `623420f48f04` (sin cambios durante el entregable). `ml/adopcion.py` y `ml/conf/` **no están en el repo** porque el pipeline no los usa; están en `ALX/ml/`.
- **Pesos congelados** en los ensambles ponderados (SUP-32).
- **Escenario S1** en todos los champions: datos corregidos (SUP-35) + V4 "as of" (SUP-28), sin imputación.
- **M4** conserva la receta de Santiago (`combo_perfil_gbml1`): ningún candidato cumplió R1–R5.

Evaluadas y no adoptadas:

- **Imputación de faltantes** (SUP-36): T0 = T1 = T2 en `ALX/imputacion/resultados/ml/decision_final.csv`; ningún champion mejora con ella. El interruptor `imputacion` queda en `false` y encenderlo aborta la corrida. Todo el experimento se conserva en `ALX/imputacion/` (§12).
- **Mejora de M5 v2**: sin cambios en el entregable. La recomendación SUP-41 no se aplicó (`ALX/m5_mejora/resultados_m5_v2.md`).
- **Descartados**: SARIMA (solo referencia, `ALX/sarima/`), CatBoost con variables categóricas, XGBoost, ETS/Theta/MSTL y modelos fundacionales.

## 12. Material no incluido en el repo

Todo sigue en Google Drive, en `Mi unidad/PoC-Bancolombia/ALX/` (en adelante `ALX/`), sin cambios. Útil para sustentación y mejoras. Algunos resultados intermedios están además en `~/.cache/poc-daas/` del equipo de Alexander Peláez.

| Material | Ruta | Contenido |
|---|---|---|
| Imputación (no adoptada) | `ALX/imputacion/` (29 MB) | Métodos, inventario de faltantes, aplicación, decisión con ML, MLflow, notebook `05_imputacion_faltantes.ipynb`, `resultados/` (incluye `ml/decision_final.csv`, `entrega_cumplimiento_pliego.md`, `entrega_comparacion_santiago.md`) y `conf/`. Corridas en `~/.cache/poc-daas/imputacion/` |
| Fase 2 de ML | `ALX/ml/` (20 MB) | Entrenamiento, Optuna, ensambles, registro en MLflow, adopción (`adopcion.py`, `huella_regla`), `conf/adopcion_ml.yml`, `conf/ensambles/`, `verificar_registro.py`, notebook `04_mejora_modelos_ml.ipynb` y `resultados/` (`adopcion.csv`). Registro MLflow en `~/.mlflow/poc-daas/mlflow.db`; colas y artefactos en `~/.cache/poc-daas/ml/` |
| Laboratorio (resto) | `ALX/lab/` | Arnés de evaluación, simuladores, explicabilidad, incertidumbre, handoff, tests y conf (`evaluacion`, `explicabilidad`, `picos`, `politicas`, `politicas_m3`, `traspaso`) |
| Registros del laboratorio | `ALX/resultados/` (14 MB) | `corridas.jsonl`, `bandas.jsonl`, `explicabilidad.jsonl`, `picos.jsonl` |
| EDA | `ALX/eda/` (22 MB) | EDA Box-Jenkins, notebook `02_eda_series_box_jenkins.ipynb` y resultados |
| SARIMA | `ALX/sarima/` (5,9 MB) | Referencia SARIMA, paridad con el arnés, notebook `03_sarima_referencia.ipynb` y resultados. Corridas en `~/.cache/poc-daas/sarima/` |
| Mejora M5 v2 | `ALX/m5_mejora/` | Regla v2, SUP-20, medición, revisión, tests e informe `resultados_m5_v2.md`. Corridas en `~/.cache/poc-daas/m5_v2/` |
| Notebook de series | `ALX/01_series_de_tiempo.ipynb` (8,9 MB) | Análisis de series de tiempo; `ALX/graficos_poc.py` lo apoya |
| Supuestos | `ALX/pipeline/docs/supuestos.md`, `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf` | Texto completo de los SUP y PDF entregado |
| Pipeline (resto) | `ALX/pipeline/` | `corrida_local.sh` (Santiago), `tests/`, `conf/aws.yml`, `conf/contracts/C-01..C-12.yml`, `pyproject.toml`/`uv.lock`/`requirements.txt` antiguos (no reproducen el entorno real), `modules/funds_m6/recommender.py`, `quality/schemas.py` |
| Publicación S3 (resto) | `ALX/publicacion_s3/` | `README.md` (detalle de la publicación y discrepancias con los contratos), inventario del bucket (`inventario_bucket.py/.csv/.md`), tests y `revision/` r1 y r2 (VersionId de r1 en `revision/r2/versiones_revision1.tsv`) |
| Consumo de pronósticos | `ALX/consumo-pronosticos/` | HUs de los flujos B–E y `README-handoff-datos.md` del arquitecto |
| Documentos para el arquitecto | `ALX/preguntas_arquitecto.md`, `ALX/estructura_pronosticos_s3.md`, `ALX/guia_datos_bucket.md` | Dudas (11 preguntas), estructura de pronósticos en S3 y guía del bucket |
| Resúmenes y análisis | `ALX/resumen_avances_v1.md`, `ALX/resumen_avances_v2.md`, `ALX/resumen_trabajo_y_consumo.md`, `ALX/analisis_repo_santiago.md`, `ALX/plan_mejora_m5.md`, `ALX/docs/metodologia-valor.md`, `ALX/README.md` | Avances, análisis del repo de Santiago, metodología y reglas contra fugas |
| Pruebas de ALX | `ALX/tests_alx/` | 17 archivos de pruebas de los cambios de ALX |
| Landing | `ALX/landing/` | Landing web (Vite/React), export y CloudFormation |
| Referencia de Santiago | `ALX/entrega/referencia_santiago/POC_Efectivo_PRAGMA.xlsx` | Excel de Santiago (sha256 `bc7d5189…`), solo para comparar |
| Workflows de agentes | `ALX/.agents/tasks/` | Planes, verificaciones y revisiones de imputación, EDA/SARIMA/MLflow, fase 2 ML y resumen v2 (`imputacion/verificacion-entrega.md` documenta la corrida del entregable) |
| Corrida del entregable | `~/.cache/poc-daas/corrida_entrega/` | `raiz/` (raw y anexos usados) y `completa/` (salidas de la corrida oficial) |
| Contexto del proyecto | `Mi unidad/PoC-Bancolombia/CONTEXTO_CONVERSACION.md` | Historia completa de la PoC, accesos (§18) y publicación S3 (§21) |

## 13. Limitaciones

- `uv.lock` está restringido a macOS arm64 (`tool.uv.environments`): la resolución universal falla con `shap==0.51.0`. En otra plataforma habría que relajar esa restricción y regenerar el lock, con riesgo de versiones distintas.
- `publicar.py` exige el Excel `52e7547f…` de `entrega/`, por eso no publica un Excel regenerado.
- `publicar.py` depende de `interim/` y `processed/` del bucket 777937796305 (sesión `alx-mx` vigente).
- El pipeline no lee `interim/`, `processed/` ni `features/` de S3: U0 los regenera desde `raw/`.
- La verificación desde este repo fue rápida (§9): no se repitió el pipeline completo ni `publicar.py generar`.
