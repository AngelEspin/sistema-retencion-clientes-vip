#!/usr/bin/env bash
# Levanta LocalStack (AWS emulado en local) dentro de WSL2 con Docker Engine.
#
# Sustituye a la cuenta de AWS Academy, que ya no esta disponible: el mismo
# despliegue (S3 + Lambda + Function URL) corre contra los servicios emulados en
# http://localhost:4566, alcanzable desde Windows por el reenvio de puertos de WSL.
#
# Uso, desde Windows:
#   wsl -d Ubuntu-24.04 -u root -- bash infra/localstack/levantar_localstack.sh
set -euo pipefail

# Desde las versiones 2026.x la imagen exige un token de licencia; 4.14.0 es la
# ultima Community que corre sin cuenta.
IMAGEN="${LOCALSTACK_IMAGEN:-localstack/localstack:4.14.0}"
RUNTIME="public.ecr.aws/lambda/python:3.12"

systemctl is-active --quiet docker || systemctl start docker
docker pull -q "$IMAGEN"
# La imagen del runtime se descarga antes para que su descarga no se mida como
# arranque en frio en la prueba de carga.
docker pull -q "$RUNTIME"
docker rm -f localstack >/dev/null 2>&1 || true

# LocalStack Community no implementa capas de Lambda (es una funcion de pago), asi
# que pandas, numpy y pyarrow viajan dentro del paquete y se suben los limites de
# tamano de codigo.
docker run -d --name localstack --restart unless-stopped \
  -p 4566:4566 -p 4510-4559:4510-4559 \
  -e SERVICES=s3,lambda,iam,sts,logs,cloudwatch \
  -e LAMBDA_LIMITS_CODE_SIZE_UNZIPPED=524288000 \
  -e LAMBDA_LIMITS_CODE_SIZE_ZIPPED=262144000 \
  -e LAMBDA_LIMITS_CREATE_FUNCTION_REQUEST_SIZE=262144000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$IMAGEN" >/dev/null

for _ in $(seq 1 90); do
  if curl -fs http://localhost:4566/_localstack/health >/dev/null 2>&1; then break; fi
  sleep 2
done
if ! curl -fs http://localhost:4566/_localstack/health; then
  docker logs --tail 40 localstack
  exit 1
fi
echo
docker image inspect "$IMAGEN" --format 'imagen {{.Id}} {{.Size}} bytes'
docker exec localstack sh -c 'localstack --version 2>/dev/null || cat /opt/code/localstack/VERSION 2>/dev/null' || true
