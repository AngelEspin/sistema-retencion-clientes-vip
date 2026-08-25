"""Handler de AWS Lambda para el simulador de escenarios.

Version serverless de la API. Se eligio Lambda en lugar de un contenedor
permanente porque el uso real es esporadico: el equipo comercial evalua
escenarios unas pocas veces al mes, y pagar por un servicio encendido las 24
horas contradice el limite de USD 80/mes del proyecto.

La poblacion de agentes se descarga de S3 en el arranque en frio y queda en
memoria del contenedor. Las invocaciones siguientes la reutilizan, que es lo
que mantiene la respuesta en el orden de milisegundos.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
import pandas as pd

from simulador import Escenario, simular

BUCKET = os.environ["BUCKET"]
CLAVE_SCORES = os.environ.get("CLAVE_SCORES", "artifacts/scores_vip.parquet")
RUTA_LOCAL = "/tmp/scores_vip.parquet"

# Cache a nivel de contenedor: sobrevive entre invocaciones del mismo worker.
_poblacion: pd.DataFrame | None = None
_s3 = boto3.client("s3")


def _cargar_poblacion() -> pd.DataFrame:
    global _poblacion
    if _poblacion is None:
        if not os.path.exists(RUTA_LOCAL):
            _s3.download_file(BUCKET, CLAVE_SCORES, RUTA_LOCAL)
        _poblacion = pd.read_parquet(RUTA_LOCAL)
    return _poblacion


def _leer_artefacto(clave: str) -> dict:
    obj = _s3.get_object(Bucket=BUCKET, Key=clave)
    return json.loads(obj["Body"].read().decode("utf-8"))


def _respuesta(codigo: int, cuerpo: Any) -> dict:
    return {
        "statusCode": codigo,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(cuerpo, ensure_ascii=False, default=str),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    # Function URL entrega la ruta en rawPath; se acepta tambien el formato de
    # API Gateway v1 por si se pone un gateway delante mas adelante.
    ruta = event.get("rawPath") or event.get("path") or "/"
    metodo = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "GET"
    )

    try:
        if ruta.endswith("/health"):
            pob = _cargar_poblacion()
            return _respuesta(200, {"status": "ok", "agentes_cargados": int(len(pob))})

        if ruta.endswith("/v1/segmentacion"):
            return _respuesta(200, _leer_artefacto("artifacts/rfm_resumen_2026-07-01.json"))

        if ruta.endswith("/v1/modelo"):
            return _respuesta(200, _leer_artefacto("artifacts/churn_metricas.json"))

        if ruta.endswith("/v1/simular") and metodo == "POST":
            payload = json.loads(event.get("body") or "{}")
            permitidos = {
                "nombre", "presupuesto_usd", "costo_promo_usd",
                "promos_por_cliente", "criterio", "pct_control", "semilla",
            }
            filtrado = {k: v for k, v in payload.items() if k in permitidos}
            resultado = simular(Escenario(**filtrado), _cargar_poblacion())
            return _respuesta(200, resultado.__dict__)

        if ruta.endswith("/v1/barrido") and metodo == "POST":
            payload = json.loads(event.get("body") or "{}")
            presupuestos = payload.get("presupuestos") or [5_000, 50_000, 150_000, 250_000]
            promos = int(payload.get("promos_por_cliente", 2))
            pob = _cargar_poblacion()

            filas = []
            for presupuesto in sorted(float(p) for p in presupuestos):
                r = simular(
                    Escenario(
                        nombre=f"barrido_{int(presupuesto)}",
                        presupuesto_usd=presupuesto,
                        promos_por_cliente=promos,
                    ),
                    pob,
                )
                filas.append(
                    {
                        "presupuesto_usd": presupuesto,
                        "clientes_alcanzados": r.clientes_alcanzados,
                        "cobertura_pct": round(100 * r.clientes_alcanzados / r.agentes, 2),
                        "reduccion_fuga_pct": r.reduccion_fuga_pct,
                        "roi": r.roi,
                        "clientes_saturados": r.clientes_saturados,
                    }
                )

            objetivo = next((f for f in filas if f["reduccion_fuga_pct"] >= 15.0), None)
            return _respuesta(
                200,
                {
                    "resultados": filas,
                    "presupuesto_minimo_para_objetivo_15pct": (
                        objetivo["presupuesto_usd"] if objetivo else None
                    ),
                },
            )

        return _respuesta(
            404,
            {
                "error": "ruta no encontrada",
                "rutas": ["/health", "/v1/segmentacion", "/v1/modelo",
                          "/v1/simular (POST)", "/v1/barrido (POST)"],
            },
        )

    except Exception as exc:  # noqa: BLE001
        # Se devuelve el error como JSON en vez de dejar que Lambda emita su
        # traza cruda, que no es util para quien consume la API.
        return _respuesta(500, {"error": type(exc).__name__, "detalle": str(exc)})
