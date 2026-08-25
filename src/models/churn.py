"""Modelo de abandono (churn) de clientes VIP con validacion temporal estricta.

El guion fija un objetivo de **AUC >= 0.75**. Ese numero solo significa algo si
la validacion no tiene fuga de informacion, asi que aqui la separacion es
temporal y no aleatoria.

Diseno del experimento
----------------------
Se elige un punto de decision C. Las variables se calculan **solo** con
transacciones anteriores a C. La etiqueta se observa **despues** de C:

    features: [inicio, C)          etiqueta: hubo compra en [C, C + 90 dias)?

Se entrena en un C temprano y se prueba en un C posterior, de modo que el
modelo nunca ve el periodo con el que se le evalua:

    ENTRENAMIENTO  C = 2026-01-01   etiqueta observada ene-mar 2026
    PRUEBA         C = 2026-04-01   etiqueta observada abr-jun 2026

Un split aleatorio daria un AUC mas alto y completamente enganoso, porque el
mismo cliente aparecería a ambos lados de la particion.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

ROOT = Path(__file__).resolve().parents[2]
VENTAS = ROOT / "data" / "processed" / "ventas"
TICKETS = ROOT / "data" / "processed" / "tickets" / "corte=2026-07-01"
ARTIFACTS = ROOT / "data" / "artifacts"

DIAS_FUGA = 90
CUANTIL_VIP = 0.80

CORTE_ENTRENAMIENTO = "2026-01-01"
CORTE_PRUEBA = "2026-04-01"

VARIABLES = [
    "recencia",
    "frecuencia",
    "monetario",
    "ticket_promedio",
    "sucursales_visitadas",
    "propension_promo",
    "antiguedad_dias",
    "tickets_ult_30",
    "tickets_ult_90",
    "gasto_ult_90",
    "tendencia_gasto",
]


def construir_dataset(con: duckdb.DuckDBPyConnection, corte: str) -> pd.DataFrame:
    """Variables anteriores a `corte` y etiqueta observada en los 90 dias siguientes.

    Se apoya en la tabla de tickets que produce `features/rfm.py`: agregar desde
    las 72M lineas crudas agota la memoria, y a nivel de ticket los conteos de
    frecuencia son un COUNT(*) trivial.
    """
    patron = (TICKETS / "*.parquet").as_posix()

    return con.execute(
        f"""
        WITH historico AS (
            SELECT * FROM read_parquet('{patron}')
            WHERE fecha < TIMESTAMP '{corte}'
        ),
        futuro AS (
            SELECT DISTINCT cliente_id
            FROM read_parquet('{patron}')
            WHERE fecha >= TIMESTAMP '{corte}'
              AND fecha <  TIMESTAMP '{corte}' + INTERVAL {DIAS_FUGA} DAY
        ),
        agregado AS (
            SELECT
                cliente_id,
                DATE_DIFF('day', MAX(fecha), TIMESTAMP '{corte}')  AS recencia,
                COUNT(*)                                            AS frecuencia,
                SUM(venta)                                          AS monetario,
                SUM(lineas)                                         AS lineas,
                DATE_DIFF('day', MIN(fecha), TIMESTAMP '{corte}')  AS antiguedad_dias,
                APPROX_COUNT_DISTINCT(sucursal_id)                  AS sucursales_visitadas,
                SUM(con_promo)                                      AS tickets_con_promo,
                -- Señales de corto plazo: capturan el enfriamiento reciente que
                -- la recencia sola no distingue de un cliente esporadico.
                COUNT(CASE
                    WHEN fecha >= TIMESTAMP '{corte}' - INTERVAL 30 DAY
                    THEN 1 END)                                     AS tickets_ult_30,
                COUNT(CASE
                    WHEN fecha >= TIMESTAMP '{corte}' - INTERVAL 90 DAY
                    THEN 1 END)                                     AS tickets_ult_90,
                SUM(CASE
                    WHEN fecha >= TIMESTAMP '{corte}' - INTERVAL 90 DAY
                    THEN venta ELSE 0 END)                          AS gasto_ult_90,
                SUM(CASE
                    WHEN fecha >= TIMESTAMP '{corte}' - INTERVAL 180 DAY
                     AND fecha <  TIMESTAMP '{corte}' - INTERVAL 90 DAY
                    THEN venta ELSE 0 END)                          AS gasto_prev_90,
                ARG_MAX(marca, venta)                               AS marca_principal
            FROM historico
            GROUP BY cliente_id
        ),
        con_vip AS (
            SELECT
                *,
                monetario / NULLIF(frecuencia, 0)             AS ticket_promedio,
                tickets_con_promo::DOUBLE / NULLIF(frecuencia, 0) AS propension_promo,
                -- Razon de gasto reciente frente al trimestre anterior: <1 indica
                -- desaceleracion, que es la senal temprana de fuga.
                gasto_ult_90 / NULLIF(gasto_prev_90, 0)       AS tendencia_gasto,
                monetario >= QUANTILE_CONT(monetario, {CUANTIL_VIP}) OVER () AS es_vip
            FROM agregado
        )
        SELECT
            c.*,
            CASE WHEN f.cliente_id IS NULL THEN 1 ELSE 0 END AS abandono
        FROM con_vip c
        LEFT JOIN futuro f USING (cliente_id)
        WHERE c.es_vip
        """
    ).df()


def preparar(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    x = df[VARIABLES].copy()
    # tendencia_gasto es infinita cuando no hubo gasto en el trimestre previo
    # (cliente nuevo). Se trata como faltante: el modelo lo maneja nativamente.
    x = x.replace([np.inf, -np.inf], np.nan)
    return x, df["abandono"].to_numpy()


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET max_temp_directory_size='5GB'")
    con.execute('SET threads=4')
    con.execute('SET preserve_insertion_order=false')
    con.execute('SET enable_progress_bar=false')
    con.execute(f"SET temp_directory='{(ROOT / 'data' / '.duckdb_tmp').as_posix()}'")

    print(f"Construyendo entrenamiento (corte {CORTE_ENTRENAMIENTO}) ...")
    df_tr = construir_dataset(con, CORTE_ENTRENAMIENTO)
    print(f"Construyendo prueba        (corte {CORTE_PRUEBA}) ...")
    df_te = construir_dataset(con, CORTE_PRUEBA)

    x_tr, y_tr = preparar(df_tr)
    x_te, y_te = preparar(df_te)

    print(f"\nVIP entrenamiento: {len(x_tr):,}  tasa de abandono: {y_tr.mean():.1%}")
    print(f"VIP prueba       : {len(x_te):,}  tasa de abandono: {y_te.mean():.1%}")

    modelo = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.06,
        max_depth=6,
        min_samples_leaf=40,
        l2_regularization=1.0,
        random_state=42,
    )
    modelo.fit(x_tr, y_tr)

    p_te = modelo.predict_proba(x_te)[:, 1]
    metricas = {
        "corte_entrenamiento": CORTE_ENTRENAMIENTO,
        "corte_prueba": CORTE_PRUEBA,
        "n_entrenamiento": int(len(x_tr)),
        "n_prueba": int(len(x_te)),
        "tasa_abandono_entrenamiento": round(float(y_tr.mean()), 4),
        "tasa_abandono_prueba": round(float(y_te.mean()), 4),
        "auc": round(float(roc_auc_score(y_te, p_te)), 4),
        "average_precision": round(float(average_precision_score(y_te, p_te)), 4),
        "brier": round(float(brier_score_loss(y_te, p_te)), 4),
        "objetivo_auc": 0.75,
    }
    metricas["cumple_objetivo"] = bool(metricas["auc"] >= 0.75)

    # Lift del decil superior: cuantos abandonos reales captura el 10% con mayor
    # riesgo. Es la metrica que de verdad usa el equipo comercial para priorizar.
    orden = np.argsort(-p_te)
    top = orden[: max(1, len(orden) // 10)]
    metricas["captura_decil_superior_pct"] = round(
        100 * float(y_te[top].sum() / max(y_te.sum(), 1)), 2
    )

    (ARTIFACTS / "churn_metricas.json").write_text(
        json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # El score por cliente alimenta al simulador: cada agente arranca con su
    # probabilidad real de fuga en lugar de un valor promedio.
    salida = df_te[["cliente_id", "marca_principal", "monetario", "frecuencia", "recencia"]].copy()
    salida["prob_abandono"] = p_te
    salida["abandono_real"] = y_te
    salida.to_parquet(ARTIFACTS / "scores_vip.parquet", index=False)

    print("\n--- Resultados (validacion temporal) ---")
    for k, v in metricas.items():
        print(f"  {k:32} {v}")
    print(
        "\nOBJETIVO CUMPLIDO" if metricas["cumple_objetivo"]
        else "\nAUC POR DEBAJO DEL OBJETIVO"
    )


if __name__ == "__main__":
    main()
