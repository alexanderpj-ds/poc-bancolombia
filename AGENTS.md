# Instrucciones para agentes

**Antes de cualquier otra cosa, lee completo `CONTEXTO_LLM.md`.** Es el contexto del proyecto: qué es la PoC, de dónde viene el código (repos de Andrés y de Santiago y el trabajo de ALX), los datos y sus problemas, los modelos y champions, los supuestos, los experimentos no adoptados (imputación, SARIMA, EDA, M5) y dónde está ese material, la publicación en S3, la reproducibilidad, los pendientes y qué no asumir (§13).

Después lee `README.md`: tiene los comandos exactos para instalar, correr y comparar.

Reglas:

- S3 es solo lectura (`ls`, `head-object`, `cp` S3→local). Nada del flujo del repo sube a S3.
- Nunca ejecutes `aws sso login`, `aws sso logout` ni `aws configure sso`. Si las credenciales vencen, pide al usuario que renueve la sesión (README §5.2).
- Corre el pipeline con la carpeta de trabajo fuera de Google Drive o de carpetas sincronizadas. `corrida_entrega.sh` borra `<trabajo>/data` y `<trabajo>/conf` al iniciar.
- No edites la lógica de los modelos ni las configuraciones congeladas (`lab/conf/experimentos/`, `pipeline/conf/`) sin acuerdo explícito: cambian el entregable.
- Para comparar una corrida nueva con `entrega/` usa `scripts/comparar_salidas.py` y el criterio de equivalencia del README §8 (el sha256 del Excel nunca coincide).
- `publicacion_s3/publicar.py` exige el Excel de `entrega/` con sha256 `52e7547f…`; no lo reemplaces.
- `output/api/` de los buckets no es el resultado vigente (es una salida anterior del pipeline de Andrés); lo vigente es `entrega/` y `output/pronosticos/v0_provisional/` (`CONTEXTO_LLM.md` §7).
- Si dos fuentes se contradicen, manda la más reciente; `CONTEXTO_LLM.md` señala las contradicciones ya resueltas.
