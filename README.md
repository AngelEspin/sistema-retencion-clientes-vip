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

| Objetivo | Meta | Medido |
|---|---|---|
| Concentración de ingreso en el 20% VIP | 70–80% | **82.63%** |
| AUC del modelo de abandono | ≥ 0.75 | **0.8745** |
| Respuesta de escenario | < 10 min | **1–3 s** |
| Reducción de fuga VIP | −15% | **−18.28%** (con USD 150.000) |
| ROI de retención | 3:1 | **5.04:1** en ese punto |

Sobre **72.5 millones de transacciones** (22.2 GB) de 3.1 millones de clientes en 682
sucursales, a lo largo de 12 meses.

## El hallazgo central: la saturación de promociones

Un modelo agregado —una cadena de Markov, por ejemplo— asume homogeneidad y trata a
todos los VIP por igual. El simulador basado en agentes captura una no linealidad
individual que el promedio disuelve: **el cliente que recibe tres promociones en un
mes se satura y deja de responder por completo**.

Con presupuesto fijo, variando solo la insistencia por cliente:

| Promociones por cliente | ROI | Clientes saturados |
|---|---|---|
| 1 | 20.64 | 0 |
| 2 | **20.70** | 0 |
| **3** | **0.00** | **1.388** |
| 4 | 0.00 | 1.041 |

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
infra/lambda_handler.py         Versión serverless para AWS Lambda
descargar_datos.py              Descarga del dataset desde Google Drive (OAuth2)
generar_diagrama.py             Genera el PDF gráfico de arquitectura
PROGRESO.md                     Registro de implementación, decisiones y problemas
```

## Reproducir

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt

./.venv/Scripts/python descargar_datos.py              # (1ª vez) desde Google Drive
./.venv/Scripts/python src/ingest/csv_to_parquet.py    # ~2 min sobre 22 GB
./.venv/Scripts/python src/features/rfm.py
./.venv/Scripts/python src/models/churn.py
./.venv/Scripts/python src/simulation/simulador.py

cd src && ../.venv/Scripts/python -m uvicorn api.main:app --port 8080
```

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
