"""Segmentacion RFM y definicion del segmento VIP.

El guion de la tesis afirma que "entre el 70% y el 80% de los ingresos dependen
del 20% de clientes VIP". Este modulo no asume esa cifra: la calcula sobre los
datos reales y la reporta, porque es la premisa que justifica todo el proyecto.

Definiciones (fijadas aqui para que el resto del pipeline las herede):
  * Recencia   -- dias entre la ultima compra y la fecha de corte.
  * Frecuencia -- numero de tickets distintos (no de lineas de venta).
  * Monetario  -- suma de venta neta.
  * VIP        -- top 20% por valor monetario dentro de la ventana observada.
  * Fuga       -- VIP sin ninguna compra en los 90 dias previos al corte.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
VENTAS = ROOT / "data" / "processed" / "ventas"
SALIDA = ROOT / "data" / "processed" / "rfm"
TICKETS = ROOT / "data" / "processed" / "tickets"
ARTIFACTS = ROOT / "data" / "artifacts"

# Ventana de inactividad que el negocio considera fuga. Viene del guion.
DIAS_FUGA = 90
# Proporcion superior de clientes por valor que define el segmento VIP.
CUANTIL_VIP = 0.80


def construir_rfm(con: duckdb.DuckDBPyConnection, corte: str) -> None:
    """Calcula RFM por cliente usando solo transacciones anteriores al corte.

    El filtro por fecha de corte es lo que hace honesta la validacion temporal:
    ninguna feature puede mirar hacia el futuro del punto de decision.
    """
    patron = (VENTAS / "**" / "*.parquet").as_posix()

    # --- Etapa 1: linea de venta -> ticket ---------------------------------
    # COUNT(DISTINCT ticket_id) sobre 72M filas agrupadas por 3.1M clientes
    # desborda el disco: obliga a materializar todos los pares (cliente, ticket)
    # en memoria a la vez. Colapsar primero a nivel de ticket convierte ese
    # DISTINCT en un COUNT(*) trivial en la segunda etapa, y de paso deja una
    # tabla de tickets que es util por si misma.
    tickets = TICKETS / f"corte={corte}"
    if tickets.exists():
        shutil.rmtree(tickets)
    tickets.mkdir(parents=True, exist_ok=True)

    # Se agrupa mes a mes en lugar de todo de golpe. Es exacto: un ticket
    # pertenece a un unico instante, asi que nunca cruza el limite de un mes y
    # agrupar por particion da el mismo resultado que agrupar globalmente. La
    # ventaja es que acota el pico de memoria al tamano de un mes (~6M filas)
    # en vez de los 72M completos.
    meses = [
        m[0]
        for m in con.execute(
            f"""
            SELECT DISTINCT anio_mes
            FROM read_parquet('{patron}', hive_partitioning=true)
            WHERE fecha < TIMESTAMP '{corte}'
            ORDER BY 1
            """
        ).fetchall()
    ]
    print(f"  Agregando a nivel de ticket, {len(meses)} meses ...")

    for i, mes in enumerate(meses, 1):
        con.execute(
            f"""
            COPY (
                SELECT
                    cliente_id,
                    ticket_id,
                    MAX(fecha)                          AS fecha,
                    ANY_VALUE(sucursal_id)              AS sucursal_id,
                    ANY_VALUE(marca)                    AS marca,
                    SUM(venta_neta)                     AS venta,
                    COUNT(*)                            AS lineas,
                    MAX(CASE WHEN promocion_id IS NOT NULL
                              AND promocion_id <> '' THEN 1 ELSE 0 END) AS con_promo
                FROM read_parquet('{patron}', hive_partitioning=true)
                WHERE anio_mes = '{mes}'
                  AND fecha < TIMESTAMP '{corte}'
                GROUP BY cliente_id, ticket_id
            )
            TO '{(tickets / f'tickets_{mes}.parquet').as_posix()}'
            (FORMAT PARQUET, COMPRESSION zstd)
            """
        )
        print(f"    [{i:2}/{len(meses)}] {mes}")

    # --- Etapa 2a: ticket -> cliente (solo agregados) -----------------------
    # Se separa la agregacion de los scores. Meterlo todo en una sentencia
    # obligaba a DuckDB a sostener a la vez el hash de 3.1M grupos y tres
    # ordenaciones completas para los NTILE, y agotaba la memoria.
    print("  Agregando a nivel de cliente ...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE agregado AS
        SELECT
            cliente_id,
            DATE_DIFF('day', MAX(fecha), TIMESTAMP '{corte}') AS recencia,
            COUNT(*)                                           AS frecuencia,
            SUM(venta)                                         AS monetario,
            SUM(lineas)                                        AS lineas,
            MIN(fecha)                                         AS primera_compra,
            MAX(fecha)                                         AS ultima_compra,
            APPROX_COUNT_DISTINCT(sucursal_id)                 AS sucursales_visitadas,
            SUM(con_promo)                                     AS tickets_con_promo,
            -- La marca del ticket de mayor valor decide a que cadena
            -- "pertenece" el cliente. ARG_MAX es de coste constante por grupo,
            -- a diferencia de MODE, que mantiene un mapa de frecuencias.
            ARG_MAX(marca, venta)                              AS marca_principal
        FROM read_parquet('{(tickets / "*.parquet").as_posix()}')
        GROUP BY cliente_id
        """
    )

    # --- Etapa 2b: scores y segmentacion ------------------------------------
    # El umbral VIP se calcula una sola vez como escalar en lugar de como
    # ventana sobre cada fila.
    umbral_vip = con.execute(
        f"SELECT QUANTILE_CONT(monetario, {CUANTIL_VIP}) FROM agregado"
    ).fetchone()[0]
    print(f"  Umbral VIP (percentil {int(CUANTIL_VIP * 100)}): {umbral_vip:,.2f}")

    print("  Calculando scores RFM ...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE rfm AS
        SELECT
            *,
            monetario / NULLIF(frecuencia, 0) AS ticket_promedio,
            tickets_con_promo::DOUBLE / NULLIF(frecuencia, 0) AS propension_promo,
            NTILE(5) OVER (ORDER BY recencia DESC)  AS r_score,
            NTILE(5) OVER (ORDER BY frecuencia)     AS f_score,
            NTILE(5) OVER (ORDER BY monetario)      AS m_score,
            monetario >= {umbral_vip}               AS es_vip,
            recencia > {DIAS_FUGA}                  AS en_fuga
        FROM agregado
        """
    )


def resumen(con: duckdb.DuckDBPyConnection, corte: str) -> dict:
    """Verifica la premisa del negocio: cuanto ingreso concentra el 20% VIP."""
    fila = con.execute(
        """
        SELECT
            COUNT(*)                                              AS clientes,
            SUM(CASE WHEN es_vip THEN 1 ELSE 0 END)               AS vips,
            SUM(monetario)                                        AS ingreso_total,
            SUM(CASE WHEN es_vip THEN monetario ELSE 0 END)       AS ingreso_vip,
            SUM(CASE WHEN es_vip AND en_fuga THEN 1 ELSE 0 END)   AS vips_en_fuga,
            AVG(recencia)                                         AS recencia_media,
            AVG(frecuencia)                                       AS frecuencia_media
        FROM rfm
        """
    ).fetchone()

    clientes, vips, ingreso_total, ingreso_vip, vips_fuga, rec_media, frec_media = fila
    concentracion = ingreso_vip / ingreso_total if ingreso_total else 0.0

    return {
        "fecha_corte": corte,
        "clientes": int(clientes),
        "vips": int(vips),
        "pct_vip": round(100 * vips / clientes, 2) if clientes else 0,
        "ingreso_total": round(float(ingreso_total), 2),
        "ingreso_vip": round(float(ingreso_vip), 2),
        "concentracion_ingreso_vip_pct": round(100 * concentracion, 2),
        "vips_en_fuga": int(vips_fuga),
        "tasa_fuga_vip_pct": round(100 * vips_fuga / vips, 2) if vips else 0,
        "recencia_media_dias": round(float(rec_media), 1),
        "frecuencia_media_tickets": round(float(frec_media), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corte",
        default="2026-07-01",
        help="Fecha de corte: solo se usan transacciones anteriores. Por defecto, fin del histórico.",
    )
    args = parser.parse_args()

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET temp_directory='{(ROOT / 'data' / '.duckdb_tmp').as_posix()}'")
    # DuckDB autoconfigura max_temp_directory_size a una fraccion del disco libre
    # y con el disco al 97% se queda en ~900 MiB, insuficiente para agregar 72M
    # filas. Se fija explicitamente dentro de lo que queda disponible.
    con.execute("SET max_temp_directory_size='6GB'")
    # Menos hilos = menos particiones de hash simultaneas en memoria. Se cambia
    # velocidad por no desbordar, que es la restriccion real de esta maquina.
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")

    print(f"Calculando RFM con corte en {args.corte} ...")
    construir_rfm(con, args.corte)

    destino = SALIDA / f"corte={args.corte}"
    destino.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY rfm TO '{(destino / 'rfm.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)"
    )

    metricas = resumen(con, args.corte)
    (ARTIFACTS / f"rfm_resumen_{args.corte}.json").write_text(
        json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n--- Segmentacion ---")
    for k, v in metricas.items():
        print(f"  {k:32} {v:,}" if isinstance(v, (int, float)) else f"  {k:32} {v}")

    print(
        f"\nPremisa del negocio: el {metricas['pct_vip']}% de clientes VIP concentra "
        f"el {metricas['concentracion_ingreso_vip_pct']}% del ingreso."
    )


if __name__ == "__main__":
    main()
