# Sistema Multiagente para la Segmentación de Clientes y Optimización de Retención

Simulador que estima el impacto comercial de una campaña de retención **antes** de
ejecutar el presupuesto, sobre la base de clientes de una cadena de farmacias.

**Proyecto de maestría en Ciencia de Datos — ESPOL**
Carlos Alberto Ramírez Celi · Angel Josué Espín Lumbano

---

## El problema

Entre el 70% y el 80% de los ingresos de la cadena dependen del 20% de clientes VIP,
pero la decisión de cómo retenerlos se toma por intuición: se lanzan presupuestos de
campaña con retorno desconocido y sin forma de comparar alternativas de antemano.

Este sistema responde a la pregunta que el negocio no podía contestar: *¿cuánto
presupuesto hace falta, y a quién dirigirlo, para mover realmente la aguja?*

## Resultados medidos

| Objetivo | Meta | Medido (re-ejecución del 02/10/2026) |
|---|---|---|
| Concentración de ingreso en el 20% VIP | 70–80% | **80.26%** (sin las 4 cuentas genéricas) |
| AUC del modelo de abandono | ≥ 0.75 | **0.8753** (regla simple por recencia: 0.8254) |
| Respuesta de escenario | < 10 min | **0.3–0.6 s** en local |
| Reducción de fuga VIP | −15% | **−15.05%** con USD 139.000/trimestre, *solo con el efecto del guion* |
| ROI de retención | 3:1 | **6.08:1 sobre ingreso, 1.39:1 sobre margen** en ese punto |

Sobre **72.5 millones de transacciones** (22.2 GB) de 3.1 millones de clientes en 682
sucursales, a lo largo de 12 meses. El pipeline completo corre en ~7 minutos.

El análisis costo/beneficio (`src/evaluacion/`) muestra que el **sistema** es rentable
frente a la práctica actual en el escenario realista (VPN USD 289.006 a 3 años, payback
4.2 meses), pero que la **campaña** de USD 139.000 solo se paga si el efecto real de una
promoción es al menos 0.25 (el guion supone 0.35; la evidencia de campo sugiere ~0.10).
El entregable completo está en `Presentaciones/entregables/`.

## El hallazgo central: la saturación de promociones

Un modelo agregado —una cadena de Markov, por ejemplo— asume homogeneidad y trata a
todos los VIP por igual. El simulador basado en agentes captura una no linealidad
individual que el promedio disuelve: **el cliente que recibe tres promociones en un
mes se satura y deja de responder por completo**.

Con presupuesto fijo, variando solo la insistencia por cliente:

| Promociones por cliente | ROI (ingreso) | ROI (margen) | Clientes saturados |
|---|---|---|---|
| 1 | 26.86 | 6.12 | 0 |
| 2 | **27.03** | **6.29** | 0 |
| **3** | **0.00** | **0.00** | **1.388** |
| 4 | 0.00 | 0.00 | 1.041 |

(Presupuesto fijo de USD 5.000 con el efecto del guion.)

El desplome a cero en la tercera promoción es el argumento de la tesis, cuantificado.

## Arquitectura

```
                          ┌────────────────────────────── LOCAL ──────────────────────────────┐
                          │                                                                   │
CSV crudo (22 GB)                                                                             │
      │  DuckDB en streaming, proyección 40 → 11 columnas                                     │
      ▼                                                                                       │
Parquet particionado (marca, mes) — 1.25 GB, compresión 17.8×                                  │
      │                                                                                       │
      ├─► Tabla de tickets (39.1M) ──► RFM ──► segmento VIP ─────────────┐                    │
      │                                      │                            │                    │
      │                                      ▼                            │                    │
      │                            Modelo de abandono                     │                    │
      │                       (validación temporal, AUC 0.87)             │                    │
      │                                      │                            │                    │
      │                                      ▼                            ▼                    │
      └─────────────────────────────► Simulador multiagente ─────► FastAPI local (dashboard)   │
                                  (538,983 agentes VIP)            · / → dashboard interactivo │
                                      │                            · respuestas 1–3 s          │
                                      └──► serializa scores       · poblacion cacheada        │
                                              ▼                                                 │
                                     ┌──────────────────────── ──┐                             │
                                     │    AWS Serverless (S3/Lambda)                            │
                                     │  mismos artefactos + código│  ───────────────────────────┘
                                     │  coste cero en reposo     │
                                     └───────────────────────────┘
```

Una vista gráfica (diagrama de flujo con métricas, algoritmo de saturación y
ambas vías de consumo) está en **`diagrama_arquitectura.pdf`**, regenerable con:

```bash
./.venv/Scripts/python generar_diagrama.py     # añade --abrir para abrirlo
```

## Estructura

```
src/ingest/csv_to_parquet.py    Ingesta en streaming a Parquet particionado
src/features/rfm.py             Segmentación RFM y definición del segmento VIP
src/models/churn.py             Modelo de abandono con validación temporal
src/simulation/simulador.py     Simulador multiagente con saturación
src/api/main.py                 API de escenarios (FastAPI) + endpoints de visibilidad
src/api/dashboard.html          Dashboard web interactivo servido en la raíz
src/evaluacion/                 Análisis costo/beneficio, figuras y criterios de validación
infra/lambda_handler.py         Versión serverless para AWS Lambda (mismas rutas que la API)
infra/desplegar.py              Despliegue idempotente: S3 + Lambda + Function URL (AWS_IAM)
infra/pruebas_funcionales.py    Rutas, entradas inválidas, casos borde y paridad nube = local
infra/prueba_carga.py           Latencia p50/p95, arranque en frío, concurrencia y costo real
ejecutar_pipeline.py            Corre las cuatro etapas y registra tiempo y RAM de cada una
descargar_datos.py              Descarga del dataset desde Google Drive (OAuth2)
generar_diagrama.py             Genera el PDF gráfico de arquitectura
PROGRESO.md                     Registro de implementación, decisiones y problemas
```

## Reproducir

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt

./.venv/Scripts/python descargar_datos.py              # (1ª vez) desde Google Drive
./.venv/Scripts/python ejecutar_pipeline.py            # ingesta + RFM + modelo + escenarios (~7 min)

cd src && ../.venv/Scripts/python -m uvicorn api.main:app --port 8080
```

Validación, nube y análisis costo/beneficio:

```bash
./.venv/Scripts/python infra/pruebas_funcionales.py           # 33 casos sobre el handler, sin AWS

# AWS emulado en local (LocalStack 4.14.0 en Docker sobre WSL2), si no hay cuenta de AWS:
wsl -d Ubuntu-24.04 -u root -- bash infra/localstack/levantar_localstack.sh
export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
./.venv/Scripts/python infra/desplegar.py --localstack        # sin --localstack: cuenta real de AWS
./.venv/Scripts/python infra/pruebas_funcionales.py --remoto  # paridad nube = local
./.venv/Scripts/python infra/prueba_carga.py                  # latencia y costo por consulta
./.venv/Scripts/python src/evaluacion/costo_beneficio.py      # ROI, payback, VPN, TCO, escenarios
./.venv/Scripts/python Presentaciones/entregables/construir_costo_beneficio.py   # PDF del entregable
```

Los datos crudos se leen de `data/Unprocessed/` (o de `Datos/`, si vienen de la descarga):
el CSV de ventas y el zip de Drive con los maestros, que la ingesta extrae sola.

## Datos desde Google Drive

El dataset original ya no está en la carpeta local; vive en una carpeta privada de
Google Drive. Para descargarlo:

1. **Crea las credenciales OAuth 2.0** (una sola vez):
   - Entra a [console.cloud.google.com](https://console.cloud.google.com)
   - Crea un proyecto (o usa uno existente).
   - Habilita la **Google Drive API**.
   - Ve a **APIs & Services → Credentials → Create Credentials → OAuth Client ID**.
   - Tipo: **Desktop app**. Guarda el JSON descargado como `credentials.json`
     en la raíz del proyecto.
2. **Ejecuta la descarga** (se abrirá el navegador para iniciar sesión en Google):

   ```bash
   ./.venv/Scripts/python descargar_datos.py
   ```

   La primera vez pedirá permisos de tu cuenta; luego guarda el token en
   `token.json` y no vuelve a pedirlos hasta que caduque.

3. Si la carpeta `Datos/` ya está completa, la descarga se omite automáticamente.
   Usa `--forzar` para forzarla o `--verificar` para revisar el estado.

## Sobre los datos

**Este repositorio no incluye los datos, y no debe incluirlos.**

El histórico transaccional de una cadena de farmacias revela condiciones de salud a
través del detalle de compra. Aunque los identificadores están seudonimizados en
origen, el detalle es reidentificable por cruce y queda cubierto por la Ley Orgánica
de Protección de Datos Personales. `Datos/` y `data/` están excluidos por
`.gitignore` de forma deliberada.

Para reproducir hace falta el dataset original, que se solicita al equipo del
proyecto.

## Limitación conocida

El tamaño del efecto de una promoción (`EFECTO_PROMO_BASE = 0.35`) y el umbral de
saturación (3 promociones) son **supuestos del modelo, no estimaciones de los datos**:
el histórico no identifica qué clientes recibieron promociones dirigidas.

Los ROI absolutos dependen enteramente de ese supuesto. Lo que sí es robusto es la
*forma* de las curvas: la existencia del desplome por saturación y los rendimientos
marginales decrecientes. Calibrar ese parámetro requiere el piloto en modo sombra
que el proyecto propone como siguiente paso.

Con 2 promociones y la receptividad media de los agentes, el 0.35 equivale a reducir la
fuga un 35% entre los tratados, el doble del mejor resultado de los experimentos de campo
de Ascarza (2018, *JMR*). Por eso el análisis costo/beneficio usa 0.10 como valor realista
y deja el 0.35 como escenario optimista. El parámetro es ajustable por escenario
(`efecto_promo`), igual que el umbral de saturación.
