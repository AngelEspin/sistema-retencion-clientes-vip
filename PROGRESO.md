# Progreso de implementación

**Proyecto:** Sistema Multiagente para la Segmentación de Clientes y Optimización de Retención
**Integrantes:** Carlos Alberto Ramírez Celi · Angel Josué Espín Lumbano
**Inicio de implementación:** 2026-08-24

Registro de lo construido, las decisiones tomadas y los problemas encontrados.

---

## Resumen de resultados

| Objetivo del guion | Meta | Medido | Estado |
|---|---|---|---|
| Concentración de ingreso en el 20% VIP | 70–80% | **80.26%** sin cuentas genéricas (82.63% con ellas) | Cumplido; supera el rango por 0.26 pp |
| AUC del modelo de abandono | ≥ 0.75 | **0.8753** | Superado |
| Respuesta de escenario | < 10 min | **0.3–0.6 s** en local | Superado |
| Reducción de fuga trimestral VIP | −15% | **−15.05%** con USD 139.000, solo con el efecto del guion | Condicionado al efecto real (ver Paso 8) |
| ROI de retención | 3:1 | **6.08:1** sobre ingreso, **1.39:1** sobre margen | Solo sobre ingreso y con el efecto del guion |

Las cifras de esta tabla son las de la re-ejecución del 02/10/2026 (Paso 8), que corrigió
cuatro defectos que inflaban o deformaban los resultados anteriores.

### Vigencia de las cifras

Los Pasos 1 a 7 conservan, como registro histórico, las cifras de la primera ejecución
(24/08–24/09/2026). Donde difieren, **vale el Paso 8**:

| Concepto | Primera ejecución (Pasos 2–7) | Vigente (Paso 8) |
|---|---|---|
| Parquet de ventas | 1.25 GB (17.8×) | 1.49 GB (14.9×): ahora conserva `p_costo` |
| Ingesta | 1.7 min | 2.9 min |
| Clientes identificados / VIP | 3.099.815 / 619.963 | 3.099.811 / 619.963 (se excluyen 4 cuentas genéricas) |
| Umbral VIP | USD 75.58 | USD 75.57 |
| Concentración del ingreso en el 20% VIP | 82.63% | 80.26% |
| AUC / AP / Brier | 0.8745 / 0.6633 / 0.1007 | 0.8753 / 0.6632 / 0.1005 |
| Agentes simulados | 538.983 | 538.982 |
| Presupuesto mínimo para −15% de fuga | USD 150.000 (−18.28%, ROI 5.04) | USD 139.000 (−15.05%, ROI 6.08 ingreso / 1.39 margen) |
| Latencia local | 1–3 s | 0.3–0.6 s |
| Nube | AWS Academy (Lambda real) | LocalStack 4.14.0: se perdió el acceso a AWS Academy |
| Exposición de la Lambda | Pendiente de decisión | Function URL `AWS_IAM` (verificada en LocalStack) |

Las cifras de reducción de fuga y ROI de la tabla anterior dependen del efecto de una
promoción que el guion supone en 0.35. Con el efecto realista (0.10) la campaña de
USD 139.000 reduce la fuga 4.3% y retorna 1.75 de ingreso y 0.40 de margen por dólar. El
umbral de saturación (3) y el decaimiento marginal (0.55) también son parámetros del
modelo, no estimaciones de los datos.

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

**Actualización:** la implementación final no usa Mesa. El simulador es vectorizado
(NumPy y pandas), porque la planificación objeto por objeto de Mesa sobre 538.982 agentes
es incompatible con una respuesta interactiva. La semántica multiagente se conserva: cada
agente mantiene su probabilidad de fuga, su gasto, su receptividad y su contador de
promociones. Ningún módulo importa `mesa`.

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

> **Resuelto en el Paso 8:** se adoptó la opción 2 (Function URL con `AWS_IAM`), verificada
> en LocalStack. En una cuenta real de AWS la petición sin firma debe devolver 403; ahí
> aún no se ha comprobado.

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

## Paso 8 — Re-ejecución completa, correcciones y análisis costo/beneficio (02/10/2026)

El pipeline se volvió a correr de punta a punta sobre los crudos (ahora en
`data/Unprocessed/`) con [`ejecutar_pipeline.py`](ejecutar_pipeline.py), que registra
tiempo y RAM por etapa en `data/artifacts/tiempos_pipeline.json`:

| Etapa | Duración | Pico de RAM |
|---|---|---|
| Ingesta (72.509.368 filas, 22.2 GB → 1.49 GB) | 2.9 min | — |
| RFM | 1.8 min | 6.7 GB |
| Modelo de abandono | 2.1 min | 8.1 GB |
| Simulación de escenarios | 0.1 min | 0.3 GB |

### Defectos encontrados y corregidos

| Defecto | Efecto | Corrección |
|---|---|---|
| **4 cuentas genéricas** (consumidor final, una cuenta RUC) compran en 114–698 sucursales | 40% de los tickets y 12% del ingreso tratados como "clientes"; encabezaban el ranking por valor | Regla `MAX_SUCURSALES_PERSONA = 100` en RFM y modelo; la concentración VIP pasa de 82.63% a 80.26% |
| `propension_promo` no llegaba a `scores_vip.parquet` | Todos los agentes con receptividad 0.75 constante, sin aviso | Se exporta la columna; receptividad heterogénea, media 0.62 |
| `monetario` cubre 274 días pero se dividía como si fuera un año | Valor trimestral del cliente subestimado 25% | Columna `dias_ventana` |
| `max(1, …)` en la asignación | Con presupuesto menor que una asignación, gastaba más de lo presupuestado | Sin piso; cubierto por prueba funcional |

Además: la ingesta conserva `p_costo` (costo efectivo, ya neto de lo que financia el
proveedor), lo que permite valorar todo a **margen** (25.37% total, 24.69% VIP) y no a
ingreso. El simulador agrega los criterios `aleatorio` y `recencia` como líneas base, los
parámetros `efecto_promo` y `umbral_saturacion` por escenario, y un cálculo vectorizado
2.5× más rápido, verificado idéntico al anterior sobre los artefactos previos.

### Costo/beneficio

[`src/evaluacion/costo_beneficio.py`](src/evaluacion/costo_beneficio.py) compara la
política del sistema contra la práctica actual (las 19 promociones del año son masivas)
con el mismo presupuesto, 10 semillas por configuración:

| Escenario | Δ margen/trimestre | TCO 3 años | VPN | Payback |
|---|---|---|---|---|
| Pesimista | USD 4.290 | USD 63.366 | −USD 34.876 | no se recupera |
| Realista | USD 42.302 | USD 24.212 | USD 289.006 | 4.2 meses |
| Optimista | USD 234.788 | USD 20.816 | USD 3.345.856 | 3.1 meses |

La campaña de USD 139.000 solo es rentable si el efecto base real es ≥ 0.25. Con el
efecto realista anclado en la literatura (0.10), el presupuesto óptimo es ~USD 4.000 por
trimestre y la meta de −15% no se alcanza con ningún presupuesto (máximo −9.7%).

**Calibración en la lista focalizada.** El sesgo medio del modelo es +1.13 pp, pero se
concentra en el decil de mayor riesgo (85.9% predicho, 76.1% observado), y el 69% de la
lista del sistema está en ese decil. En la lista, la fuga predicha es 73.8% y la observada
64.4%. Corrigiendo el margen con la fuga observada, el Δ realista baja de USD 42.302 a
USD 35.841 por trimestre y el VPN de USD 289.006 a USD 241.750 (sigue positivo). Con la
fuga observada, el MDE del piloto regional sube de 3.5% a 4.3%: cumple T6 (≤ 5%) pero ya
no detecta el efecto pesimista (4.0%). Cálculo en `calibracion_lista()` de
`costo_beneficio.py`; las figuras del entregable salen de `src/evaluacion/figuras_cb.py`.

### Validación

Criterios registrados antes de medir en `src/evaluacion/criterios_validacion.json`.
[`infra/pruebas_funcionales.py`](infra/pruebas_funcionales.py): 33/33 casos en local
(rutas, paridad exacta, 14 entradas inválidas → 422, 6 casos borde). La API local y el
dashboard se verificaron por HTTP.

### Nube: AWS emulado en local (LocalStack)

Se perdió el acceso a AWS Academy Learner Lab. El despliegue se hace contra **AWS
emulado en local**: LocalStack 4.14.0 Community en Docker sobre WSL2 (Ubuntu 24.04),
levantado con [`infra/localstack/levantar_localstack.sh`](infra/localstack/levantar_localstack.sh).
Las versiones 2026.x de LocalStack exigen token de licencia; la 4.14.0 es la última
Community que corre sin cuenta.

| Paso | Resultado |
|---|---|
| `desplegar.py --localstack` | Bucket privado y cifrado, Lambda con las 7 rutas, Function URL `AWS_IAM`; paquete de 73.4 MB (sin capas en Community: pandas, numpy y pyarrow empaquetados con las versiones locales) |
| `pruebas_funcionales.py --remoto` | 33/33 casos; paridad exacta con el simulador local |
| `prueba_carga.py` | Caliente p50 148 ms / p95 180 ms; arranque en frío máx. 7.8 s; 0 errores con 10×3 concurrentes |
| Petición sin firma a la Function URL | 200: LocalStack Community no aplica IAM (en AWS sería 403) |

La enmienda que cambia el instrumento (AWS → LocalStack) se registró en
`criterios_validacion.json` antes de medir; los umbrales no cambiaron. Para el costo,
la duración medida se duplica: LocalStack no limita la CPU como una Lambda de 2 GB.

Para retomar: `wsl -d Ubuntu-24.04 -u root -- bash infra/localstack/levantar_localstack.sh`
y mantener abierta una sesión de WSL (la distribución se apaga cuando no queda ninguna),
luego exportar `AWS_ENDPOINT_URL=http://localhost:4566` con credenciales `test`/`test`.

---

## Paso 9 — Tablero ampliado y versión estática (27/10/2026)

El tablero de `localhost:8080` mostraba cifras de la primera ejecución (82,63 %, 538 983
agentes, 1,25 GB, AUC 0,874, "Mesa", "respuestas 1–3 s"), presentaba la nube como "AWS
SERVERLESS" y tenía fijo un presupuesto de USD 250 000 para la meta de −15 %. Se rehízo:

- **Datos del panel desde los artefactos.** `src/api/panel.py` arma las series agregadas
  (curva de concentración, ROC, calibración, efecto por promociones, políticas, economía de
  la campaña, flujo acumulado, tornado, VPN según el efecto, matriz de validación y piloto)
  y la API las sirve en `GET /v1/panel`. Ninguna cifra está escrita a mano.
- **Simulador con el efecto como control.** El tablero elige presupuesto, promociones por
  cliente, criterio y efecto (0,04, 0,10 o 0,35). `/v1/barrido` acepta ahora `efecto_promo`
  y `costo_promo_usd` (con los valores anteriores por defecto).
- **Versión estática.** `generar_pagina_estatica.py` precalcula 720 escenarios (5 min) y los
  incrusta con el panel en `web/index.html` (0,47 MB). Solo contiene agregados: ningún ID de
  cliente. Se verificó que la versión en vivo y la estática dan cifras idénticas para siete
  combinaciones y para el barrido.
- **Nube descrita como es.** La sección de arquitectura dice que el tablero y la API corren en
  local, que el manejador Lambda se valida en LocalStack sin tablero y que falta AWS real.

---

## Pendiente

- [x] Completar en el handler de Lambda las rutas `/v1/poblacion` y `/v1/simular/pasos`
- [x] Desplegar la versión nueva y medir latencia y costo (en AWS emulado, LocalStack)
- [ ] Repetir latencia, arranque en frío y seguridad IAM en una cuenta real de AWS
- [x] Exponer la Lambda: Function URL con `AWS_IAM` (verificada en LocalStack)
- [ ] Backtest o piloto contra campañas reales ejecutadas (requiere datos de campañas,
      que no están en el dataset actual)
- [ ] Recalibrar el modelo por decil (p. ej., isotónica sobre un corte de validación, no
      sobre el de prueba) antes del piloto: en la lista focalizada el sesgo es +9.5 pp
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
