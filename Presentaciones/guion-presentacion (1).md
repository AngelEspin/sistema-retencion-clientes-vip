# Guion de defensa: Sistema multiagente para segmentación de clientes y optimización de retención en cadenas de farmacias

**Ponentes:** Angel Josué Espín Lumbano (Angel) y Carlos Alberto Ramírez Celi (Carlos)
**Tutor:** Allan Roberto Avendaño Sudario · **Profesor:** Carlos Enrique Cedeño Zamora
**Duración:** 10 minutos de exposición, más preguntas del tribunal (ritmo objetivo: 130 a 140 palabras por minuto)
**Diapositivas:** `entregables/Defensa – Sistema multiagente para retención de clientes VIP.pptx` (14 diapositivas)
**Fuente de las cifras:** re-ejecución del 02/10/2026 (`PROGRESO.md`, Paso 8; `data/artifacts/`; `entregables/Entregable - Analisis costo-beneficio y validacion.md`)

> **Nota de versión.** Este guion reemplaza al de 5 minutos de la presentación de agosto. Aquel describía una arquitectura que no se construyó (Mesa, DMS CDC, Glue, Fargate, SageMaker Spot, Control Room), un universo de 2 millones de clientes y dos marcas, un costo de USD 75/mes, y daba por cumplidos objetivos que entonces no estaban medidos. Esta versión describe lo que se construyó y se midió. La anterior sigue en el historial de git (commit `9737da2`).

---

## Reglas del discurso

1. **Lo simulado se dice "simulado".** El −15,05 %, el 6,08 y el 1,39 salen del efecto del diseño (0,35), no de una medición. Con el efecto realista (0,10) son −4,3 %, 1,75 y 0,40.
2. **El umbral de saturación (3) y el decaimiento (0,55) son supuestos del modelo.** Lo robusto es la forma de la curva y que focalizar rinde más que la campaña masiva.
3. **La nube es AWS emulado (LocalStack).** Se perdió el acceso a AWS Academy. No decir "desplegado en AWS" sin ese matiz.
4. **Frases que no se dicen:** "demostramos", "lista para producción", "cero fuga de información", "reducción efectiva". Se dice: "la simulación indica", "listo para piloto", "sin fuga temporal", "reducción simulada".

## Tiempos

| Tramo | Ponente | Diapositivas | Minutos |
|---|---|---|---|
| 0:00 – 5:00 | Angel | 1 a 7: problema, objetivo, alternativas, diseño, datos, modelo | 5:00 |
| 5:00 – 10:00 | Carlos | 8 a 14: simulador, hallazgo, resultados, economía, piloto, conclusiones | 5:00 |

Ritmo medido sobre este texto: 126 palabras por minuto en promedio (1 265 palabras en 10 minutos), con un máximo de 139 en la diapositiva 6. Si el tiempo aprieta, se recorta en la 4 y la 5, que son contexto; no se acelera.

---

### [0:00 – 0:30] Diapositiva 1: Portada
* **Ponente:** Angel
* **Se ve:** título, autores, tutor y profesor.
* **Guion:**
  > "Buenos días, miembros del tribunal. Soy Angel Espín y, junto a Carlos Ramírez, presentamos nuestro proyecto de titulación: un sistema multiagente para segmentar clientes y optimizar estrategias de retención en una cadena de farmacias ecuatoriana. Nuestra idea es sencilla: decidir antes de gastar a quién retener, con cuánta intensidad y con qué presupuesto. En diez minutos veremos cómo lo construimos, qué encontramos y cuáles son sus límites."

### [0:30 – 1:25] Diapositiva 2: El problema
* **Ponente:** Angel
* **Se ve:** 80,3 %; 682 sucursales, 72,5 M líneas de venta, 39,1 M comprobantes, 3,1 M clientes; 18,9 % de fuga VIP; 19 de 19 promociones masivas.
* **Guion:**
  > "Trabajamos con una cadena de operación nacional: 682 sucursales y, entre julio de 2025 y junio de 2026, 72,5 millones de líneas de venta, 39,1 millones de comprobantes y 3,1 millones de clientes identificados. El dato que motiva el proyecto: el 20 % de los clientes genera el 80,3 % del ingreso, por encima del 73 % que reporta la literatura para bienes de consumo empacados. Y ese segmento se pierde: el 18,9 % de los VIP no volvió a comprar en los 90 días siguientes. Aun así, las 19 promociones del año fueron masivas: a quién dirigir una campaña, con qué intensidad y con cuánto presupuesto se decide por experiencia, sin estimar el efecto."

### [1:25 – 2:00] Diapositiva 3: Objetivo general
* **Ponente:** Angel
* **Se ve:** objetivo general y los cinco objetivos específicos de la propuesta aprobada.
* **Guion:**
  > "Nuestro objetivo general fue desarrollar un sistema multiagente de simulación que segmente a los clientes con RFM y estime el impacto de las estrategias de retención sobre la fuga y el margen de los VIP. Lo desagregamos en cinco objetivos: segmentar; predecir el abandono mejor que la regla de recencia; simular campañas con rendimientos decrecientes y saturación; desplegar una API y un tablero que respondan en menos de diez minutos; y evaluar la viabilidad económica, dejando diseñado el piloto."

### [2:00 – 2:45] Diapositiva 4: Alternativas de solución
* **Ponente:** Angel
* **Se ve:** tabla de cinco alternativas por cinco criterios; el límite asumido de A5.
* **Guion:**
  > "Comparamos cinco alternativas con cinco criterios. Las reglas RFM y el modelo predictivo describen o predicen, pero no simulan la respuesta a una intervención. La cadena de Markov trata como iguales a todos los clientes de un estado. El modelo de efecto incremental necesita campañas pasadas con grupo de control, que la cadena no tiene. Solo la combinación de modelo predictivo y simulación basada en agentes cumplió los cinco. Y declaramos su límite: el efecto de una promoción entra como parámetro, con análisis de sensibilidad, hasta que un piloto lo mida."

### [2:45 – 3:20] Diapositiva 5: Diseño conceptual
* **Ponente:** Angel
* **Se ve:** flujo por lotes mensual (cinco etapas) y consulta bajo demanda (cuatro pasos), unidos por artefactos en S3.
* **Guion:**
  > "El diseño separa dos flujos. Un lote mensual transforma el histórico en una población de agentes: ingesta, segmentación RFM, modelo de abandono y población de agentes. Y una consulta bajo demanda: el usuario comercial define presupuesto, costo, intensidad y criterio; la API llama al simulador y en segundos devuelve la fuga evitada, el margen, el retorno y los clientes saturados. Ambos flujos comparten artefactos a través de S3."

### [3:20 – 4:05] Diapositiva 6: Datos y segmentación RFM
* **Ponente:** Angel
* **Se ve:** 22,2 GB a 1,49 GB; cuentas genéricas; umbral USD 75,57; 619 963 VIP.
* **Guion:**
  > "El archivo de ventas pesaba 22,2 gigabytes y no cabía en memoria: lo leímos por bloques con DuckDB, conservamos 11 de 40 columnas y lo guardamos en Parquet por marca y mes, 1,49 gigabytes. Excluimos cuatro cuentas genéricas, como el consumidor final, que concentraban el 40 % de los comprobantes. Calculamos el margen con el costo efectivo, porque retener vale por lo que la cadena realmente gana. No hubo muestreo: analizamos a los 3,1 millones de clientes. Con RFM definimos como VIP al 20 % de mayor gasto: umbral de 75,57 dólares al año y 619 963 clientes al corte del 1 de julio."

### [4:05 – 5:00] Diapositiva 7: Modelo de abandono
* **Ponente:** Angel
* **Se ve:** barras de validación temporal; AUC 0,875 frente a 0,825.
* **Guion:**
  > "Para cada VIP estimamos la probabilidad de no comprar en los 90 días siguientes, con 11 variables calculadas solo con información anterior al corte, usando HistGradientBoosting. La decisión clave fue la validación temporal: entrenamos con 446 821 VIP al 1 de enero de 2026 y evaluamos con 538 982 al 1 de abril, con etiquetas de trimestres distintos; una partición aleatoria habría inflado el desempeño. El AUC fue 0,875 frente a 0,825 de la regla de recencia: cinco centésimas más, y muy por encima del mínimo de 0,75. Una advertencia: el modelo sobreestima la fuga en la lista focalizada, 73,8 % predicho frente a 64,4 % observado; lo recalibraremos antes del piloto. Carlos les explicará el simulador."

### [5:00 – 5:50] Diapositiva 8: Simulador basado en agentes
* **Ponente:** Carlos
* **Se ve:** los cuatro atributos del agente (pᵢ, mᵢ, rᵢ, kᵢ) y las cuatro reglas de respuesta.
* **Guion:**
  > "Gracias, Angel. Cada uno de los 538 982 VIP se convierte en un agente con cuatro atributos: su probabilidad de abandono, que viene del modelo; su margen trimestral; su receptividad a las promociones, entre 0,30 y 1 según su historial; y las promociones recibidas. Con presupuesto fijo, más promociones por cliente significan menos clientes alcanzados. La respuesta tiene rendimientos decrecientes, porque cada promoción aporta el 55 % de la anterior, y saturación desde la tercera. Cada corrida simula dos mundos con el mismo azar por agente, con y sin campaña, de modo que la diferencia es el efecto, sin ruido de muestreo."

### [5:50 – 6:40] Diapositiva 9: Hallazgo central
* **Ponente:** Carlos
* **Se ve:** ROI sobre margen 6,12 / 6,29 / 0,00 / 0,00 con presupuesto fijo de USD 5 000; recomendación de dos promociones.
* **Guion:**
  > "Este es el hallazgo central. Con presupuesto fijo de cinco mil dólares, variando solo la insistencia por cliente, el retorno sobre margen pasa de 6,12 con una promoción a 6,29 con dos, y cae a cero con tres: 1 388 clientes saturados. Un modelo agregado, como una cadena de Markov, trabaja con promedios y disuelve esta no linealidad; el modelo de agentes la hace visible cliente por cliente. La recomendación operativa: no más de dos promociones por cliente al trimestre. Y somos transparentes: el efecto base de 0,35 y el umbral de tres son supuestos del diseño; lo robusto es la forma de la curva."

### [6:40 – 7:35] Diapositiva 10: Resultados frente a los criterios
* **Ponente:** Carlos
* **Se ve:** tabla de siete criterios con su resultado y el pie de página sobre el efecto 0,35.
* **Guion:**
  > "Contrastamos lo medido con los criterios. El ingreso del segmento VIP fue 80,26 %, apenas por encima del rango de 70 a 80 %. El AUC fue 0,8753 y superó a la recencia por cinco centésimas. Cada escenario responde en menos de un segundo; en la nube emulada, 0,18 segundos en caliente. Con 139 000 dólares por trimestre, la fuga VIP baja 15,05 %, con retornos de 6,08 sobre ingreso y 1,39 sobre margen; aclaro que esas cifras son simuladas con el efecto del diseño, 0,35, y solo el piloto las confirma. El resultado más sólido es el último: con un efecto realista de 0,10, la campaña focalizada genera 4,3 veces el margen de una masiva con el mismo presupuesto."
* **Ajuste recomendado a la diapositiva:** ver la lista del final (estados "Cumple *", marca de criterios fijados con el valor conocido y fila de calibración).

### [7:35 – 8:25] Diapositiva 11: Viabilidad económica
* **Ponente:** Carlos
* **Se ve:** VPN USD 289 006; recuperación 4,2 meses; escala del efecto con 0,10, 0,25 y 0,35.
* **Guion:**
  > "En la evaluación económica a 36 meses, el sistema frente a la práctica actual, en el escenario realista, tiene un valor presente neto de 289 006 dólares y se recupera en 4,2 meses. En el pesimista no se recupera: VPN de menos 34 876. La campaña de 139 000 dólares por trimestre solo se paga si el efecto real de una promoción es de al menos 0,25. El diseño suponía 0,35; un valor realista, anclado en la literatura de campo, es cercano a 0,10. Por eso el valor del sistema está en dimensionar la campaña antes de gastar: con el efecto realista, el presupuesto óptimo ronda los 4 000 dólares por trimestre."

### [8:25 – 9:05] Diapositiva 12: Identificación del efecto y ética
* **Ponente:** Carlos
* **Se ve:** tres vías para el efecto; 14 479 clientes, 20 % de control, 4,3 % de efecto mínimo detectable, 80 % de potencia; cuadro LOPDP.
* **Guion:**
  > "El histórico no registra a quién se dirigió una acción de retención: el efecto causal no puede estimarse de los datos. El simulador lo acota con análisis de sensibilidad; solo un experimento de campo lo mide: 14 479 clientes de una región, con control aleatorio del 20 % durante un trimestre, y 80 % de potencia para detectar reducciones de la fuga de 4,3 %. Como la compra en una farmacia revela salud, aplicamos la LOPDP: seudonimización en origen, minimización de columnas, almacenamiento cifrado y opción de no recibir promociones."

### [9:05 – 9:45] Diapositiva 13: Conclusiones
* **Ponente:** Carlos
* **Se ve:** cuatro respuestas (a quién, quién se va, con qué intensidad, con qué presupuesto) y la recomendación del piloto.
* **Guion:**
  > "Respondimos cuatro preguntas. A quién retener: al 20 % que genera el 80 % del ingreso. Quién se va: AUC de 0,875 con validación temporal. Con qué intensidad: no más de dos promociones al trimestre; focalizar rinde 4,3 veces el margen de la masiva. Con qué presupuesto: 139 000 dólares solo se justifican con un efecto de al menos 0,25; mientras no se mida, operar cerca de 4 000. Todo responde en menos de un segundo, sin servidor, validado en AWS emulado. Recomendamos el piloto antes de escalar."
* **Ajuste recomendado a la diapositiva:** la tarjeta "Con qué presupuesto" dice hoy "Escenarios en menos de un segundo"; debe decir lo que se dice aquí.

### [9:45 – 10:00] Diapositiva 14: Cierre
* **Ponente:** Carlos
* **Guion:**
  > "Muchas gracias. Quedamos atentos a sus preguntas."

---

## Cifras de respaldo

| Cifra | Valor | Fuente |
|---|---|---|
| Ingreso del 20 % VIP | 80,26 % (sin 4 cuentas genéricas) | `rfm_resumen_2026-07-01.json` |
| Cuentas genéricas excluidas | 4: 40,01 % de los comprobantes, 12,03 % del ingreso | `rfm_resumen_2026-07-01.json` |
| Líneas de venta / comprobantes / clientes | 72.509.368 / 39.115.519 / 3.099.811 | ingesta y `rfm_resumen_2026-07-01.json` |
| Parquet | 22,2 GB a 1,49 GB (14,9×) | `PROGRESO.md`, Paso 8 |
| Umbral VIP / VIP al 01/07/2026 | USD 75,57 / 619.963 | `rfm.parquet` |
| VIP del conjunto de prueba | 538.982 (20 % de 2.694.908 clientes con historial al 01/04/2026) | `churn_metricas.json` |
| AUC / regla de recencia | 0,8753 / 0,8254 | `churn_metricas.json` |
| Tasa de abandono en la prueba | 18,93 % | `churn_metricas.json` |
| Calibración | +1,13 pp en la población; en la lista focalizada 73,8 % predicho frente a 64,4 % observado (+9,5 pp) | costo-beneficio, secciones 9 y 10 |
| Saturación con USD 5.000 | ROI margen 6,12 / 6,29 / 0,00 / 0,00; saturados 0 / 0 / 1.388 / 1.041 | `escenarios.json` |
| Campaña de USD 139.000, efecto 0,35 | −15,05 % de fuga; ROI 6,08 (ingreso) y 1,39 (margen) | `escenarios.json` |
| Campaña de USD 139.000, efecto 0,10 | −4,3 % de fuga; ROI 1,75 y 0,40; pérdida de USD 83.355 por trimestre | `costo_beneficio.json` |
| Focalizada frente a masiva, efecto 0,10 | USD 55.137 frente a USD 12.836 (4,3 veces) | costo-beneficio, sección 4.1 |
| VPN, payback, TCO (realista) | USD 289.006; 4,2 meses; USD 24.212 | costo-beneficio, sección 5 |
| VPN pesimista / con regla de recencia / corregido por calibración | −USD 34.876 / USD 52.198 / USD 241.750 | costo-beneficio, secciones 6 y 10 |
| Efecto mínimo para pagar la campaña de USD 139.000 | 0,25 | costo-beneficio, sección 7 |
| Presupuesto óptimo con efecto 0,10 | USD 4.000 por trimestre; reducción máxima de fuga 9,7 % | costo-beneficio, sección 7 |
| Latencia | 0,3 a 0,6 s en local; Lambda emulada: p95 0,18 s en caliente, 7,8 s máximo en frío | `aws_mediciones.json` |
| Pruebas funcionales | 33 de 33 casos; paridad exacta nube = local | `pruebas_funcionales_*.json` |
| Costo de nube / operación | USD 0,45 al mes / USD 177 al mes (99,7 % horas de personal) | costo-beneficio, sección 3.3 |
| Piloto | 14.479 clientes, control 20 %, efecto mínimo detectable 4,3 %, 80 % de potencia, α = 5 % | costo-beneficio, sección 9.2 |

---

## Preguntas probables del tribunal

**1. Si el umbral de saturación y el decaimiento son supuestos, ¿cómo es un hallazgo?**
No es un hallazgo empírico sobre los clientes; es una consecuencia del modelo. Lo que muestra es que, si existe saturación individual, un modelo agregado no la ve y la decisión cambia (limitar a dos promociones). El umbral es un parámetro por escenario y el piloto debe registrar la exposición total de cada cliente para calibrarlo. Lo robusto es la forma de la curva y que focalizar rinde más que la masiva incluso con efectos muy pequeños.

**2. ¿Por qué reportan −15,05 % si con el efecto realista es −4,3 %?**
Porque USD 139.000 es el presupuesto mínimo que alcanza −15 % *bajo el efecto del diseño (0,35)*. Con el efecto realista no se alcanza con ningún presupuesto (máximo −9,7 %). Por eso proponemos reformular la meta: maximizar el margen neto de la retención y mantener el −15 % como meta condicionada a lo que mida el piloto.

**3. ¿De dónde sale el efecto de 0,10?**
De la literatura: Ascarza (2018), un experimento con una operadora de telefonía. Es un valor intermedio entre focalizar solo por riesgo (−4 % relativo) y el mejor decil por sensibilidad al tratamiento (−16 %). No es evidencia de farmacias; por eso se presenta con sensibilidad (0,04, 0,10 y 0,35). El sistema supera a la campaña masiva desde un efecto de 0,008 y a la regla de recencia desde 0,030.

**4. ¿Es realmente un sistema multiagente? Los agentes no interactúan.**
Cada agente conserva estado propio (probabilidad, margen, receptividad y contador de promociones) y la saturación se evalúa por individuo, no con promedios. No hay interacción entre agentes ni red social: es una simulación basada en agentes sin interacción. La propuesta contemplaba Mesa o SimPy; usamos NumPy y pandas vectorizados porque planificar 538.982 objetos uno por uno es incompatible con responder en segundos. La desviación está declarada en el entregable de stack.

**5. ¿Por qué 538.982 agentes si los VIP son 619.963?**
Son dos cortes distintos. Los 619.963 son el 20 % de los clientes con historial al 01/07/2026. Los 538.982 son el 20 % de los 2.694.908 clientes con historial al 01/04/2026, el corte que define el conjunto de prueba con etiqueta observada de abril a junio.

**6. ¿Qué tan bien calibrado está el modelo?**
En la población, bien: sesgo medio de +1,13 pp. En la lista focalizada no: predice 73,8 % de fuga y se observa 64,4 % (+9,5 pp), por encima del límite de 2 pp del criterio T3. Corregido con la fuga observada, el VPN realista baja de USD 289.006 a USD 241.750 y sigue siendo positivo. Se recalibrará por decil antes del piloto.

**7. ¿Está desplegado en AWS?**
En AWS emulado: LocalStack 4.14 en Docker sobre WSL2, porque se perdió el acceso a AWS Academy. Allí pasaron 33 de 33 pruebas con paridad exacta con el simulador local; en caliente el p95 fue de 0,18 s y el arranque en frío máximo de 7,8 s. LocalStack Community no aplica IAM ni limita la CPU como una Lambda de 2 GB, así que los tiempos son optimistas y la seguridad solo se verificó en su configuración. Repetirlo en una cuenta real es pendiente. Además, el tablero se sirve desde FastAPI en local: la Lambda expone las siete rutas de la API, sin el tablero.

**8. ¿Cuánto cuesta operarlo?**
USD 0,45 al mes de nube, con la duración medida en LocalStack y los precios de lista de AWS. La operación total es de USD 177 al mes, el 99,7 % en horas de personal, y el TCO a tres años es de USD 24.212. El límite de la propuesta era USD 80 al mes de nube.

**9. ¿Y si el negocio ya usa la regla de recencia, no la campaña masiva?**
El VPN realista baja a USD 52.198, que sigue siendo positivo, porque esa regla ya captura buena parte del valor de focalizar. En el escenario pesimista el sistema no se paga (−USD 34.876) y solo se pagaría con un efecto superior a 0,114.

**10. ¿Todos los criterios se fijaron antes de medir?**
No todos. Los de la propuesta (P) y los fijados el 02/10 antes de las pruebas (D) son de aceptación. Los marcados D-obs se fijaron con el valor ya conocido y se reportan como evidencia complementaria: la mejora del AUC (≥ 0,03), la calibración, el PSI y el margen frente a la masiva (≥ 2 veces). La enmienda que cambió el instrumento de AWS a LocalStack se registró antes de medir y sin modificar umbrales.

**11. ¿Cómo garantizan que no hay fuga de información?**
Las variables y la definición de VIP de cada corte se calculan solo con datos anteriores a ese corte, y la etiqueta se observa después. Entrenamos con el corte del 01/01/2026 y probamos con el del 01/04/2026. Una partición aleatoria pondría al mismo cliente a ambos lados y daría un AUC más alto y engañoso.

**12. ¿Qué pasa con la privacidad? Es información de salud.**
Los identificadores llegan seudonimizados de origen; el histórico no se publica y los datos están excluidos del repositorio. Conservamos 11 de las 40 columnas, sin género ni edad, y el almacenamiento en la nube es privado y cifrado. Una precisión: el Parquet local conserva el código de producto, que ningún modelo usa; si el tribunal lo pide, se elimina de la ingesta con un cambio de una línea. El piloto ofrece la opción de no recibir promociones y se registra en la evaluación de impacto de la LOPDP.

**13. ¿Por qué un piloto de 14.479 clientes con control del 20 %?**
Es una región con cerca del 25 % de la lista focalizada. Con ese control y la fuga observada (64,4 %), el piloto detecta efectos de 4,3 % relativo con 80 % de potencia, suficiente para el efecto realista (9,9 %) pero no para el pesimista (4,0 %). Si el efecto resultara cercano al pesimista, se extiende a una segunda región (3,1 %) o se sube el control a 30 % (3,8 %).

**14. El ingreso del VIP es 80,26 %, fuera del rango de 70 a 80 %. ¿Se cumple?**
Lo supera por 0,26 puntos porcentuales; refuerza la premisa, no la debilita. El resultado depende de excluir las cuatro cuentas genéricas: con ellas sería 82,63 %.

**15. ¿Por qué la regla de recencia como línea base?**
Es la regla simple que el negocio ya usa para decidir a quién contactar. El modelo debe superarla; lo hace por 0,05 de AUC (0,8753 frente a 0,8254). Las comparaciones de negocio se hacen contra la campaña masiva, que es la práctica real: las 19 promociones del año fueron masivas.

---

## Ajustes pendientes en las diapositivas

Estos cambios hacen que lo escrito en pantalla coincida con lo que se dice y con los entregables:

1. **Diapositiva 10.**
   - Cambiar "Cumple *" por "Simulado *" en las filas de reducción de fuga y de retorno; el entregable las clasifica como simuladas hasta el piloto.
   - Cambiar "En el límite" por "+0,26 pp sobre el rango".
   - Marcar con † los criterios fijados con el valor ya conocido (mejora del AUC y margen frente a la masiva).
   - Añadir una fila de calibración en la lista focalizada: +9,5 pp frente a ≤ 2 pp, no cumple.
2. **Diapositiva 11.** Añadir "Pesimista: VPN −USD 34 876" y cambiar "evidencia de campo" por "literatura (Ascarza, 2018)".
3. **Diapositiva 13.** Cambiar la tarjeta "Con qué presupuesto" por: "USD 139 000 solo se justifican con efecto ≥ 0,25; mientras no se mida, cerca de USD 4 000".
4. **Diapositiva 12.**
   - Retitular los puntos 1 y 2 como "acotar" y el 3 como "medir": solo el experimento de campo identifica el efecto.
   - Sustituir "sin categorías de producto" por "sin categorías terapéuticas", o eliminar `producto_id` de la ingesta ([csv_to_parquet.py](../src/ingest/csv_to_parquet.py), líneas 78 y 113) y repetir la ingesta de unos 3 minutos.
5. **Diapositivas 3 y 5.** Aclarar que la API corre en Lambda emulada y que el tablero se sirve desde FastAPI en local. Cambiar "DuckDB por flujo" por "DuckDB en streaming".
6. **Diapositiva 14.** Confirmar los correos: la propuesta y los entregables usan `angelumb@espol.edu.ec` y `carlrami@espol.edu.ec`, no `angel.espin@…` ni `carlos.ramirez@…`.
