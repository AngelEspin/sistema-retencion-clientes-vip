"""Genera un PDF grafico que explica como funciona todo el proyecto.

Uso:
    python generar_diagrama.py            # genera el PDF
    python generar_diagrama.py --abrir    # genera y abre el PDF
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
SALIDA = ROOT / "diagrama_arquitectura.pdf"
PNG = ROOT / "diagrama_arquitectura.png"

# ---------------------------------------------------------------------------
# Paleta y estilos
# ---------------------------------------------------------------------------
AZUL = "#2563eb"
AZUL_OSCURO = "#1e3a8a"
VERDE = "#16a34a"
ROJO = "#dc2626"
AMBAR = "#d97706"
GRIS = "#64748b"
FONDO = "#f8fafc"
CELESTE = "#0ea5e9"
BLANCO = "#ffffff"

AZUL_SUAVE = "#eff6ff"
VERDE_SUAVE = "#dcfce7"
ROJO_SUAVE = "#fee2e2"
AMBAR_SUAVE = "#fef3c7"


def caja(ax, x, y, w, h, titulo, texto, color_borde, color_fondo, tam_titulo=13, tam_texto=8.5, texto_color="#1e293b", titulo_color="white"):
    """Dibuja una caja con titulo (fondo color) y cuerpo (texto pequeno)."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.6,rounding_size=0.08",
            linewidth=1.5,
            edgecolor=color_borde,
            facecolor=color_fondo,
            zorder=3,
        )
    )
    # Titulo en barra superior
    ax.add_patch(
        Rectangle((x, y + h - 0.3), w, 0.3,
                  facecolor=color_borde, edgecolor="none", zorder=4)
    )
    ax.text(x + w / 2, y + h - 0.15, titulo,
            ha="center", va="center", fontsize=tam_titulo,
            fontweight="bold", color=titulo_color, zorder=5)
    # Cuerpo
    ax.text(x + w / 2, y + h / 2 - 0.1, texto,
            ha="center", va="center", fontsize=tam_texto,
            color=texto_color, zorder=5, linespacing=1.5)


def flecha(ax, x1, y1, x2, y2, color=GRIS, texto=None, tcol=GRIS, tfs=8, rad=0.0, estilo="-|>", ms=9, lw=1.6):
    """Flecha entre dos puntos con etiqueta opcional."""
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2),
            arrowstyle=estilo, mutation_scale=ms,
            linewidth=lw, color=color,
            connectionstyle=f"arc3,rad={rad}",
            zorder=2, shrinkA=1, shrinkB=1,
        )
    )
    if texto:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.03, texto,
                ha="center", va="center", fontsize=tfs,
                color=tcol, style="italic", zorder=6)


def chip_aws(ax, x, y, w=2.1, h=0.5, texto="", y_extra=0.35):
    """Etiqueta AWS amarilla encima de una caja."""
    ax.add_patch(
        FancyBboxPatch((x, y, w, h), boxstyle="round,pad=0.15",
                       linewidth=1.2, edgecolor="#ff9900",
                       facecolor="#fff7ed", zorder=6)
    )
    ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center",
            fontsize=8.5, fontweight="bold", color="#7c2d12", zorder=7)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abrir", action="store_true", help="Abrir el PDF al generarlo.")
    args = parser.parse_args()

    fig, ax = plt.subplots(figsize=(20, 15))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 15)
    ax.axis("off")
    fig.patch.set_facecolor(FONDO)

    # ------------------------------------------------------------------
    # ENCABEZADO
    # ------------------------------------------------------------------
    ax.add_patch(Rectangle((0, 14.0), 20, 1.0, facecolor=AZUL_OSCURO, edgecolor="none", zorder=2))
    ax.text(10, 14.5, "Sistema Multiagente de Segmentacion de Clientes y Optimizacion de Retencion",
            ha="center", va="center", fontsize=17, fontweight="bold", color="white", zorder=3)
    ax.text(10, 14.05, "Simulador que estima el impacto comercial de una campana de retencion ANTES de ejecutar el presupuesto",
            ha="center", va="center", fontsize=10, color="#dbeafe", zorder=3)

    # ------------------------------------------------------------------
    # FILA 1: PROBLEMA DE NEGOCIO
    # ------------------------------------------------------------------
    caja(ax, 0.5, 12.3, 4.2, 1.2, "El problema",
         "70-80% del ingreso depende\ndel 20% de clientes VIP\npero la retencion se decide por intuicion",
         AZUL, AZUL_SUAVE)
    caja(ax, 5.3, 12.3, 4.2, 1.2, "Pregunta que responde",
         "CuanTO presupuesto hace falta,\ny A QUIEN dirigirlo, para\nmover realmente la aguja",
         CELESTE, "#f0f9ff")
    caja(ax, 10.0, 12.3, 4.5, 1.2, "Datos reales",
         "72.5M transacciones (22.2 GB)\n3.1M clientes · 682 sucursales\n12 meses: 2025-07 a 2026-06",
         VERDE, VERDE_SUAVE)
    caja(ax, 15.1, 12.3, 4.4, 1.2, "Resultado medido",
         "Los VIP concentran 82.63%\ndel ingreso · AUC 0.874\ntiempo de escenario: 1-3 s",
         ROJO, ROJO_SUAVE, titulo_color="white")

    # ------------------------------------------------------------------
    # FLECHA hacia el pipeline
    # ------------------------------------------------------------------
    flecha(ax, 10, 12.25, 10, 11.55, color=GRIS, texto="pipeline de datos", tfs=9, lw=2)

    # ------------------------------------------------------------------
    # FILA 2: PIPELINE DE DATOS
    # ------------------------------------------------------------------
    # 1. Ingesta
    caja(ax, 0.5, 10.0, 4.4, 1.4, "1. Ingesta", "DuckDB en streaming\nCSV 22.2 GB -> Parquet 1.25 GB\nproyeccion 40 -> 11 columnas\nparticion (marca, anio_mes)\ncompresion 17.8x",
         AZUL_OSCURO, AZUL_SUAVE, titulo_color="white")
    # 2. RFM
    caja(ax, 5.4, 10.0, 4.4, 1.4, "2. Segmentacion RFM", "Recencia · Frecuencia · Monetario\nVIP = top 20% por valor\numbral USD 75.58\nconcentracion 82.63%",
         AZUL, AZUL_SUAVE)
    # 3. Modelo churn
    caja(ax, 10.3, 10.0, 4.5, 1.4, "3. Modelo de abandono", "validacion temporal (no aleatoria)\nAUC 0.8743 · AP 0.66\ncaptura decil superior 40.11%\ncada VIP con su prob. de fuga",
         CELESTE, "#f0f9ff")
    # 4. Simulador
    caja(ax, 15.3, 10.0, 4.2, 1.4, "4. Simulador multiagente", "538,983 agentes VIP\ncada uno con riesgo y gasto\ncontrafactual: control vs tratamiento",
         VERDE, VERDE_SUAVE, titulo_color="white")

    # flechas horizontales (chevron)
    for x1, x2 in [(4.9, 5.4), (9.8, 10.3), (14.8, 15.3)]:
        flecha(ax, x1, 10.7, x2, 10.7, color=GRIS, estilo="-|>", ms=12, lw=2)

    # ------------------------------------------------------------------
    # FLECHA del pipeline al simulador en detalle
    # ------------------------------------------------------------------
    flecha(ax, 17.4, 9.95, 17.4, 8.55, color=VERDE, texto="el simulador decide", tfs=9, lw=2)

    # ------------------------------------------------------------------
    # FILA 3: COMO FUNCIONA EL SIMULADOR (detalle central)
    # ------------------------------------------------------------------
    caja(ax, 12.0, 7.4, 5.5, 1.4, "Presupuesto fijo", "se reparten promos por cliente\ncriterio: valor en riesgo (prob x gasto)\ncompromiso: alcance vs intensidad\ninsistir mas = llegar a menos gente",
         AMBAR, AMBAR_SUAVE)
    caja(ax, 5.4, 7.4, 5.0, 1.4, "Saturacion de promociones", "a la 3ra promo el cliente se satura\ny su respuesta cae a CERO\nRSI colapsa a 0.00\nES EL HALLAZGO CENTRAL",
         ROJO, ROJO_SUAVE, titulo_color="white")

    #      | simulador
    # 5.4  o---> criterio
    flecha(ax, 6.0, 7.95, 6.0, 8.95, color=GRIS, rad=0.2, tfs=0)
    # de la caja de saturacion subimos
    flecha(ax, 6, 8.95, 6, 9.95, color=GRIS, lw=1.4, tfs=0)

    # detalle del efecto acumulado (grafico mini)
    # tabla de ROI por promociones
    datos_promos = [
        ("1 promo", "20.64", VERDE),
        ("2 promos", "20.70", VERDE),
        ("3 promos", "0.00", ROJO),
        ("4 promos", "0.00", ROJO),
    ]
    x0, y0 = 0.8, 7.3
    ax.add_patch(Rectangle((x0, y0), 3.8, 1.8, facecolor="white", edgecolor=GRIS, lw=1.2, zorder=3, fill=True, alpha=0.0))
    ax.text(x0 + 1.9, y0 + 1.55, "ROI por insistencia (USD 5.000)", ha="center",
            fontsize=9, fontweight="bold", color=GRIS, zorder=4)
    for i, (nombre, roi, color) in enumerate(datos_promos):
        yy = y0 + 1.15 - i * 0.38
        ax.text(x0 + 0.3, yy, nombre, ha="left", va="center", fontsize=8, color="#334155", zorder=4)
        ax.text(x0 + 3.5, yy, roi, ha="right", va="center", fontsize=8,
                fontweight="bold", color=color, zorder=4)
    ax.text(x0 + 1.9, y0 + 0.28, "el desplome a 0 es la tesis", ha="center",
            fontsize=7.5, color=ROJO, style="italic", zorder=4)

    # ------------------------------------------------------------------
    # FLECHA del simulador hacia la API
    # ------------------------------------------------------------------
    flecha(ax, 5, 7.0, 5, 5.85, color=CELESTE, texto="resultados por agente", tfs=8.5, lw=2)

    # ------------------------------------------------------------------
    # FILA 4: CONSUMO
    # ------------------------------------------------------------------
    caja(ax, 0.5, 3.3, 4.2, 2.0, "5. API FastAPI (local)", "endpoint /v1/simular, /v1/barrido\n/etc · dashboard interactivo en la raiz\nrespuesta en 1-3 s\npoblacion cacheada en arranque",
         AZUL, AZUL_SUAVE, titulo_color="white")

    # modulo central que describe los dos caminos
    # via local
    flecha(ax, 5, 4.35, 4.7, 4.35, color=AZUL, tfs=0)
    # via aws
    caja(ax, 11.5, 3.0, 8.0, 2.3, "6. AWS Lambda + S3 (serverless)", "MISMO modulo simulacion importado en lambda_handler\npoblacion descargada de S3 y cacheada en arranque en frio\nuso esporadico -> coste cero en reposo\ninvocable por SDK/IAM o Function URL",
         color_borde="#ff9900", color_fondo="#fff7ed", titulo_color="#ff9900", texto_color="#7c2d12")

    # flecha de la API local -> AWS (misma logica)
    flecha(ax, 9.2, 4.35, 11.5, 4.35, color="#ff9900",
          texto="misma logica, sin servidor 24/7", tcol="#7c2d12", tfs=8.5, lw=2)

    # ------------------------------------------------------------------
    # FILA 5: FRONTERA DE NEGOCIO (resultado)
    # ------------------------------------------------------------------
    caja(ax, 0.5, 0.8, 6.4, 1.9, "Decision de negocio", "Presupuesto minimo para -15% de fuga:\nUSD 250,000 (cobertura 19.3%, ROI 3.79)\nCon USD 5.000 solo se alcanza el 0.39% de VIP",
         VERDE, VERDE_SUAVE, titulo_color="white")
    caja(ax, 7.4, 0.8, 5.8, 1.9, "Utilidad", "Comparar alternativas ANTES de gastar\njustificar presupuesto ante la gerencia\nmedir rendimientos marginales decrecientes",
         AZUL, AZUL_SUAVE, titulo_color="white")
    caja(ax, 13.7, 0.8, 5.8, 1.9, "Siguiente paso", "Piloto en modo sombra para calibrar\nEFECTO_PROMO (hoy es supuesto 0.35)\nbacktest vs campanas reales\ncontrol room de deriva (PSI)",
         ROJO, ROJO_SUAVE, titulo_color="white")

    # flechas finales
    flecha(ax, 5, 3.25, 5, 2.7, color=VERDE, tfs=0)
    flecha(ax, 15.5, 2.95, 15.5, 2.7, color=ROJO, tfs=0)

    # pie
    ax.text(10, 0.35, "Proyecto de maestria en Ciencia de Datos - ESPOL  |  Carlos Ramirez  &  Angel Espin  |  datos seudonimizados (LOPDP)",
            ha="center", va="center", fontsize=8.5, color=GRIS, zorder=3)

    plt.tight_layout(pad=0.4)
    fig.savefig(SALIDA, bbox_inches="tight", facecolor=FONDO)
    fig.savefig(PNG, bbox_inches="tight", facecolor=FONDO, dpi=150)
    print(f"PDF generado: {SALIDA}")
    print(f"PNG generado: {PNG}")
    if args.abrir:
        import os
        os.startfile(str(SALIDA))


if __name__ == "__main__":
    main()
