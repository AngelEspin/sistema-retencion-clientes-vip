"""Pruebas funcionales del handler: rutas, casos borde y paridad con el simulador.

Es la evidencia del nivel *funcional* de la matriz de validacion: que el sistema
responde bien, rechaza lo que debe rechazar y que la version en la nube calcula
exactamente lo mismo que la local.

Uso:
    python infra/pruebas_funcionales.py            # handler en proceso, sin AWS
    python infra/pruebas_funcionales.py --remoto   # contra la Lambda desplegada

Escribe data/artifacts/pruebas_funcionales_{local|remoto}.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "data" / "artifacts"
sys.path.insert(0, str(ROOT / "src" / "simulation"))
sys.path.insert(0, str(ROOT / "infra"))

FUNCION = os.environ.get("FUNCION", "simulador-retencion")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def evento(ruta: str, metodo: str = "GET", cuerpo: Any = None, crudo: str | None = None) -> dict:
    """Evento con el formato de Lambda Function URL (payload v2)."""
    ev: dict[str, Any] = {"rawPath": ruta, "requestContext": {"http": {"method": metodo}}}
    if crudo is not None:
        ev["body"] = crudo
    elif cuerpo is not None:
        ev["body"] = json.dumps(cuerpo)
    return ev


class _S3Local:
    """Sustituto de S3 que sirve los artefactos desde data/artifacts."""

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803 (firma de boto3)
        import io

        return {"Body": io.BytesIO((ARTIFACTS / Path(Key).name).read_bytes())}

    def download_file(self, bucket: str, key: str, destino: str) -> None:
        raise AssertionError("No deberia descargar: RUTA_LOCAL apunta al artefacto local")


def invocador_local() -> Callable[[dict], dict]:
    os.environ.setdefault("BUCKET", "local")
    os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
    import lambda_handler as h

    h._s3 = _S3Local()
    h.RUTA_LOCAL = str(ARTIFACTS / "scores_vip.parquet")
    return lambda ev: h.lambda_handler(ev, None)


def invocador_remoto() -> Callable[[dict], dict]:
    import boto3

    cliente = boto3.client("lambda", region_name=REGION)

    def invocar(ev: dict) -> dict:
        r = cliente.invoke(FunctionName=FUNCION, Payload=json.dumps(ev).encode())
        if r.get("FunctionError"):
            return {"statusCode": 599, "body": r["Payload"].read().decode()}
        return json.loads(r["Payload"].read())

    return invocar


def _cuerpo(resp: dict) -> Any:
    return json.loads(resp["body"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remoto", action="store_true", help="Probar la Lambda desplegada")
    args = parser.parse_args()

    from simulador import Escenario, cargar_poblacion, simular

    invocar = invocador_remoto() if args.remoto else invocador_local()
    pob = cargar_poblacion()

    casos: list[tuple[str, str, dict, Callable[[dict], bool]]] = []

    def caso(grupo: str, nombre: str, ev: dict, verificar: Callable[[dict], bool]) -> None:
        casos.append((grupo, nombre, ev, verificar))

    # --- Rutas basicas ------------------------------------------------------
    caso("rutas", "health responde con la poblacion completa", evento("/health"),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["agentes_cargados"] == len(pob))
    caso("rutas", "segmentacion devuelve el resumen RFM", evento("/v1/segmentacion"),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["clientes"] > 0)
    caso("rutas", "modelo devuelve las metricas de validacion", evento("/v1/modelo"),
         lambda r: r["statusCode"] == 200 and "auc" in _cuerpo(r))
    caso("rutas", "poblacion devuelve 10 deciles de riesgo", evento("/v1/poblacion"),
         lambda r: r["statusCode"] == 200 and len(_cuerpo(r)["deciles_riesgo"]) == 10)
    caso("rutas", "ruta inexistente -> 404 con el listado de rutas", evento("/v1/nada"),
         lambda r: r["statusCode"] == 404 and "rutas" in _cuerpo(r))
    caso("rutas", "GET sobre una ruta POST -> 404", evento("/v1/simular", "GET"),
         lambda r: r["statusCode"] == 404)

    # --- Paridad exacta con el simulador local ------------------------------
    for params in (
        {"presupuesto_usd": 150_000, "promos_por_cliente": 2},
        {"presupuesto_usd": 25_000, "promos_por_cliente": 2, "criterio": "aleatorio"},
        {"presupuesto_usd": 5_000, "promos_por_cliente": 3},
        {"presupuesto_usd": 80_000, "promos_por_cliente": 1, "efecto_promo": 0.2,
         "umbral_saturacion": 4, "semilla": 7},
    ):
        esperado = asdict(simular(Escenario(**params), pob))
        caso("paridad", f"simular == local {params}", evento("/v1/simular", "POST", params),
             lambda r, e=esperado: r["statusCode"] == 200 and _cuerpo(r) == json.loads(json.dumps(e)))

    total_150k = simular(Escenario(presupuesto_usd=150_000), pob)
    caso("paridad", "pasos: los salvados por cohorte suman el total del escenario",
         evento("/v1/simular/pasos", "POST", {"presupuesto_usd": 150_000}),
         lambda r: r["statusCode"] == 200
         and sum(c["salvados"] for c in _cuerpo(r)["cohortes"]) == total_150k.detalle["clientes_salvados"])
    caso("paridad", "barrido: la reduccion de fuga crece con el presupuesto",
         evento("/v1/barrido", "POST", {"presupuestos": [250_000, 5_000, 50_000, 150_000]}),
         lambda r: r["statusCode"] == 200
         and [f["presupuesto_usd"] for f in _cuerpo(r)["resultados"]] == [5_000, 50_000, 150_000, 250_000]
         and all(a["reduccion_fuga_pct"] <= b["reduccion_fuga_pct"]
                 for a, b in zip(_cuerpo(r)["resultados"], _cuerpo(r)["resultados"][1:])))

    # --- Entradas invalidas: deben dar 422, nunca 500 -----------------------
    invalidos = {
        "presupuesto negativo": {"presupuesto_usd": -10},
        "presupuesto cero": {"presupuesto_usd": 0},
        "presupuesto sobre el tope": {"presupuesto_usd": 20_000_000},
        "presupuesto como texto": {"presupuesto_usd": "mucho"},
        "presupuesto booleano": {"presupuesto_usd": True},
        "criterio desconocido": {"criterio": "corazonada"},
        "cero promociones": {"promos_por_cliente": 0},
        "promociones decimales": {"promos_por_cliente": 2.5},
        "control sobre 50%": {"pct_control": 0.9},
        "efecto mayor a 0.95": {"efecto_promo": 1.5},
    }
    for nombre, cuerpo in invalidos.items():
        caso("validacion", f"{nombre} -> 422", evento("/v1/simular", "POST", cuerpo),
             lambda r: r["statusCode"] == 422)
    caso("validacion", "cuerpo que no es JSON -> 422", evento("/v1/simular", "POST", crudo="{presupuesto"),
         lambda r: r["statusCode"] == 422)
    caso("validacion", "cuerpo que es una lista -> 422", evento("/v1/simular", "POST", [1, 2]),
         lambda r: r["statusCode"] == 422)
    caso("validacion", "barrido con 13 presupuestos -> 422",
         evento("/v1/barrido", "POST", {"presupuestos": [1000] * 13}),
         lambda r: r["statusCode"] == 422)
    caso("validacion", "barrido con un monto no numerico -> 422",
         evento("/v1/barrido", "POST", {"presupuestos": [1000, "x"]}),
         lambda r: r["statusCode"] == 422)
    caso("validacion", "cuerpo en base64 se decodifica",
         {**evento("/v1/simular", "POST"), "isBase64Encoded": True,
          "body": base64.b64encode(json.dumps({"presupuesto_usd": 5000}).encode()).decode()},
         lambda r: r["statusCode"] == 200)

    # --- Casos borde de negocio ---------------------------------------------
    caso("borde", "presupuesto menor que una asignacion no gasta nada",
         evento("/v1/simular", "POST", {"presupuesto_usd": 1, "costo_promo_usd": 1.2, "promos_por_cliente": 2}),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["costo_total_usd"] == 0
         and _cuerpo(r)["promos_enviadas"] == 0)
    caso("borde", "el costo nunca supera el presupuesto",
         evento("/v1/simular", "POST", {"presupuesto_usd": 1234.56, "costo_promo_usd": 1.7, "promos_por_cliente": 2}),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["costo_total_usd"] <= 1234.56)
    caso("borde", "3 promociones por cliente: saturacion, efecto cero",
         evento("/v1/simular", "POST", {"presupuesto_usd": 5000, "promos_por_cliente": 3}),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["reduccion_fuga_pct"] == 0
         and _cuerpo(r)["clientes_saturados"] > 0)
    caso("borde", "presupuesto maximo: alcanza a toda la poblacion elegible sin desbordar",
         evento("/v1/simular", "POST", {"presupuesto_usd": 10_000_000}),
         lambda r: r["statusCode"] == 200
         and _cuerpo(r)["clientes_alcanzados"] == _cuerpo(r)["detalle"]["clientes_tratamiento"])
    caso("borde", "sin grupo de control: responde y no divide por cero",
         evento("/v1/simular", "POST", {"presupuesto_usd": 5000, "pct_control": 0}),
         lambda r: r["statusCode"] == 200 and _cuerpo(r)["detalle"]["clientes_control"] == 0)
    caso("borde", "misma semilla, mismo resultado (reproducible)",
         evento("/v1/simular", "POST", {"presupuesto_usd": 50_000, "semilla": 123}),
         lambda r, e=json.loads(json.dumps(asdict(simular(Escenario(presupuesto_usd=50_000, semilla=123), pob)))):
         r["statusCode"] == 200 and _cuerpo(r) == e)

    resultados = []
    for grupo, nombre, ev, verificar in casos:
        inicio = time.perf_counter()
        try:
            resp = invocar(ev)
            ok = bool(verificar(resp))
            detalle = resp.get("statusCode")
        except Exception as exc:  # noqa: BLE001
            ok, detalle = False, f"{type(exc).__name__}: {exc}"
        ms = (time.perf_counter() - inicio) * 1000
        resultados.append({"grupo": grupo, "caso": nombre, "ok": ok, "status": detalle, "ms": round(ms, 1)})
        print(f"  [{'OK ' if ok else 'FALLA'}] {grupo:10} {nombre}  ({ms:,.0f} ms)")

    aprobados = sum(r["ok"] for r in resultados)
    modo = "remoto" if args.remoto else "local"
    resumen = {
        "modo": modo,
        "funcion": FUNCION if args.remoto else "lambda_handler en proceso",
        # Con AWS_ENDPOINT_URL definido, el "remoto" es AWS emulado (LocalStack).
        "endpoint": os.environ.get("AWS_ENDPOINT_URL") if args.remoto else None,
        "casos": len(resultados),
        "aprobados": aprobados,
        "tasa_aprobacion_pct": round(100 * aprobados / len(resultados), 1),
        "errores_500": sum(1 for r in resultados if r["status"] == 500),
        "resultados": resultados,
    }
    (ARTIFACTS / f"pruebas_funcionales_{modo}.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n{aprobados}/{len(resultados)} casos aprobados ({modo})")
    if aprobados != len(resultados):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
