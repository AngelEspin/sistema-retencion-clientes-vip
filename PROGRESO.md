# Progreso de implementación

**Proyecto:** Sistema Multiagente para la Segmentación de Clientes y Optimización de Retención
**Integrantes:** Carlos Alberto Ramírez Celi · Angel Josué Espín Lumbano
**Inicio de implementación:** 2026-08-24

Registro de lo construido, las decisiones tomadas y los problemas encontrados.

---

## Resumen de resultados

| Objetivo del guion | Meta | Medido | Estado |
|---|---|---|---|
| Concentración de ingreso en el 20% VIP | 70–80% | **82.63%** | Superado |
| AUC del modelo de abandono | ≥ 0.75 | **0.8745** | Superado |
| Respuesta de escenario | < 10 min | **1–3 s** | Superado |
| Reducción de fuga trimestral VIP | −15% | **−18.28%** con USD 150.000 | Alcanzable, pero no con presupuestos pequeños |
| ROI de retención | 3:1 | **5.04:1** en ese mismo punto | Superado |

---

## Restricciones reales del entorno

| Restricción | Valor medido | Consecuencia |
|---|---|---|
| Histórico de ventas | **22.2 GB** en un CSV | Prohibido cargar en memoria; todo en streaming |
| Espacio libre en disco | **11 GB** (disco al 96%) | El Parquet debe comprimir agresivamente |
| RAM | 31.4 GB (≈16 libres) | Suficiente, pero exige acotar el pico por etapa |

---

## Inventario de datos

| Archivo | Tamaño | Contenido |
|---|---|---|
| `Datos/ventas_anonimizado-001.csv` | 22.2 GB | Transacciones línea a línea, 40 columnas |
| `Datos/clientes_anonimizado.csv` | 150 MB | Maestro de clientes |
| `Datos/catalogo_filtrado.csv` | 3.2 MB | Productos con 5 niveles de categoría |
| `Datos/sucursales_anonimizado.csv` | 55 KB | 682 sucursales |

**Rango temporal:** 2025-07-01 → 2026-06-30 (12 meses).

---

## Paso 1 — Entorno ✅

Entorno virtual con **Python 3.13.2**. Dependencias: `duckdb 1.5.5`, `pyarrow 25.0.1`,
`mesa 3.5.1`, `scikit-learn 1.9.0`, `pandas 3.0.5`, `fastapi`, `boto3`, `networkx`.

**Nota:** `mesa 3.5.1` importa `networkx` sin declararlo como dependencia obligatoria.
Hubo que añadirlo a mano.

---

## Paso 2 — Ingesta a Parquet particionado ✅

**Script:** [`src/ingest/csv_to_parquet.py`](src/ingest/csv_to_parquet.py)

Reproduce localmente el tramo que en la arquitectura de la tesis hace
**DMS CDC → S3 → Glue**.

| Métrica | Valor |
|---|---|
| Filas procesadas | **72.509.368** |
| Tamaño resultante | **1.25 GB** (desde 22.2 GB) |
| Factor de compresión | **17.8×** |
| Duración | **1.7 min** |

### Decisiones

- **Proyección temprana de columnas: 40 → 11.** El mayor ahorro de disco. Se
  descartan costo contable, IVA y precios paralelos, que no alimentan ningún modelo.
- **Partición `(marca, anio_mes)`**, que es lo que permite leer solo el trozo relevante.

### Problemas resueltos

**1. El sniffer de CSV abortaba.** El origen trae filas fuera de estándar (nombres de
producto con comas y comillas sueltas). Se fijaron `delim`, `quote` y `escape`
explícitamente con `strict_mode=false` y `null_padding=true`.

**2. El join con sucursales fallaba en silencio.** Se usó `s_id` como clave, que es un
entero interno del POS (`8689`). La clave real es **`s_nombre`** (`SUC_0491`). El fallo
no lanzaba error: producía un dataset completo y plausible con el 100% de las filas
marcadas `SIN_MARCA`, dejando inservible la dimensión de marca.

**3. Conteos inflados entre corridas.** `OVERWRITE_OR_IGNORE` no borra las particiones
previas: las mezcla. Una prueba de 200.000 filas devolvía 399.549.

---

## Paso 3 — Segmentación RFM ✅

**Script:** [`src/features/rfm.py`](src/features/rfm.py)

| Métrica | Valor |
|---|---|
| Clientes | 3.099.815 |
| VIP (top 20% por valor) | 619.963 |
| Umbral VIP | USD 75.58 |
| Ingreso total | USD 261.105.010 |
| **Concentración de ingreso en VIP** | **82.63%** |
| Fuga VIP (>90 días sin compra) | 13.61% |

> **La premisa central del proyecto queda validada con datos reales.** El guion
> afirmaba 70–80%; la realidad es 82.63%, algo mejor de lo que se presentaba.

### Problema: tres intentos fallidos por memoria

Calcular `COUNT(DISTINCT ticket_id)` sobre 72M filas agrupadas por 3.1M clientes
agotó primero el disco y luego la RAM. La solución tuvo tres partes:

1. **Agregación en dos etapas.** Colapsar primero a nivel de ticket convierte el
   `DISTINCT` en un `COUNT(*)` trivial. Deja además una tabla de 39.1M tickets
   reutilizable.
2. **Procesamiento mes a mes.** Es exacto —un ticket nunca cruza el límite de un
   mes— y acota el pico de memoria a ~6M filas en vez de 72M.
3. **Separar agregación de scores.** Una sola sentencia obligaba a sostener a la vez
   el hash de 3.1M grupos y tres ordenaciones completas para los `NTILE`.
   También se sustituyó `MODE(marca)` por `ARG_MAX(marca, venta)`, de coste
   constante por grupo.

---

## Paso 4 — Modelo de abandono ✅

**Script:** [`src/models/churn.py`](src/models/churn.py)

Validación **temporal**, no aleatoria. Las variables se calculan solo con datos
anteriores al punto de decisión; la etiqueta se observa después:

```
ENTRENAMIENTO  corte 2026-01-01   etiqueta observada ene–mar 2026   446.821 VIP
PRUEBA         corte 2026-04-01   etiqueta observada abr–jun 2026   538.983 VIP
```

| Métrica | Valor | Objetivo |
|---|---|---|
| **AUC** | **0.8745** | ≥ 0.75 ✅ |
| Average precision | 0.6633 | — |
| Brier score | 0.1007 | — |
| Captura del decil de mayor riesgo | **40.26%** de todas las fugas | — |

Un split aleatorio habría dado un AUC más alto y engañoso, porque el mismo cliente
aparecería a ambos lados de la partición.

---

## Paso 5 — Simulador multiagente ✅

**Script:** [`src/simulation/simulador.py`](src/simulation/simulador.py)

Cada agente arranca con **su** probabilidad real de fuga (la predicha por el modelo)
y su propio historial. Cada corrida simula dos mundos con la misma semilla:
tratamiento y control.

### El fenómeno de saturación, demostrado

Presupuesto fijo de USD 5.000, variando la insistencia por cliente:

| Escenario | ROI | Reducción fuga | Clientes saturados |
|---|---|---|---|
| 1 promoción | 20.64 | 0.87% | 0 |
| 2 promociones | **20.70** | 0.67% | 0 |
| **3 promociones** | **0.00** | **0.00%** | **1.388** |
| 4 promociones | 0.00 | 0.00% | 1.041 |

El desplome a cero al llegar a la tercera promoción es exactamente la no linealidad
que un modelo agregado no puede representar. **Es el argumento central de la tesis,
ahora con números.**

### Corrección de diseño durante el desarrollo

La primera versión repartía "una ronda a todos, luego otra", y con 538K VIP elegibles
frente a presupuesto para 4.166 promociones la primera ronda agotaba el dinero: nadie
recibía una segunda y la saturación nunca aparecía. La asignación correcta modela el
compromiso real —**alcance frente a intensidad**—: con presupuesto fijo, insistir más
sobre cada cliente significa llegar a menos gente.

### Dos estimaciones del efecto, deliberadamente separadas

- **Pareada:** los mismos individuos en ambos mundos. Efecto causal exacto del modelo.
- **Entre grupos:** tratados contra control, lo único observable en una campaña real.

La segunda marcaba 1.49% de reducción en escenarios donde el efecto verdadero era
exactamente cero: puro ruido de partición. Reportar solo esa cifra haría pasar ruido
por resultado.

---

## Paso 6 — API de escenarios ✅

**Script:** [`src/api/main.py`](src/api/main.py)

| Endpoint | Función |
|---|---|
| `GET /health` | Estado y agentes cargados |
| `GET /v1/segmentacion` | Resumen RFM |
| `GET /v1/modelo` | Métricas de validación temporal |
| `POST /v1/simular` | Simula una campaña |
| `POST /v1/barrido` | Compara varios presupuestos |

**Tiempo de respuesta: 1–3 segundos** frente al objetivo de 10 minutos. La población
se carga una vez al arrancar y se reutiliza entre peticiones.

---

## Hallazgo principal: cuánto cuesta de verdad el −15%

El guion promete reducir la fuga trimestral un 15%, pero no dice con qué presupuesto.
El barrido lo cuantifica:

| Presupuesto | Cobertura VIP | Reducción fuga | ROI |
|---|---|---|---|
| USD 5.000 | 0.39% | 0.67% | 20.70 |
| USD 25.000 | 1.93% | 3.27% | 10.86 |
| USD 50.000 | 3.87% | 6.45% | 8.17 |
| USD 100.000 | 7.73% | 12.82% | 6.12 |
| **USD 150.000** | **11.60%** | **18.28%** | **5.04** |
| USD 250.000 | 19.33% | 25.25% | 3.85 |
| USD 1.000.000 | 77.31% | 40.37% | 1.40 |

**Los dos objetivos son compatibles**, pero solo a partir de ~USD 150.000 de campaña.
Con USD 5.000 se alcanza al 0.39% de los VIP: matemáticamente imposible mover la fuga
agregada un 15%. El ROI decrece con el presupuesto —rendimientos marginales
decrecientes—, así que la frontera útil está entre 150K y 250K.

---

## Discrepancias con la presentación

Tres puntos que conviene corregir en el guion antes de defender:

**1. Son tres marcas, no dos.** Además de MIA y SAN GREGORIO aparece **7 DIAS**
(355.187 transacciones, 7.573 clientes). La diapositiva 2 dice "dos marcas".

**2. El objetivo de −15% necesita contexto de presupuesto.** Tal como está enunciado
suena alcanzable con cualquier campaña. No lo es.

**3. El tamaño del efecto de una promoción es un supuesto, no una medición.**
`EFECTO_PROMO_BASE = 0.35` y el umbral de saturación en 3 están tomados del guion, no
estimados de los datos: el histórico no identifica qué clientes recibieron
promociones dirigidas. **Los ROI absolutos dependen enteramente de ese supuesto**; lo
que sí es robusto es la *forma* de las curvas —la existencia del desplome por
saturación y los rendimientos decrecientes—. Validar ese parámetro exige el piloto en
modo sombra que la diapositiva 12 propone como siguiente paso.

---

## Paso 7 — Despliegue serverless en AWS ✅

**Cuenta:** `<ACCOUNT_ID>` (AWS Academy Learner Lab) · **Región:** `us-east-1`

### Capa de datos — S3

Bucket `proyecto-retencion-vip-<ACCOUNT_ID>`:

```
artifacts/churn_metricas.json              369 B
artifacts/escenarios.json                  7.0 KiB
artifacts/rfm_resumen_2026-07-01.json      335 B
artifacts/scores_vip.parquet              15.9 MiB
curated/rfm/corte=2026-07-01/rfm.parquet 102.3 MiB
```

### Cómputo — AWS Lambda

Función `simulador-retencion`: Python 3.12, 2048 MB, timeout 120 s, rol `LabRole`.

**Por qué Lambda y no un contenedor permanente.** El uso real es esporádico: el
equipo comercial evalúa escenarios unas pocas veces al mes. Pagar por un servicio
encendido 24/7 contradice el límite de USD 80/mes. Con Lambda el coste en reposo es
exactamente cero.

**Cómo se evitó Docker.** En lugar de construir una imagen de contenedor se usó la
capa gestionada `AWSSDKPandas-Python312:20`, que ya trae pandas, numpy y pyarrow. El
paquete desplegado son **7.5 KB** de código propio, frente a los ~500 MB que habría
pesado una imagen equivalente. Despliegue en segundos en lugar de minutos.

La población de agentes se descarga de S3 en el arranque en frío y queda cacheada a
nivel de contenedor; las invocaciones siguientes la reutilizan.

### Verificación

| Endpoint | Resultado |
|---|---|
| `/health` | `{"status":"ok","agentes_cargados":538983}` |
| `/v1/simular` (USD 150.000) | reducción 18.28%, ROI 5.04, ingreso USD 756.703 |
| `/v1/barrido` | mínimo para −15%: **USD 150.000** |

**Los resultados en Lambda coinciden exactamente con los locales**, que es la prueba
de que el despliegue no alteró la lógica.

### Pendiente de tu decisión: el endpoint público

Intenté crear una **Function URL** con `auth-type NONE`, y quedó bloqueada por
política de seguridad: expondría la API a internet sin autenticación alguna, y esa
Lambda lee datos de clientes. La función está desplegada y verificada por invocación
directa; falta solo decidir cómo exponerla. Tres opciones, de menos a más abierta:

1. **Dejarla como está** — se invoca con `aws lambda invoke` o desde el SDK con
   credenciales IAM. Es lo más seguro y suficiente para una demo.
2. **Function URL con `auth-type AWS_IAM`** — URL HTTP, pero cada petición debe ir
   firmada con SigV4. Apto para Power BI o un backend propio.
3. **Function URL pública (`NONE`)** — cualquiera con el enlace accede. Solo si es
   para una demo puntual y se elimina después.

---

## Pendiente

- [ ] Exponer la Lambda (decisión de arriba)
- [ ] Paso 8 — Backtest contra campañas reales ejecutadas (requiere datos de campañas,
      que no están en el dataset actual)
- [ ] Control Room: tablero de deriva (PSI, caída de AUC, simulación vs realidad)
- [ ] Step Functions para orquestar el recálculo mensual de RFM

---

## Cómo reproducir

```bash
cd "Proyecto Maestria"
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt

./.venv/Scripts/python src/ingest/csv_to_parquet.py      # 22 GB -> Parquet   (~2 min)
./.venv/Scripts/python src/features/rfm.py               # segmentacion RFM
./.venv/Scripts/python src/models/churn.py               # modelo de abandono
./.venv/Scripts/python src/simulation/simulador.py       # escenarios + barrido

cd src && ../.venv/Scripts/python -m uvicorn api.main:app --port 8080
```

## Limpieza de AWS

```bash
aws lambda delete-function --function-name simulador-retencion --region us-east-1
aws s3 rb s3://proyecto-retencion-vip-<ACCOUNT_ID> --force --region us-east-1
```
