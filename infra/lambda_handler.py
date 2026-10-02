"""Handler de AWS Lambda para el simulador de escenarios.

Version serverless de la API. Se eligio Lambda en lugar de un contenedor
permanente porque el uso real es esporadico: el equipo comercial evalua
escenarios unas pocas veces al mes, y pagar por un servicio encendido las 24
horas contradice el limite de USD 80/mes del proyecto.

La poblacion de agentes se descarga de S3 en el arranque en frio y queda en
memoria del contenedor. Las invocaciones siguientes la reutilizan, que es lo
que mantiene la respuesta en el orden de milisegundos.

Expone las mismas rutas que la API local (src/api/main.py) salvo el dashboard,
y aplica las mismas cotas de validacion: la capa gestionada de pandas no trae
Pydantic, asi que se validan a mano.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

import boto3
import pandas as pd

from simulador import (
    CRITERIOS,
    Escenario,
    deciles,
    desglose_por_cohorte,
    fila_barrido,
    simular,
)

BUCKET = os.environ["BUCKET"]
CLAVE_SCORES = os.environ.get("CLAVE_SCORES", "artifacts/scores_vip.parquet")
CLAVE_RFM = os.environ.get("CLAVE_RFM", "artifacts/rfm_resumen_2026-07-01.json")
CLAVE_MODELO = os.environ.get("CLAVE_MODELO", "artifacts/churn_metricas.json")
RUTA_LOCAL = "/tmp/scores_vip.parquet"

# Cache a nivel de contenedor: sobrevive entre invocaciones del mismo worker.
_poblacion: pd.DataFrame | None = None
_s3 = boto3.client("s3")

# (tipo, minimo, maximo) -- las mismas cotas que SolicitudEscenario en la API.
_COTAS: dict[str, tuple[type, float, float]] = {
    "presupuesto_usd": (float, 0.0, 10_000_000),
    "costo_promo_usd": (float, 0.0, 100),
    "promos_por_cliente": (int, 1, 10),
    "pct_control": (float, 0.0, 0.5),
    "semilla": (int, -(2**31), 2**31 - 1),
    "efecto_promo": (float, 0.0, 0.95),
    "umbral_saturacion": (int, 1, 11),
}
# Cotas estrictas por abajo: un presupuesto o costo de cero no es una campana.
_ESTRICTOS = {"presupuesto_usd", "costo_promo_usd"}


class EntradaInvalida(ValueError):
    """Error del cliente: se responde 422 en lugar de 500."""


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


def _cuerpo(event: dict) -> dict:
    crudo = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        crudo = base64.b64decode(crudo).decode("utf-8")
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError as exc:
        raise EntradaInvalida(f"El cuerpo no es JSON valido: {exc}") from exc
    if not isinstance(datos, dict):
        raise EntradaInvalida("El cuerpo debe ser un objeto JSON.")
    return datos


def _escenario(payload: dict) -> Escenario:
    """Construye un Escenario validando tipos y rangos campo por campo."""
    params: dict[str, Any] = {}
    if "nombre" in payload:
        params["nombre"] = str(payload["nombre"])[:80]
    if "criterio" in payload:
        if payload["criterio"] not in CRITERIOS:
            raise EntradaInvalida(f"criterio debe ser uno de {list(CRITERIOS)}")
        params["criterio"] = payload["criterio"]
    for campo, (tipo, minimo, maximo) in _COTAS.items():
        if campo not in payload:
            continue
        valor = payload[campo]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise EntradaInvalida(f"{campo} debe ser numerico")
        if tipo is int and float(valor) != int(valor):
            raise EntradaInvalida(f"{campo} debe ser entero")
        fuera = valor <= minimo if campo in _ESTRICTOS else valor < minimo
        if fuera or valor > maximo:
            raise EntradaInvalida(f"{campo} fuera de rango ({minimo}, {maximo})")
        params[campo] = tipo(valor)
    return Escenario(**params)


def lambda_handler(event: dict, context: Any) -> dict:
    # Function URL entrega la ruta en rawPath; se acepta tambien el formato de
    # API Gateway v1 por si se pone un gateway delante mas adelante.
    ruta = (event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"
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
            return _respuesta(200, _leer_artefacto(CLAVE_RFM))

        if ruta.endswith("/v1/modelo"):
            return _respuesta(200, _leer_artefacto(CLAVE_MODELO))

        if ruta.endswith("/v1/poblacion"):
            pob = _cargar_poblacion()
            return _respuesta(
                200,
                {
                    "agentes_totales": int(len(pob)),
                    "deciles_riesgo": deciles(pob, "prob_abandono"),
                    "deciles_valor": deciles(pob, "monetario", invertido=True),
                },
            )

        if ruta.endswith("/v1/simular/pasos") and metodo == "POST":
            esc = _escenario(_cuerpo(event))
            return _respuesta(200, desglose_por_cohorte(esc, _cargar_poblacion()))

        if ruta.endswith("/v1/simular") and metodo == "POST":
            resultado = simular(_escenario(_cuerpo(event)), _cargar_poblacion())
            return _respuesta(200, asdict(resultado))

        if ruta.endswith("/v1/barrido") and metodo == "POST":
            payload = _cuerpo(event)
            presupuestos = payload.get("presupuestos") or [5_000, 50_000, 150_000, 250_000]
            if not isinstance(presupuestos, list) or not 1 <= len(presupuestos) <= 12:
                raise EntradaInvalida("presupuestos debe ser una lista de 1 a 12 montos")
            base = _escenario(
                {k: v for k, v in payload.items() if k in ("promos_por_cliente", "criterio")}
            )
            # Se valida cada monto antes de ordenar: una lista con tipos mezclados
            # haria fallar sorted() con un 500 en lugar de un 422.
            escenarios = [
                _escenario(
                    {
                        "nombre": f"barrido_{presupuesto}",
                        "presupuesto_usd": presupuesto,
                        "promos_por_cliente": base.promos_por_cliente,
                        "criterio": base.criterio,
                    }
                )
                for presupuesto in presupuestos
            ]
            pob = _cargar_poblacion()

            filas = []
            for esc in sorted(escenarios, key=lambda e: e.presupuesto_usd):
                filas.append(fila_barrido(simular(esc, pob), esc.presupuesto_usd))

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
                "rutas": ["/health", "/v1/segmentacion", "/v1/modelo", "/v1/poblacion",
                          "/v1/simular (POST)", "/v1/simular/pasos (POST)", "/v1/barrido (POST)"],
            },
        )

    except EntradaInvalida as exc:
        return _respuesta(422, {"error": "entrada_invalida", "detalle": str(exc)})
    except Exception as exc:  # noqa: BLE001
        # Se devuelve el error como JSON en vez de dejar que Lambda emita su
        # traza cruda, que no es util para quien consume la API.
        return _respuesta(500, {"error": type(exc).__name__, "detalle": str(exc)})
