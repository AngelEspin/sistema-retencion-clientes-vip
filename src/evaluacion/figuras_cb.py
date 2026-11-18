"""Figuras del analisis costo/beneficio (PNG para el PDF del entregable).

Convenciones: lineas de 2 pt, grilla tenue y continua, texto en tinta neutra
(nunca en el color de la serie), leyenda mas etiquetas directas selectivas. Los
escenarios llevan siempre el mismo color en todas las figuras; lo que no es un
escenario usa grises o la paleta de capas, para no confundir identidades.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

SUPERFICIE = "#ffffff"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRILLA = "#e6e5e1"
CERO = "#9a9893"
NEUTRO = "#b3b1aa"            # marcas de referencia
COLOR = {"pesimista": "#eb6834", "realista": "#2a78d6", "optimista": "#1baf7a"}
LADO = {"pesimista": "#e34948", "optimista": "#2a78d6"}
NOMBRE = {"pesimista": "Pesimista", "realista": "Realista", "optimista": "Optimista"}
# Capas del costo.
CAPA = {"Desarrollo": "#4a3aa7", "Operación": "#e87ba4", "Ocultos": "#eda100"}

# Referencias de campo para el efecto de una campana de retencion (reduccion
# relativa de la fuga entre tratados). Ascarza (2018), JMR 55(1), estudio 1.
LITERATURA = (
    ("Ascarza (2018): decil de mayor riesgo", 100 * 1.6 / 95.3),
    ("Ascarza (2018): mejor decil por riesgo", 100 * 2.9 / 71.2),
    ("Ascarza (2018): mejor decil por sensibilidad", 100 * 9.2 / 57.0),
)

plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 10,
    "axes.edgecolor": GRILLA,
    "axes.labelcolor": TINTA_2,
    "axes.titlesize": 11,
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


def _num(x: float, dec: int = 0) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _miles(x: float, _pos=None) -> str:
    if x == 0:
        return "0"
    if abs(x) >= 1_000_000:
        return f"{x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{x / 1e3:,.0f} k".replace(",", ".")


def _usd(x: float) -> str:
    return ("−" if x < 0 else "") + "USD " + f"{abs(x):,.0f}".replace(",", ".")


def _usd_k(x: float) -> str:
    return "USD " + _num(x / 1e3, 1) + " k"


def _pct_eje(dec: int = 0):
    return FuncFormatter(lambda v, _p: _num(v, dec) + "%")


def _guardar(fig, destino: Path) -> None:
    fig.savefig(destino, dpi=220)
    plt.close(fig)


# --- Seccion 2: premisa del proyecto ---------------------------------------------
def concentracion_ingreso(salida: dict, destino: Path) -> None:
    lor = salida["graficos"]["lorenz"]
    x = [100 * v for v in lor["x"]]
    y = [100 * v for v in lor["y"]]
    top20 = y[20]
    fig, eje = plt.subplots(figsize=(6.4, 3.0))
    eje.plot([0, 100], [0, 100], color=NEUTRO, linewidth=1.0, zorder=2)
    eje.plot(x, y, color=COLOR["realista"], linewidth=2.0, zorder=3)
    eje.fill_between(x, y, x, color=COLOR["realista"], alpha=0.10, linewidth=0, zorder=1)
    eje.scatter([20], [top20], s=36, color=COLOR["realista"], edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
    eje.annotate(f"el 20% de los clientes (VIP)\nconcentra el {_num(top20, 1)}% del ingreso", (20, top20),
                 xytext=(14, -34), textcoords="offset points", color=TINTA, fontsize=9.5,
                 arrowprops={"arrowstyle": "-", "color": TINTA_2, "linewidth": 0.7, "shrinkA": 0, "shrinkB": 4})
    eje.annotate("reparto igualitario", (62, 62), xytext=(4, -12), textcoords="offset points",
                 color=TINTA_2, fontsize=9, rotation=27)
    eje.set_xlim(0, 100)
    eje.set_ylim(0, 102)
    eje.xaxis.set_major_formatter(_pct_eje())
    eje.yaxis.set_major_formatter(_pct_eje())
    eje.set_xlabel(f"Clientes ordenados de mayor a menor gasto ({_num(lor['clientes'])} en total)")
    eje.set_ylabel("Ingreso acumulado")
    fig.tight_layout()
    _guardar(fig, destino)


# --- Seccion 3: costos ---------------------------------------------------------------
def tco_capas(salida: dict, destino: Path) -> None:
    fig, eje = plt.subplots(figsize=(9.2, 2.5))
    filas = ("optimista", "realista", "pesimista")
    for y, nombre in enumerate(filas):
        cc = salida["escenarios"][nombre]["costos"]
        partes = {
            "Desarrollo": cc["total_desarrollo"],
            "Operación": 36 * cc["total_operacion_mes"],
            "Ocultos": cc["total_ocultos_unica"] + 36 * cc["total_ocultos_mes"],
        }
        total = sum(partes.values())
        izquierda = 0.0
        for capa, valor in partes.items():
            eje.barh(y, valor, left=izquierda, height=0.56, color=CAPA[capa], edgecolor=SUPERFICIE,
                     linewidth=1.5, zorder=3, label=capa if y == 0 else None)
            # Etiqueta interior solo si el tramo tiene ancho suficiente (~3 k en el eje de 75 k).
            if valor > 3_000:
                eje.text(izquierda + valor / 2, y, f"{_num(100 * valor / total)}%", ha="center", va="center",
                         color="white" if capa == "Desarrollo" else TINTA, fontsize=9)
            izquierda += valor
        eje.text(total, y, f"  {_usd(total)}", ha="left", va="center", color=TINTA, fontsize=9.5)
    eje.set_yticks(range(len(filas)), [NOMBRE[f] for f in filas])
    eje.tick_params(axis="y", length=0)
    eje.grid(axis="y", visible=False)
    eje.xaxis.set_major_formatter(FuncFormatter(_miles))
    eje.set_xlabel("Costo total de propiedad a 3 años (USD)")
    eje.set_xlim(0, 75_000)
    eje.legend(loc="lower right", ncol=3, fontsize=9.5, bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    _guardar(fig, destino)


# --- Seccion 4: beneficios ------------------------------------------------------------
def politicas_saturacion(salida: dict, destino: Path) -> None:
    g = salida["graficos"]
    ref = salida["presupuesto_referencia"]
    fig, (izq, der) = plt.subplots(1, 2, figsize=(9.2, 3.3), gridspec_kw={"width_ratios": [1.55, 1]})

    pol = sorted(g["politicas_realista"], key=lambda p: p["margen_incremental_usd"])
    ys = range(len(pol))
    valores = [p["margen_incremental_usd"] for p in pol]
    desv = [p["margen_incremental_usd_sd"] for p in pol]
    colores = [COLOR["realista"] if p["criterio"] == "valor_en_riesgo" else NEUTRO for p in pol]
    izq.barh(list(ys), valores, xerr=desv, height=0.58, color=colores, zorder=3,
             error_kw={"ecolor": TINTA_2, "elinewidth": 0.8, "capsize": 2})
    for y, pol_i, v, s in zip(ys, pol, valores, desv):
        texto = (_usd_k(v) if v > 0 else
                 f"0: los {_num(pol_i['clientes_saturados'] / 1e3, 1)} mil clientes se saturan")
        izq.text(v + s + 900, y, texto, va="center", ha="left", color=TINTA, fontsize=9)
    izq.set_yticks(list(ys), [p["politica"] for p in pol])
    izq.tick_params(axis="y", length=0)
    izq.grid(axis="y", visible=False)
    izq.xaxis.set_major_formatter(FuncFormatter(_miles))
    izq.set_xlim(0, max(valores) * 1.28)
    izq.set_xlabel("Margen adicional por trimestre (USD)")
    izq.set_title(f"Con el mismo gasto ({_usd(ref)})", loc="left")

    sat = g["saturacion_realista"]
    xs = [s["promos"] for s in sat]
    vs = [s["margen_incremental_usd"] for s in sat]
    der.bar(xs, vs, width=0.6, color=COLOR["realista"], zorder=3)
    tope = max(vs)
    for s in sat:
        if s["margen_incremental_usd"] > 0:
            der.text(s["promos"], s["margen_incremental_usd"] + tope * 0.03, _usd_k(s["margen_incremental_usd"]),
                     ha="center", va="bottom", color=TINTA, fontsize=9)
        else:
            der.text(s["promos"], tope * 0.03, "0\n(satura)", ha="center", va="bottom", color=TINTA, fontsize=9)
    # El alcance va en el eje: con el mismo gasto, cada promocion extra por
    # cliente reduce cuantos clientes reciben la campana.
    der.set_xticks(xs, [f"{s['promos']}\n{_num(s['clientes_alcanzados'] / 1e3, 0)} mil" for s in sat])
    der.set_ylim(0, tope * 1.25)
    der.yaxis.set_major_formatter(FuncFormatter(_miles))
    der.axhline(0, color=CERO, linewidth=0.9, zorder=2)
    der.set_xlabel("Promociones por cliente\ny clientes alcanzados")
    der.set_title("Alcance frente a insistencia", loc="left")
    der.grid(axis="x", visible=False)
    fig.tight_layout(w_pad=2.0)
    _guardar(fig, destino)


def efecto_literatura(salida: dict, destino: Path) -> None:
    equiv = {round(e["efecto_base"], 2): e["reduccion_relativa_tratados_pct"]
             for e in salida["graficos_equivalencia"]}
    filas = [(etq, v, NEUTRO) for etq, v in LITERATURA]
    filas += [
        ("Escenario pesimista (efecto base 0,04)", equiv[0.04], COLOR["pesimista"]),
        ("Escenario realista (efecto base 0,10)", equiv[0.1], COLOR["realista"]),
        ("Escenario optimista = guion (0,35)", equiv[0.35], COLOR["optimista"]),
    ]
    fig, eje = plt.subplots(figsize=(9.2, 2.8))
    ys = list(range(len(filas)))[::-1]
    for y, (etq, v, color) in zip(ys, filas):
        eje.plot([0, v], [y, y], color=color, linewidth=2.0, solid_capstyle="round", zorder=2)
        eje.scatter([v], [y], s=46, color=color, edgecolor=SUPERFICIE, linewidth=1.6, zorder=3)
        eje.text(v + 0.8, y, f"{_num(v, 1)}%", va="center", ha="left", color=TINTA, fontsize=9.5)
    eje.axhline(2.5, color=GRILLA, linewidth=1.0)
    eje.set_yticks(ys, [f[0] for f in filas])
    eje.tick_params(axis="y", length=0)
    eje.grid(axis="y", visible=False)
    eje.set_xlim(0, 40)
    eje.xaxis.set_major_formatter(_pct_eje())
    eje.set_xlabel("Reducción relativa de la fuga entre los clientes tratados")
    fig.tight_layout()
    _guardar(fig, destino)


# --- Seccion 5: indicadores -------------------------------------------------------------
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
        # El VPN va como subtitulo a la derecha: fuera del area de datos no pisa la linea del cero.
        eje.set_title(f"VPN {_usd(ind['vpn'])}", loc="right", fontsize=9.5, fontweight="normal", color=TINTA_2)
        eje.set_xticks([0, 6, 12, 18, 24, 30, 36])
        eje.set_xlabel("Mes")
        pb = ind["payback_meses"]
        if pb is not None:
            # Rotulo por debajo de la recta, en la zona sombreada, con guia hasta el cruce.
            eje.scatter([pb], [0], s=36, color=COLOR[nombre], edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
            eje.annotate(f"recupera en el mes {_num(pb, 1)}", (pb, 0), xytext=(12, 0.09 * max(acumulado)),
                         textcoords="data", va="center", color=TINTA, fontsize=9.5,
                         arrowprops={"arrowstyle": "-", "color": TINTA_2, "linewidth": 0.7, "shrinkA": 2, "shrinkB": 4})
        else:
            eje.text(18, acumulado[-1] / 2, "no recupera la inversión", ha="center", va="center",
                     color=TINTA, fontsize=9.5)
    ejes[0].set_ylabel("Flujo neto acumulado (USD)")
    fig.tight_layout(w_pad=1.6)
    _guardar(fig, destino)


# --- Seccion 6: sensibilidad ------------------------------------------------------------
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
                         va="center", color=TINTA, fontsize=9)
    eje.annotate(f"escenario realista: {_usd(base)}", (base, ys[0] + 0.62), ha="center", va="bottom",
                 color=TINTA_2, fontsize=9, annotation_clip=False)
    eje.legend(loc="lower right", fontsize=9.5)
    lo = min(min(f["vpn_pesimista"], f["vpn_optimista"]) for f in filas)
    hi = max(max(f["vpn_pesimista"], f["vpn_optimista"]) for f in filas)
    margen = (hi - lo) * 0.22
    eje.set_xlim(lo - margen, hi + margen)
    fig.tight_layout()
    _guardar(fig, destino)


def vpn_efecto(salida: dict, destino: Path) -> None:
    grilla = salida["graficos"]["vpn_vs_efecto"]
    eq = salida["equilibrio_sistema"]
    xs = [g["efecto"] for g in grilla]
    fig, eje = plt.subplots(figsize=(9.2, 3.1))
    eje.axhline(0, color=CERO, linewidth=0.9, zorder=1)
    series = (("aleatorio", "Frente a la campaña masiva (línea base realista)", COLOR["realista"],
               eq["efecto_minimo_vpn0"]),
              ("recencia", "Frente a la regla de recencia (línea base pesimista)", COLOR["pesimista"],
               eq["efecto_minimo_vpn0_contra_recencia"]))
    for clave, etiqueta, color, equilibrio in series:
        eje.plot(xs, [g[clave] for g in grilla], color=color, linewidth=2.0, label=etiqueta, zorder=3)
        eje.scatter([equilibrio], [0], s=36, color=color, edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
    eje.text(0.02, 0.84, f"Los puntos marcan el equilibrio (VPN = 0): efecto de {_num(eq['efecto_minimo_vpn0'], 3)}\n"
                         f"frente a la campaña masiva y de {_num(eq['efecto_minimo_vpn0_contra_recencia'], 3)} frente a la recencia",
             transform=eje.transAxes, va="top", color=TINTA, fontsize=9.5, zorder=5,
             bbox={"boxstyle": "square,pad=0.25", "facecolor": SUPERFICIE, "edgecolor": "none"})
    alto = max(g["aleatorio"] for g in grilla)
    # Solo grilla horizontal: las verticales son los tres valores del efecto, punteadas
    # para no confundirse con la grilla.
    eje.grid(axis="x", visible=False)
    for efecto, nombre in ((0.04, "pesimista"), (0.10, "realista"), (0.35, "guion")):
        eje.axvline(efecto, color=NEUTRO, linewidth=1.0, linestyle=(0, (3, 3)), zorder=1)
        eje.text(efecto, alto * 1.04, nombre, ha="center", va="bottom", color=TINTA_2, fontsize=9, zorder=5,
                 bbox={"boxstyle": "square,pad=0.15", "facecolor": SUPERFICIE, "edgecolor": "none"})
    eje.set_xlim(0, 0.36)
    eje.set_ylim(top=alto * 1.15)
    eje.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: _num(v, 2)))
    eje.yaxis.set_major_formatter(FuncFormatter(_miles))
    eje.set_xlabel("Efecto base de una promoción")
    eje.set_ylabel("VPN del sistema a 3 años (USD)")
    fig.legend(*eje.get_legend_handles_labels(), loc="lower center", ncol=2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    _guardar(fig, destino)


# --- Seccion 7: rentabilidad de la campana ----------------------------------------------
def economia_campana(salida: dict, destino: Path) -> None:
    ref = salida["presupuesto_referencia"]
    fig, (izq, der) = plt.subplots(1, 2, figsize=(9.2, 3.7))
    for eje in (izq, der):
        eje.axvline(ref, color=TINTA_2, linewidth=0.9, zorder=1)
        eje.xaxis.set_major_formatter(FuncFormatter(_miles))
        eje.set_xlim(-5_000, 305_000)
        eje.set_xlabel("Presupuesto por trimestre (USD)")
    izq.axhline(0, color=CERO, linewidth=0.9, zorder=1)
    for nombre in ("pesimista", "realista", "optimista"):
        c = salida["campana"][nombre]
        xs = [p["presupuesto"] for p in c["curva"]]
        etiqueta = f"{NOMBRE[nombre]} (efecto {_num(c['efecto'], 2)})"
        izq.plot(xs, [p["neto"] for p in c["curva"]], color=COLOR[nombre], linewidth=2.0, label=etiqueta, zorder=3)
        der.plot(xs, [p["reduccion"] for p in c["curva"]], color=COLOR[nombre], linewidth=2.0, zorder=3)
        der.text(xs[-1] + 3_000, c["curva"][-1]["reduccion"], f"{_num(c['curva'][-1]['reduccion'], 1)}%",
                 va="center", ha="left", color=TINTA, fontsize=9)
        if c["neto_optimo"] > 0 and nombre == "optimista":
            izq.scatter([c["presupuesto_optimo"]], [c["neto_optimo"]], s=36, color=COLOR[nombre],
                        edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
            # Arriba a la izquierda del punto: a la derecha lo cruzaria la linea de referencia.
            izq.annotate(f"óptimo\n{_usd(c['presupuesto_optimo'])}", (c["presupuesto_optimo"], c["neto_optimo"]),
                         xytext=(-6, 8), textcoords="offset points", ha="right", va="bottom",
                         color=TINTA, fontsize=9)
    izq.yaxis.set_major_formatter(FuncFormatter(_miles))
    izq.set_ylabel("Margen adicional − gasto (USD)")
    izq.set_title("Beneficio neto de la campaña", loc="left")
    # Una sola leyenda para los dos paneles.
    fig.legend(*izq.get_legend_handles_labels(), loc="lower center", ncol=3, fontsize=9)
    izq.annotate(f"presupuesto de\nreferencia\n{_usd(ref)}", (ref, 0.03), xycoords=("data", "axes fraction"),
                 xytext=(4, 0), textcoords="offset points", va="bottom", color=TINTA_2, fontsize=8.5)
    izq.set_ylim(top=190_000)  # aire para el rotulo del optimo

    der.axhline(15, color=TINTA_2, linewidth=0.9, zorder=1)
    der.text(170_000, 15.6, "meta de la propuesta: −15%", color=TINTA_2, fontsize=9, va="bottom")
    der.yaxis.set_major_formatter(_pct_eje())
    der.set_ylim(0, max(p["reduccion"] for p in salida["campana"]["optimista"]["curva"]) + 4)
    der.set_xlim(-5_000, 335_000)
    der.set_ylabel("Reducción de la fuga VIP")
    der.set_title("Reducción de fuga lograda", loc="left")
    fig.tight_layout(w_pad=2.4, rect=(0, 0.08, 1, 1))
    _guardar(fig, destino)


# --- Seccion 9: validacion ------------------------------------------------------------------
def validacion_modelo(salida: dict, destino: Path) -> None:
    g = salida["graficos"]
    auc = salida["graficos_auc"]
    fig, (izq, der) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    izq.plot([0, 1], [0, 1], color=NEUTRO, linewidth=1.0, zorder=1)
    izq.plot(g["roc"]["recencia"]["fpr"], g["roc"]["recencia"]["tpr"], color=NEUTRO, linewidth=2.0,
             label=f"Regla de recencia (AUC {_num(auc['recencia'], 3)})", zorder=2)
    izq.plot(g["roc"]["modelo"]["fpr"], g["roc"]["modelo"]["tpr"], color=COLOR["realista"], linewidth=2.0,
             label=f"Modelo de abandono (AUC {_num(auc['modelo'], 3)})", zorder=3)
    izq.text(0.62, 0.52, "azar (AUC 0,5)", color=TINTA_2, fontsize=9, rotation=35)
    izq.set_xlim(0, 1)
    izq.set_ylim(0, 1.02)
    izq.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: _num(v, 1)))
    izq.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: _num(v, 1)))
    izq.set_xlabel("Tasa de falsos positivos")
    izq.set_ylabel("Tasa de verdaderos positivos")
    izq.set_title("Discriminación (T1 y T2)", loc="left")
    izq.legend(loc="lower right", fontsize=9)

    cal = g["calibracion"]
    pred = [100 * c["predicha"] for c in cal]
    obs = [100 * c["observada"] for c in cal]
    der.plot([0, 100], [0, 100], color=NEUTRO, linewidth=1.0, zorder=1)
    der.plot(pred, obs, color=COLOR["realista"], linewidth=2.0, zorder=2)
    der.scatter(pred, obs, s=36, color=COLOR["realista"], edgecolor=SUPERFICIE, linewidth=1.6, zorder=3)
    der.text(20, 31, "calibración perfecta", color=TINTA_2, fontsize=9, rotation=40)
    der.annotate(f"decil de mayor riesgo: {_num(pred[-1], 1)}% predicho,\n{_num(obs[-1], 1)}% observado",
                 (pred[-1], obs[-1]), xytext=(-150, 22), textcoords="offset points", color=TINTA, fontsize=9,
                 arrowprops={"arrowstyle": "-", "color": TINTA_2, "linewidth": 0.7, "shrinkA": 0, "shrinkB": 4})
    der.annotate(f"sesgo medio: +{_num(salida['graficos_sesgo_pp'], 2)} pp", (0.97, 0.05),
                 xycoords="axes fraction", ha="right", va="bottom", color=TINTA, fontsize=9.5)
    der.set_xlim(0, 100)
    der.set_ylim(0, 100)
    der.xaxis.set_major_formatter(_pct_eje())
    der.yaxis.set_major_formatter(_pct_eje())
    der.set_xlabel("Fuga predicha (promedio por decil)")
    der.set_ylabel("Fuga observada abr–jun 2026")
    der.set_title("Calibración por decil (T3)", loc="left")
    fig.tight_layout(w_pad=2.4)
    _guardar(fig, destino)


def potencia_piloto(salida: dict, destino: Path) -> None:
    mde = salida["validacion"]["mde"]
    equiv = {round(e["efecto_base"], 2): e["reduccion_relativa_tratados_pct"]
             for e in salida["graficos_equivalencia"]}
    # La potencia se calcula con la fuga OBSERVADA de la lista: el modelo la
    # sobreestima justo en los clientes que elige, y el control real tendra la observada.
    cal = salida["validacion"].get("calibracion_lista")
    p = cal["fuga_observada"] if cal else mde[0]["fuga_base"]
    tamanos = ((mde[2]["clientes_lista"], f"Una región ({_num(mde[2]['clientes_lista'])} clientes)", COLOR["realista"]),
               (mde[0]["clientes_lista"], f"Lista completa ({_num(mde[0]['clientes_lista'])} clientes)", NEUTRO))
    fracciones = [f / 100 for f in range(5, 51)]
    fig, eje = plt.subplots(figsize=(9.2, 3.0))
    for n, etiqueta, color in tamanos:
        curva = [100 * 2.80 * math.sqrt(p * (1 - p) * (1 / (n * (1 - h)) + 1 / (n * h))) / p for h in fracciones]
        eje.plot([100 * h for h in fracciones], curva, color=color, linewidth=2.0, label=etiqueta, zorder=3)
    region_20 = cal["mde_relativo_pct"]["una_region_control_20"] if cal else mde[3]["mde_relativo_pct"]
    eje.scatter([20], [region_20], s=36, color=COLOR["realista"], edgecolor=SUPERFICIE, linewidth=1.6, zorder=4)
    # Entre las dos curvas: arriba quedan el criterio T6 y la linea del efecto pesimista.
    eje.annotate(f"diseño propuesto: control de 20%, detecta {_num(region_20, 1)}%", (20, region_20),
                 xytext=(23, 2.95), textcoords="data", va="center", color=TINTA, fontsize=9,
                 arrowprops={"arrowstyle": "-", "color": TINTA_2, "linewidth": 0.7, "shrinkA": 2, "shrinkB": 4,
                             "relpos": (0, 0.5)})
    # El criterio es continuo y oscuro; los efectos a detectar, punteados, para
    # distinguirlos de la grilla.
    for valor, texto in ((equiv[0.1], "efecto realista"), (5.0, "criterio T6"), (equiv[0.04], "efecto pesimista")):
        criterio = "criterio" in texto
        eje.axhline(valor, color=TINTA_2 if criterio else NEUTRO, linewidth=1.0,
                    linestyle="-" if criterio else (0, (3, 3)), zorder=1)
        eje.text(50.5, valor, f" {texto} ({_num(valor, 1)}%)", va="center", ha="left", color=TINTA_2, fontsize=9)
    eje.set_xlim(5, 50)
    eje.set_ylim(0, 11)
    eje.set_yticks([0, 2, 4, 6, 8])
    eje.xaxis.set_major_formatter(_pct_eje())
    eje.yaxis.set_major_formatter(_pct_eje())
    eje.set_xlabel("Tamaño del grupo de control dentro de la lista")
    eje.set_ylabel("Efecto mínimo detectable (relativo)")
    eje.legend(loc="center right", fontsize=9.5, bbox_to_anchor=(0.98, 0.66))
    fig.tight_layout()
    _guardar(fig, destino)


FIGURAS = {
    "concentracion_ingreso.png": concentracion_ingreso,
    "tco_capas.png": tco_capas,
    "politicas_saturacion.png": politicas_saturacion,
    "efecto_literatura.png": efecto_literatura,
    "flujo_acumulado.png": flujo_acumulado,
    "tornado_vpn.png": tornado,
    "vpn_efecto.png": vpn_efecto,
    "economia_campana.png": economia_campana,
    "validacion_modelo.png": validacion_modelo,
    "potencia_piloto.png": potencia_piloto,
}


def generar(salida: dict, carpeta: Path, churn: dict | None = None) -> None:
    """Genera todas las figuras. ``churn`` aporta AUC y sesgo de calibracion medidos."""
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = dict(salida)
    salida["graficos_equivalencia"] = salida["validacion"]["equivalencia_efecto"]
    if churn is None:
        import json

        ruta = Path(__file__).resolve().parents[2] / "data" / "artifacts" / "churn_metricas.json"
        churn = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
    if churn:
        salida["graficos_auc"] = {"modelo": churn["auc"], "recencia": churn["auc_linea_base_recencia"]}
        salida["graficos_sesgo_pp"] = churn["sesgo_calibracion_pp"]
    for archivo, funcion in FIGURAS.items():
        if "graficos" not in salida and funcion not in (flujo_acumulado, tornado, economia_campana, tco_capas):
            continue  # artefacto anterior sin series de graficos
        funcion(salida, carpeta / archivo)
    print(f"Figuras en {carpeta}")
