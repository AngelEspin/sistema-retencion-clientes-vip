"""Panel analitico del tablero.

Reune en un solo diccionario las cifras y series agregadas que grafica el
tablero: concentracion del ingreso, validacion del modelo, efecto de las
promociones, economia de la campana y del sistema, piloto y criterios de
validacion. Todo sale de los artefactos de data/artifacts y de los datos
procesados; aqui no se escribe ninguna cifra a mano.

Solo contiene agregados (curvas de 101 puntos, deciles, totales): ninguna fila
por cliente. Por eso la version estatica del tablero puede incrustarlo sin
exponer datos personales.

Lo usan la API (GET /v1/panel) y generar_pagina_estatica.py, para que el
tablero local y el estatico muestren exactamente lo mismo.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from simulation.simulador import (
    DECAIMIENTO_MARGINAL,
    UMBRAL_SATURACION,
    efecto_acumulado,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data" / "artifacts"
PROCESADOS = ROOT / "data" / "processed"
# Los crudos viven en data/Unprocessed o, si vienen de la descarga, en Datos/.
CARPETAS_CRUDOS = (ROOT / "data" / "Unprocessed", ROOT / "Datos")

# Grilla de escenarios que ofrece el tablero. La version estatica la precalcula
# completa; la local la resuelve en vivo con los mismos valores, asi ambas
# muestran las mismas cifras para la misma eleccion.
PRESUPUESTOS = [1_000, 2_000, 4_000, 5_000, 10_000, 25_000, 50_000,
                100_000, 139_000, 250_000, 500_000, 1_000_000]
PROMOS = [1, 2, 3, 4]
CRITERIOS = ["valor_en_riesgo", "riesgo", "recencia", "valor", "aleatorio"]
COSTO_PROMO_USD = 1.20
PCT_CONTROL = 0.10
SEMILLA = 42

ESCENARIOS_CB = ("pesimista", "realista", "optimista")


def _leer(nombre: str) -> dict[str, Any]:
    return json.loads((ARTIFACTS / nombre).read_text(encoding="utf-8"))


def _leer_opcional(nombre: str) -> dict[str, Any] | None:
    ruta = ARTIFACTS / nombre
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def parametros_grilla() -> dict[str, Any]:
    """Valores de cada control del simulador del tablero.

    Los tres efectos son los de los escenarios del analisis costo/beneficio
    (pesimista, realista, optimista), no una eleccion del tablero.
    """
    cb = _leer("costo_beneficio.json")
    return {
        "presupuestos": PRESUPUESTOS,
        "promos": PROMOS,
        "criterios": CRITERIOS,
        "efectos": [cb["campana"][e]["efecto"] for e in ESCENARIOS_CB],
        "costo_promo_usd": COSTO_PROMO_USD,
        "pct_control": PCT_CONTROL,
        "semilla": SEMILLA,
        "umbral_saturacion": UMBRAL_SATURACION,
    }


def _tamano_gb(carpeta: Path) -> float | None:
    if not carpeta.exists():
        return None
    total = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    return round(total / 1e9, 2)


def _filas_parquet(carpeta: Path) -> int | None:
    """Filas de un conjunto Parquet leyendo solo los metadatos, sin cargarlo."""
    archivos = sorted(carpeta.rglob("*.parquet")) if carpeta.exists() else []
    if not archivos:
        return None
    import pyarrow.parquet as pq

    return int(sum(pq.ParquetFile(f).metadata.num_rows for f in archivos))


def _archivo_crudo(patron: str) -> Path | None:
    for carpeta in CARPETAS_CRUDOS:
        hallado = next(iter(sorted(carpeta.glob(patron))), None) if carpeta.exists() else None
        if hallado:
            return hallado
    return None


@lru_cache(maxsize=1)
def _datos_pipeline() -> dict[str, Any]:
    """Tamanos y conteos del pipeline. Se calcula una vez por proceso."""
    ventas_csv = _archivo_crudo("ventas*.csv")
    sucursales_csv = _archivo_crudo("sucursales*.csv")
    sucursales = None
    if sucursales_csv:
        with sucursales_csv.open(encoding="utf-8", errors="ignore", newline="") as f:
            sucursales = max(sum(1 for _ in csv.reader(f)) - 1, 0)
    # El umbral VIP no se guarda en el resumen RFM: es el menor gasto del segmento.
    umbral_vip = None
    rfm = sorted((PROCESADOS / "rfm").rglob("*.parquet")) if (PROCESADOS / "rfm").exists() else []
    if rfm:
        import duckdb

        umbral_vip = duckdb.connect().execute(
            f"SELECT MIN(monetario) FROM read_parquet('{rfm[-1].as_posix()}') WHERE es_vip"
        ).fetchone()[0]
    return {
        "csv_gb": round(ventas_csv.stat().st_size / 1e9, 1) if ventas_csv else None,
        "parquet_gb": _tamano_gb(PROCESADOS / "ventas"),
        "lineas": _filas_parquet(PROCESADOS / "ventas"),
        "comprobantes": _filas_parquet(PROCESADOS / "tickets"),
        "sucursales": sucursales,
        "umbral_vip_usd": round(float(umbral_vip), 2) if umbral_vip is not None else None,
    }


def _d(valor: float, decimales: int) -> str:
    """Numero con coma decimal, como el resto del tablero y la defensa."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def _criterios(rfm: dict, churn: dict, esc: dict, cb: dict, nube: dict | None) -> list[dict]:
    """Filas de la matriz de validacion que el tablero resume.

    El estado se calcula contra el umbral; las filas que dependen del efecto
    supuesto se marcan como simuladas, porque solo el piloto las confirma.
    """
    ref = next(p for p in esc["comparacion_politicas"] if p["escenario"] == "simulador_valor_en_riesgo")
    real = cb["campana"]["realista"]["en_referencia"]
    lista = cb["validacion"]["calibracion_lista"]
    ben = cb["escenarios"]["realista"]["beneficios"]
    sesgo_lista = 100 * (lista["fuga_predicha"] - lista["fuga_observada"])
    veces = ben["sistema"]["margen_incremental_usd"] / ben["linea_base"]["margen_incremental_usd"]
    conc = rfm["concentracion_ingreso_vip_pct"]
    delta_auc = churn["auc"] - churn["auc_linea_base_recencia"]

    filas = [
        {"id": "N1", "metrica": "Ingreso que concentra el 20 % VIP", "criterio": "70 % a 80 %",
         "medido": f"{_d(conc, 2)} %", "estado": "cumple" if 70 <= conc <= 80 else "fuera",
         "nota": f"{_d(conc - 80, 2)} pp sobre el rango" if conc > 80 else ""},
        {"id": "T1", "metrica": "AUC en la prueba temporal", "criterio": "≥ 0,75",
         "medido": _d(churn["auc"], 4), "estado": "cumple" if churn["auc"] >= 0.75 else "no_cumple"},
        {"id": "T2", "metrica": "Mejora del AUC frente a la regla de recencia", "criterio": "≥ +0,03",
         "medido": f"+{_d(delta_auc, 3)}", "estado": "cumple" if delta_auc >= 0.03 else "no_cumple",
         "nota": "criterio fijado con el valor ya conocido"},
        {"id": "T3", "metrica": "Sesgo de calibración en la lista focalizada", "criterio": "≤ 2 pp",
         "medido": f"+{_d(sesgo_lista, 1)} pp", "estado": "cumple" if abs(sesgo_lista) <= 2 else "no_cumple",
         "nota": f"en toda la población: +{_d(churn['sesgo_calibracion_pp'], 2)} pp"},
        {"id": "T4", "metrica": "Deriva del score (PSI)", "criterio": "< 0,10",
         "medido": _d(churn["psi_score_entrenamiento_vs_prueba"], 3),
         "estado": "cumple" if churn["psi_score_entrenamiento_vs_prueba"] < 0.10 else "no_cumple"},
        {"id": "N2", "metrica": "Reducción de la fuga VIP con USD 139 000", "criterio": "≥ 15 %",
         "medido": f"{_d(ref['reduccion_fuga_pct'], 2)} % (efecto 0,35) · {_d(real['reduccion'], 1)} % (0,10)",
         "estado": "simulado", "nota": "solo con el efecto supuesto de 0,35"},
        {"id": "N3", "metrica": "Retorno de la campaña (ingreso y margen)", "criterio": "≥ 3 y ≥ 1",
         "medido": f"{_d(ref['roi'], 2)} y {_d(ref['roi_margen'], 2)} (0,35) · "
                   f"{_d(real['retorno_ingreso'], 2)} y {_d(real['retorno_margen'], 2)} (0,10)",
         "estado": "simulado", "nota": "solo con el efecto supuesto de 0,35"},
        {"id": "N5", "metrica": "Margen de la lista del sistema frente a la campaña masiva",
         "criterio": "≥ 2 veces", "medido": f"{_d(veces, 1)} veces (efecto 0,10)",
         "estado": "cumple" if veces >= 2 else "no_cumple",
         "nota": "criterio fijado con el valor ya conocido"},
    ]
    if nube:
        p95 = nube["caliente_simular"]["cliente_ms_p95"]
        filas.insert(5, {
            "id": "F1", "metrica": "Latencia p95 de /v1/simular en la nube emulada", "criterio": "< 3 s",
            "medido": f"{_d(p95 / 1000, 2)} s", "estado": "cumple" if p95 < 3000 else "no_cumple",
            "nota": "LocalStack; falta repetirlo en AWS real"})
    return filas


def construir_panel() -> dict[str, Any]:
    """Diccionario completo que consume el tablero."""
    rfm_archivo = sorted(ARTIFACTS.glob("rfm_resumen_*.json"))[-1]
    rfm = json.loads(rfm_archivo.read_text(encoding="utf-8"))
    churn = _leer("churn_metricas.json")
    esc = _leer("escenarios.json")
    cb = _leer("costo_beneficio.json")
    tiempos = _leer_opcional("tiempos_pipeline.json")
    nube = _leer_opcional("aws_mediciones.json")
    pruebas = _leer_opcional("pruebas_funcionales_local.json")
    pruebas_nube = _leer_opcional("pruebas_funcionales_remoto.json")

    g = cb["graficos"]
    receptividad = esc["escenarios"][0]["detalle"]["receptividad_media"]
    efectos = parametros_grilla()["efectos"]

    # Serie de la figura 4 del capitulo 2: reduccion del riesgo de un agente de
    # receptividad media segun las promociones que recibe.
    curvas_efecto = [
        {"efecto": e, "puntos": [
            {"promos": n, "reduccion_pct": round(100 * efecto_acumulado(n, receptividad, e, UMBRAL_SATURACION), 2)}
            for n in range(0, 6)]}
        for e in efectos
    ]

    saturacion_guion = [
        {"promos": int(r["promos_enviadas"] / max(r["clientes_alcanzados"], 1) + 0.5),
         "roi_margen": r["roi_margen"], "roi_ingreso": r["roi"],
         "reduccion_fuga_pct": r["reduccion_fuga_pct"], "clientes_alcanzados": r["clientes_alcanzados"],
         "clientes_saturados": r["clientes_saturados"]}
        for r in esc["escenarios"][:4]
    ]

    campana = {
        e: {"efecto": cb["campana"][e]["efecto"],
            "curva": [{"presupuesto": p["presupuesto"], "neto": p["neto"], "reduccion": p["reduccion"]}
                      for p in cb["campana"][e]["curva"]],
            "presupuesto_optimo": cb["campana"][e]["presupuesto_optimo"],
            "neto_optimo": cb["campana"][e]["neto_optimo"],
            "en_referencia": cb["campana"][e]["en_referencia"],
            "reduccion_maxima": cb["campana"][e]["reduccion_maxima_2M"]}
        for e in ESCENARIOS_CB
    }

    sistema = {}
    for e in ESCENARIOS_CB:
        ind = cb["escenarios"][e]["indicadores"]
        acumulado, suma = [], 0.0
        for flujo in ind["flujo_mensual"]:
            suma += flujo
            acumulado.append(round(suma, 2))
        aws = cb["escenarios"][e]["costos"]["aws"]
        sistema[e] = {
            "efecto": cb["escenarios"][e]["supuestos"]["efecto_promo"],
            "vpn": ind["vpn"], "payback_meses": ind["payback_meses"], "tco_3a": ind["tco_3a"],
            "roi_pct": ind["roi_pct"], "beneficios_3a": ind["beneficios_3a"],
            "delta_margen_trimestre": cb["escenarios"][e]["beneficios"]["delta_margen_trimestre"],
            "nube_mes_usd": round(sum(aws["lineas"].values()), 2),
            "acumulado": acumulado,
        }

    lista = cb["validacion"]["calibracion_lista"]
    piloto_clientes = next((m["clientes_lista"] for m in cb["validacion"]["mde"]
                            if m["clientes_lista"] != lista["clientes_lista"]), None)

    return {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "grilla": parametros_grilla(),
        "resumen": {
            "clientes": rfm["clientes"], "vips": rfm["vips"],
            "concentracion_vip_pct": rfm["concentracion_ingreso_vip_pct"],
            "ingreso_total_usd": rfm["ingreso_total"], "ingreso_vip_usd": rfm["ingreso_vip"],
            "margen_vip_pct": rfm["margen_bruto_vip_pct"], "ticket_promedio_vip": rfm["ticket_promedio_vip"],
            "umbral_vip_usd": _datos_pipeline()["umbral_vip_usd"], "fecha_corte": rfm["fecha_corte"],
            "agentes": churn["n_prueba"], "fuga_prueba_pct": round(100 * churn["tasa_abandono_prueba"], 2),
        },
        "datos": {
            **_datos_pipeline(),
            "cuentas_genericas": rfm["cuentas_genericas_excluidas"],
            "pct_comprobantes_genericas": rfm["pct_tickets_cuentas_genericas"],
            "pct_ingreso_genericas": rfm["pct_ingreso_cuentas_genericas"],
            "etapas": [{"etapa": k, "segundos": v["segundos"], "pico_ram_gb": v["pico_ram_gb"]}
                       for k, v in (tiempos or {}).get("etapas", {}).items()],
        },
        "concentracion": g["lorenz"],
        "modelo": {
            "auc": churn["auc"], "auc_recencia": churn["auc_linea_base_recencia"],
            "average_precision": churn["average_precision"], "brier": churn["brier"],
            "captura_decil_superior_pct": churn["captura_decil_superior_pct"],
            "n_entrenamiento": churn["n_entrenamiento"], "n_prueba": churn["n_prueba"],
            "corte_entrenamiento": churn["corte_entrenamiento"], "corte_prueba": churn["corte_prueba"],
            "sesgo_pp": churn["sesgo_calibracion_pp"], "psi": churn["psi_score_entrenamiento_vs_prueba"],
            "roc": g["roc"], "calibracion": g["calibracion"],
            "lista": {"clientes": lista["clientes_lista"], "fuga_predicha": lista["fuga_predicha"],
                      "fuga_observada": lista["fuga_observada"],
                      "en_decil_superior_pct": lista["en_decil_superior_pct"]},
        },
        "efecto_promos": {"receptividad_media": receptividad, "decaimiento": DECAIMIENTO_MARGINAL,
                          "umbral": UMBRAL_SATURACION, "curvas": curvas_efecto},
        "saturacion_guion": saturacion_guion,
        "politicas": g["politicas_realista"],
        "campana": campana,
        "referencia": {
            "presupuesto": cb["presupuesto_referencia"],
            "efecto_equilibrio": cb["campana"]["efecto_equilibrio_en_referencia"],
            "efecto_meta_15": cb["campana"]["efecto_para_meta_15_en_referencia"],
            "semillas": len(cb["semillas"]) if isinstance(cb["semillas"], list) else cb["semillas"],
        },
        "sistema": sistema,
        "tornado": cb["tornado"],
        "vpn_vs_efecto": g["vpn_vs_efecto"],
        "equilibrio": cb["equilibrio_sistema"],
        "piloto": {"clientes": piloto_clientes, "fuga_observada": lista["fuga_observada"],
                   "mde_relativo_pct": lista["mde_relativo_pct"],
                   "efectos_relativos_pct": {round(v["efecto_base"], 2): v["reduccion_relativa_tratados_pct"]
                                             for v in cb["validacion"]["equivalencia_efecto"]}},
        "criterios": _criterios(rfm, churn, esc, cb, nube),
        "nube": None if not nube else {
            "entorno": nube.get("entorno"),
            "p95_caliente_ms": nube["caliente_simular"]["cliente_ms_p95"],
            "frio_mediana_ms": nube["frio_simular"]["cliente_ms_p50"],
            "frio_max_ms": nube["frio_simular"]["cliente_ms_max"],
            "errores_concurrencia": nube["concurrencia_simular"]["errores"],
            "pruebas": None if not pruebas else {"aprobadas": pruebas["aprobados"], "casos": pruebas["casos"]},
            "pruebas_nube": None if not pruebas_nube else {"aprobadas": pruebas_nube["aprobados"],
                                                           "casos": pruebas_nube["casos"]},
        },
    }
