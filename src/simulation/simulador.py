"""Simulador multiagente de campanas de retencion (Mesa).

Este es el nucleo del proyecto y la razon de no usar un modelo agregado. Una
cadena de Markov trata a todos los VIP por igual; aqui cada agente arranca con
**su** probabilidad real de fuga (la que predijo el modelo de churn) y con su
propio historial de gasto.

El fenomeno que justifica el enfoque es la **saturacion de promociones**: el
guion sostiene que un cliente que recibe tres promociones en un mes deja de
reaccionar. Eso es una no linealidad a nivel individual que ningun modelo
agregado puede representar, porque el promedio la disuelve.

Contrafactual
-------------
Cada corrida simula dos mundos con la misma semilla y la misma poblacion:
  * TRATAMIENTO -- se envian promociones segun la politica del escenario.
  * CONTROL     -- nadie recibe nada.
La diferencia entre ambos es el efecto causal estimado de la campana. Sin ese
contrafactual el "delta de retencion" no significa nada.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data" / "artifacts"

# --- Parametros de comportamiento ------------------------------------------
# Reduccion relativa maxima del riesgo de fuga que consigue una promocion
# perfectamente dirigida sobre un cliente receptivo.
EFECTO_PROMO_BASE = 0.35
# A partir de esta cantidad de promociones en el mes, el cliente se satura y
# su respuesta cae a cero. Es la cifra que fija el guion.
UMBRAL_SATURACION = 3
# Cada promocion adicional antes del umbral rinde menos que la anterior.
DECAIMIENTO_MARGINAL = 0.55
# Fraccion del gasto historico que se recupera al retener a un cliente durante
# el trimestre simulado.
HORIZONTE_DIAS = 90


@dataclass
class Escenario:
    """Definicion de una campana que el usuario comercial quiere evaluar."""

    nombre: str = "escenario_base"
    presupuesto_usd: float = 5000.0
    costo_promo_usd: float = 1.20
    # Cuantas promociones se permite enviar a un mismo cliente en el trimestre.
    promos_por_cliente: int = 2
    # Criterio de seleccion: 'riesgo' (mayor probabilidad de fuga),
    # 'valor' (mayor gasto historico) o 'valor_en_riesgo' (producto de ambos).
    criterio: str = "valor_en_riesgo"
    # Porcentaje de la poblacion que se reserva sin intervencion para medir.
    pct_control: float = 0.10
    semilla: int = 42


@dataclass
class ResultadoSimulacion:
    escenario: str
    agentes: int
    promos_enviadas: int
    clientes_alcanzados: int
    costo_total_usd: float
    retenidos_tratamiento: int
    retenidos_control: int
    tasa_fuga_tratamiento: float
    tasa_fuga_control: float
    reduccion_fuga_pct: float
    ingreso_incremental_usd: float
    roi: float
    clientes_saturados: int
    promos_desperdiciadas: int
    detalle: dict = field(default_factory=dict)


class ClienteVIP:
    """Un agente. Heterogeneo por construccion: cada uno trae sus propios datos.

    No hereda de ``mesa.Agent`` porque el modelo no necesita ni grilla ni red
    espacial; la poblacion se resuelve de forma vectorizada, que es lo que
    permite simular medio millon de clientes en segundos y no en horas. La
    semantica de agente (estado propio, decision propia, heterogeneidad) se
    mantiene intacta.
    """

    __slots__ = ("id", "prob_fuga_base", "gasto", "receptividad", "promos_recibidas")

    def __init__(self, id_: str, prob_fuga: float, gasto: float, receptividad: float):
        self.id = id_
        self.prob_fuga_base = prob_fuga
        self.gasto = gasto
        self.receptividad = receptividad
        self.promos_recibidas = 0


def efecto_acumulado(n_promos: int, receptividad: float) -> float:
    """Reduccion relativa del riesgo tras recibir ``n_promos`` en el trimestre.

    Modela dos cosas a la vez:
      1. **Rendimientos marginales decrecientes** -- la segunda promocion
         convence menos que la primera.
      2. **Saturacion dura** -- alcanzado el umbral, el cliente deja de
         responder por completo y el efecto colapsa a cero. No se queda en el
         maximo: se pierde, que es lo que observa el negocio cuando satura a
         su base.
    """
    if n_promos <= 0:
        return 0.0
    if n_promos >= UMBRAL_SATURACION:
        return 0.0

    efecto = 0.0
    for k in range(n_promos):
        efecto += EFECTO_PROMO_BASE * (DECAIMIENTO_MARGINAL ** k)
    return min(efecto, 0.95) * receptividad


class ModeloRetencion:
    """Orquesta la poblacion de agentes y ejecuta el contrafactual."""

    def __init__(self, poblacion: pd.DataFrame, escenario: Escenario):
        self.escenario = escenario
        self.rng = np.random.default_rng(escenario.semilla)

        self.ids = poblacion["cliente_id"].to_numpy()
        self.prob_fuga = poblacion["prob_abandono"].to_numpy(dtype=float)
        self.gasto = poblacion["monetario"].to_numpy(dtype=float)

        # La receptividad hereda del historial: quien ya compro en promocion
        # responde mas. Se acota para que nadie sea inmune ni infalible.
        if "propension_promo" in poblacion:
            base = poblacion["propension_promo"].fillna(0).to_numpy(dtype=float)
        else:
            base = np.full(len(self.ids), 0.3)
        self.receptividad = np.clip(0.45 + base, 0.3, 1.0)

        n = len(self.ids)
        # Grupo de control: reservado ANTES de decidir a quien se promociona,
        # para que no haya seleccion sobre la variable de resultado.
        self.es_control = self.rng.random(n) < escenario.pct_control
        self.promos = np.zeros(n, dtype=int)

    def asignar_promociones(self) -> None:
        """Reparte el presupuesto segun el criterio del escenario."""
        esc = self.escenario
        max_promos = int(esc.presupuesto_usd // esc.costo_promo_usd)

        elegibles = np.where(~self.es_control)[0]
        if esc.criterio == "riesgo":
            puntaje = self.prob_fuga[elegibles]
        elif esc.criterio == "valor":
            puntaje = self.gasto[elegibles]
        else:  # valor_en_riesgo
            # Priorizar el valor esperado en juego, no solo la probabilidad:
            # retener a un cliente de alto gasto con riesgo medio vale mas que
            # a uno marginal con riesgo alto.
            puntaje = self.prob_fuga[elegibles] * self.gasto[elegibles]

        orden = elegibles[np.argsort(-puntaje)]

        # El presupuesto es fijo, asi que insistir mas sobre cada cliente
        # significa necesariamente llegar a menos gente. Ese es el compromiso
        # que el escenario pone a prueba: alcance frente a intensidad.
        #
        # Repartir "una ronda a todos y luego otra" no modelaria nada: con
        # 538k VIP elegibles y presupuesto para ~4k promociones, la primera
        # ronda agotaria el dinero y nadie recibiria una segunda.
        n_objetivo = max(1, max_promos // max(esc.promos_por_cliente, 1))
        objetivo = orden[:n_objetivo]
        self.promos[objetivo] = esc.promos_por_cliente

    def ejecutar(self) -> ResultadoSimulacion:
        self.asignar_promociones()
        esc = self.escenario
        n = len(self.ids)

        reduccion = np.array(
            [efecto_acumulado(int(p), r) for p, r in zip(self.promos, self.receptividad)]
        )
        prob_tratamiento = self.prob_fuga * (1.0 - reduccion)

        # Misma tirada aleatoria para ambos mundos: el unico factor que cambia
        # entre tratamiento y control es la promocion, no el azar. Es el
        # equivalente simulado a un experimento pareado.
        sorteo = self.rng.random(n)
        fuga_control = sorteo < self.prob_fuga
        fuga_tratamiento = sorteo < prob_tratamiento

        tratados = ~self.es_control
        n_trat = int(tratados.sum())
        n_ctrl = int(self.es_control.sum())

        tasa_trat = float(fuga_tratamiento[tratados].mean()) if n_trat else 0.0
        tasa_ctrl = float(fuga_control[self.es_control].mean()) if n_ctrl else 0.0

        # Los saturados son el hallazgo que justifica el simulador: clientes en
        # los que se gasto presupuesto y cuya respuesta es exactamente cero.
        saturados = int((self.promos >= UMBRAL_SATURACION).sum())
        desperdiciadas = int(self.promos[self.promos >= UMBRAL_SATURACION].sum())

        promos_enviadas = int(self.promos.sum())
        costo = promos_enviadas * esc.costo_promo_usd

        # Ingreso incremental: clientes que se fugaban en el contrafactual y no
        # se fugan con la campana, valorados a su gasto trimestral historico.
        salvados = fuga_control & ~fuga_tratamiento
        gasto_trimestral = self.gasto * (HORIZONTE_DIAS / 365.0)
        ingreso = float(gasto_trimestral[salvados].sum())

        # Dos estimaciones distintas del mismo efecto, y conviene no confundirlas:
        #
        # 1. PAREADA -- compara los mismos individuos en ambos mundos. Solo es
        #    posible dentro de la simulacion, y es el efecto causal exacto del
        #    modelo, sin ruido de muestreo.
        # 2. ENTRE GRUPOS -- compara tratados contra el grupo de control, que es
        #    lo unico observable en una campana real. Incluye el ruido de haber
        #    partido la poblacion en dos, y por eso puede marcar diferencias
        #    aunque el efecto verdadero sea cero.
        #
        # Reportar solo la segunda haria pasar ruido por resultado; reportar
        # solo la primera prometeria una precision que el negocio no tendra.
        fuga_ctrl_en_tratados = fuga_control[tratados]
        fuga_trat_en_tratados = fuga_tratamiento[tratados]
        base_pareada = float(fuga_ctrl_en_tratados.mean()) if n_trat else 0.0
        post_pareada = float(fuga_trat_en_tratados.mean()) if n_trat else 0.0
        reduccion_rel = (
            100.0 * (base_pareada - post_pareada) / base_pareada if base_pareada > 0 else 0.0
        )
        reduccion_entre_grupos = (
            100.0 * (tasa_ctrl - tasa_trat) / tasa_ctrl if tasa_ctrl > 0 else 0.0
        )

        return ResultadoSimulacion(
            escenario=esc.nombre,
            agentes=n,
            promos_enviadas=promos_enviadas,
            clientes_alcanzados=int((self.promos > 0).sum()),
            costo_total_usd=round(costo, 2),
            retenidos_tratamiento=int((~fuga_tratamiento).sum()),
            retenidos_control=int((~fuga_control).sum()),
            tasa_fuga_tratamiento=round(tasa_trat, 4),
            tasa_fuga_control=round(tasa_ctrl, 4),
            reduccion_fuga_pct=round(reduccion_rel, 2),
            ingreso_incremental_usd=round(ingreso, 2),
            roi=round(ingreso / costo, 2) if costo > 0 else 0.0,
            clientes_saturados=saturados,
            promos_desperdiciadas=desperdiciadas,
            detalle={
                "clientes_tratamiento": n_trat,
                "clientes_control": n_ctrl,
                "clientes_salvados": int(salvados.sum()),
                "umbral_saturacion": UMBRAL_SATURACION,
                "efecto_promo_base": EFECTO_PROMO_BASE,
                "reduccion_fuga_entre_grupos_pct": round(reduccion_entre_grupos, 2),
                "tasa_fuga_base_pareada": round(base_pareada, 4),
            },
        )


def cargar_poblacion(muestra: int | None = None, semilla: int = 42) -> pd.DataFrame:
    """Carga los VIP con su probabilidad de fuga ya predicha por el modelo."""
    ruta = ARTIFACTS / "scores_vip.parquet"
    if not ruta.exists():
        raise SystemExit(
            f"Falta {ruta}. Ejecuta primero src/models/churn.py para generar los scores."
        )
    df = pd.read_parquet(ruta)
    if muestra and muestra < len(df):
        df = df.sample(muestra, random_state=semilla).reset_index(drop=True)
    return df


def simular(escenario: Escenario, poblacion: pd.DataFrame) -> ResultadoSimulacion:
    return ModeloRetencion(poblacion, escenario).ejecutar()


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    poblacion = cargar_poblacion()
    print(f"Poblacion de agentes: {len(poblacion):,} clientes VIP\n")

    # Barrido que demuestra el fenomeno central: al aumentar la insistencia por
    # cliente, el ROI no crece de forma monotona porque aparece la saturacion.
    escenarios = [
        Escenario(nombre="conservador_1promo", presupuesto_usd=5000, promos_por_cliente=1),
        Escenario(nombre="equilibrado_2promos", presupuesto_usd=5000, promos_por_cliente=2),
        Escenario(nombre="agresivo_3promos", presupuesto_usd=5000, promos_por_cliente=3),
        Escenario(nombre="agresivo_4promos", presupuesto_usd=5000, promos_por_cliente=4),
        Escenario(nombre="presupuesto_alto_2promos", presupuesto_usd=20000, promos_por_cliente=2),
        Escenario(nombre="solo_riesgo", presupuesto_usd=5000, promos_por_cliente=2, criterio="riesgo"),
        Escenario(nombre="solo_valor", presupuesto_usd=5000, promos_por_cliente=2, criterio="valor"),
    ]

    filas = []
    for esc in escenarios:
        r = simular(esc, poblacion)
        filas.append(asdict(r))
        print(
            f"  {r.escenario:26} ROI {r.roi:6.2f}  "
            f"reduccion fuga {r.reduccion_fuga_pct:6.2f}%  "
            f"saturados {r.clientes_saturados:7,}  "
            f"costo ${r.costo_total_usd:,.0f}"
        )

    # --- Cuanto cuesta el objetivo de -15% de fuga? -------------------------
    # El guion promete reducir la fuga trimestral de VIP en un 15%. Con la
    # poblacion real (538k VIP) un presupuesto de 5.000 USD alcanza al 0.8% de
    # ellos, asi que conviene medir que presupuesto haria falta de verdad en
    # lugar de dar el objetivo por cumplido.
    print("\n--- Barrido de presupuesto (2 promos, valor_en_riesgo) ---")
    barrido = []
    for presupuesto in (5_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000):
        r = simular(
            Escenario(
                nombre=f"barrido_{presupuesto}",
                presupuesto_usd=presupuesto,
                promos_por_cliente=2,
            ),
            poblacion,
        )
        cobertura = 100.0 * r.clientes_alcanzados / r.agentes
        barrido.append(
            {
                "presupuesto_usd": presupuesto,
                "clientes_alcanzados": r.clientes_alcanzados,
                "cobertura_pct": round(cobertura, 2),
                "reduccion_fuga_pct": r.reduccion_fuga_pct,
                "roi": r.roi,
                "ingreso_incremental_usd": r.ingreso_incremental_usd,
            }
        )
        print(
            f"  ${presupuesto:>9,}  cobertura {cobertura:5.2f}%  "
            f"reduccion fuga {r.reduccion_fuga_pct:6.2f}%  ROI {r.roi:6.2f}"
        )

    alcanza = [b for b in barrido if b["reduccion_fuga_pct"] >= 15.0]
    if alcanza:
        print(f"\n  Objetivo -15% alcanzable desde ${alcanza[0]['presupuesto_usd']:,}")
    else:
        print(
            f"\n  El objetivo de -15% NO se alcanza ni con ${barrido[-1]['presupuesto_usd']:,}: "
            f"maximo observado {barrido[-1]['reduccion_fuga_pct']}%"
        )

    (ARTIFACTS / "escenarios.json").write_text(
        json.dumps({"escenarios": filas, "barrido_presupuesto": barrido}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nResultados en {ARTIFACTS / 'escenarios.json'}")


if __name__ == "__main__":
    main()
