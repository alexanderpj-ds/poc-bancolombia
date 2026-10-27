# Instrucciones para agentes

**Antes de cualquier otra cosa, lee completo `CONTEXTO_LLM.md`.** Es el contexto del proyecto: qué es la PoC, de dónde viene el código (repos de Andrés y de Santiago y el trabajo de ALX), los datos y sus problemas, los modelos y champions, los supuestos, los experimentos no adoptados (imputación, SARIMA, EDA, M5) y dónde está ese material, la publicación en S3, la reproducibilidad, los pendientes y qué no asumir (§13).

Después lee `README.md`: tiene los comandos exactos para instalar, correr y comparar.

Reglas:

- S3 es solo lectura (`ls`, `head-object`, `cp` S3→local). Nada del flujo de reproducción del repo sube a S3. No ejecutes `publicacion_s3/publicar.py subir` sin pedido explícito, ni borres o sobrescribas `output/pronosticos/v0_provisional/`, `output/pronosticos/v2/` o `version_vigente.json`.
- Nunca ejecutes `aws sso login`, `aws sso logout` ni `aws configure sso`. Si las credenciales vencen, pide al usuario que renueve la sesión (README §5.2).
- Corre el pipeline con la carpeta de trabajo fuera de Google Drive o de carpetas sincronizadas. `corrida_entrega.sh` borra `<trabajo>/data` y `<trabajo>/conf` al iniciar.
- No edites la lógica de los modelos ni las configuraciones congeladas (`lab/conf/experimentos/`, `pipeline/conf/`) sin acuerdo explícito: cambian el entregable.
- Para comparar una corrida nueva con `entrega/` usa `scripts/comparar_salidas.py` y el criterio de equivalencia del README §8 (el sha256 del Excel nunca coincide).
- El entregable vigente es la **v2** (26-oct-2026): `entrega/POC_Efectivo_PRAGMA.xlsx` con sha256 `167a52e41f00cfa3c3bb202a51743d4182e7d9664a953927ccb4ea00aa2b9461` y `entrega/output_api/`; los cambios frente a la v1 (`52e7547f…`, commit `955115d`) están en `entrega/CAMBIOS_v2.md`. No reemplaces el Excel ni los contratos sin acuerdo.
- `pipeline/conf/alx.yml` lleva los interruptores v2 en `true` (`m6_cajeros_sucursal`, `m2_tarifa_interurbana`, `m3_escala_anexo_a`, `nivel_riesgo_previo`, `monto_minimo_recoleccion`, `m6_operaciones_rn84`, `m6_traslado_t1`, `m6_tarifa_traslado_declarada`, `hoja04_v2`, `hoja03_textos_v2`) además de los de la v1; `imputacion` sigue en `false`. Con esos valores la corrida reproduce la v2.
- La publicación vigente en S3 es `s3://poc-daas-bancolombia-777937796305/output/pronosticos/v2/` (v2, 249 objetos); el puntero `output/pronosticos/version_vigente.json` dice cuál es la vigente y cuál la anterior. `output/pronosticos/v0_provisional/` es la v1, conservada sin cambios. `publicacion_s3/publicar.py` está parametrizado por versión (`--version v2` por defecto, exige el sha256 completo del Excel `167a52e4…`; `--version v0_provisional` reproduce la v1). No cambies `PUBLICACIONES` ni las salvaguardas de `subir` sin acuerdo.
- Los supuestos vigentes son los del registro propio `pipeline/docs/supuestos.md` (SUP-01..SUP-53, versión final). No uses los documentos de Andrés (`revision-andres/`, PDF de supuestos) como fuente: usan otra numeración.
- `output/api/` de los buckets no es el resultado vigente (es una salida anterior del pipeline de Andrés); lo vigente es `entrega/` (v2) y `output/pronosticos/v2/` (`CONTEXTO_LLM.md` §7).
- Si dos fuentes se contradicen, manda la más reciente; `CONTEXTO_LLM.md` señala las contradicciones ya resueltas.
