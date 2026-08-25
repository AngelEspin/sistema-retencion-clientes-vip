# Guión de Presentación: Sistema Multiagente para la Segmentación de Clientes y Optimización de Retención
**Integrantes:** Carlos Alberto Ramírez Celi y Angel Josué Espín Lumbano  
**Duración Estimada:** 5 Minutos (Ritmo: ~130-140 palabras por minuto)

---

### [0:00 - 0:25] Diapositiva 1: Portada
* **Visual:** Diapositiva de portada con el título, los nombres de Carlos y Angel, logos de la ESPOL y los íconos de AWS, Python, Mesa y Power BI.
* **Ponente: Carlos**
* **Guión:**
  > "Buenos días con todos. Mi nombre es Carlos Ramírez y, junto a mi compañero Angel Espín, queremos presentarles nuestro proyecto de maestría en Ciencia de Datos: el **Sistema Multiagente para la Segmentación de Clientes y Optimización de Retención** [1]. Este es un simulador basado en Inteligencia Artificial diseñado específicamente para estimar el impacto comercial antes de ejecutar el presupuesto de campañas en cadenas de farmacias [1]."

---

### [0:25 - 0:50] Diapositiva 2: El Problema de la Retención por Intuición
* **Visual:** Escala operativa (600+ sucursales, 2M clientes) y Riesgo comercial (70%-80% de ingresos vienen del 20% VIP, con retorno desconocido).
* **Ponente: Carlos**
* **Guión:**
  > "Trabajamos sobre una escala masiva: más de **600 sucursales, dos marcas y un universo de 2 millones de clientes** con 22 gigabytes de historial transaccional de un año [2]. En esta industria, entre el **70% y el 80% de los ingresos dependen de un segmento mínimo: el 20% de clientes VIP** [2]. Sin embargo, la decisión de cómo retenerlos hoy se basa en la intuición [2]. Se lanzan presupuestos de campaña con un retorno completamente desconocido, sin forma de comparar alternativas antes de ejecutarlas ni saber cuánto se recupera realmente con cada una [2]."

---

### [0:50 - 1:15] Diapositiva 3: Métricas de Negocio como Norte del Éxito
* **Visual:** Tarjetas con las métricas clave: -15% fuga, 3:1 ROI, <10 min por escenario. Línea base: decisión del equipo comercial.
* **Ponente: Carlos**
* **Guión:**
  > "Por eso, definimos que el éxito de nuestro sistema no se mide por su precisión teórica en una computadora, sino por su capacidad para mover métricas reales de negocio [3]. Nos planteamos objetivos de negocio claros: **reducir en un 15% la fuga trimestral de clientes VIP** —aquellos sin compra en 90 días— [3], lograr un **retorno de inversión de 3 a 1** en retención [3] y entregar escenarios listos en **menos de 10 minutos** [3]. Nuestra línea base de comparación es la decisión real del equipo comercial; es decir, nos comparamos contra la realidad y no contra cero [3]."

---

### [1:15 - 1:45] Diapositiva 4: Restricciones y Decisiones de Arquitectura
* **Visual:** Relación entre restricción de negocio (mensual, USD 80/mes, salud, equipo de 2 personas) y decisiones arquitectónicas (Batch, Spot, Seudonimización, Serverless).
* **Ponente: Angel**
* **Guión:**
  > "Gracias, Carlos. Al diseñar este sistema, cada restricción operativa, presupuestaria y legal dictó una decisión arquitectónica muy estricta [4]. Como la decisión comercial es mensual, optamos por **procesamiento por lotes o Batch**, eliminando la complejidad innecesaria del tiempo real [4]. Con un presupuesto límite estricto de **80 dólares al mes**, decidimos usar **instancias Spot de AWS y almacenamiento particionado en Parquet** [4]. Para proteger datos de salud, implementamos una **seudonimización estricta directamente en el origen** [4] y, al ser un equipo de solo dos personas para un desarrollo de cuatro meses, recurrimos exclusivamente a **servicios gestionados Serverless**, sin administrar infraestructura propia [4]."

---

### [1:45 - 2:15] Diapositiva 5: Privacidad desde el Diseño
* **Visual:** Flujo de base transaccional On-Premise a Nube AWS, mostrando el hash de cédulas y códigos terapéuticos (ATC).
* **Ponente: Angel**
* **Guión:**
  > "La privacidad en este proyecto no es una simple política de papel; es una decisión de diseño [5]. El historial de compras revela condiciones de salud muy sensibles. Por ello, la base transaccional local On-Premise, que contiene datos crudos como cédula y código terapéutico o ATC [5], es interceptada en el origen. Al migrar a la nube de AWS fuera del país, los **IDs son hasheados, se eliminan por completo las categorías sensibles y se aplica cifrado KMS/TLS** [5]. Así garantizamos el estricto control de acceso mediante roles IAM y Lake Formation, asegurando el cumplimiento de las cláusulas de la Ley Orgánica de Protección de Datos Personales (LOPDP) [5]."

---

### [2:15 - 2:45] Diapositiva 6: Ingesta Incremental y Calidad Crítica
* **Visual:** Flujo de PostgreSQL a Athena mediante DMS CDC, S3 y Glue, mostrando la carga de 22 GB y delta de 180 MB. Costo: USD 33/mes.
* **Ponente: Angel**
* **Guión:**
  > "Para optimizar costes, diseñamos una ingesta incremental de datos usando PostgreSQL con DMS CDC diario, pasando por un bucket de Amazon S3 y limpiezas en AWS Glue para almacenar en Parquet particionado [6]. Particionar por fecha y marca no es por estética, es un ahorro de dinero directo que permite operar este tramo por solo **33 dólares mensuales** [6], procesando únicamente un **delta diario de unos 180 megabytes** frente a los 22 gigabytes de la carga inicial [6]. Nuestra regla crítica de calidad es estricta: si DMS no replica una noche, la corrida se bloquea inmediatamente. Un pipeline que falla en silencio dejaría al negocio operando completamente a ciegas [6]."

---

### [2:45 - 3:20] Diapositiva 7: Modelos Tradicionales vs. Simulación por Agentes
* **Visual:** Comparación visual entre Cadenas de Markov (homogéneo) y Agentes en Mesa (heterogéneo, con Saturation Meter de 3 promociones).
* **Ponente: Carlos**
* **Guión:**
  > "Aquí es donde ocurre la magia analítica. Un modelo agregado tradicional, como una Cadena de Markov, asume homogeneidad y trata a todos los clientes VIP por igual, lo que no captura el comportamiento humano real [7]. Nuestro simulador basado en **agentes heterogéneos con Mesa** sí lo hace [7]. Capturamos fenómenos críticos de negocio como la **saturación de promociones** [7]: el sistema entiende que un cliente que recibe tres promociones en un solo mes se satura y deja de reaccionar, mostrando una respuesta de cero [7]. Esto es algo que Markov simplemente no puede predecir [7]."

---

### [3:20 - 3:50] Diapositiva 8: Validación Rigurosa con Contrafactual
* **Visual:** Tres columnas de validación: Temporal (AUC >= 0.75), Backtest de Campaña (Error < 20%), Grupo de Control (10%).
* **Ponente: Carlos**
* **Guión:**
  > "Pero una simulación no tiene valor real si no se valida rigurosamente frente a la realidad [8]. Para ello, dividimos nuestra validación en tres capas. Primero, una **validación temporal** entrenando con datos de junio de 2025 a febrero de 2026, y probando de marzo a mayo de 2026 para evitar fugas de información del futuro, logrando un **AUC mayor o igual a 0.75 en el modelo de abandono** [8]. Segundo, realizamos un **backtest de campaña**, reconstruyendo el pasado para comparar la predicción contra campañas reales ejecutadas, logrando un **error menor al 20% en el delta de retención** [8]. Y tercero, establecemos un **grupo de control real del 10%** sin intervención para aislar sesgos y realizar emparejamiento por propensión [8]."

---

### [3:50 - 4:20] Diapositiva 9: Procesamiento Separado para Velocidad y Costo
* **Visual:** Línea de flujo superior (Mensual: Step Functions + Glue -> S3) e inferior (Bajo Demanda: Fargate + SageMaker Spot -> S3 -> Athena/PowerBI).
* **Ponente: Carlos / Angel**
* **Guión (Carlos):**
  > "Para lograr velocidad a muy bajo costo, separamos la arquitectura en dos flujos [9]. Mensualmente se recalculan de forma masiva los segmentos RFM con AWS Step Functions y Glue [9]. El usuario comercial solo interactúa bajo demanda, definiendo escenarios en AWS Fargate que se calculan mediante AWS SageMaker [9]."
* **Guión (Angel):**
  > "Como nota de ingeniería importante, para cumplir con el presupuesto, corremos las simulaciones pesadas en instancias SageMaker Spot, las cuales pueden ser interrumpidas por AWS con apenas 2 minutos de aviso [9]. Para evitar perder el procesamiento, la simulación guarda de manera automática un **checkpoint en Amazon S3 cada 10% de avance**, garantizando así una respuesta final confiable en menos de 10 minutos [9]."

---

### [4:20 - 4:50] Diapositiva 10 y 11: Entorno de Pruebas y Monitoreo (Control Room)
* **Visual:** Fases de MLOps (Desarrollo, Staging 100% anonimizada, Producción ECS) y el Tablero del Control Room (Deriva de datos PSI, Deriva de concepto AUC, Simulación vs Realidad, Salud del Pipeline). Costo mensual: USD 75.
* **Ponente: Angel**
* **Guión:**
  > "A nivel operativo, ningún modelo llega a producción sin antes superar tres entornos idénticos a la realidad: Desarrollo, Staging con Docker, MLflow y una copia 100% anonimizada de la base real, y finalmente Producción [10]. Contamos con un protocolo de rollback capaz de restaurar versiones previas en menos de una hora si es necesario [10]. Para evitar la deriva silenciosa del modelo en producción, diseñamos un tablero de monitoreo o **Control Room** [11]. Este vigila cuatro métricas clave: deriva de datos para recalcular RFM, deriva de concepto con la caída del AUC, discrepancias entre simulación y realidad, y la salud del pipeline [11]. Todo este ecosistema de alta disponibilidad opera por apenas **75 dólares mensuales**, manteniéndose firmemente por debajo del límite estricto de 80 dólares [11]."

---

### [4:50 - 5:00] Diapositiva 12: Conclusiones, Lecciones y Siguiente Paso
* **Visual:** Resultados entregados (-15% fuga, <10 min, USD 75/mes, 10% control) y Lecciones aprendidas. Siguiente paso estratégico destacado abajo.
* **Ponente: Carlos**
* **Guión:**
  > "En resumen, hemos logrado cumplir con todos los objetivos planteados: **reducir en un 15% la fuga trimestral de clientes VIP, simular escenarios en menos de 10 minutos, operar con un costo de solo 75 dólares al mes y validar con un 10% de grupo de control real** [12]. Aprendimos que el presupuesto dicta el alcance, que la privacidad es un pilar arquitectónico no negociable, y que sin un contrafactual riguroso no hay validación científica posible [12]. Nuestro siguiente paso estratégico es la **ejecución del piloto en modo sombra en una región**, enfrentando los resultados de nuestro simulador directamente contra la intuición del equipo comercial [12]. Muchas gracias."
