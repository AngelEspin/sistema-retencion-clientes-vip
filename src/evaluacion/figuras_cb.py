"""Figuras del analisis costo/beneficio (PNG para el PDF del entregable).

Convenciones: lineas de 2 pt, grilla tenue y continua, texto en tinta neutra
(nunca en el color de la serie), leyenda mas etiquetas directas selectivas. Los
escenarios llevan siempre el mismo color en todas las figuras.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SUPERFICIE = "#ffffff"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRILLA = "#e6e5e1"
CERO = "#9a9893"
COLOR = {"pesimista": "#eb6834", "realista": "#2a78d6", "optimista": "#1baf7a"}
LADO = {"pesimista": "#e34948", "optimista": "#2a78d6"}
NOMBRE = {"pesimista": "Pesimista", "realista": "Realista", "optimista": "Optimista"}

plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 9,
    "axes.edgecolor": GRILLA,
    "axes.labelcolor": TINTA_2,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": TINTA,
    "xtick.color": TINTA_2,
    "ytick.color": TINTA_2,
    "axes.grid": True,
    "grid.color": GRILLA,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE,
    "legend.frameon": False,
})


def _miles(x: float, _pos=None) -> str:
    if x == 0:
        return "0"
    if abs(x) >= 1_000_000:
        return f"{x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{x / 1e3:,.0f} k".replace(",", ".")


def _usd(x: float) -> str:
    return "USD " + f"{x:,.0f}".replace(",", ".")


def flujo_acumulado(salida: dict, destino: Path) -> None:
    """Pequenos multiplos: las escalas de los tres escenarios difieren en dos ordenes."""
    fig, ejes = plt.subplots(1, 3, figsize=(9.2, 3.0), sharex=True)
    for eje, nombre in zip(ejes, ("pesimista", "realista", "optimista")):
        ind = salida["escenarios"][nombre]["indicadores"]
        acumulado = ind["acumulado"]
        meses = list(range(len(acumulado)))
        eje.axhline(0, color=CERO, linewidth=0.9, zorder=1)
        eje.plot(meses, acumulado, color=COLOR[nombre], linewidth=2.0, solid_capstyle="round", zorder=3)
        eje.fill_between(meses, acumulado, 0, color=COLOR[nombre], alpha=0.10, linewidth=0, zorder=2)
        eje.yaxis.set_major_formatter(FuncFormatter(_miles))
        eje.set_title(NOMBRE[nombre], loc="left")
        eje.set_xticks([0, 6, 12, 18, 24, 30, 36])
        eje.set_xlabel("Mes")
        pb = ind["payback_meses"]
        if pb is not None:
            y_pb = 0
            eje.scatter([pb], [y_pb], s=36, color=COLOR[nombre], edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
            eje.annotate(f"recupera en el mes {pb:.1f}".replace(".", ","), (pb, y_pb), xytext=(6, 10),
                         textcoords="offset points", color=TINTA, fontsize=8.5)
        else:
            eje.annotate("no recupera la inversión", (36, acumulado[-1]), xytext=(-4, 10),
                         textcoords="offset points", ha="right", color=TINTA, fontsize=8.5)
        eje.annotate(f"VPN {_usd(ind['vpn'])}", (0.02, 0.97), xycoords="axes fraction", va="top",
                     color=TINTA_2, fontsize=8.5)
    ejes[0].set_ylabel("Flujo neto acumulado (USD)")
    fig.tight_layout(w_pad=1.6)
    fig.savefig(destino, dpi=220)
    plt.close(fig)


def tornado(salida: dict, destino: Path) -> None:
    filas = salida["tornado"]
    base = salida["escenarios"]["realista"]["indicadores"]["vpn"]
    fig, eje = plt.subplots(figsize=(9.2, 3.6))
    ys = list(range(len(filas)))[::-1]
    for y, fila in zip(ys, filas):
        for lado in ("pesimista", "optimista"):
            v = fila[f"vpn_{lado}"]
            eje.barh(y, v - base, left=base, height=0.55, color=LADO[lado], zorder=3,
                     label=f"Supuesto en su valor {lado}" if y == ys[0] else None)
    eje.axvline(base, color=TINTA_2, linewidth=1.0, zorder=4)
    eje.set_yticks(ys, [f["variable"] for f in filas])
    eje.xaxis.set_major_formatter(FuncFormatter(_miles))
    eje.set_xlabel("VPN a 3 años (USD)")
    eje.grid(axis="y", visible=False)
    eje.tick_params(axis="y", length=0)
    # Etiquetas solo en las tres variables que mas mueven el resultado.
    for y, fila in list(zip(ys, filas))[:3]:
        for lado, ha, dx in (("pesimista", "right", -4), ("optimista", "left", 4)):
            v = fila[f"vpn_{lado}"]
            if abs(v - base) < 1:
                continue  # el supuesto no cambia en ese lado: no hay barra que rotular
            eje.annotate(_usd(v), (v, y), xytext=(dx, 0), textcoords="offset points", ha=ha,
                         va="center", color=TINTA, fontsize=8)
    eje.annotate(f"escenario realista: {_usd(base)}", (base, ys[0] + 0.62), ha="center", va="bottom",
                 color=TINTA_2, fontsize=8, annotation_clip=False)
    eje.legend(loc="lower right", fontsize=8.5)
    lo = min(min(f["vpn_pesimista"], f["vpn_optimista"]) for f in filas)
    hi = max(max(f["vpn_pesimista"], f["vpn_optimista"]) for f in filas)
    margen = (hi - lo) * 0.18
    eje.set_xlim(lo - margen, hi + margen)
    fig.tight_layout()
    fig.savefig(destino, dpi=220)
    plt.close(fig)


def economia_campana(salida: dict, destino: Path) -> None:
    fig, eje = plt.subplots(figsize=(9.2, 3.4))
    ref = salida["presupuesto_referencia"]
    eje.axhline(0, color=CERO, linewidth=0.9, zorder=1)
    eje.axvline(ref, color=TINTA_2, linewidth=0.9, zorder=1)
    eje.annotate(f"presupuesto para la meta de −15%\n(efecto del guion): {_usd(ref)}", (ref, 0.04),
                 xycoords=("data", "axes fraction"), xytext=(5, 0), textcoords="offset points",
                 va="bottom", color=TINTA_2, fontsize=8)
    for nombre in ("pesimista", "realista", "optimista"):
        c = salida["campana"][nombre]
        xs = [p["presupuesto"] for p in c["curva"]]
        ys = [p["neto"] for p in c["curva"]]
        etiqueta = f"{NOMBRE[nombre]} (efecto base {c['efecto']:.2f})".replace(".", ",")
        eje.plot(xs, ys, color=COLOR[nombre], linewidth=2.0, label=etiqueta, zorder=3)
        # El optimo pesimista cae practicamente en cero (no invertir): se rotula
        # solo en la tabla. El realista se separa con una guia para no chocar.
        if c["neto_optimo"] > 0 and nombre != "pesimista":
            eje.scatter([c["presupuesto_optimo"]], [c["neto_optimo"]], s=36, color=COLOR[nombre],
                        edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
            desplazamiento = (6, 6) if nombre == "optimista" else (40, 34)
            eje.annotate(f"óptimo: {_usd(c['presupuesto_optimo'])}", (c["presupuesto_optimo"], c["neto_optimo"]),
                         xytext=desplazamiento, textcoords="offset points", color=TINTA, fontsize=8,
                         arrowprops=None if nombre == "optimista" else
                         {"arrowstyle": "-", "color": TINTA_2, "linewidth": 0.7, "shrinkA": 0, "shrinkB": 4})
    eje.xaxis.set_major_formatter(FuncFormatter(_miles))
    eje.yaxis.set_major_formatter(FuncFormatter(_miles))
    eje.set_xlabel("Presupuesto de campaña por trimestre (USD)")
    eje.set_ylabel("Margen incremental − gasto (USD)")
    eje.legend(loc="lower left", fontsize=8.5)
    eje.set_xlim(-5_000, 305_000)
    fig.tight_layout()
    fig.savefig(destino, dpi=220)
    plt.close(fig)


def generar(salida: dict, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    flujo_acumulado(salida, carpeta / "flujo_acumulado.png")
    tornado(salida, carpeta / "tornado_vpn.png")
    economia_campana(salida, carpeta / "economia_campana.png")
    print(f"Figuras en {carpeta}")
