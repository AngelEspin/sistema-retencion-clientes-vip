"""Despliegue serverless del simulador (S3 + Lambda + Function URL IAM).

Idempotente: crea lo que falta y actualiza lo que ya existe, asi que sirve tanto
para el primer despliegue como para publicar artefactos nuevos tras recalcular.

Dos destinos, el mismo codigo:

  * AWS real (AWS Academy Learner Lab): usa el rol LabRole existente (el lab no
    permite crear roles) y la capa gestionada AWSSDKPandas, que trae pandas,
    numpy y pyarrow. El paquete propio son dos archivos .py.
  * LocalStack (--localstack): AWS emulado en local, ver infra/localstack/. La
    edicion Community no implementa capas, asi que pandas, numpy y pyarrow se
    empaquetan para Linux con las MISMAS versiones del entorno local -es lo que
    hace exacta la paridad numerica-, y el paquete se sube a S3.

La Function URL se crea con auth AWS_IAM: cada peticion debe ir firmada con
SigV4. Una URL publica (auth NONE) expondria a internet una funcion que lee
datos de clientes; esa decision no se toma por defecto.

Uso:
    python infra/desplegar.py                  # AWS real
    python infra/desplegar.py --localstack     # AWS emulado en http://localhost:4566
    python infra/desplegar.py --sin-url        # solo invocacion directa
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "data" / "artifacts"
BUILD = ROOT / "build" / "lambda_deps"
REGION = "us-east-1"
FUNCION = "simulador-retencion"
MEMORIA_MB = 2048
TIMEOUT_S = 120
# Capa publica de AWS SDK for pandas para Python 3.12 (cuenta 336392948345).
CAPA = "arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python312:20"
ENDPOINT_LOCALSTACK = "http://localhost:4566"
DEPENDENCIAS = ("pandas", "numpy", "pyarrow")

ARCHIVOS_CODIGO = {
    "simulador.py": ROOT / "src" / "simulation" / "simulador.py",
    "lambda_handler.py": ROOT / "infra" / "lambda_handler.py",
}


def _configurar_localstack() -> None:
    """boto3 lee AWS_ENDPOINT_URL: todos los clientes apuntan al emulador."""
    os.environ.setdefault("AWS_ENDPOINT_URL", ENDPOINT_LOCALSTACK)
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", REGION)


def _dependencias_linux() -> Path:
    """Instala pandas, numpy y pyarrow para Linux x86_64 / CPython 3.12.

    Se fijan las versiones del entorno local: la paridad nube = local exige el
    mismo numpy (generador aleatorio y ordenamientos identicos).
    """
    pines = [f"{d}=={metadata.version(d)}" for d in DEPENDENCIAS]
    marca = BUILD / ".versiones"
    if marca.exists() and marca.read_text(encoding="utf-8") == " ".join(pines):
        return BUILD
    print(f"Empaquetando dependencias para Lambda: {' '.join(pines)}")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--target", str(BUILD),
         "--only-binary=:all:", "--implementation", "cp", "--python-version", "3.12",
         "--platform", "manylinux_2_28_x86_64", "--platform", "manylinux_2_17_x86_64",
         "--platform", "manylinux2014_x86_64", *pines],
        check=True,
    )
    marca.write_text(" ".join(pines), encoding="utf-8")
    return BUILD


def _paquete(con_dependencias: bool) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for nombre, ruta in ARCHIVOS_CODIGO.items():
            z.write(ruta, nombre)
        if con_dependencias:
            base = _dependencias_linux()
            for ruta in base.rglob("*"):
                rel = ruta.relative_to(base).as_posix()
                # Las pruebas de las librerias son ~30% del peso y no se ejecutan.
                if ruta.is_dir() or "__pycache__" in rel or "/tests/" in f"/{rel}" or rel == ".versiones":
                    continue
                z.write(ruta, rel)
    return buffer.getvalue()


def _esperar(lam, nombre: str) -> None:
    """Lambda rechaza un update mientras otro sigue en curso."""
    for _ in range(120):
        cfg = lam.get_function_configuration(FunctionName=nombre)
        if cfg.get("State") == "Active" and cfg.get("LastUpdateStatus") in ("Successful", None):
            return
        if cfg.get("LastUpdateStatus") == "Failed" or cfg.get("State") == "Failed":
            raise SystemExit(f"Fallo la funcion: {cfg.get('LastUpdateStatusReason') or cfg.get('StateReason')}")
        time.sleep(2)
    raise SystemExit("La funcion no quedo activa a tiempo")


def asegurar_bucket(s3, bucket: str) -> None:
    from botocore.exceptions import ClientError

    try:
        s3.head_bucket(Bucket=bucket)
        print(f"Bucket existente: {bucket}")
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        print(f"Bucket creado   : {bucket}")
    # Privado siempre: contiene seudonimos de clientes y su probabilidad de fuga.
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )


def subir_artefactos(s3, bucket: str) -> dict[str, int]:
    subidos: dict[str, int] = {}
    objetos = {f"artifacts/{p.name}": p for p in ARTIFACTS.glob("*") if p.suffix in (".json", ".parquet")}
    for rfm in (ROOT / "data" / "processed" / "rfm").glob("corte=*/rfm.parquet"):
        objetos[f"curated/rfm/{rfm.parent.name}/rfm.parquet"] = rfm
    for clave, ruta in sorted(objetos.items()):
        s3.upload_file(str(ruta), bucket, clave)
        subidos[clave] = ruta.stat().st_size
        print(f"  s3://{bucket}/{clave}  ({ruta.stat().st_size / 1e6:,.1f} MB)")
    return subidos


def asegurar_rol(iam, cuenta: str) -> str:
    """En AWS Academy el rol ya existe; en LocalStack se crea con el mismo nombre."""
    try:
        return iam.get_role(RoleName="LabRole")["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        confianza = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
                                                              "Principal": {"Service": "lambda.amazonaws.com"}}]}
        return iam.create_role(RoleName="LabRole", AssumeRolePolicyDocument=json.dumps(confianza))["Role"]["Arn"]


def desplegar_funcion(lam, rol: str, bucket: str, codigo: dict, capas: list[str]) -> dict:
    entorno = {"Variables": {"BUCKET": bucket}}
    comun = dict(Runtime="python3.12", Handler="lambda_handler.lambda_handler", Role=rol,
                 MemorySize=MEMORIA_MB, Timeout=TIMEOUT_S, Layers=capas, Environment=entorno)
    try:
        lam.get_function(FunctionName=FUNCION)
        _esperar(lam, FUNCION)
        lam.update_function_code(FunctionName=FUNCION, **codigo)
        _esperar(lam, FUNCION)
        lam.update_function_configuration(FunctionName=FUNCION, **comun)
        print(f"Funcion actualizada: {FUNCION}")
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(FunctionName=FUNCION, Code=codigo, Architectures=["x86_64"],
                            Description="Simulador multiagente de retencion VIP", **comun)
        print(f"Funcion creada     : {FUNCION}")
    _esperar(lam, FUNCION)
    return lam.get_function_configuration(FunctionName=FUNCION)


def asegurar_url(lam) -> str:
    try:
        return lam.get_function_url_config(FunctionName=FUNCION)["FunctionUrl"]
    except lam.exceptions.ResourceNotFoundException:
        return lam.create_function_url_config(FunctionName=FUNCION, AuthType="AWS_IAM")["FunctionUrl"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--localstack", action="store_true", help="Desplegar en AWS emulado (LocalStack)")
    parser.add_argument("--sin-url", action="store_true", help="No crear la Function URL")
    args = parser.parse_args()
    if args.localstack:
        _configurar_localstack()

    import boto3
    from botocore.config import Config

    sesion = boto3.Session(region_name=REGION)
    cuenta = sesion.client("sts").get_caller_identity()["Account"]
    bucket = f"proyecto-retencion-vip-{cuenta}"
    s3 = sesion.client("s3")
    # El primer arranque en el emulador incluye crear el contenedor: margen amplio.
    lam = sesion.client("lambda", config=Config(read_timeout=600, retries={"max_attempts": 1}))
    rol = asegurar_rol(sesion.client("iam"), cuenta) if args.localstack else f"arn:aws:iam::{cuenta}:role/LabRole"

    asegurar_bucket(s3, bucket)
    print("Subiendo artefactos ...")
    subidos = subir_artefactos(s3, bucket)

    paquete = _paquete(con_dependencias=args.localstack)
    print(f"Paquete Lambda: {len(paquete) / 1e6:,.1f} MB "
          f"({'codigo + pandas, numpy y pyarrow' if args.localstack else ', '.join(ARCHIVOS_CODIGO)})")
    if args.localstack:
        # Por encima de 50 MB el codigo no puede ir en la llamada: se sube a S3.
        s3.put_object(Bucket=bucket, Key="lambda/paquete.zip", Body=paquete)
        codigo, capas = {"S3Bucket": bucket, "S3Key": "lambda/paquete.zip"}, []
    else:
        codigo, capas = {"ZipFile": paquete}, [CAPA]
    cfg = desplegar_funcion(lam, rol, bucket, codigo, capas)
    url = None if args.sin_url else asegurar_url(lam)

    # Verificacion inmediata: la funcion carga la poblacion desde S3.
    inicio = time.perf_counter()
    r = lam.invoke(FunctionName=FUNCION, Payload=json.dumps({"rawPath": "/health"}).encode())
    respuesta = json.loads(r["Payload"].read())
    if r.get("FunctionError") or "body" not in respuesta:
        raise SystemExit(f"/health fallo: {respuesta}")
    salud = json.loads(respuesta["body"])
    print(f"/health -> {salud}  ({time.perf_counter() - inicio:,.1f} s, primer arranque)")

    registro = {
        "desplegado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entorno": "LocalStack (AWS emulado en local)" if args.localstack else "AWS",
        "endpoint": os.environ.get("AWS_ENDPOINT_URL") if args.localstack else None,
        "region": REGION,
        "cuenta": cuenta,
        "bucket": bucket,
        "funcion": cfg["FunctionArn"],
        "function_url": url,
        "auth_url": "AWS_IAM" if url else None,
        "runtime": cfg["Runtime"],
        "memoria_mb": cfg["MemorySize"],
        "timeout_s": cfg["Timeout"],
        "capa": capas[0] if capas else None,
        "dependencias_empaquetadas": {d: metadata.version(d) for d in DEPENDENCIAS} if args.localstack else None,
        "paquete_mb": round(len(paquete) / 1e6, 1),
        "objetos_s3_bytes": subidos,
        "almacenamiento_s3_gb": round(sum(subidos.values()) / 1e9, 4),
        "acceso_publico_bucket": s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"],
        "health": salud,
    }
    (ARTIFACTS / "aws_despliegue.json").write_text(
        json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDespliegue registrado en {ARTIFACTS / 'aws_despliegue.json'}")
    if url:
        print(f"Function URL (firmada con SigV4): {url}")


if __name__ == "__main__":
    main()
