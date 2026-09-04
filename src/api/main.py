"""API de escenarios de retencion.

Es la pieza con la que interactua el usuario comercial: define una campana
hipotetica y recibe su impacto estimado. El guion exige respuesta en menos de
10 minutos; al resolver la poblacion de forma vectorizada la respuesta es de
segundos, lo que permite comparar alternativas en una misma reunion.

La poblacion de agentes se carga una sola vez al arrancar y se reutiliza entre
peticiones: leerla en cada llamada seria el cuello de botella.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.simulador import (  # noqa: E402
    Escenario,
    cargar_poblacion,
    desglose_por_cohorte,
    simular,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data" / "artifacts"

app = FastAPI(
    title="Simulador de Retencion VIP",
    version="1.0.0",
    description=(
        "Estima el impacto comercial de una campana de retencion antes de "
        "ejecutar el presupuesto. Nucleo multiagente vectorizado sobre la "
        "poblacion real de clientes VIP."
    ),
)

# Estado del proceso. Se llena en el arranque.
_estado: dict[str, Any] = {"poblacion": None}

_DASHBOARD_FILE = Path(__file__).resolve().parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
def raiz() -> str:
    """Dashboard interactivo con el que el equipo comercial explora el sistema."""
    try:
        return _DASHBOARD_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Dashboard no encontrado</h1><p>Falta dashboard.html junto a api/main.py</p>"


class SolicitudEscenario(BaseModel):
    nombre: str = Field(default="escenario", description="Etiqueta para identificar la corrida.")
    presupuesto_usd: float = Field(default=5000, gt=0, le=10_000_000)
    costo_promo_usd: float = Field(default=1.20, gt=0, le=100)
    promos_por_cliente: int = Field(default=2, ge=1, le=10)
    criterio: Literal["riesgo", "valor", "valor_en_riesgo"] = "valor_en_riesgo"
    pct_control: float = Field(default=0.10, ge=0.0, le=0.5)
    semilla: int = 42


class SolicitudBarrido(BaseModel):
    presupuestos: list[float] = Field(
        default=[5_000, 25_000, 50_000, 100_000, 250_000],
        min_length=1,
        max_length=12,
    )
    promos_por_cliente: int = Field(default=2, ge=1, le=10)
    criterio: Literal["riesgo", "valor", "valor_en_riesgo"] = "valor_en_riesgo"


@app.on_event("startup")
def cargar() -> None:
    try:
        _estado["poblacion"] = cargar_poblacion()
    except SystemExit as exc:
        # No se aborta el arranque: /health debe poder informar del problema en
        # lugar de dejar el contenedor en un bucle de reinicios.
        _estado["error"] = str(exc)


def _poblacion() -> pd.DataFrame:
    pob = _estado.get("poblacion")
    if pob is None:
        raise HTTPException(
            status_code=503,
            detail=_estado.get("error", "La poblacion de agentes no esta cargada."),
        )
    return pob


@app.get("/health")
def health() -> dict[str, Any]:
    pob = _estado.get("poblacion")
    return {
        "status": "ok" if pob is not None else "degradado",
        "agentes_cargados": int(len(pob)) if pob is not None else 0,
        "error": _estado.get("error"),
    }


@app.get("/v1/segmentacion")
def segmentacion() -> dict[str, Any]:
    """Devuelve el resumen RFM: la foto del negocio sobre la que se simula."""
    archivos = sorted(ARTIFACTS.glob("rfm_resumen_*.json"))
    if not archivos:
        raise HTTPException(status_code=404, detail="Aun no se ha calculado la segmentacion RFM.")
    return json.loads(archivos[-1].read_text(encoding="utf-8"))


@app.get("/v1/modelo")
def modelo() -> dict[str, Any]:
    """Metricas de validacion temporal del modelo de abandono."""
    ruta = ARTIFACTS / "churn_metricas.json"
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Aun no se ha entrenado el modelo de abandono.")
    return json.loads(ruta.read_text(encoding="utf-8"))


def _deciles(df: pd.DataFrame, col: str, invertido: bool = False) -> list[dict]:
    """Divide la poblacion en 10 deciles segun una columna numerica."""
    if df.empty:
        return []
    orden = df[col].to_numpy(dtype=float)
    # pd.qcut requiere valores unicos por decil; ante empates se usan cortes
    # por rango lineal para que siempre haya 10 cohortes.
    try:
        bins = pd.qcut(orden, 10, labels=False, duplicates="drop")
    except (ValueError, TypeError):
        bins = np.clip((np.argsort(np.argsort(orden)) * 10) // len(orden), 0, 9)
    res = []
    for d in range(10):
        sel = df[bins == d]
        if sel.empty:
            continue
        vals = sel[col].to_numpy(dtype=float)
        res.append(
            {
                "decil": d + 1,
                "agentes": int(len(sel)),
                "min": round(float(vals.min()), 4) if not invertido else round(float(vals.max()), 4),
                "max": round(float(vals.max()), 4) if not invertido else round(float(vals.min()), 4),
                "promedio": round(float(vals.mean()), 4),
            }
        )
    return res


@app.get("/v1/poblacion")
def poblacion_en_vivo() -> dict[str, Any]:
    """Muestra la poblacion de agentes en vivo: deciles de riesgo y de valor."""
    pob = _poblacion()
    riesgo = _deciles(pob, "prob_abandono")
    valor = _deciles(pob, "monetario", invertido=True)
    return {
        "agentes_totales": int(len(pob)),
        "deciles_riesgo": riesgo,
        "deciles_valor": valor,
    }


@app.post("/v1/simular")
def simular_escenario(payload: SolicitudEscenario) -> dict[str, Any]:
    """Simula una campana y devuelve su impacto frente al contrafactual."""
    resultado = simular(Escenario(**payload.model_dump()), _poblacion())
    return asdict(resultado)


@app.post("/v1/simular/pasos")
def simular_con_trazos(payload: SolicitudEscenario) -> dict[str, Any]:
    """Igual que /v1/simular pero ademas descompone la reaccion por decil de riesgo.

    Es lo que permite al dashboard mostrar a los agentes "trabajando": como
    responde cada cohorte (salvados, saturados, fuga) bajo el escenario.
    """
    esc = Escenario(**payload.model_dump())
    return desglose_por_cohorte(esc, _poblacion())


@app.post("/v1/barrido")
def barrido(payload: SolicitudBarrido) -> dict[str, Any]:
    """Compara varios presupuestos de una vez.

    Es la consulta que de verdad necesita el negocio: no "cuanto rinde esta
    campana" sino "cuanto tengo que gastar para mover la aguja".
    """
    pob = _poblacion()
    filas = []
    for presupuesto in sorted(payload.presupuestos):
        r = simular(
            Escenario(
                nombre=f"barrido_{int(presupuesto)}",
                presupuesto_usd=presupuesto,
                promos_por_cliente=payload.promos_por_cliente,
                criterio=payload.criterio,
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
                "ingreso_incremental_usd": r.ingreso_incremental_usd,
                "clientes_saturados": r.clientes_saturados,
            }
        )

    objetivo = next((f for f in filas if f["reduccion_fuga_pct"] >= 15.0), None)
    return {
        "resultados": filas,
        "presupuesto_minimo_para_objetivo_15pct": objetivo["presupuesto_usd"] if objetivo else None,
    }


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
