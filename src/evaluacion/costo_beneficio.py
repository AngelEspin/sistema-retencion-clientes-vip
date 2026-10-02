"""Analisis costo/beneficio del sistema a 3 anios.

Responde las dos preguntas del entregable con cifras reproducibles:

  A. Vale la pena el SISTEMA? Se compara decidir las campanas con el simulador
     frente a la decision actual del equipo comercial, con el MISMO presupuesto,
     la misma poblacion y el mismo azar. La tesis fijo esa linea base: "nos
     comparamos contra la realidad y no contra cero".
  B. Es rentable la CAMPANA misma? Su margen incremental frente a no hacer nada,
     el presupuesto que maximiza el beneficio neto y el efecto minimo que la
     vuelve rentable.

Los beneficios no se suponen: salen del simulador corriendo sobre la poblacion
real de VIP. Los costos de nube salen de las mediciones en AWS cuando existen
(infra/prueba_carga.py) y, si no, de precios de lista con el tiempo medido del
pipeline; el informe declara cual de los dos se uso.

Uso:
    python src/evaluacion/costo_beneficio.py              # 10 semillas
    python src/evaluacion/costo_beneficio.py --semillas 20

Escribe data/artifacts/costo_beneficio.json y las figuras del entregable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data" / "artifacts"
FIGURAS = ROOT / "Presentaciones" / "entregables" / "figuras_costo_beneficio"
sys.path.insert(0, str(ROOT / "src"))

from simulation.simulador import Escenario, cargar_poblacion, simular  # noqa: E402

HORIZONTE_MESES = 36
TRIMESTRES = HORIZONTE_MESES // 3

# --- Precios de lista us-east-1 (consultados el 2026-10-02) -----------------
PRECIO_LAMBDA_GB_S = 0.0000166667      # aws.amazon.com/lambda/pricing (x86)
PRECIO_LAMBDA_PETICION = 0.20 / 1e6
PRECIO_S3_GB_MES = 0.023               # S3 Standard, primeros 50 TB
PRECIO_EC2_R6I_XLARGE_H = 0.252        # On-Demand Linux, 4 vCPU / 32 GiB
PRECIO_LOGS_GB = 0.50                  # CloudWatch Logs, ingesta estandar
PRECIO_ALARMA_MES = 0.10               # CloudWatch, alarma estandar
ALARMAS = 3                            # deriva de datos, de concepto y salud
# Duracion en Lambda real frente a la medida en LocalStack (que no limita la CPU).
FACTOR_CPU_LAMBDA = 2.0

# --- Costo laboral cargado en Ecuador ---------------------------------------
# Sueldo: mediana Glassdoor 2026 para data scientist en Ecuador (~USD 2.000 base,
# p25-p75 1.457-2.654); se toma 1.800 para un perfil con 2-3 anios.
SUELDO_EQUIPO = 1_800.0
SBU_2026 = 482.0                       # Acuerdo MDT-2025-195
# Aporte patronal IESS 11,15% + IECE 0,5% + SECAP 0,5% + decimo tercero 8,33%
# + fondos de reserva 8,33%. El decimo cuarto es un SBU al anio.
CARGA_PATRONAL = 0.1215 + 0.0833 + 0.0833
HORAS_PRODUCTIVAS_MES = 160            # 173 h nominales menos vacaciones y feriados
TARIFA_INTERNA = round((SUELDO_EQUIPO * (1 + CARGA_PATRONAL) + SBU_2026 / 12) / HORAS_PRODUCTIVAS_MES, 2)
TARIFA_CONSULTORA = 30.0               # contratar fuera: ~2x el costo interno
TARIFA_ANALISTA_COMERCIAL = 10.0       # sueldo ~USD 1.200 con la misma carga
TARIFA_LEGAL = 25.0                    # delegado de proteccion de datos / abogado

# Esfuerzo de desarrollo, por actividad (horas de las dos personas del equipo).
HORAS_DESARROLLO = {
    "Levantamiento, diseño de arquitectura y privacidad": 80,
    "Ingeniería de datos: ingesta de 22 GB, RFM y calidad": 100,
    "Modelo de abandono con validación temporal": 60,
    "Simulador multiagente y contrafactual": 100,
    "API, dashboard y pruebas funcionales": 60,
    "Despliegue en AWS y pruebas de carga": 60,
    "Validación, documentación y gestión": 80,
}


@dataclass(frozen=True)
class Supuestos:
    """Todo lo que cambia entre escenarios. Cada campo es un supuesto declarado."""

    nombre: str
    # Reduccion relativa maxima del riesgo con una promocion (parametro del
    # simulador). Anclado a la evidencia de campo, no al guion: ver informe.
    efecto_promo: float
    # Decision de referencia del equipo comercial sin el sistema.
    linea_base: str
    promos_linea_base: int
    costo_promo_usd: float
    adopcion: float                # fraccion de campanas decididas con el sistema
    trimestre_inicio: int          # primer trimestre con beneficio (Q1 = piloto en sombra)
    persistencia: float            # trimestres de margen que aporta un cliente salvado
    tarifa_hora: float             # costo de una hora del equipo de datos
    factor_horas: float            # sobrecosto de esfuerzo
    tasa_descuento: float          # anual
    invocaciones_mes: int
    horas_operacion_mes: float


ESCENARIOS = {
    "pesimista": Supuestos(
        nombre="pesimista", efecto_promo=0.04, linea_base="recencia", promos_linea_base=2,
        costo_promo_usd=1.60, adopcion=0.60, trimestre_inicio=3, persistencia=1.0,
        tarifa_hora=TARIFA_CONSULTORA, factor_horas=1.30, tasa_descuento=0.16,
        invocaciones_mes=3_000, horas_operacion_mes=20,
    ),
    "realista": Supuestos(
        nombre="realista", efecto_promo=0.10, linea_base="aleatorio", promos_linea_base=2,
        costo_promo_usd=1.20, adopcion=0.80, trimestre_inicio=2, persistencia=1.0,
        tarifa_hora=TARIFA_INTERNA, factor_horas=1.00, tasa_descuento=0.12,
        invocaciones_mes=300, horas_operacion_mes=12,
    ),
    "optimista": Supuestos(
        nombre="optimista", efecto_promo=0.35, linea_base="valor", promos_linea_base=3,
        costo_promo_usd=0.80, adopcion=1.00, trimestre_inicio=2, persistencia=1.5,
        tarifa_hora=TARIFA_INTERNA, factor_horas=0.90, tasa_descuento=0.09,
        invocaciones_mes=100, horas_operacion_mes=8,
    ),
}

ETIQUETA_LINEA_BASE = {
    ("aleatorio", 2): "campaña masiva sin focalizar (2 promociones)",
    ("recencia", 2): "regla RFM: primero los de mayor recencia (2 promociones)",
    ("valor", 3): "los de mayor gasto, con insistencia de 3 promociones",
    ("valor", 2): "los de mayor gasto (2 promociones)",
}


# --- Simulacion (con cache: muchas configuraciones se repiten) ---------------
_POBLACION = None


def poblacion():
    global _POBLACION
    if _POBLACION is None:
        _POBLACION = cargar_poblacion()
    return _POBLACION


@lru_cache(maxsize=None)
def _corrida(presupuesto: float, criterio: str, promos: int, efecto: float,
             costo_promo: float, semilla: int, pct_control: float = 0.10) -> dict:
    r = simular(
        Escenario(nombre="cb", presupuesto_usd=presupuesto, costo_promo_usd=costo_promo,
                  promos_por_cliente=promos, criterio=criterio, pct_control=pct_control,
                  semilla=semilla, efecto_promo=efecto),
        poblacion(),
    )
    return {k: v for k, v in asdict(r).items() if k != "detalle"} | {"detalle": r.detalle}


def promedio(presupuesto: float, criterio: str, promos: int, efecto: float,
             costo_promo: float, semillas: tuple[int, ...], pct_control: float = 0.10) -> dict:
    """Media y desvio sobre semillas: el azar del control, del sorteo y de la masiva."""
    corridas = [_corrida(presupuesto, criterio, promos, efecto, costo_promo, s, pct_control)
                for s in semillas]
    out = {}
    for campo in ("margen_incremental_usd", "ingreso_incremental_usd", "reduccion_fuga_pct",
                  "costo_total_usd", "clientes_alcanzados", "clientes_saturados"):
        vals = np.array([c[campo] for c in corridas], dtype=float)
        out[campo] = float(vals.mean())
        out[campo + "_sd"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    return out


# --- Costos ------------------------------------------------------------------
def costos_aws(s: Supuestos) -> dict:
    """Costo mensual de nube, medido si hay mediciones y estimado si no."""
    med_path, desp_path = ARTIFACTS / "aws_mediciones.json", ARTIFACTS / "aws_despliegue.json"
    tiempos = json.loads((ARTIFACTS / "tiempos_pipeline.json").read_text(encoding="utf-8"))
    medido = med_path.exists() and desp_path.exists()
    if medido:
        med = json.loads(med_path.read_text(encoding="utf-8"))
        desp = json.loads(desp_path.read_text(encoding="utf-8"))
        gb_s3 = desp["almacenamiento_s3_gb"]
        if med.get("entorno", "AWS").startswith("LocalStack"):
            # LocalStack no limita la CPU: una Lambda de 2.048 MB recibe ~1,2 vCPU,
            # menos que el contenedor local. Se duplica la duracion medida.
            facturado_s = med["caliente_simular"]["facturado_ms_medio"] * FACTOR_CPU_LAMBDA / 1000
            por_invocacion = facturado_s * 2.0 * PRECIO_LAMBDA_GB_S + PRECIO_LAMBDA_PETICION
            fuente = f"duración medida en LocalStack × {FACTOR_CPU_LAMBDA:g} (CPU de Lambda) × precio de lista"
        else:
            por_invocacion = med["caliente_simular"]["costo_usd_por_invocacion"]
            fuente = "medido en AWS (prueba_carga.py)"
    else:
        # 2048 MB x ~0,6 s facturados por /v1/simular (tiempo medido en local).
        por_invocacion = 0.6 * 2.0 * PRECIO_LAMBDA_GB_S + PRECIO_LAMBDA_PETICION
        gb_s3 = 0.135
        fuente = "estimado con precios de lista (sin credenciales AWS vigentes)"
    # Lago de datos: el Parquet de ventas crece ~1,3 GB por anio; media a 3 anios.
    gb_lago = 1.3 * 2
    # Recalculo mensual (RFM + modelo) en una r6i.xlarge bajo demanda. El tiempo
    # local (14 hilos) se escala x2,5 por tener 4 vCPU, mas 10 min de arranque.
    seg_batch = sum(tiempos["etapas"][e]["segundos"] for e in ("rfm", "churn", "simulacion"))
    horas_batch = (seg_batch * 2.5 + 600) / 3600
    lineas = {
        "Lambda (consultas al simulador)": s.invocaciones_mes * por_invocacion,
        "S3 (artefactos y lago de datos Parquet)": (gb_s3 + gb_lago) * PRECIO_S3_GB_MES,
        "EC2 r6i.xlarge para el recálculo mensual": horas_batch * PRECIO_EC2_R6I_XLARGE_H,
        "CloudWatch (registros y 3 alarmas)": ALARMAS * PRECIO_ALARMA_MES
        + s.invocaciones_mes * 2e-6 * PRECIO_LOGS_GB,
    }
    return {
        "lineas": lineas,
        "total_mes": sum(lineas.values()),
        "fuente": fuente,
        "costo_por_invocacion": por_invocacion,
        "horas_batch_mes": horas_batch,
    }


def tabla_costos(s: Supuestos) -> dict:
    t = s.tarifa_hora
    horas_dev = {k: v * s.factor_horas for k, v in HORAS_DESARROLLO.items()}
    equipo_dev = sum(horas_dev.values()) * t
    desarrollo = {
        "Horas del equipo de datos": equipo_dev,
        "Extracción y seudonimización por TI de la cadena (24 h)": 24 * t,
        "Licencias (stack de código abierto)": 0.0,
        "Cómputo de experimentación (equipo existente, 4 meses)": 1_200 / 36 * 4,
    }
    aws = costos_aws(s)
    reparto = {"refresco": 4 / 12, "monitoreo": 2 / 12, "soporte": 6 / 12}
    h = s.horas_operacion_mes
    operacion = dict(aws["lineas"]) | {
        f"Refresco mensual de datos y reentrenamiento ({h * reparto['refresco']:.1f} h)".replace(".", ","): h * reparto["refresco"] * t,
        f"Monitoreo de deriva y calibración ({h * reparto['monitoreo']:.1f} h)".replace(".", ","): h * reparto["monitoreo"] * t,
        f"Soporte y mantenimiento ({h * reparto['soporte']:.1f} h)".replace(".", ","): h * reparto["soporte"] * t,
    }
    ocultos_unica = {
        "Capacitación de usuarios (6 personas × 4 h + 12 h de preparación)": 6 * 4 * TARIFA_ANALISTA_COMERCIAL + 12 * t,
        "Gestión del cambio: piloto en modo sombra (40 h)": 40 * t,
        "Integración con sistemas actuales (extracción automática, CRM y cupones en POS: 100 h)": 100 * t,
        "Cumplimiento LOPDP: evaluación de impacto y delegado (30 h)": 30 * TARIFA_LEGAL,
    }
    ocultos_mes = {
        "Deuda técnica: reserva del 20% anual del desarrollo": 0.20 * equipo_dev / 12,
        "Recapacitación por rotación (50% anual)": 0.5 * ocultos_unica[
            "Capacitación de usuarios (6 personas × 4 h + 12 h de preparación)"] / 12,
        "Revisión anual LOPDP (10 h)": 10 * TARIFA_LEGAL / 12,
    }
    return {
        "horas_desarrollo": horas_dev,
        "desarrollo": desarrollo,
        "operacion_mes": operacion,
        "ocultos_unica": ocultos_unica,
        "ocultos_mes": ocultos_mes,
        "aws": aws,
        "total_desarrollo": sum(desarrollo.values()),
        "total_operacion_mes": sum(operacion.values()),
        "total_ocultos_unica": sum(ocultos_unica.values()),
        "total_ocultos_mes": sum(ocultos_mes.values()),
    }


# --- Beneficios e indicadores -------------------------------------------------
def beneficio_trimestral(s: Supuestos, presupuesto: float, semillas: tuple[int, ...]) -> dict:
    sistema = promedio(presupuesto, "valor_en_riesgo", 2, s.efecto_promo, s.costo_promo_usd, semillas)
    base = promedio(presupuesto, s.linea_base, s.promos_linea_base, s.efecto_promo, s.costo_promo_usd, semillas)
    delta = sistema["margen_incremental_usd"] - base["margen_incremental_usd"]
    # Desvio de la diferencia pareada por semilla (mismo azar en ambas politicas).
    difs = [
        _corrida(presupuesto, "valor_en_riesgo", 2, s.efecto_promo, s.costo_promo_usd, x)["margen_incremental_usd"]
        - _corrida(presupuesto, s.linea_base, s.promos_linea_base, s.efecto_promo, s.costo_promo_usd, x)["margen_incremental_usd"]
        for x in semillas
    ]
    horas_ahorradas = 20  # por campana trimestral: de ~24 h de planillas a ~4 h
    return {
        "sistema": sistema,
        "linea_base": base,
        "delta_margen_trimestre": delta,
        "delta_margen_sd": float(np.std(difs, ddof=1)) if len(difs) > 1 else 0.0,
        "focalizacion_trimestre": delta * s.adopcion * s.persistencia,
        "horas_ahorradas_trimestre": horas_ahorradas * TARIFA_ANALISTA_COMERCIAL,
    }


def flujos(s: Supuestos, costos: dict, benef: dict) -> tuple[np.ndarray, np.ndarray]:
    """Beneficio y costo por mes: mes 0 = inversion; meses 1..36 = operacion.

    El beneficio de una campana trimestral se reparte en sus tres meses y solo
    corre desde el trimestre de inicio: el primero es el piloto en sombra.
    """
    beneficio = np.zeros(HORIZONTE_MESES + 1)
    costo = np.zeros(HORIZONTE_MESES + 1)
    costo[0] = costos["total_desarrollo"] + costos["total_ocultos_unica"]
    for mes in range(1, HORIZONTE_MESES + 1):
        costo[mes] = costos["total_operacion_mes"] + costos["total_ocultos_mes"]
        if (mes - 1) // 3 + 1 >= s.trimestre_inicio:
            beneficio[mes] = (benef["focalizacion_trimestre"] + benef["horas_ahorradas_trimestre"]) / 3
    return beneficio, costo


def indicadores(s: Supuestos, costos: dict, benef: dict) -> dict:
    beneficio, costo = flujos(s, costos, benef)
    f = beneficio - costo
    r_m = (1 + s.tasa_descuento) ** (1 / 12) - 1
    vpn = float(sum(v / (1 + r_m) ** t for t, v in enumerate(f)))
    tco = float(costo.sum())
    beneficios = float(beneficio.sum())
    acumulado = np.cumsum(f)
    payback = None
    for t in range(1, len(acumulado)):
        if acumulado[t] >= 0 > acumulado[t - 1]:
            payback = (t - 1) + (-acumulado[t - 1]) / (acumulado[t] - acumulado[t - 1])
            break
    return {
        "tco_3a": tco,
        "beneficios_3a": beneficios,
        "roi_pct": 100 * (beneficios - tco) / tco,
        "vpn": vpn,
        "payback_meses": payback,
        "tasa_mensual": r_m,
        "flujo_mensual": f.tolist(),
        "acumulado": acumulado.tolist(),
    }


def evaluar(s: Supuestos, presupuesto: float, semillas: tuple[int, ...]) -> dict:
    costos = tabla_costos(s)
    benef = beneficio_trimestral(s, presupuesto, semillas)
    return {"supuestos": asdict(s), "costos": costos, "beneficios": benef,
            "indicadores": indicadores(s, costos, benef)}


# --- Vista B: economia de la campana -----------------------------------------
def economia_campana(efecto: float, costo_promo: float, presupuesto_ref: float,
                     semilla: int = 42) -> dict:
    """Beneficio neto (margen - gasto) de la campana del sistema segun presupuesto."""
    # Fina en la zona baja, donde cae el optimo cuando el efecto es chico.
    grilla = [0.0] + [float(x) for x in range(1_000, 10_000, 1_000)] + [float(x) for x in range(10_000, 300_001, 5_000)]
    curva = []
    for p in grilla:
        if p == 0:
            curva.append({"presupuesto": 0.0, "neto": 0.0, "margen": 0.0, "reduccion": 0.0})
            continue
        r = _corrida(p, "valor_en_riesgo", 2, efecto, costo_promo, semilla)
        curva.append({"presupuesto": p, "neto": r["margen_incremental_usd"] - r["costo_total_usd"],
                      "margen": r["margen_incremental_usd"], "reduccion": r["reduccion_fuga_pct"],
                      "ingreso": r["ingreso_incremental_usd"]})
    mejor = max(curva, key=lambda c: c["neto"])
    ref = _corrida(presupuesto_ref, "valor_en_riesgo", 2, efecto, costo_promo, semilla)
    techo = _corrida(2_000_000, "valor_en_riesgo", 2, efecto, costo_promo, semilla)
    return {
        "efecto": efecto,
        "curva": curva,
        "presupuesto_optimo": mejor["presupuesto"],
        "neto_optimo": mejor["neto"],
        "reduccion_en_optimo": mejor["reduccion"],
        "en_referencia": {
            "presupuesto": presupuesto_ref,
            "margen": ref["margen_incremental_usd"],
            "ingreso": ref["ingreso_incremental_usd"],
            "neto": ref["margen_incremental_usd"] - ref["costo_total_usd"],
            "retorno_margen": ref["roi_margen"],
            "retorno_ingreso": ref["roi"],
            "reduccion": ref["reduccion_fuga_pct"],
        },
        "reduccion_maxima_2M": techo["reduccion_fuga_pct"],
    }


def biseccion(f, bajo: float, alto: float, iteraciones: int = 10) -> float | None:
    """Raiz de una funcion creciente en [bajo, alto]; None si no cambia de signo."""
    if f(bajo) > 0 or f(alto) < 0:
        return None
    for _ in range(iteraciones):
        medio = (bajo + alto) / 2
        if f(medio) >= 0:
            alto = medio
        else:
            bajo = medio
    return alto


# --- Diseno de la validacion de negocio -------------------------------------
def efecto_minimo_detectable(presupuesto: float, costo_promo: float, fraccion_holdout: float,
                             fraccion_piloto: float = 1.0) -> dict:
    """MDE de un A/B con grupo reservado DENTRO de la lista focalizada.

    Potencia 80%, alfa 5% bilateral: (1,96 + 0,84) * sqrt(p(1-p)(1/n_t + 1/n_c)).
    """
    pob = poblacion()
    n_lista = int(presupuesto // costo_promo) // 2
    puntaje = (pob["prob_abandono"] * pob["monetario"]).to_numpy()
    seleccion = np.argsort(-puntaje)[:n_lista]
    p = float(pob["prob_abandono"].to_numpy()[seleccion].mean())
    n = n_lista * fraccion_piloto
    n_c, n_t = n * fraccion_holdout, n * (1 - fraccion_holdout)
    mde = 2.80 * math.sqrt(p * (1 - p) * (1 / n_t + 1 / n_c))
    return {"clientes_lista": int(n), "holdout": fraccion_holdout, "fuga_base": p,
            "mde_pp": 100 * mde, "mde_relativo_pct": 100 * mde / p}


def ruido_entre_grupos(semillas: tuple[int, ...]) -> dict:
    """Con efecto verdadero cero (3 promos = saturacion), cuanto 'efecto' marca
    la comparacion ingenua tratados vs control de toda la poblacion."""
    vals = [_corrida(5_000, "valor_en_riesgo", 3, 0.35, 1.20, s)["detalle"]["reduccion_fuga_entre_grupos_pct"]
            for s in semillas]
    return {"semillas": len(vals), "media_pct": float(np.mean(vals)), "sd_pct": float(np.std(vals, ddof=1)),
            "max_abs_pct": float(np.max(np.abs(vals)))}


# --- Orquestacion ---------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semillas", type=int, default=10)
    args = parser.parse_args()
    semillas = tuple(range(1, args.semillas + 1))
    inicio = time.time()

    escenarios_sim = json.loads((ARTIFACTS / "escenarios.json").read_text(encoding="utf-8"))
    presupuesto_ref = float(escenarios_sim["presupuesto_minimo_meta_15pct"] or 150_000)
    print(f"Presupuesto de referencia: USD {presupuesto_ref:,.0f} por trimestre "
          f"(minimo para -15% con el efecto del guion)")
    print(f"Tarifa interna cargada: USD {TARIFA_INTERNA}/h")

    resultados = {}
    for nombre, s in ESCENARIOS.items():
        resultados[nombre] = evaluar(s, presupuesto_ref, semillas)
        ind = resultados[nombre]["indicadores"]
        print(f"  {nombre:10} dM/trim {resultados[nombre]['beneficios']['delta_margen_trimestre']:>11,.0f}  "
              f"TCO {ind['tco_3a']:>9,.0f}  VPN {ind['vpn']:>11,.0f}  ROI {ind['roi_pct']:>8,.0f}%  "
              f"payback {ind['payback_meses']}")

    # Tornado: cada supuesto a su valor pesimista y optimista, el resto realista.
    real, pes, opt = ESCENARIOS["realista"], ESCENARIOS["pesimista"], ESCENARIOS["optimista"]
    variables = {
        "Efecto de una promoción": ("efecto_promo",),
        "Decisión de referencia (línea base)": ("linea_base", "promos_linea_base"),
        "Adopción por el equipo comercial": ("adopcion",),
        "Trimestre en que empieza el beneficio": ("trimestre_inicio",),
        "Persistencia del cliente salvado": ("persistencia",),
        "Costo por promoción": ("costo_promo_usd",),
        "Tarifa y esfuerzo del equipo": ("tarifa_hora", "factor_horas"),
        "Tasa de descuento": ("tasa_descuento",),
        "Horas de operación": ("horas_operacion_mes", "invocaciones_mes"),
    }
    vpn_base = resultados["realista"]["indicadores"]["vpn"]
    tornado = []
    for etiqueta, campos in variables.items():
        extremos = {}
        for lado, fuente in (("pesimista", pes), ("optimista", opt)):
            s = replace(real, nombre=f"tornado_{lado}", **{c: getattr(fuente, c) for c in campos})
            extremos[lado] = evaluar(s, presupuesto_ref, semillas)["indicadores"]["vpn"]
        tornado.append({"variable": etiqueta, "vpn_pesimista": extremos["pesimista"],
                        "vpn_optimista": extremos["optimista"],
                        "rango": abs(extremos["optimista"] - extremos["pesimista"])})
    tornado.sort(key=lambda x: -x["rango"])
    print(f"\nVariable mas sensible: {tornado[0]['variable']} "
          f"(VPN {tornado[0]['vpn_pesimista']:,.0f} a {tornado[0]['vpn_optimista']:,.0f})")

    # Puntos de equilibrio del sistema (vista A), con el resto en realista.
    semillas_eq = semillas[:5]

    def vpn_con(**cambios):
        return evaluar(replace(real, **cambios), presupuesto_ref, semillas_eq)["indicadores"]["vpn"]

    equilibrio = {
        "efecto_minimo_vpn0": biseccion(lambda e: vpn_con(efecto_promo=e), 0.0, 0.35),
        "adopcion_minima_vpn0": biseccion(lambda a: vpn_con(adopcion=a), 0.0, 1.0),
        "efecto_minimo_vpn0_contra_recencia": biseccion(
            lambda e: vpn_con(efecto_promo=e, linea_base="recencia"), 0.0, 0.35),
        # Con TODOS los demas supuestos en su valor pesimista.
        "efecto_minimo_vpn0_escenario_pesimista": biseccion(
            lambda e: evaluar(replace(pes, efecto_promo=e), presupuesto_ref, semillas_eq)["indicadores"]["vpn"],
            0.0, 0.35),
        "adopcion_minima_vpn0_escenario_pesimista": biseccion(
            lambda a: evaluar(replace(pes, adopcion=a), presupuesto_ref, semillas_eq)["indicadores"]["vpn"],
            0.0, 1.0),
    }

    # Vista B: la campana frente a no hacer nada, para los tres efectos.
    campana = {n: economia_campana(s.efecto_promo, s.costo_promo_usd, presupuesto_ref)
               for n, s in ESCENARIOS.items()}
    campana["efecto_equilibrio_en_referencia"] = biseccion(
        lambda e: _corrida(presupuesto_ref, "valor_en_riesgo", 2, e, 1.20, 42)["margen_incremental_usd"]
        - _corrida(presupuesto_ref, "valor_en_riesgo", 2, e, 1.20, 42)["costo_total_usd"], 0.0, 0.95)
    campana["efecto_para_meta_15_en_referencia"] = biseccion(
        lambda e: _corrida(presupuesto_ref, "valor_en_riesgo", 2, e, 1.20, 42)["reduccion_fuga_pct"] - 15.0,
        0.0, 0.95)
    campana["efecto_para_retorno_3a1_margen_en_referencia"] = biseccion(
        lambda e: _corrida(presupuesto_ref, "valor_en_riesgo", 2, e, 1.20, 42)["roi_margen"] - 3.0, 0.0, 0.95)
    # La meta del guion (3:1) se formulo sobre ingreso, no sobre margen.
    campana["efecto_para_retorno_3a1_ingreso_en_referencia"] = biseccion(
        lambda e: _corrida(presupuesto_ref, "valor_en_riesgo", 2, e, 1.20, 42)["roi"] - 3.0, 0.0, 0.95)

    # Costo de medir: margen que se deja de ganar por reservar el 10% de control.
    sin_control = _corrida(presupuesto_ref, "valor_en_riesgo", 2, real.efecto_promo, real.costo_promo_usd, 42, 0.0)
    con_control = _corrida(presupuesto_ref, "valor_en_riesgo", 2, real.efecto_promo, real.costo_promo_usd, 42, 0.10)
    costo_control = sin_control["margen_incremental_usd"] - con_control["margen_incremental_usd"]

    # Que reduccion implica cada efecto entre los clientes de la lista: es la
    # cifra comparable con los experimentos de campo de la literatura.
    pob = poblacion()
    n_lista = int(presupuesto_ref // real.costo_promo_usd) // 2
    orden = np.argsort(-(pob["prob_abandono"] * pob["monetario"]).to_numpy())[:n_lista]
    recept = np.clip(0.45 + pob["propension_promo"].fillna(0).to_numpy()[orden], 0.3, 1.0)
    p_lista = pob["prob_abandono"].to_numpy()[orden]
    equivalencia = []
    for e in sorted({0.04, 0.10, 0.25, 0.35}):
        rel = np.minimum(e * (1 + 0.55), 0.95) * recept
        equivalencia.append({"efecto_base": e, "reduccion_relativa_tratados_pct": float(100 * rel.mean()),
                             "reduccion_pp_tratados": float(100 * (p_lista * rel).mean()),
                             "fuga_base_lista_pct": float(100 * p_lista.mean())})

    validacion = {
        "equivalencia_efecto": equivalencia,
        "mde": [efecto_minimo_detectable(presupuesto_ref, real.costo_promo_usd, h, f)
                for h, f in ((0.10, 1.0), (0.20, 1.0), (0.10, 0.25), (0.20, 0.25))],
        "ruido_entre_grupos": ruido_entre_grupos(tuple(range(100, 130))),
    }

    salida = {
        "generado_segundos": round(time.time() - inicio, 1),
        "semillas": len(semillas),
        "presupuesto_referencia": presupuesto_ref,
        "tarifa_interna": TARIFA_INTERNA,
        "horas_desarrollo_base": HORAS_DESARROLLO,
        "escenarios": resultados,
        "tornado": tornado,
        "equilibrio_sistema": equilibrio,
        "campana": campana,
        "costo_grupo_control_trimestre": costo_control,
        "validacion": validacion,
        "etiquetas_linea_base": {f"{k[0]}_{k[1]}": v for k, v in ETIQUETA_LINEA_BASE.items()},
    }
    (ARTIFACTS / "costo_beneficio.json").write_text(
        json.dumps(salida, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"\nEquilibrio: {equilibrio}")
    print(f"Campana: optimo realista USD {campana['realista']['presupuesto_optimo']:,.0f} "
          f"(neto {campana['realista']['neto_optimo']:,.0f}); efecto de equilibrio a "
          f"USD {presupuesto_ref:,.0f}: {campana['efecto_equilibrio_en_referencia']}")
    print(f"Resultados en {ARTIFACTS / 'costo_beneficio.json'} ({salida['generado_segundos']} s)")

    from evaluacion.figuras_cb import generar  # noqa: E402

    generar(salida, FIGURAS)


if __name__ == "__main__":
    main()
