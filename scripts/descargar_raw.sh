#!/bin/sh
# Descarga los 19 insumos raw/ de la réplica S3 (SOLO LECTURA) a datos/raiz/raw/ y verifica sus sha256.
# Uso: sh scripts/descargar_raw.sh        (requiere sesión SSO vigente del perfil alx-poc; ver README §5)
# Variables opcionales: AWS_PROFILE_RAW (perfil, por defecto alx-poc), AWS_BIN (binario aws, por defecto aws).
set -eu
BUCKET=poc-daas-bancolombia-replica-903641686926
PERFIL=${AWS_PROFILE_RAW:-alx-poc}
AWS=${AWS_BIN:-aws}
REPO=$(cd "$(dirname "$0")/.." && pwd)
DESTINO="$REPO/datos/raiz/raw"
mkdir -p "$DESTINO"
"$AWS" s3 cp "s3://$BUCKET/raw/" "$DESTINO/" --recursive --profile "$PERFIL" --region us-east-1
cd "$REPO/datos/raiz" && shasum -a 256 -c "$REPO/scripts/raw.sha256"
echo "raw/ listo en $DESTINO (19 archivos verificados)"
