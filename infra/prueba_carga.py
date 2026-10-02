"""Prueba de carga y latencia de la Lambda desplegada.

Mide lo que el analisis de costo/beneficio y la matriz de validacion necesitan
medido, no supuesto:

  * Latencia p50/p95 en caliente y en arranque en frio, vista por el cliente.
  * Duracion facturada y memoria maxima por invocacion, leidas de la linea
    REPORT que Lambda devuelve con LogType=Tail. Es la base del costo real.
  * Comportamiento con peticiones concurrentes (errores, nuevos arranques).
  * La Function URL firmada con SigV4, de extremo a extremo por HTTPS.

Uso:
    python infra/prueba_carga.py                # pruebas completas
    python infra/prueba_carga.py --rapida       # menos repeticiones

Escribe data/artifacts/aws_mediciones.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "data" / "artifacts"
REGION = "us-east-1"
FUNCION = "simulador-retencion"

# Precios de lista de AWS Lambda en us-east-1 (x86_64), consultados en
# aws.amazon.com/lambda/pricing. Se fijan aqui para que el costo derivado de la
# medicion sea trazable.
PRECIO_GB_SEGUNDO = 0.0000166667
PRECIO_POR_PETICION = 0.20 / 1_000_000

_REPORT = re.compile(
    r"Duration: (?P<dur>[\d.]+) ms\s+Billed Duration: (?P<fact>\d+) ms\s+"
    r"Memory Size: (?P<mem>\d+) MB\s+Max Memory Used: (?P<usada>\d+) MB"
    r"(?:\s+Init Duration: (?P<init>[\d.]+) ms)?"
)


def evento(ruta: str, cuerpo: dict | None = None) -> dict:
    ev = {"rawPath": ruta, "requestContext": {"http": {"method": "POST" if cuerpo is not None else "GET"}}}
    if cuerpo is not None:
        ev["body"] = json.dumps(cuerpo)
    return ev


def invocar(lam, ev: dict) -> dict:
    """Invoca y devuelve latencia de cliente + metricas de la linea REPORT."""
    inicio = time.perf_counter()
    r = lam.invoke(FunctionName=FUNCION, Payload=json.dumps(ev).encode(), LogType="Tail")
    cuerpo = json.loads(r["Payload"].read())
    cliente_ms = (time.perf_counter() - inicio) * 1000
    log = base64.b64decode(r.get("LogResult", "")).decode("utf-8", "replace")
    m = _REPORT.search(log)
    return {
        "ruta": ev["rawPath"],
        "status": cuerpo.get("statusCode", 599) if isinstance(cuerpo, dict) else 599,
        "error_funcion": r.get("FunctionError"),
        "cliente_ms": round(cliente_ms, 1),
        "duracion_ms": float(m["dur"]) if m else None,
        "facturado_ms": int(m["fact"]) if m else None,
        "memoria_mb": int(m["mem"]) if m else None,
        "memoria_usada_mb": int(m["usada"]) if m else None,
        "init_ms": float(m["init"]) if m and m["init"] else None,
    }


def forzar_arranque_en_frio(lam, i: int) -> None:
    """Cambiar una variable de entorno obliga a Lambda a crear entornos nuevos."""
    cfg = lam.get_function_configuration(FunctionName=FUNCION)
    variables = dict(cfg.get("Environment", {}).get("Variables", {}))
    variables["ARRANQUE"] = f"{i}-{time.time():.0f}"
    lam.update_function_configuration(FunctionName=FUNCION, Environment={"Variables": variables})
    for _ in range(60):
        cfg = lam.get_function_configuration(FunctionName=FUNCION)
        if cfg.get("LastUpdateStatus") == "Successful":
            return
        time.sleep(1)


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * p / 100
    bajo = int(k)
    alto = min(bajo + 1, len(ordenados) - 1)
    return round(ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (k - bajo), 1)


def resumir(muestras: list[dict]) -> dict:
    def campo(c: str) -> list[float]:
        return [m[c] for m in muestras if m.get(c) is not None]

    cli, dur, fact, usada, init = (campo(c) for c in
                                   ("cliente_ms", "duracion_ms", "facturado_ms", "memoria_usada_mb", "init_ms"))
    memoria_gb = (muestras[0].get("memoria_mb") or 2048) / 1024
    costo = (
        (statistics.mean(fact) / 1000) * memoria_gb * PRECIO_GB_SEGUNDO + PRECIO_POR_PETICION
        if fact else None
    )
    return {
        "n": len(muestras),
        "errores": sum(1 for m in muestras if m["status"] != 200 or m["error_funcion"]),
        "cliente_ms_p50": _percentil(cli, 50),
        "cliente_ms_p95": _percentil(cli, 95),
        "cliente_ms_max": round(max(cli), 1) if cli else None,
        "servidor_ms_p50": _percentil(dur, 50),
        "servidor_ms_p95": _percentil(dur, 95),
        "facturado_ms_medio": round(statistics.mean(fact), 1) if fact else None,
        "memoria_usada_mb_max": max(usada) if usada else None,
        "init_ms_medio": round(statistics.mean(init), 1) if init else None,
        "init_ms_max": round(max(init), 1) if init else None,
        "costo_usd_por_invocacion": costo,
    }


def firmado(sesion: boto3.Session, url: str, metodo: str, cuerpo: dict | None) -> tuple[int, float]:
    """Peticion HTTPS a la Function URL firmada con SigV4 (servicio 'lambda')."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = AWSRequest(method=metodo, url=url, data=datos,
                          headers={"Content-Type": "application/json"} if datos else {})
    SigV4Auth(sesion.get_credentials().get_frozen_credentials(), "lambda", REGION).add_auth(peticion)
    req = urllib.request.Request(url, data=datos, method=metodo, headers=dict(peticion.headers.items()))
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
            codigo = resp.status
    except urllib.error.HTTPError as exc:
        codigo = exc.code
    return codigo, round((time.perf_counter() - inicio) * 1000, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rapida", action="store_true")
    args = parser.parse_args()
    n_frio, n_caliente, n_conc = (2, 10, 4) if args.rapida else (5, 40, 10)

    sesion = boto3.Session(region_name=REGION)
    lam = sesion.client("lambda")
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    resultado: dict = {"medido": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "funcion": FUNCION, "region": REGION,
                       # Con AWS_ENDPOINT_URL definido se mide AWS emulado (LocalStack):
                       # la duracion refleja el CPU local y la memoria informada es la
                       # configurada, no la usada.
                       "entorno": "LocalStack (AWS emulado en local)" if endpoint else "AWS",
                       "endpoint": endpoint,
                       "precios": {"gb_segundo": PRECIO_GB_SEGUNDO, "peticion": PRECIO_POR_PETICION}}

    print(f"Arranques en frio forzados: {n_frio}")
    frio = []
    for i in range(n_frio):
        forzar_arranque_en_frio(lam, i)
        m = invocar(lam, evento("/v1/simular", {"presupuesto_usd": 150_000}))
        frio.append(m)
        print(f"  frio {i + 1}: cliente {m['cliente_ms']:,.0f} ms  init {m['init_ms']} ms  "
              f"facturado {m['facturado_ms']} ms  memoria {m['memoria_usada_mb']} MB")
    resultado["frio_simular"] = resumir(frio)

    print(f"\nInvocaciones en caliente: {n_caliente} x /v1/simular")
    caliente = []
    for i in range(n_caliente):
        presupuesto = [5_000, 25_000, 50_000, 100_000, 150_000, 250_000][i % 6]
        caliente.append(invocar(lam, evento("/v1/simular", {"presupuesto_usd": presupuesto,
                                                            "semilla": i})))
    resultado["caliente_simular"] = resumir(caliente)
    print(f"  {resultado['caliente_simular']}")

    for ruta, cuerpo, n in (("/v1/barrido", {"presupuestos": [5_000, 50_000, 150_000, 250_000]}, 5),
                            ("/v1/simular/pasos", {"presupuesto_usd": 150_000}, 5),
                            ("/health", None, 5)):
        muestras = [invocar(lam, evento(ruta, cuerpo)) for _ in range(n)]
        clave = "caliente_" + ruta.strip("/").replace("/", "_")
        resultado[clave] = resumir(muestras)
        print(f"  {ruta}: {resultado[clave]}")

    print(f"\nConcurrencia: {n_conc} peticiones simultaneas x 3 rondas")
    concurrentes = []
    with ThreadPoolExecutor(max_workers=n_conc) as pool:
        for ronda in range(3):
            concurrentes += list(pool.map(
                lambda k: invocar(boto3.Session(region_name=REGION).client("lambda"),
                                  evento("/v1/simular", {"presupuesto_usd": 50_000 + 1_000 * k})),
                range(n_conc)))
    resultado["concurrencia_simular"] = resumir(concurrentes)
    resultado["concurrencia_simular"]["arranques_en_frio"] = sum(1 for m in concurrentes if m["init_ms"])
    print(f"  {resultado['concurrencia_simular']}")

    despliegue = ARTIFACTS / "aws_despliegue.json"
    url = json.loads(despliegue.read_text(encoding="utf-8")).get("function_url") if despliegue.exists() else None
    if url:
        print(f"\nFunction URL firmada: {url}")
        http = [firmado(sesion, url.rstrip("/") + "/health", "GET", None) for _ in range(3)]
        http += [firmado(sesion, url.rstrip("/") + "/v1/simular", "POST", {"presupuesto_usd": 150_000})
                 for _ in range(5)]
        sin_firma = urllib.request.Request(url.rstrip("/") + "/health")
        try:
            urllib.request.urlopen(sin_firma, timeout=30)
            codigo_sin_firma = 200
        except urllib.error.HTTPError as exc:
            codigo_sin_firma = exc.code
        lat = [ms for _, ms in http]
        resultado["function_url"] = {
            "url": url,
            "peticiones": len(http),
            "codigos": sorted({c for c, _ in http}),
            "latencia_ms_p50": _percentil(lat, 50),
            "latencia_ms_max": max(lat),
            "codigo_sin_firma": codigo_sin_firma,
        }
        print(f"  {resultado['function_url']}")

    (ARTIFACTS / "aws_mediciones.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    print(f"\nMediciones en {ARTIFACTS / 'aws_mediciones.json'}")


if __name__ == "__main__":
    main()
