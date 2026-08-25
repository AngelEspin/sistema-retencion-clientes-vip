"""Ingesta: CSV crudo (22 GB) -> Parquet particionado y seudonimizado.

Reproduce localmente el tramo que en produccion hace DMS CDC + Glue:
lee el historial transaccional en streaming, se queda solo con las columnas
que el negocio necesita, aplica la regla de privacidad y escribe Parquet
particionado por marca y mes.

Decisiones de diseno:
  * DuckDB en modo out-of-core: el CSV nunca entra completo en memoria.
  * Proyeccion temprana de columnas (40 -> 11): el grueso del ahorro de disco.
  * Particion (marca, anio_mes): es lo que despues permite que Athena y las
    consultas locales lean solo el trozo que necesitan.
  * Seudonimizacion: se conserva el ID ya anonimizado del origen y se
    descartan las columnas de costo/contabilidad que no alimentan el modelo.
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATOS = ROOT / "Datos"
DESTINO = ROOT / "data" / "processed" / "ventas"

VENTAS_CSV = DATOS / "ventas_anonimizado-001.csv"
SUCURSALES_CSV = DATOS / "sucursales_anonimizado.csv"

# Presupuesto de memoria deliberadamente bajo: la maquina tiene el disco al 96%
# y DuckDB debe preferir spill controlado antes que agotar RAM.
MEMORY_LIMIT = "10GB"


def construir_consulta() -> str:
    """SELECT que proyecta, limpia y enriquece las ventas.

    Se hace un LEFT JOIN con sucursales para traer la marca, que es una de las
    dos claves de particion. El join es barato: sucursales cabe en memoria.
    """
    return f"""
    WITH sucursales AS (
        SELECT
            Sucursal          AS sucursal_id,
            marca             AS marca,
            Provincia         AS provincia,
            Region            AS region,
            formato_farmacia  AS formato
        FROM read_csv(
            '{SUCURSALES_CSV.as_posix()}',
            header=true, delim=',', quote='"',
            strict_mode=false, null_padding=true, ignore_errors=true,
            all_varchar=true
        )
    ),
    ventas AS (
        SELECT
            cli_cedula                          AS cliente_id,
            CAST(p_fecha AS TIMESTAMP)           AS fecha,
            -- OJO: la clave de sucursal es s_nombre (formato 'SUC_0491'), no
            -- s_id, que es un entero interno del POS sin correspondencia en el
            -- maestro de sucursales.
            s_nombre                             AS sucursal_id,
            pt_code                              AS producto_id,
            p_numero                             AS ticket_id,
            TRY_CAST(p_cantidad AS DOUBLE)       AS cantidad,
            TRY_CAST(p_subtotal AS DOUBLE)       AS venta_neta,
            TRY_CAST(p_descuento AS DOUBLE)      AS descuento,
            id_promocion                         AS promocion_id,
            tipo_promocion                       AS promocion_tipo
        FROM read_csv(
            '{VENTAS_CSV.as_posix()}',
            header=true,
            delim=',',
            quote='"',
            escape='"',
            -- El origen trae filas que no cumplen el estandar (nombres de
            -- producto con comas y comillas sueltas). strict_mode=false mas
            -- null_padding evita abortar la corrida por esas filas.
            strict_mode=false,
            null_padding=true,
            ignore_errors=true,
            all_varchar=true
        )
        -- Regla de calidad: sin cliente no hay segmentacion posible, y una
        -- fecha invalida contamina la particion. Se descartan en origen.
        WHERE cli_cedula IS NOT NULL
          AND cli_cedula <> ''
          AND TRY_CAST(p_fecha AS TIMESTAMP) IS NOT NULL
    )
    SELECT
        v.cliente_id,
        v.fecha,
        v.sucursal_id,
        v.producto_id,
        v.ticket_id,
        v.cantidad,
        v.venta_neta,
        v.descuento,
        v.promocion_id,
        v.promocion_tipo,
        COALESCE(s.provincia, 'DESCONOCIDA') AS provincia,
        COALESCE(s.region, 'DESCONOCIDA')    AS region,
        COALESCE(s.formato, 'DESCONOCIDO')   AS formato,
        COALESCE(s.marca, 'SIN_MARCA')       AS marca,
        strftime(v.fecha, '%Y-%m')           AS anio_mes
    FROM ventas v
    LEFT JOIN sucursales s USING (sucursal_id)
    """


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Procesar solo N filas (para validar el pipeline antes de la corrida completa).",
    )
    args = parser.parse_args()

    if not VENTAS_CSV.exists():
        raise SystemExit(f"No se encontro el CSV de ventas: {VENTAS_CSV}")

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = ROOT / "data" / ".duckdb_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory='{temp_dir.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")

    consulta = construir_consulta()
    if args.limite:
        consulta += f"\n    LIMIT {args.limite}"

    destino = DESTINO if not args.limite else DESTINO.with_name("ventas_muestra")

    print(f"Origen : {VENTAS_CSV}  ({VENTAS_CSV.stat().st_size / 1e9:.1f} GB)")
    print(f"Destino: {destino}")
    print(f"Modo   : {'MUESTRA de ' + str(args.limite) + ' filas' if args.limite else 'COMPLETO'}")

    # OVERWRITE_OR_IGNORE conserva las particiones antiguas y las mezcla con las
    # nuevas, lo que produce conteos inflados entre corridas. Se limpia el
    # destino explicitamente para que cada corrida sea reproducible.
    if destino.exists():
        shutil.rmtree(destino)

    inicio = time.time()
    con.execute(
        f"""
        COPY ({consulta})
        TO '{destino.as_posix()}'
        (FORMAT PARQUET,
         PARTITION_BY (marca, anio_mes),
         COMPRESSION zstd,
         OVERWRITE true)
        """
    )
    minutos = (time.time() - inicio) / 60

    filas = con.execute(
        f"SELECT count(*) FROM read_parquet('{destino.as_posix()}/**/*.parquet')"
    ).fetchone()[0]
    tam = sum(f.stat().st_size for f in destino.rglob("*.parquet")) / 1e9

    print(f"\nFilas escritas : {filas:,}")
    print(f"Tamano Parquet : {tam:.2f} GB")
    print(f"Compresion     : {VENTAS_CSV.stat().st_size / 1e9 / max(tam, 0.001):.1f}x")
    print(f"Duracion       : {minutos:.1f} min")


if __name__ == "__main__":
    main()
