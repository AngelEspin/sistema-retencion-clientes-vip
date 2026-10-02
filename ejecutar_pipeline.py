"""Ejecuta el pipeline completo y registra cuanto tarda cada etapa.

Las duraciones alimentan el analisis de costo/beneficio: el recalculo mensual
se dimensiona con tiempos medidos sobre los 22 GB reales, no con supuestos.

Uso:
    python ejecutar_pipeline.py                      # las cuatro etapas
    python ejecutar_pipeline.py --desde rfm          # retomar desde una etapa
    python ejecutar_pipeline.py --hasta churn        # detenerse antes de simular
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "data" / "artifacts"
REGISTRO = ARTIFACTS / "tiempos_pipeline.json"

ETAPAS = [
    ("ingesta", "src/ingest/csv_to_parquet.py"),
    ("rfm", "src/features/rfm.py"),
    ("churn", "src/models/churn.py"),
    ("simulacion", "src/simulation/simulador.py"),
]


def _memoria_total_gb() -> float | None:
    try:
        import psutil  # opcional

        return round(psutil.virtual_memory().total / 1e9, 1)
    except ImportError:
        return None


def _ejecutar(script: str) -> tuple[float, float | None]:
    """Corre una etapa y devuelve (segundos, pico de RAM en GB si psutil existe)."""
    inicio = time.time()
    proceso = subprocess.Popen([sys.executable, script], cwd=str(ROOT))
    pico = None
    try:
        import psutil

        hijo = psutil.Process(proceso.pid)
        pico = 0.0
        while proceso.poll() is None:
            try:
                # En Windows el python del venv es un lanzador que arranca el
                # interprete real como hijo: hay que sumar todo el arbol.
                arbol = [hijo, *hijo.children(recursive=True)]
                pico = max(pico, sum(p.memory_info().rss for p in arbol) / 1e9)
            except psutil.Error:
                pass
            time.sleep(0.5)
    except ImportError:
        pass
    proceso.wait()
    if proceso.returncode != 0:
        raise SystemExit(f"La etapa {script} fallo con codigo {proceso.returncode}")
    return time.time() - inicio, (round(pico, 2) if pico is not None else None)


def main() -> None:
    nombres = [n for n, _ in ETAPAS]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", choices=nombres, default=nombres[0])
    parser.add_argument("--hasta", choices=nombres, default=nombres[-1])
    args = parser.parse_args()

    seleccion = ETAPAS[nombres.index(args.desde): nombres.index(args.hasta) + 1]

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    registro = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else {}
    registro["maquina"] = {
        "sistema": platform.platform(),
        "procesador": platform.processor(),
        "nucleos_logicos": os.cpu_count(),
        "ram_gb": _memoria_total_gb(),
        "python": platform.python_version(),
    }
    registro.setdefault("etapas", {})

    for nombre, script in seleccion:
        print(f"\n===== {nombre} ({script}) =====", flush=True)
        segundos, pico = _ejecutar(script)
        registro["etapas"][nombre] = {
            "segundos": round(segundos, 1),
            "pico_ram_gb": pico,
            "ejecutado": datetime.now().isoformat(timespec="seconds"),
        }
        print(f"===== {nombre}: {segundos / 60:.1f} min =====", flush=True)
        REGISTRO.write_text(json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(e["segundos"] for e in registro["etapas"].values())
    print(f"\nTiempo acumulado de las etapas registradas: {total / 60:.1f} min")


if __name__ == "__main__":
    main()
