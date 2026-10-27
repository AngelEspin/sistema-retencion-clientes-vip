"""Genera la version estatica del tablero: una pagina que no necesita la API.

Precalcula con el simulador una grilla de escenarios (presupuesto x promociones
x criterio x efecto) y la incrusta, junto con el panel analitico, en una copia
de src/api/dashboard.html. La pagina resultante solo contiene agregados: ninguna
fila por cliente sale de la maquina, asi que puede alojarse gratis (GitHub
Pages) o abrirse con doble clic sin correr ningun codigo.

Uso:
    python generar_pagina_estatica.py               # usa la grilla en cache si existe
    python generar_pagina_estatica.py --recalcular  # vuelve a simular la grilla
    python generar_pagina_estatica.py --solo-grilla # calcula la grilla y no escribe la pagina

Salidas:
    web/index.html                     documento completo
    docs/index.html                    la misma pagina, publicada por GitHub Pages
    web/simulador_retencion.html       fragmento sin <html>/<head>/<body>, para publicar como artefacto
    data/artifacts/grilla_escenarios.json   cache de la grilla
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from api.panel import construir_panel, parametros_grilla  # noqa: E402
from simulation.simulador import (  # noqa: E402
    Escenario,
    cargar_poblacion,
    desglose_por_cohorte,
    simular,
)

DASHBOARD = ROOT / "src" / "api" / "dashboard.html"
CACHE = ROOT / "data" / "artifacts" / "grilla_escenarios.json"
SALIDA = ROOT / "web"
PAGES = ROOT / "docs"
MARCA = "<!--DATOS_ESTATICOS-->"


def clave(presupuesto: float, promos: int, criterio: str, efecto: float) -> str:
    # Debe coincidir con claveGrilla() del tablero: String() de JS y str() de
    # Python escriben igual los enteros y los decimales de la grilla.
    return f"{int(presupuesto)}|{promos}|{criterio}|{efecto}"


def calcular_grilla(forzar: bool = False) -> dict:
    params = parametros_grilla()
    if CACHE.exists() and not forzar:
        previa = json.loads(CACHE.read_text(encoding="utf-8"))
        if previa.get("parametros") == params:
            print(f"Grilla en cache: {len(previa['resultados'])} escenarios ({CACHE.name})")
            return previa

    poblacion = cargar_poblacion()
    combinaciones = list(product(params["presupuestos"], params["promos"],
                                 params["criterios"], params["efectos"]))
    print(f"Simulando {len(combinaciones)} escenarios sobre {len(poblacion):,} agentes...")
    inicio = time.time()
    resultados = {}
    for i, (presupuesto, promos, criterio, efecto) in enumerate(combinaciones, 1):
        esc = Escenario(
            nombre=clave(presupuesto, promos, criterio, efecto),
            presupuesto_usd=presupuesto,
            costo_promo_usd=params["costo_promo_usd"],
            promos_por_cliente=promos,
            criterio=criterio,
            pct_control=params["pct_control"],
            semilla=params["semilla"],
            efecto_promo=efecto,
            umbral_saturacion=params["umbral_saturacion"],
        )
        r = simular(esc, poblacion)
        cohortes = desglose_por_cohorte(esc, poblacion)["cohortes"]
        resultados[esc.nombre] = {
            "r": r.reduccion_fuga_pct, "m": r.margen_incremental_usd, "rm": r.roi_margen,
            "i": r.ingreso_incremental_usd, "ri": r.roi, "b": r.beneficio_neto_usd,
            "c": r.costo_total_usd, "a": r.clientes_alcanzados, "s": r.clientes_saturados,
            "e": r.promos_enviadas, "fc": r.tasa_fuga_control, "ft": r.tasa_fuga_tratamiento,
            # Por decil de riesgo: decil, agentes, tratados, salvados, saturados,
            # fuga control %, fuga tratamiento %. Son conteos, no clientes.
            "co": [[c["decil"], c["agentes"], c["tratados"], c["salvados"], c["saturados"],
                    c["fuga_control_pct"], c["fuga_tratamiento_pct"]] for c in cohortes],
        }
        if i % 60 == 0 or i == len(combinaciones):
            print(f"  {i}/{len(combinaciones)} escenarios ({time.time() - inicio:.0f} s)")

    grilla = {"parametros": params, "segundos": round(time.time() - inicio, 1),
              "resultados": resultados}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(grilla, ensure_ascii=False), encoding="utf-8")
    return grilla


def _bloque(html: str, etiqueta: str) -> str:
    hallado = re.search(rf"<{etiqueta}[^>]*>(.*?)</{etiqueta}>", html, flags=re.S | re.I)
    if not hallado:
        raise SystemExit(f"dashboard.html no tiene <{etiqueta}>")
    return hallado.group(1)


def escribir_pagina(grilla: dict) -> tuple[Path, Path]:
    html = DASHBOARD.read_text(encoding="utf-8")
    if MARCA not in html:
        raise SystemExit(f"dashboard.html no tiene la marca {MARCA}")

    datos = {"panel": construir_panel(), "grilla": grilla}
    # "</" dentro de un <script> lo cerraria antes de tiempo.
    carga = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = f'<script id="datos-estaticos" type="application/json">{carga}</script>'
    completo = html.replace(MARCA, script)

    SALIDA.mkdir(exist_ok=True)
    pagina = SALIDA / "index.html"
    pagina.write_text(completo, encoding="utf-8")
    # GitHub Pages publica la carpeta docs/ de la rama main.
    PAGES.mkdir(exist_ok=True)
    (PAGES / "index.html").write_text(completo, encoding="utf-8")

    # El artefacto recibe solo el contenido: la plataforma pone el esqueleto.
    cabeza = _bloque(completo, "head")
    titulo = re.search(r"<title>.*?</title>", cabeza, flags=re.S).group(0)
    metas = "".join(re.findall(r'<meta name="claude:[^>]*>', cabeza))
    estilos = "".join(re.findall(r"<style>.*?</style>", cabeza, flags=re.S))
    fragmento = SALIDA / "simulador_retencion.html"
    fragmento.write_text(f"{titulo}\n{metas}\n{estilos}\n{_bloque(completo, 'body')}", encoding="utf-8")
    return pagina, fragmento


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recalcular", action="store_true", help="Volver a simular la grilla.")
    parser.add_argument("--solo-grilla", action="store_true", help="Calcular la grilla sin escribir la pagina.")
    args = parser.parse_args()

    grilla = calcular_grilla(forzar=args.recalcular)
    if args.solo_grilla:
        return
    pagina, fragmento = escribir_pagina(grilla)
    for ruta in (pagina, fragmento):
        print(f"Escrito {ruta.relative_to(ROOT)} ({ruta.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
