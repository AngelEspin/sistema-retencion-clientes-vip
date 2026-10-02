"""Simulador multiagente de campanas de retencion.

Este es el nucleo del proyecto y la razon de no usar un modelo agregado. Una
cadena de Markov trata a todos los VIP por igual; aqui cada agente arranca con
**su** probabilidad real de fuga (la que predijo el modelo de churn), con su
propio historial de gasto y margen, y con su propia receptividad a promociones.

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
from dataclasses import dataclass, field, asdict, replace
from pathlib import Path
from typing import Any

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
# Trimestre simulado: el valor de un cliente retenido es lo que compra en el.
HORIZONTE_DIAS = 90
# Dias que cubren `monetario` y `margen` cuando el artefacto no lo declara
# (artefactos anteriores a la columna dias_ventana). Conserva el comportamiento
# historico, que los trataba como un anio completo.
DIAS_VENTANA_DEFECTO = 365

CRITERIOS = ("riesgo", "valor", "valor_en_riesgo", "aleatorio", "recencia")


@dataclass
class Escenario:
    """Definicion de una campana que el usuario comercial quiere evaluar."""

    nombre: str = "escenario_base"
    presupuesto_usd: float = 5000.0
    costo_promo_usd: float = 1.20
    # Cuantas promociones se permite enviar a un mismo cliente en el trimestre.
    promos_por_cliente: int = 2
    # Criterio de seleccion: 'riesgo' (mayor probabilidad de fuga),
    # 'valor' (mayor gasto historico), 'valor_en_riesgo' (producto de ambos).
    # Dos mas sirven de linea base, porque no necesitan el modelo: 'aleatorio'
    # (la campana masiva que se decide por intuicion) y 'recencia' (la regla RFM
    # de siempre: primero los que hace mas tiempo no compran).
    criterio: str = "valor_en_riesgo"
    # Porcentaje de la poblacion que se reserva sin intervencion para medir.
    pct_control: float = 0.10
    semilla: int = 42
    # Supuestos de comportamiento. Son parametros del escenario para poder
    # someterlos a sensibilidad; por defecto valen lo que fija el guion.
    efecto_promo: float = EFECTO_PROMO_BASE
    umbral_saturacion: int = UMBRAL_SATURACION


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
    # Valoracion a margen bruto: lo que la cadena gana de verdad al retener.
    # None si la poblacion no trae la columna `margen`.
    margen_incremental_usd: float | None = None
    roi_margen: float | None = None
    beneficio_neto_usd: float | None = None
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


def efecto_acumulado(
    n_promos: int,
    receptividad: float,
    efecto_base: float = EFECTO_PROMO_BASE,
    umbral: int = UMBRAL_SATURACION,
) -> float:
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
    if n_promos >= umbral:
        return 0.0

    efecto = 0.0
    for k in range(n_promos):
        efecto += efecto_base * (DECAIMIENTO_MARGINAL ** k)
    return min(efecto, 0.95) * receptividad


def _efecto_vectorizado(
    promos: np.ndarray, receptividad: np.ndarray, efecto_base: float, umbral: int
) -> np.ndarray:
    """``efecto_acumulado`` resuelto para toda la poblacion de una vez.

    El efecto solo depende del numero de promociones, asi que basta una tabla
    por conteo. Recorrer 540k agentes en Python dominaba el tiempo de respuesta,
    y en Lambda ese tiempo se factura por milisegundo.
    """
    tabla = np.array(
        [efecto_acumulado(n, 1.0, efecto_base, umbral) for n in range(int(promos.max()) + 1)]
    )
    return tabla[promos] * receptividad


class ModeloRetencion:
    """Orquesta la poblacion de agentes y ejecuta el contrafactual."""

    def __init__(self, poblacion: pd.DataFrame, escenario: Escenario):
        if escenario.criterio not in CRITERIOS:
            raise ValueError(f"Criterio desconocido: {escenario.criterio}. Opciones: {CRITERIOS}")
        self.escenario = escenario
        self.rng = np.random.default_rng(escenario.semilla)

        self.ids = poblacion["cliente_id"].to_numpy()
        self.prob_fuga = poblacion["prob_abandono"].to_numpy(dtype=float)
        self.gasto = poblacion["monetario"].to_numpy(dtype=float)
        self.recencia = (
            poblacion["recencia"].to_numpy(dtype=float) if "recencia" in poblacion else None
        )

        # `monetario` y `margen` suman toda la ventana observada, que no es un
        # anio: se llevan a valor trimestral con el largo real de la ventana.
        if "dias_ventana" in poblacion:
            dias = poblacion["dias_ventana"].to_numpy(dtype=float)
        else:
            dias = np.full(len(self.ids), float(DIAS_VENTANA_DEFECTO))
        self.valor_trimestral = self.gasto * HORIZONTE_DIAS / dias
        self.margen_trimestral = (
            poblacion["margen"].to_numpy(dtype=float) * HORIZONTE_DIAS / dias
            if "margen" in poblacion
            else None
        )

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
        elif esc.criterio == "aleatorio":
            # Flujo aleatorio propio: asi la linea base comparte con los demas
            # criterios el mismo grupo de control y el mismo sorteo de fuga, y
            # la comparacion entre politicas queda pareada.
            puntaje = np.random.default_rng([esc.semilla, 1]).random(len(elegibles))
        elif esc.criterio == "recencia":
            if self.recencia is None:
                raise ValueError("El criterio 'recencia' requiere la columna recencia en la poblacion")
            puntaje = self.recencia[elegibles]
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
        #
        # Sin piso de un cliente: si el presupuesto no paga ni una asignacion
        # completa, no se envia nada. Forzar un minimo de 1 gastaba mas de lo
        # presupuestado (USD 1 con 2 promos de USD 1.20 costaba USD 2.40).
        n_objetivo = max_promos // max(esc.promos_por_cliente, 1)
        objetivo = orden[:n_objetivo]
        self.promos[objetivo] = esc.promos_por_cliente

    def _resolver(self) -> tuple[np.ndarray, np.ndarray]:
        """Asigna la campana y resuelve la fuga en ambos mundos.

        Misma tirada aleatoria para ambos mundos: el unico factor que cambia
        entre tratamiento y control es la promocion, no el azar. Es el
        equivalente simulado a un experimento pareado.
        """
        self.asignar_promociones()
        esc = self.escenario
        reduccion = _efecto_vectorizado(
            self.promos, self.receptividad, esc.efecto_promo, esc.umbral_saturacion
        )
        prob_tratamiento = self.prob_fuga * (1.0 - reduccion)
        sorteo = self.rng.random(len(self.ids))
        return sorteo < self.prob_fuga, sorteo < prob_tratamiento

    def ejecutar(self) -> ResultadoSimulacion:
        fuga_control, fuga_tratamiento = self._resolver()
        esc = self.escenario
        n = len(self.ids)

        tratados = ~self.es_control
        n_trat = int(tratados.sum())
        n_ctrl = int(self.es_control.sum())

        tasa_trat = float(fuga_tratamiento[tratados].mean()) if n_trat else 0.0
        tasa_ctrl = float(fuga_control[self.es_control].mean()) if n_ctrl else 0.0

        # Los saturados son el hallazgo que justifica el simulador: clientes en
        # los que se gasto presupuesto y cuya respuesta es exactamente cero.
        saturados = int((self.promos >= esc.umbral_saturacion).sum())
        desperdiciadas = int(self.promos[self.promos >= esc.umbral_saturacion].sum())

        promos_enviadas = int(self.promos.sum())
        costo = promos_enviadas * esc.costo_promo_usd

        # Valor incremental: clientes que se fugaban en el contrafactual y no
        # se fugan con la campana, valorados a lo que compran en el trimestre.
        salvados = fuga_control & ~fuga_tratamiento
        ingreso = float(self.valor_trimestral[salvados].sum())
        margen = (
            float(self.margen_trimestral[salvados].sum())
            if self.margen_trimestral is not None
            else None
        )

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
            margen_incremental_usd=round(margen, 2) if margen is not None else None,
            roi_margen=(round(margen / costo, 2) if costo > 0 else 0.0) if margen is not None else None,
            beneficio_neto_usd=round(margen - costo, 2) if margen is not None else None,
            detalle={
                "clientes_tratamiento": n_trat,
                "clientes_control": n_ctrl,
                "clientes_salvados": int(salvados.sum()),
                "criterio": esc.criterio,
                "umbral_saturacion": esc.umbral_saturacion,
                "efecto_promo_base": esc.efecto_promo,
                "receptividad_media": round(float(self.receptividad.mean()), 4),
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


def presupuesto_para_meta(
    poblacion: pd.DataFrame,
    meta_reduccion_pct: float = 15.0,
    base: Escenario | None = None,
    tope_usd: float = 2_000_000,
    paso_usd: float = 1_000,
) -> float | None:
    """Presupuesto minimo, redondeado a ``paso_usd``, que alcanza la meta de fuga.

    Con la semilla fija, mas presupuesto solo agrega clientes al final del mismo
    orden de prioridad, asi que la reduccion es monotona y basta una biseccion.
    Devuelve None si ni el tope alcanza la meta.
    """
    base = base or Escenario()

    def reduccion(presupuesto: float) -> float:
        esc = replace(base, nombre=f"meta_{int(presupuesto)}", presupuesto_usd=presupuesto)
        return simular(esc, poblacion).reduccion_fuga_pct

    if reduccion(tope_usd) < meta_reduccion_pct:
        return None
    bajo, alto = 0.0, tope_usd
    while alto - bajo > paso_usd:
        medio = (bajo + alto) / 2
        if reduccion(medio) >= meta_reduccion_pct:
            alto = medio
        else:
            bajo = medio
    return float(math.ceil(alto / paso_usd) * paso_usd)


def deciles(df: pd.DataFrame, col: str, invertido: bool = False) -> list[dict]:
    """Divide la poblacion en 10 deciles segun una columna numerica.

    Vive aqui y no en la API para que la version Lambda, que no tiene FastAPI,
    sirva exactamente los mismos deciles.
    """
    if df.empty:
        return []
    orden = df[col].to_numpy(dtype=float)
    # pd.qcut requiere valores unicos por decil; ante empates se usan cortes
    # por rango lineal para que siempre haya 10 cohortes.
    try:
        bins = pd.qcut(orden, 10, labels=False, duplicates="drop")
    except (ValueError, TypeError):
        bins = np.clip((np.argsort(np.argsort(orden)) * 10) // len(orden), 0, 9)
    res = []
    for d in range(10):
        sel = df[bins == d]
        if sel.empty:
            continue
        vals = sel[col].to_numpy(dtype=float)
        res.append(
            {
                "decil": d + 1,
                "agentes": int(len(sel)),
                "min": round(float(vals.min()), 4) if not invertido else round(float(vals.max()), 4),
                "max": round(float(vals.max()), 4) if not invertido else round(float(vals.min()), 4),
                "promedio": round(float(vals.mean()), 4),
            }
        )
    return res


def desglose_por_cohorte(
    escenario: Escenario, poblacion: pd.DataFrame
) -> dict[str, Any]:
    """Devuelve como se comporta cada cohorte de riesgo bajo el escenario.

    Permite "ver" a los agentes trabajando: el simulador resuelve la poblacion
    de forma vectorizada (por eso tarda segundos), pero este desglose muestra
    por decil de riesgo cuantos agentes hay, cuantos reciben promo, cuantos se
    saturan, cuantos se fugan en control vs tratamiento y cuantos se salvan.
    El dashboard lo presenta como el proceso vivo que el modelo realiza.
    """
    model = ModeloRetencion(poblacion, escenario)
    esc = model.escenario
    n = len(model.ids)

    # Misma resolucion que ejecutar(), para que las cohortes cuadren con el
    # resultado agregado del mismo escenario.
    fuga_control, fuga_tratamiento = model._resolver()

    # Deciles de riesgo (10 cohortes) para que el usuario vea la distribucion.
    prob = model.prob_fuga
    deciles_riesgo = np.clip(
        (prob * 10).astype(int), 0, 9
    )  # decil 0 = menor riesgo, decil 9 = mayor

    cohortes = []
    for d in range(10):
        sel = np.where(deciles_riesgo == d)[0]
        if len(sel) == 0:
            continue
        miembro = ~model.es_control[sel]
        promos = model.promos[sel]
        gastos = model.gasto[sel]
        fuga_c = fuga_control[sel]
        fuga_t = fuga_tratamiento[sel]
        salvados = fuga_c & ~fuga_t

        fila = {
            "decil": d + 1,
            "rango_riesgo": [round(float(prob[sel].min()), 3), round(float(prob[sel].max()), 3)],
            "agentes": int(len(sel)),
            "tratados": int(miembro.sum()),
            "promos_recibidas": int(promos.sum()),
            "promos_por_agente": round(float(promos.mean()), 2),
            "saturados": int((promos >= esc.umbral_saturacion).sum()),
            "fuga_control_pct": round(float(fuga_c.mean()) * 100, 2),
            "fuga_tratamiento_pct": round(float(fuga_t.mean()) * 100, 2),
            "salvados": int(salvados.sum()),
            "gasto_en_riesgo_usd": round(float(model.valor_trimestral[sel][salvados].sum()), 2),
            "valor_promedio_usd": round(float(gastos.mean()), 2),
        }
        if model.margen_trimestral is not None:
            fila["margen_salvado_usd"] = round(
                float(model.margen_trimestral[sel][salvados].sum()), 2
            )
        cohortes.append(fila)

    return {
        "escenario": esc.nombre,
        "agentes_totales": n,
        "umbral_saturacion": esc.umbral_saturacion,
        "efecto_promo_base": esc.efecto_promo,
        "cohortes": cohortes,
    }


def fila_barrido(r: ResultadoSimulacion, presupuesto: float) -> dict[str, Any]:
    return {
        "presupuesto_usd": presupuesto,
        "clientes_alcanzados": r.clientes_alcanzados,
        "cobertura_pct": round(100.0 * r.clientes_alcanzados / r.agentes, 2),
        "reduccion_fuga_pct": r.reduccion_fuga_pct,
        "roi": r.roi,
        "ingreso_incremental_usd": r.ingreso_incremental_usd,
        "roi_margen": r.roi_margen,
        "margen_incremental_usd": r.margen_incremental_usd,
        "beneficio_neto_usd": r.beneficio_neto_usd,
        "clientes_saturados": r.clientes_saturados,
    }


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
        Escenario(nombre="aleatorio", presupuesto_usd=5000, promos_por_cliente=2, criterio="aleatorio"),
    ]

    filas = []
    for esc in escenarios:
        r = simular(esc, poblacion)
        filas.append(asdict(r))
        print(
            f"  {r.escenario:26} ROI {r.roi:6.2f}  ROI margen {r.roi_margen or 0:6.2f}  "
            f"reduccion fuga {r.reduccion_fuga_pct:6.2f}%  "
            f"saturados {r.clientes_saturados:7,}  "
            f"costo ${r.costo_total_usd:,.0f}"
        )

    # --- Cuanto cuesta el objetivo de -15% de fuga? -------------------------
    # El guion promete reducir la fuga trimestral de VIP en un 15%. Con la
    # poblacion real (538k VIP) un presupuesto de 5.000 USD alcanza a menos del
    # 1% de ellos, asi que conviene medir que presupuesto haria falta de verdad
    # en lugar de dar el objetivo por cumplido.
    print("\n--- Barrido de presupuesto (2 promos, valor_en_riesgo) ---")
    barrido = []
    for presupuesto in (5_000, 25_000, 50_000, 100_000, 150_000, 250_000, 500_000, 1_000_000):
        r = simular(
            Escenario(
                nombre=f"barrido_{presupuesto}",
                presupuesto_usd=presupuesto,
                promos_por_cliente=2,
            ),
            poblacion,
        )
        fila = fila_barrido(r, presupuesto)
        barrido.append(fila)
        print(
            f"  ${presupuesto:>9,}  cobertura {fila['cobertura_pct']:5.2f}%  "
            f"reduccion fuga {r.reduccion_fuga_pct:6.2f}%  ROI {r.roi:6.2f}  "
            f"ROI margen {r.roi_margen or 0:5.2f}"
        )

    minimo = presupuesto_para_meta(poblacion, 15.0)
    if minimo is not None:
        print(f"\n  Presupuesto minimo para -15% de fuga: ${minimo:,.0f} por trimestre")
    else:
        print("\n  El objetivo de -15% NO se alcanza ni con el tope del barrido")

    # --- Cuanto aporta decidir con el simulador y no por intuicion? ---------
    # Mismo presupuesto, misma poblacion y mismo azar; solo cambia a quien se
    # dirige la campana y con cuanta insistencia.
    referencia = minimo or 150_000
    politicas = [
        ("simulador_valor_en_riesgo", "valor_en_riesgo", 2),
        ("intuicion_aleatoria", "aleatorio", 2),
        ("intuicion_mayor_gasto", "valor", 2),
        ("intuicion_mayor_riesgo", "riesgo", 2),
        ("intuicion_insistente", "valor", 3),
    ]
    print(f"\n--- Politicas con el mismo presupuesto (${referencia:,.0f}) ---")
    comparacion = []
    for nombre, criterio, promos in politicas:
        r = simular(
            Escenario(nombre=nombre, presupuesto_usd=referencia,
                      promos_por_cliente=promos, criterio=criterio),
            poblacion,
        )
        comparacion.append(asdict(r))
        print(
            f"  {nombre:28} reduccion {r.reduccion_fuga_pct:6.2f}%  "
            f"margen ${r.margen_incremental_usd or 0:>12,.0f}  ROI margen {r.roi_margen or 0:5.2f}"
        )

    (ARTIFACTS / "escenarios.json").write_text(
        json.dumps(
            {
                "escenarios": filas,
                "barrido_presupuesto": barrido,
                "presupuesto_minimo_meta_15pct": minimo,
                "comparacion_politicas": comparacion,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nResultados en {ARTIFACTS / 'escenarios.json'}")


if __name__ == "__main__":
    main()
