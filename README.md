# PoC DaaS Bancolombia: pronósticos de efectivo (Pragma)

Guía para personas y agentes LLM. Este repo contiene **solo** lo indispensable para reproducir los dos resultados vigentes de la PoC:

1. El Excel del Anexo D **v2** `entrega/POC_Efectivo_PRAGMA.xlsx` (26-oct-2026, sha256 `167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461`) y sus contratos `entrega/output_api/`. Qué cambió frente a la v1 del 21-oct (`52e7547f…4688`) está en [`entrega/CAMBIOS_v2.md`](entrega/CAMBIOS_v2.md).
2. La publicación en S3 de la v2: `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/` (26-oct-2026, revisión 1, 249 objetos, 10.401.803 B; manifest sha256 `967eac4b…2bf1`). El puntero `s3://poc-daas-bancolombia-777937796305/output/pronosticos/version_vigente.json` indica la versión vigente (`v2`) y la anterior. `output/pronosticos/v0_provisional/` es la publicación de la **v1**, conservada sin cambios (249 objetos). La genera `publicacion_s3/publicar.py` (§6).

Qué entró y qué no se decidió con una corrida auditada que registró cada archivo abierto y cada módulo cargado (§9); la v2 agregó solo los archivos que tocaron las correcciones (§4). Todo lo demás (imputación, EDA, SARIMA, mejora de M5, notebooks, revisiones, resúmenes, guías) quedó fuera del repo y sigue en la carpeta `ALX/` del Google Drive del proyecto (§12).

La v1 no se versiona aparte: está en el historial de git (commit `955115d`; por ejemplo `git show 955115d:entrega/POC_Efectivo_PRAGMA.xlsx > /tmp/v1.xlsx`) y en el Drive (`ALX/entrega/historico/v1_2026-10-21/`).

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

PoC de *Data as a Service* para la administración del efectivo de Bancolombia (segunda ronda, Pragma). Con corte al **31-ago-2026** se pronostica el horizonte **1 al 15-sep-2026** de cajeros, multifuncionales, sucursales y fondos, y se generan el plan operativo (provisiones, recolecciones, traslados, ventas, retiros BanRep), las alertas y las métricas del backtest (17–31 ago). El entregable formal es el Anexo D (Excel de 6 hojas). La misma información se publica en S3 con la forma de los contratos OpenAPI del arquitecto (flujos B, C, D y E).

La base es el pipeline de Santiago Higuita (`pipeline/`; las salidas antiguas de `output/api/` en los buckets son del pipeline de Andrés Vergara). ALX agregó, detrás de interruptores (`pipeline/conf/alx.yml`), los champions de ML del laboratorio, el contexto "as of", correcciones de datos y supuestos nuevos (v1, 21-oct) y las correcciones de supuestos, M6 y plan operativo de la v2 (26-oct).

El registro de supuestos propio (`pipeline/docs/supuestos.md`, SUP-01..SUP-53) es la **versión final** de los supuestos (decisión del 26-oct-2026). El banco indicó que la información que no suministró se supla con supuestos documentados, y así se hizo: cada SUP dice qué no entregó el banco, qué se asume, por qué, su efecto, la alternativa y dónde se aplica. Los documentos de supuestos de Andrés Vergara (carpeta `revision-andres/` del Drive y el PDF `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf`) **no se usan**.

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

WAPE global del backtest 17–31 ago (Santiago → entregable; **iguales en v1 y v2**, la v2 no cambia pronósticos ni métricas predictivas): M1 0,2551 → 0,2490; M2 pagado 0,3652 → 0,3642; M2 cash-in 0,3868 → 0,3832; M3 entradas 0,4219 → 0,3884; M3 salidas 0,4577 → 0,4166; M4 0,3196 → 0,3196; M5 0,5668 → 0,5160. En M3, SUP-02 excluye del WAPE 3 sucursales en entradas y 4 en salidas. En M1 y M2 la lectura RN-08 (con la que puntúa el banco) es M1 0,3145, M2 pagado 0,4488 y M2 cash-in 0,4814.

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

Interruptores de `pipeline/conf/alx.yml` (clave ausente = `false`):

- v1 (21-oct): `campeones_ml`, `contexto_asof`, `correcciones_datos`, `correccion_m6`, `sup02_denominador_cero`, `origen_dato` y `supuestos_alx` en `true`; `imputacion: false` (encenderlo aborta la corrida, SUP-36).
- v2 (26-oct), los diez en `true`:

  | Interruptor | Qué cambia | SUP |
  |---|---|---|
  | `m6_cajeros_sucursal` | M6 integra los cajeros administrados por sucursal al fondo de su sucursal | SUP-12 |
  | `m2_tarifa_interurbana` | Tarifa MF interurbano para los MF de TDV fuera del municipio de la ciudad del fondo | SUP-21 |
  | `m3_escala_anexo_a` | Escala de sucursal interurbana desde `Escalas` de Oficinas | SUP-22 |
  | `nivel_riesgo_previo` | `nivel_riesgo` de la hoja 02 antes de la acción; cupo insuficiente declarado | SUP-42, SUP-44 |
  | `monto_minimo_recoleccion` | M3 no recomienda recolecciones de efectivo ocioso que no pagan su visita | SUP-43 |
  | `m6_operaciones_rn84` | Sin intercambio ni cambio de denominación dentro del fondo | SUP-14 |
  | `m6_traslado_t1` | El traslado llega al destino al día siguiente (nota del Anexo E); se ordena el día anterior al faltante | SUP-52 |
  | `m6_tarifa_traslado_declarada` | Solo textos y la métrica `costo_traslado_tarifa_destino`: tarifa usada en traslados entre ciudades | SUP-53 |
  | `hoja04_v2` | Hoja 04 reescrita para el evaluador y validada (exige `supuestos_alx`) | todos |
  | `hoja03_textos_v2` | Solo `comentarios` y `metodologia_validacion` de la hoja 03 | — |

Con los diez de la v2 apagados (el `alx.yml` de la v1, `git show 955115d:pipeline/conf/alx.yml`, sha256 `e841aca2…6832`) la corrida reproduce la v1; con todos en `false` el pipeline se comporta como el de Santiago.

Después del pipeline, `publicacion_s3/publicar.py` (`--version v2`, por defecto) toma `entrega/output_api/` y el Excel de `entrega/` (exige su sha256 completo `167a52e4…`), lee a memoria maestros e insumos de `interim/` y `processed/` **de la corrida local que generó la v2** (`~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`, constante `CORRIDAS`; no lee S3) e importa funciones de `daas` (simulación M1–M3, corrección de disponibles M6, métricas) para armar la publicación en una carpeta local. `--version v0_provisional` reproduce la publicación de la v1 (necesita el respaldo `entrega/historico/v1_2026-10-21/`, que no está en el repo, y los insumos de S3). El subcomando `subir` solo escribe bajo `output/pronosticos/v2/` y en `version_vigente.json`, exige destino vacío y nunca borra; como la v2 ya está publicada, hoy se detiene sin escribir.

Buckets (us-east-1):

| Bucket | Cuenta | Perfil | Uso |
|---|---|---|---|
| `poc-daas-bancolombia-replica-903641686926` | 903641686926 | `alx-poc` | Réplica, **solo lectura**. Fuente de `raw/` (19 objetos, 110.501.133 bytes) |
| `poc-daas-bancolombia-777937796305` | 777937796305 | `alx-mx` | Bucket destino. `raw/` idéntico (19/19). Aloja `output/pronosticos/v2/` (vigente), `output/pronosticos/version_vigente.json` y `output/pronosticos/v0_provisional/` (v1) |

Ojo: `output/api/` y `output/anexo_d/` de ambos buckets son salidas del 8–9-oct del pipeline de Andrés, **no** el entregable vigente (el Excel del bucket tiene sha256 `6e781aaa…`). La publicación vigente de ALX es `output/pronosticos/v2/` (ver `version_vigente.json`); `v0_provisional/` es la v1.

## 4. Mapa del repo

El layout replica las rutas relativas de la carpeta `ALX/` original: `ml/__init__.py`, `lab/__init__.py` e `imputacion/__init__.py` agregan la raíz y `pipeline/src` a `sys.path` por posición relativa, `corrida_entrega.sh` usa su carpeta padre como raíz y `publicar.py` usa `parents[1]`. **No muevas carpetas.**

| Ruta | Qué es |
|---|---|
| `README.md`, `AGENTS.md` | Esta guía y las reglas para agentes |
| `CONTEXTO_LLM.md` | Contexto completo del proyecto para personas y agentes LLM (leer primero) |
| `pyproject.toml`, `uv.lock`, `.python-version` | Entorno exacto (Python 3.11.16, versiones del venv que generó el entregable). `package = false`: `daas` corre por PYTHONPATH |
| `.gitignore` | Ignora `.venv/`, cachés, `mlruns/`, `datos/raiz/raw/`, `salidas/`, logs y `.env` |
| `pipeline/corrida_entrega.sh` | **Punto de entrada** del pipeline U0→U7 en modo local (ver §6) |
| `pipeline/conf/*.yml` (13) | Configuración del pipeline: `alx` (interruptores), `calendario_co`, `costos`, `dq_rules`, `entity_id_map`, `export_anexo_d` (incluye los textos `hoja_04_v2` y `hoja_03_v2`), `model_m3`, `model_u1_u2`, `model_u4_u5`, `model_u6`, `paths`, `pronosticadores`, `sources` |
| `pipeline/docs/supuestos.md` | Registro final de supuestos SUP-01..SUP-53 (v2, 26-oct). Lo citan el código, la configuración y la hoja 04 |
| `pipeline/src/daas/` | Paquete del pipeline (95 módulos; la v2 agregó `publish/anexo_d/sheet_04_v2.py`) |
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
| `publicacion_s3/publicar.py` | `generar` arma la publicación en local (`--version v2` por defecto, o `v0_provisional`); `verificar` comprueba una descarga contra su manifest; `subir` publica con salvaguardas (solo `output/pronosticos/v2/` y `version_vigente.json`) |
| `consumo-pronosticos/contratos/*.yaml` (4) | OpenAPI de los flujos B, C, D y E del arquitecto; `publicar.py` valida contra ellos |
| `entrega/POC_Efectivo_PRAGMA.xlsx` | Anexo D entregado, v2 (`167a52e4…`). Referencia de comparación y entrada de `publicar.py` (exige su sha256 completo) |
| `entrega/output_api/*.parquet` + `_schemas/*.json` | Contratos del entregable v2: `alertas`, `backtest`, `metricas`, `predicciones`, `recomendaciones`, `silenciosos` |
| `entrega/CAMBIOS_v2.md` | Qué cambió de v1 a v2, por qué y cuánto; interruptores, sha256 y pendientes |
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
| `alx-mx` | 777937796305 (rol `Ps-HackatonAgentic-Mexico`) | Bucket destino: aloja las publicaciones; lo lee `publicar.py --version v0_provisional` |

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

# 4. Publicación v2 en local (no lee S3: usa los insumos de ~/.cache/poc-daas/corrida_entrega_v2/B2_v2; escribe solo en la carpeta indicada)
cd /tmp && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO:$REPO/pipeline/src" \
  "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" generar "$HOME/.cache/poc-daas/repo_pub_v2" --version v2
# 5. (Opcional) verificar una descarga de S3 contra su manifest
#    aws s3 cp s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/ /tmp/v2_s3/ --recursive --profile alx-mx
#    cd /tmp && PYTHONPATH="$REPO:$REPO/pipeline/src" "$REPO/.venv/bin/python" "$REPO/publicacion_s3/publicar.py" verificar /tmp/v2_s3
```

Notas:

- `corrida_entrega.sh` acepta `UNIDADES="u0 u1_u2 ..."` (subconjunto de unidades), `REANUDAR=1` (no borra el trabajo) y `CONF_ALX=<otro alx.yml>` (por ejemplo, todos los interruptores en `false` = pipeline de Santiago). Fuerza `DAAS_SCHEME=local`, quita `DAAS_S3_BUCKET` y, antes de cada unidad, aborta si alguna ruta de salida no resuelve a `file://` (registro en `$TRABAJO/rutas.log`).
- Las variables `*_NUM_THREADS=1` reducen el ruido de punto flotante entre corridas.
- **Insumos del paso 4.** `publicar.py --version v2` lee las capas `interim/` y `processed/` de `~/.cache/poc-daas/corrida_entrega_v2/B2_v2/` (constante `CORRIDAS` del script). En un equipo sin esa carpeta, corre el paso 2 con `TRABAJO=$HOME/.cache/poc-daas/corrida_entrega_v2/B2_v2` (el script borra `data/` y `conf/` ahí: no lo hagas si esa carpeta ya tiene la corrida original). Publica el Excel del repo, no el regenerado en el paso 2. `--version v0_provisional` necesita `entrega/historico/v1_2026-10-21/` y `~/.cache/poc-daas/corrida_entrega_v2/A2_v1/conf`, que no están en el repo.
- Para reproducir la v1 con el código actual: `git show 955115d:pipeline/conf/alx.yml > /tmp/alx_v1.yml` y `CONF_ALX=/tmp/alx_v1.yml` en el paso 2; compara contra la v1 extraída con `mkdir /tmp/v1 && git archive 955115d entrega | tar -x -C /tmp/v1`.
- La subida a S3 (`publicar.py subir`) **no forma parte del flujo de reproducción** y no debe ejecutarse para verificar: la v2 ya está publicada y `subir` se detiene si el destino no está vacío. Cómo se publicó y cómo republicar: `ALX/publicacion_s3/README.md` (Drive).

## 7. Salidas y dónde quedan

Pipeline (paso 2), dentro de `$TRABAJO`:

- `data/output/anexo_d/POC_Efectivo_PRAGMA.xlsx`: Anexo D v2 (hojas 01_Predicciones 9.690 filas, 02_Plan_Operativo 2.585, 03_Metricas_Desarrollo 105, 04_Descripcion_Solucion 8, 05_M6_Fondos 566, 06_Diccionario_Campos 20). En la v1 eran 2.592 en la hoja 02 y 565 en la 05.
- `data/output/api/`: `predicciones` (10.230), `recomendaciones` (2.897), `alertas` (2.547), `metricas` (50), `backtest` (15.804), `silenciosos` (15) en parquet, con `*.meta.json` y `_schemas/`. En la v1: 2.923 recomendaciones, 2.590 alertas y 46 métricas.

Cifras principales de la v2 (detalle en `entrega/CAMBIOS_v2.md`):

- Hoja 02: M1 1.349 provisiones; M2 28 provisiones y 719 recolecciones; M3 2 provisiones y 425 recolecciones (7 omitidas por SUP-43); 62 sin acción. `nivel_riesgo` antes de la acción: 1.098 alto, 1.216 medio, 271 bajo (v1: todo bajo).
- Hoja 05: 566 filas = 198 de traslado (99 traslados), 148 ventas, 4 retiros BanRep (CALI|TRANSPORTADORA_003, 1-sep) y 216 sin acción. 82 de los 84 cajeros de sucursal integrados a M6 (SUP-12).
- Hoja 03, costos: M1 158.509.198 (sin cambios frente a la v1); M2 75.341.516 (v1 71.404.981); M3 140.258.965 (v1 147.650.688); **M6 1.441.530 COP (v1 0)**: 545.413 de 2 traslados Ipiales → Pasto y 896.117 de los 4 retiros BanRep; almacenamiento de M6 41.460.623 (v1 43.368.281). Las 91 métricas predictivas no cambian.
- `data/output/explicabilidad/importancias.parquet`.
- `data/interim/`, `data/processed/`, `data/features/`, `data/quality/reports/`.
- Logs: `u0.log` … `u7.log` y `rutas.log`.

Publicación (paso 4), en la carpeta indicada: `manifest.json` (versión `v2`, revisión 1, fuente, `insumos_locales` y `conf` con sha256, champions, decisiones, discrepancias, sha256 por archivo) más 248 archivos: `anexo_d/POC_Efectivo_PRAGMA_v2.xlsx` (copia del Excel), `tablas/<tabla>/modelo=mX[/fecha=AAAA-MM-DD]/part-0.parquet`, `esquemas/`, `api/flujo_{b,c,d,e}/` y `validacion/`. Es lo publicado en `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/` (249 objetos con el manifest; 1.176 instancias OpenAPI con 0 errores de esquema). `version_vigente.json` apunta a ese prefijo y guarda el sha256 del manifest (`967eac4b…`) y del Excel, más la versión anterior. `v0_provisional/` (v1, revisión 2; 249 objetos, incluido el Excel v1 subido aparte el 24-oct) se conserva sin cambios; su revisión 1 sigue recuperable por versiones de S3 (manifest r1 VersionId `Fz0ZPux6iCZu6ZHNywyI8SiXcT8ZpvHL`). La estructura sigue siendo **provisional** hasta que el arquitecto entregue la especificación de almacenamiento.

Referencias versionadas en el repo: `entrega/POC_Efectivo_PRAGMA.xlsx` v2 (sha256 `167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461`, 929.096 B) y `entrega/output_api/` v2. La v1 (`52e7547f…4688`, 917.601 B) está en el commit `955115d`; sus `output_api` coinciden 6/6 por sha256 con `fuente.archivos` del manifest de `v0_provisional/`. Los de la v2 coinciden 6/6 con `fuente.archivos` del manifest de `v2/`. Entre v1 y v2, `silenciosos.parquet` y los 6 `_schemas/*.json` son idénticos byte a byte.

## 8. Comparación con la referencia y criterio de equivalencia

Una corrida nueva **no** reproduce el sha256 del Excel: el xlsx guarda la fecha de generación (`docProps/core.xml`) y los floats llevan ruido de 1e-7 por sumas paralelas (Prophet/joblib) y el orden de reducción en LightGBM/numpy. Criterio de equivalencia (el mismo de `ml/verificar_registro.py` en ALX):

- mismas hojas, filas y columnas, y mismo esquema arrow;
- celdas de texto y fecha idénticas;
- en columnas numéricas, Σ|dif| / Σ|ref| ≤ 1e-6 por columna.

Solo `silenciosos.parquet` y los `_schemas/*.json` pueden coincidir byte a byte. `run_id` usa `git rev-parse --short HEAD` sobre `pipeline/` y solo afecta a `*.meta.json`.

## 9. Evidencia de reproducibilidad

### 9.1 Entregable v2 (26-oct-2026)

- **Corrida B2** (la que generó el Excel v2): `pipeline/corrida_entrega.sh` con los interruptores v2, el venv original (mismas versiones que `uv.lock`) y los mismos raw (19/19 sha256 de `scripts/raw.sha256`), fuera de Drive (`~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`). `validate_anexo_d` da 0 errores. Frente a la v1: hojas 01 y 06 idénticas, 91 métricas predictivas de la hoja 03 iguales (rtol 1e-12), `predicciones` de M1–M5, `backtest` y `silenciosos` iguales.
- **Corrida A2** (código v2 con el `alx.yml` de la v1): las 6 hojas iguales a la v1 celda a celda (valor, fórmula y formato) salvo 1 celda de la hoja 03 (`03!F21`, WAPE de M3 entradas, 2 ulp de ruido de punto flotante). Los interruptores nuevos no alteran la v1.
- **Corrida desde este repo** (copia limpia del índice en `/tmp`, `uv sync --frozen`, raw verificado por sha256): ver §9.3.

El detalle está en `entrega/CAMBIOS_v2.md` ("Reproducción de v1") y en la verificación del workflow de correcciones v2 (Drive, §12).

### 9.2 Entregable v1 (23-oct-2026)

Corrida auditada del 23-oct-2026 (12:28–12:43, 14 min) sobre una copia de ALX en `/tmp`, con el venv original (`~/.venvs/poc-daas`, mismas versiones que `uv.lock`), los mismos raw (sha256 de `scripts/raw.sha256`) y los mismos anexos. Se ejecutó `corrida_entrega.sh` con un hook de auditoría (`sys.addaudithook`) que registró 187 archivos leídos de ALX; con eso se decidió el contenido del repo. Resultado frente a `entrega/` con `scripts/comparar_salidas.py`:

| Salida | Resultado |
|---|---|
| Excel | 6 hojas, mismas dimensiones. **1 celda distinta**: `03_Metricas_Desarrollo!F23` (Bias de M3 entradas), 0.02064426798851951 frente a 0.02064426798851952 (1 ulp). En el zip difieren `docProps/core.xml` (fecha) y `xl/worksheets/sheet3.xml` (esa celda) |
| `silenciosos.parquet` y los 6 `_schemas/*.json` | Idénticos byte a byte |
| `alertas`, `backtest`, `metricas`, `predicciones`, `recomendaciones` | Mismas filas, columnas y esquema; diferencias ≤ 9,5e-7 COP absolutas y ≤ 2,8e-18 relativas (máx. `predicciones.band_high`) |

Conclusión: equivalente según §8. La causa es ruido de punto flotante y la marca de tiempo del xlsx, no cambios de modelo ni de datos.

Lo que el 23-oct **no** se volvió a correr desde este repo: el pipeline completo (pasos 2–3) ni `publicar.py generar` (paso 4); se priorizó tener el repo disponible. Desde una copia limpia del repo sí se comprobaron `uv sync --frozen`, la importación de todos los módulos, el arranque del punto de entrada y la existencia de todas las rutas referenciadas. Las tablas de `publicar.py` son copia de `entrega/output_api` y deberían coincidir byte a byte con S3, pero esto no se verificó.

### 9.3 Corrida completa desde el repo (v2, 26-oct-2026)

Se ejecutó el 26-oct-2026 desde una copia limpia del índice del repo (`git checkout-index` en `/tmp/repo-v2`, fuera de Drive), con `uv sync --frozen`, los 19 raw verificados contra `scripts/raw.sha256` y `TRABAJO=~/.cache/poc-daas/repo_v2_corrida`, con los comandos del §6:

- `pipeline/corrida_entrega.sh` (pasos 2): U0 → U7 en 20,5 min (19:24:37 → 19:44:58), `rutas.log` con 6/6 rutas locales, 566 filas en la hoja 05.
- `scripts/comparar_salidas.py` contra `entrega/` (paso 3), exit 0:

| Salida | Resultado frente a la v2 de `entrega/` |
|---|---|
| Excel | 6 hojas con las mismas dimensiones; hojas 01, 02, 04, 05 y 06 iguales celda a celda; **1 celda distinta: `03_Metricas_Desarrollo!F23`** (Bias de M3 entradas), 0.02064426798851951 frente a 0.02064426798851952 (1 ulp). En el zip difieren `docProps/core.xml` (fecha) y `xl/worksheets/sheet3.xml` (esa celda) |
| `alertas`, `recomendaciones`, `silenciosos` y los 6 `_schemas/*.json` | Idénticos (valores exactos y mismo orden; `_schemas` byte a byte) |
| `backtest`, `metricas`, `predicciones` | Mismas filas y columnas; diferencias ≤ 4,8e-7 COP absolutas y ≤ 2,4e-18 relativas |

- `publicacion_s3/publicar.py generar --version v2` (paso 4) desde la copia, sin credenciales AWS: 249 archivos; **248/248 con el mismo sha256 que la subida publicada en `output/pronosticos/v2/`** (listado de la publicación); solo difiere `manifest.json`, que guarda la fecha de generación.

Conclusión: el repo reproduce la v2 según el criterio de §8.

## 10. Supuestos (SUP-xx)

El texto completo está en [`pipeline/docs/supuestos.md`](pipeline/docs/supuestos.md), el **registro final** de la v2 (26-oct-2026). Cada SUP tiene seis encabezados: no lo entregó el banco, qué asumimos, por qué (con el texto literal del pliego o los Anexos), efecto, alternativa y dónde se aplica. La hoja 04 del Excel cita cada SUP por número y título. No se renumeró nada: SUP-01..SUP-23 y SUP-M3-01/02 vienen de Santiago, SUP-24..SUP-40 de la v1 de ALX, **SUP-41 está reservado** (propuesta de M5 v2, no adoptada) y **SUP-42..SUP-53 son nuevos de la v2**. En la v2 se reescribieron SUP-01, 02, 03, 06, 08, 12, 13, 14, 16, 18, 21, 22, 27, 29, 36, 37, 40 y M3-01, y las "Preguntas abiertas" pasaron a "Preguntas convertidas en supuestos".

| SUP | Título en el registro |
|---|---|
| SUP-01 | Exclusión de métricas por cajero, no por entidad-día |
| SUP-02 | Ceros reales, faltantes y lectura RN-08 en el WAPE |
| SUP-03 | Días calendario en M1–M3 |
| SUP-04 | Umbral de agotamiento de M1 = 8 % del cupo (RN-34) |
| SUP-05 | Cassette de depósitos de M2 (sin efecto) |
| SUP-06 | Código de cajero reutilizado: una serie por código (RN-06) |
| SUP-07 | Saldo inicial de M6 = último registro ≤ 31-ago por fondo y denominación |
| SUP-08 | Operaciones habilitadas por fondo, inferidas del histórico (M6) |
| SUP-09 | Reparto del efecto de M1–M5 por denominación (M6) |
| SUP-10 | Mínimos y máximos operativos de M6 |
| SUP-11 | Métrica de M6 sin WAPE |
| SUP-12 | Flujo de M1–M3 al fondo, con los cajeros de sucursal (M6, RN-70) — **reescrito en v2** |
| SUP-13 | BanRep: habilitación por tarifa y restricción a Cali (M6, RN-75) |
| SUP-14 | Sin intercambio ni cambio de denominación dentro del fondo (M6, RN-84) — **reescrito en v2** |
| SUP-M3-01 | Saldo de la bóveda de M3 en [0, `cupo_max_suc`] |
| SUP-M3-02 | `cupo_max_suc` vigente por sucursal |
| SUP-15 | Nivel de servicio y costo del agotamiento (M1, M2) |
| SUP-16 | Lead time de la provisión (M1) |
| SUP-17 | Entidades con poca historia |
| SUP-18 | Nada posterior al corte entra a entrenar ni a elegir |
| SUP-19 | El 8 % de RN-34 es umbral de alerta; la política de M1 es la del pliego |
| SUP-20 | Corrección del total de M5 que consume M6 |
| SUP-21 | Tarifa urbana o interurbana de los cajeros (RN-04A) — **reescrito en v2** |
| SUP-22 | Escala de la sucursal para el costo (Escalas de Oficinas) — **reescrito en v2** |
| SUP-23 | Tasa de venta de M6 |
| SUP-24 | Métricas marcadas `origen_dato = ESTIMADO` |
| SUP-25 | Recomendaciones y alertas marcadas ESTIMADO, no SIMULADO |
| SUP-26 | REAL no aparece en los contratos de salida |
| SUP-27 | Entidad con denominador cero fuera del WAPE agregado |
| SUP-28 | Variables de contexto con el maestro vigente en cada origen |
| SUP-29 | Corrección de los disponibles de M6: sin `TOTAL` y TDV_001 en pesos |
| SUP-30 | Regla de adopción R1–R5 declarada antes de medir |
| SUP-31 | k = 2 en R1 por búsqueda múltiple |
| SUP-32 | Pesos congelados en los ensambles ponderados |
| SUP-33 | Contexto empaquetado en el modelo registrado |
| SUP-34 | Demanda censurada: se modela lo dispensado |
| SUP-35 | Duplicado del 13-may-2026 y valores corruptos: corrección de datos, no imputación |
| SUP-36 | Imputación de faltantes: evaluada y no adoptada |
| SUP-37 | Ceros de M3 en agosto de 2026 leídos como reales |
| SUP-38 | Repetición acotada del laboratorio a los finalistas |
| SUP-39 | Modelos finales del laboratorio en el pipeline del entregable |
| SUP-40 | Plantilla del Anexo D y tarifas del Anexo E de la corrida |
| SUP-41 | Reservado (M5 v2, no adoptado) |
| SUP-42 | Nivel de riesgo antes de la acción (hoja 02) — v2 |
| SUP-43 | Monto mínimo de recolección — v2 |
| SUP-44 | Cupo insuficiente (M1–M3) — v2 |
| SUP-45 | Maestro CP vigente (snapshot del 8-sep-2026) — v2 |
| SUP-46 | Insumos del Anexo A no recibidos (`Historico BANREP.xlsx`, `Historico Traslados.xlsx`) — v2 |
| SUP-47 | Nivel de riesgo residual de la hoja 05 — v2 |
| SUP-48 | Columna de cumplimiento ausente en la plantilla — v2 |
| SUP-49 | Definiciones de calendario de RN-04 — v2 |
| SUP-50 | RN-08 como pronóstico cero de equipos silenciosos — v2 |
| SUP-51 | Variables de eventos y externas (RN-04, §5) — v2 |
| SUP-52 | Traslado disponible en el fondo destino al día siguiente (M6, Anexo E y RN-74) — v2 |
| SUP-53 | Tarifa del traslado entre ciudades: la de la transportadora del fondo origen (M6) — v2 |

Detalle de los que más pesan en el resultado:

- **SUP-02 / SUP-27**: una entidad cuyo valor real suma cero en la ventana sale solo del WAPE agregado (métricas y hoja 03). Interruptor `sup02_denominador_cero`.
- **SUP-12 (v2)**: M6 integra el flujo de 82 de los 84 cajeros administrados por sucursal al fondo de su sucursal (Oficinas); 9859 y 9860 quedan fuera y declarados (2.568.045.929 COP de pagado de M1; sucursal 787 ausente de Oficinas). Interruptor `m6_cajeros_sucursal`.
- **SUP-14 (v2)**: sin intercambio ni cambio de denominación dentro del fondo; las operaciones de RN-84 usadas son `traslado_fondos` (198 filas), `venta_efectivo` (148) y `retiro_banrep` (4). Interruptor `m6_operaciones_rn84`.
- **SUP-21 / SUP-22 (v2)**: tarifa MF interurbano para 5 MF de TDV fuera del municipio del fondo (+3.936.535 COP en M2) y escala de la sucursal 70 desde `Escalas` (−6.757.937 COP en M3).
- **SUP-28**: las variables de contexto V4 usan el maestro vigente en cada origen, construido por `imputacion/contexto_asof.py`. Interruptor `contexto_asof`.
- **SUP-29**: los disponibles de M6 se corrigen (sin la fila `TOTAL`, TDV_001 de piezas a pesos, sin días con blancos o doble formato). Interruptor `correccion_m6` y `correccion_disponibles.aplicar` en `model_u6.yml`.
- **SUP-35 / SUP-36**: corrección de datos (duplicado del 13-may-2026, corruptos a NaN), no imputación; la imputación se evaluó y no se adoptó (§11).
- **SUP-42..SUP-44 (v2)**: `nivel_riesgo` de la hoja 02 antes de la acción; M3 no recoge efectivo ocioso que no paga su visita (7 omitidas por 548.282 COP); cupo insuficiente declarado en los MF 8667 y 9311.
- **SUP-46 (v2)**: los insumos no recibidos son `Historico BANREP.xlsx` e `Historico Traslados.xlsx` del Anexo A; la habilitación de BanRep, traslados y ventas se suple con SUP-08 y SUP-13. Los Anexos A–E sí se recibieron.
- **SUP-52 / SUP-53 (v2)**: el traslado llega al destino al día siguiente (nota del Anexo E) y se ordena el día anterior al faltante, con las dos filas en la fecha de ejecución (RN-74); el traslado entre ciudades se cobra con la tarifa de la transportadora del fondo origen (545.413 COP; con la del destino serían 938.560).

## 11. Decisiones adoptadas y descartadas

Adoptadas:

- **Regla de adopción R1–R5 con k = 2** (SUP-30, SUP-31), declarada antes de medir. Un candidato reemplaza a la receta de Santiago solo si la cumple. La huella de la regla se calcula con `ml.adopcion.huella_regla()` sobre `ml/conf/adopcion_ml.yml` y vale `623420f48f04` (sin cambios durante el entregable). `ml/adopcion.py` y `ml/conf/` **no están en el repo** porque el pipeline no los usa; están en `ALX/ml/`.
- **Pesos congelados** en los ensambles ponderados (SUP-32).
- **Escenario S1** en todos los champions: datos corregidos (SUP-35) + V4 "as of" (SUP-28), sin imputación.
- **M4** conserva la receta de Santiago (`combo_perfil_gbml1`): ningún candidato cumplió R1–R5.
- **Correcciones v2** (26-oct; `entrega/CAMBIOS_v2.md`): las de los diez interruptores de §3, tras una auditoría del entregable v1 contra el texto literal del pliego y de los Anexos B y C. Las decisiones D-1 (escala desde `Escalas`, SUP-22) y D-2 (textos de la hoja 03) las confirmó el usuario el 26-oct. No cambian pronósticos ni métricas predictivas.
- **Registro propio como versión final de supuestos** (26-oct): los documentos de Andrés en `revision-andres/` no se usan.

Pendientes de decisión del usuario (sin aplicar): segunda atención consolidada en 8667/9311 (alternativa de SUP-44) y tarifa interurbana para los 4 dispensadores INDIVIDUAL (alternativa de SUP-21, +575.069 COP).

Evaluadas y no adoptadas:

- **Imputación de faltantes** (SUP-36): T0 = T1 = T2 en `ALX/imputacion/resultados/ml/decision_final.csv`; ningún champion mejora con ella. El interruptor `imputacion` queda en `false` y encenderlo aborta la corrida. Todo el experimento se conserva en `ALX/imputacion/` (§12).
- **Mejora de M5 v2**: sin cambios en el entregable. La recomendación SUP-41 no se aplicó y el número queda reservado (`ALX/m5_mejora/resultados_m5_v2.md`).
- **Descartados**: SARIMA (solo referencia, `ALX/sarima/`), CatBoost con variables categóricas, XGBoost, ETS/Theta/MSTL y modelos fundacionales.

## 12. Material no incluido en el repo

Todo sigue en Google Drive, en `Mi unidad/PoC-Bancolombia/ALX/` (en adelante `ALX/`), sin cambios. Útil para sustentación y mejoras. Algunos resultados intermedios están además en `~/.cache/poc-daas/` del equipo de Alexander Peláez.

| Material | Ruta | Contenido |
|---|---|---|
| Imputación (no adoptada) | `ALX/imputacion/` (29 MB) | Métodos, inventario de faltantes, aplicación, decisión con ML, MLflow, notebook `05_imputacion_faltantes.ipynb`, `resultados/` (incluye `ml/decision_final.csv`, `entrega_cumplimiento_pliego.md`, `entrega_comparacion_santiago.md`) y `conf/`. Corridas en `~/.cache/poc-daas/imputacion/` |
| Fase 2 de ML | `ALX/ml/` (20 MB) | Entrenamiento, Optuna, ensambles, registro en MLflow, adopción (`adopcion.py`, `huella_regla`), `conf/adopcion_ml.yml`, `conf/ensambles/`, `verificar_registro.py`, notebook `04_mejora_modelos_ml.ipynb` y `resultados/` (`adopcion.csv`). Registro MLflow en `~/.mlflow/poc-daas/mlflow.db`; colas y artefactos en `~/.cache/poc-daas/ml/` |
| Laboratorio (resto) | `ALX/lab/` | Arnés de evaluación, simuladores, explicabilidad, incertidumbre, handoff, tests y conf (`evaluacion`, `explicabilidad`, `picos`, `politicas`, `politicas_m3`, `traspaso`) |
| Registros del laboratorio | `ALX/resultados/` (14 MB) | `corridas.jsonl`, `bandas.jsonl`, `explicabilidad.jsonl`, `picos.jsonl` |
| EDA Box-Jenkins v2 (vigente) | `ALX/eda/03_eda_box_jenkins_v2.ipynb` (24-oct), módulo `ALX/eda/eda_bj.py` | EDA de M1–M6 solo en fase de identificación, sin estimar modelos: correlogramas clásicos, ADF + KPSS (D antes que d), estacionalidad y eventos de calendario, intermitencia, relaciones multivariadas, qué variables importan (§9) y conclusiones por modelo (§10). Resumen en `CONTEXTO_LLM.md` §6.2 |
| EDA de M5 | `ALX/eda/04_eda_m5.ipynb` (25-oct), módulo `ALX/eda/eda_m5.py` | EDA dedicado de M5: concentración por punto, colas pesadas, megapuntos, cambio de 2026 y causas del sesgo del champion. Resumen en `CONTEXTO_LLM.md` §6.5 y en `Mi unidad/PoC-Bancolombia/.agents/tasks/eda-m5/final_report.md` |
| EDA por serie (superado) | `ALX/eda/` (36 MB en total con los dos anteriores) | Primera versión del EDA Box-Jenkins (18-oct), notebook `02_eda_series_box_jenkins.ipynb` y resultados; **superado por el 03** |
| SARIMA | `ALX/sarima/` (5,9 MB) | Referencia SARIMA, paridad con el arnés, notebook `03_sarima_referencia.ipynb` y resultados. Corridas en `~/.cache/poc-daas/sarima/` |
| Mejora M5 v2 | `ALX/m5_mejora/` | Regla v2, SUP-20, medición, revisión, tests e informe `resultados_m5_v2.md`. Corridas en `~/.cache/poc-daas/m5_v2/` |
| Notebook de series | `ALX/01_series_de_tiempo.ipynb` (8,9 MB) | Análisis de series de tiempo; `ALX/graficos_poc.py` lo apoya |
| Guía de supuestos | `ALX/guia_supuestos.md` | Guía para quien llega sin contexto: qué es cada SUP, su efecto, relación con el pliego y diferencias con los documentos de Andrés. Escrita antes de la v2 (cubre SUP-01..SUP-41); para el texto vigente manda `pipeline/docs/supuestos.md` |
| Variables por modelo | `ALX/variables_por_modelo.md` | Qué variables usa cada champion, qué significan y cuánto pesan (los pronósticos no cambian en v2) |
| Auditoría del pliego | `Mi unidad/PoC-Bancolombia/.agents/tasks/auditoria-pliego/auditoria.md` | Auditoría independiente del entregable v1 contra el pliego y el texto literal de los Anexos B y C; origen de las correcciones v2 |
| Correcciones v2 | `Mi unidad/PoC-Bancolombia/.agents/tasks/correcciones-v2/` (`plan.md`, `verificacion.md`, `revision-final.md`, `evidencia/`) | Plan, verificación (corridas A2 y B2, `verificar_v2.py`, `verificar_t1.py`) y revisión de la v2. Corridas y scripts en `~/.cache/poc-daas/corrida_entrega_v2/` |
| Pruebas de la v2 | `ALX/tests_alx/test_correcciones_v2.py` | Pruebas de los interruptores v2 (no hay pruebas en el repo, §13) |
| Respaldo v1 | `ALX/entrega/historico/v1_2026-10-21/` | Excel `52e7547f…` y `output_api` de la v1. No se copia al repo: git la conserva en el commit `955115d` |
| Contexto para Andrés | `ALX/entrega/CONTEXTO_v2_para_Andres.md` | Comunicación interna sobre la corrida v2; no entra al repo |
| Supuestos de Andrés (no se usan) | `Mi unidad/PoC-Bancolombia/revision-andres/`, `ALX/Supuestos-Analiticos-PoC-DaaS-Bancolombia.pdf` | Otra numeración desde SUP-15; desde el 26-oct manda el registro propio `pipeline/docs/supuestos.md` |
| Anexos A, B y C originales | `~/Desktop/datos-anexo-poc-bancolombia/` (equipo de Alexander Peláez) | Metadatos de insumos, reglas de negocio RN-xx y observaciones de calidad. El repo versiona solo D y E porque la corrida no lee A, B ni C |
| Pipeline (resto) | `ALX/pipeline/` | `corrida_local.sh` (Santiago), `tests/`, `conf/aws.yml`, `conf/contracts/C-01..C-12.yml`, `pyproject.toml`/`uv.lock`/`requirements.txt` antiguos (no reproducen el entorno real), `modules/funds_m6/recommender.py`, `quality/schemas.py` |
| Publicación S3 (resto) | `ALX/publicacion_s3/`, `Mi unidad/PoC-Bancolombia/.agents/tasks/publicacion-s3-v2/reporte.md` | `README.md` (versiones `v2`/`v0_provisional`, `version_vigente.json`, salvaguardas de `subir`, cómo se publicó la v2 y cómo republicar, discrepancias con los contratos); reporte y listados de la publicación v2, inventario del bucket (`inventario_bucket.py/.csv/.md`), tests y `revision/` r1 y r2 (VersionId de r1 en `revision/r2/versiones_revision1.tsv`) |
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
- `publicar.py --version v2` depende de los insumos locales de la corrida B2 (`~/.cache/poc-daas/corrida_entrega_v2/B2_v2/`, ruta fija en el script); `--version v0_provisional` depende del respaldo v1 (fuera del repo) y de `interim/`/`processed/` del bucket 777937796305 (sesión `alx-mx` vigente).
- El pipeline no lee `interim/`, `processed/` ni `features/` de S3: U0 los regenera desde `raw/`.
- No hay pruebas automatizadas en el repo (están en `ALX/pipeline/tests` y `ALX/tests_alx`).
- `publicar.py subir` no se probó desde el repo: no hace falta, la v2 ya está publicada (`generar` sí, §9.3).
