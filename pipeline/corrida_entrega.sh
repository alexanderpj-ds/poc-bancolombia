#!/bin/sh
# ALX PARTE 7: corrida del entregable con los champions finales (misma secuencia que corrida_local.sh de Santiago).
# Uso: [UNIDADES="u0 u1_u2 u3 u4_u5 u6 u7"] [CONF_ALX=<alx.yml>] sh corrida_entrega.sh <raiz_de_datos> <trabajo> [python]
# Diferencias con corrida_local.sh (que no se modifica):
#   - PYTHONPATH incluye la raiz de ALX (paquetes ml, lab, imputacion: familia ml_laboratorio y contexto "as of");
#   - DAAS_SCHEME=local forzado y, antes de cada unidad, se comprueba que ninguna ruta de salida resuelve a s3://;
#   - CONF_ALX permite correr con otro conf/alx.yml (p. ej. todos los interruptores apagados = Santiago);
#   - con REANUDAR=1 no se borra la carpeta de trabajo y se parte de lo ya escrito (unidades indicadas en UNIDADES).
# Deja: <trabajo>/data (copia + salidas), <trabajo>/conf y <trabajo>/<unidad>.log.
set -eu
ORIGEN=$(cd "$1" && pwd); mkdir -p "$2"; TRABAJO=$(cd "$2" && pwd)
AQUI=$(cd "$(dirname "$0")" && pwd); ALX=$(cd "$AQUI/.." && pwd); PY=${3:-python}
UNIDADES=${UNIDADES:-"u0 u1_u2 u3 u4_u5 u6 u7"}
if [ "${REANUDAR:-0}" != "1" ]; then
  rm -rf "$TRABAJO/data" "$TRABAJO/conf"
  cp -R "$ORIGEN" "$TRABAJO/data"; cp -R "$AQUI/conf" "$TRABAJO/conf"
  rm -rf "$TRABAJO/data/output"
  case " $UNIDADES " in
    *" u0 "*) rm -rf "$TRABAJO/data/features" "$TRABAJO/data/processed" "$TRABAJO/data/interim" ;;
    *) rm -rf "$TRABAJO/data/processed/_holdout" "$TRABAJO/data/raw" ;;
  esac
  sed -e 's|^default_scheme:.*|default_scheme: local|' -e "s|^  root:.*|  root: $TRABAJO/data|" \
      "$AQUI/conf/paths.yml" > "$TRABAJO/conf/paths.yml"
  if [ -n "${CONF_ALX:-}" ]; then cp "$CONF_ALX" "$TRABAJO/conf/alx.yml"; fi
fi
export DAAS_CONF="$TRABAJO/conf" PYTHONPATH="$ALX:$AQUI/src" DAAS_SCHEME=local PYTHONDONTWRITEBYTECODE=1
unset DAAS_S3_BUCKET || true
for U in $UNIDADES; do
  "$PY" -c "
from daas.io import storage
for uri in ('daas://output/api/predicciones', 'daas://output/anexo_d/x', 'daas://processed/m1_atm_dispensador',
            'daas://interim/cp_historico', 'daas://features/ts_features_m1', 'daas://quality/reports/x'):
    r = storage.resolve_uri(uri)
    assert r.startswith('file://'), r
print('rutas de salida locales (sin s3://): ok')
" >> "$TRABAJO/rutas.log" 2>&1 || { echo "FALLO chequeo de rutas"; exit 1; }
  echo "== $U $(date +%H:%M:%S)"
  "$PY" -m daas.pipeline.run_$U > "$TRABAJO/$U.log" 2>&1 || { echo "FALLO $U"; tail -20 "$TRABAJO/$U.log"; exit 1; }
  tail -3 "$TRABAJO/$U.log"
done
echo "== listo $(date +%H:%M:%S)"
