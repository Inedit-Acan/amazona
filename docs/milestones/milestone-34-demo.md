# Milestone 34 — Product Intelligence Adapter Architecture

**Fecha:** 26-09-2026 · **ADR:** [0012](../architecture/adr-0012-product-intelligence-adapters.md)
· **Anterior:** [Milestone 33](milestone-33-demo.md)

Primera conversión de mock → real del plan maestro (§8 y §32). El sistema mide
algo de verdad por primera vez, y —más importante— deja de poder confundir un
número medido con uno inventado.

---

## Qué cambia

### El contrato: señales con procedencia

`ProductSignalProvider` deja de devolver candidatos ya cocinados y devuelve
**señales**. Cada una lleva los nueve campos del plan maestro §8: quién la
produjo, de qué fuente, preguntando qué, en qué mercado, cuándo, con qué método,
con cuánta confianza, cómo volver al dato crudo, y si es simulada.

El cambio no es de forma. Una fuente real no responde «aquí tienes cuatro
productos con su nivel de competencia»: responde «este término tuvo este interés
en este mercado en estas fechas». El contrato anterior solo se podía implementar
con datos reales inventando la otra mitad.

`method` es el campo que más trabaja: es donde se escribe qué **es** y qué **no
es** el número, porque el número viaja lejos de donde se produjo.

### Adaptador real #1: Wikimedia Pageviews

Mide cuánta gente consultó un artículo de una enciclopedia. **Es un proxy de
interés: no es demanda de compra, no son ventas, no es intención de gasto.** Cada
señal lo lleva escrito, en mayúsculas, dentro de su `method`.

- Ventana de doce meses completos, sin contar el mes en curso (está a medias:
  compararlo con meses completos inventaría una caída).
- Normalización logarítmica contra un techo declarado de un millón de visitas al
  mes — porque el interés se reparte por órdenes de magnitud.
- Confianza que sube con el volumen y la cobertura y **nunca llega a 1**.
- Trayectoria: último trimestre contra el anterior, solo si hay seis meses.
- Mercado → proyecto lingüístico (`mx` → `es.wikipedia`), que es una
  aproximación y se dice.

**Ante cualquier fallo —404, 429, 500, cuerpo raro, timeout— no hay señal.**
Nunca un cero: un cero se leería como «no hay demanda» cuando lo cierto es «no lo
sabemos».

### De dónde salen los candidatos, y por qué es provisional

Una API de interés responde sobre términos que le des. Los términos viven en
`terms.py`, versionados en git; los `keywords` de la petición van primero. Es la
pregunta, no la respuesta: ninguna cifra sale de ahí.

**No es el mecanismo definitivo de descubrimiento y no debe tomarse por tal.** Un
catálogo escrito a mano no descubre productos: solo mide los que alguien ya
pensó. El descubrimiento real —marketplaces, minería de reseñas y problemas,
señales sociales, distribución de precios, persistencia de tendencia: los ocho
ejes del §8— necesita fuentes y mecanismos que este milestone no construye y que
deberán añadirse después. Mientras esa lista sea el único origen de candidatos,
el sistema encuentra lo que ya sabíamos buscar.

### La procedencia, persistida

Tabla nueva `product_signals`: una fila por medición, con sus nueve campos. De la
base de datos se puede volver a responder la pregunta que antes no se podía:
**¿esto es real o inventado?** `product_analyses` no cambia de forma; sigue
guardando el análisis y su score, y ahora se sabe de qué está hecho.

### Composición: lo real primero, el relleno después

`composite` combina fuentes: cada proveedor aporta solo las señales que ninguno
anterior dio, nada se promedia, y el relleno va marcado como simulado.

Con una consecuencia que conviene mirar de frente: **hoy el relleno no puede
completar un candidato real**, porque lo real descubre por término («Air fryer»)
y el mock solo sabe de los suyos. Un candidato real se queda con su demanda
medida, sin competencia, y por tanto **sin score**. Es correcto —la alternativa
sería inventarle la competencia a un producto real— y lo que falta no es rellenar
mejor sino una segunda fuente real, que es el Milestone 35 en adelante.

`composite` **no se admite** en `staging` ni en `production`: puede servir
fixtures, y ahí eso no vale. Allí se usa `real`, y lo que no se sabe queda
ausente.

### El score no cambia

La fórmula sigue siendo `demanda × factor de competencia` (§9: primero fuentes
reales, después el score). Lo nuevo es que cada candidato dice si es `real`,
`mixed` o `simulated`, y que un conjunto mixto baja la confianza del agente a
0,6. Si faltan las señales que el score necesita, el score es `None` — no un
valor por defecto.

### La pantalla

Investigación distingue ahora cuatro cosas que antes se veían igual: medido,
mixto, fixture del backend y relleno de la propia pantalla. La cabecera ya no
dice «Simulación (señales de fixtures)» pase lo que pase: lo calcula, y basta una
señal de relleno para que no pueda decir «real».

## Probarlo

```bash
cd backend && alembic upgrade head

# Con fixtures (por defecto): igual que siempre, ahora con procedencia.
curl -X POST localhost:8000/api/research/runs -H 'Content-Type: application/json' \
  -d '{"category":"home","max_results":3}'

# Con la fuente real:
PRODUCT_INTELLIGENCE_PROVIDER=real python -m app.jobs.worker
# …y en el Control Center, la cabecera de Investigación pasa a «Real».
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1143 tests** (1069 antes, +74).
- Frontend: `tsc` y `eslint` limpios · **280 tests** (272 antes, +8).
- `next build --webpack` en una copia, sin tocar el `.next` de desarrollo.
- **Humo contra Wikimedia de verdad, sin transporte simulado**: «Air fryer» en
  `en.wikipedia` devolvió 0,7483 de demanda con 0,6939 de confianza y 0,4271 de
  trayectoria, con su URL cruda guardada; «Freidora de aire» consultó
  `es.wikipedia`; un término inventado no produjo señal; ocho señales reales
  quedaron persistidas con sus nueve campos; y un timeout de 1 ms dejó cero
  señales en vez de ceros.
- **Y dentro del runtime**: un `research.run` encolado y ejecutado por el
  `Worker` con `PRODUCT_INTELLIGENCE_PROVIDER=real` terminó en `COMPLETED` en
  0,4 s —muy dentro del arriendo de 60 s— dejando seis señales, las seis
  medidas, con su URL cruda y su método declarado. Es donde esto va a vivir en
  producción: red dentro de un trabajo con arriendo.
- El adaptador está probado con transporte simulado para lo que no se puede
  provocar a voluntad: 404, 429, 500, cuerpo no-JSON, forma inesperada, serie
  vacía, término medido a cero, fallo de red término a término, tope de
  peticiones, ventana de meses, identificación y cierre del cliente.
- La migración se ejecuta de verdad en los tests, arriba y abajo, y se comprueba
  columna a columna contra el modelo.
- Regresión del dataset: el mock sigue dando las mismas cifras y el mismo
  ganador que en Fase 3, y la fórmula del score se comprueba candidato a
  candidato.

## No verificado

- **Los cinco pendientes de integración** siguen igual y ninguno bloqueaba este
  milestone (ver [system-overview §20](../architecture/system-overview.md#20-pendientes-de-integración)).
- **El comportamiento de Wikimedia bajo carga real**: no se ha ejercido el límite
  de ritmo de verdad (el 429 está probado con transporte simulado).
- **La calidad de la señal como predictor de negocio.** Que «Air fryer» tenga
  0,7483 no dice que se venda. Compararlo contra el mock y contra la realidad es
  el Milestone 35.

## Lo que queda abierto

1. **Wikimedia es un proxy de interés**, no demanda de compra ni ventas. Se dice
   en cada señal (`method`), en la ADR y aquí; el riesgo es que alguien lo lea
   como demanda de todos modos.
2. **No hay una segunda fuente real** de competencia ni de demanda comercial, y
   por eso **un candidato real no tiene score**: sin competencia no hay fórmula,
   y la fórmula no se toca (§9).
3. **El catálogo de términos no es descubrimiento** (arriba, y en la ADR 0012
   §5). Hace falta un mecanismo real: marketplaces, minería de reseñas, señales
   sociales, distribución de precios.
4. **No hay resolución de entidades entre proveedores.** Hoy dos señales se
   juntan si el nombre coincide ignorando mayúsculas y espacios. Con dos fuentes
   reales eso deja de bastar —«Air fryer», «Airfryer», «Freidora de aire» y un
   ASIN son el mismo producto para una persona y cuatro candidatos para este
   código—, así que hace falta **antes** de añadir la segunda fuente: si no,
   componer no compone, duplica.
5. **Milestone 35**: primera investigación real de verdad, comparando resultados
   contra el mock, sin eliminar el mock.
6. **El `opportunity_score` v2** del §9 sigue sin tocarse, a propósito, y no debe
   tocarse fuera del milestone que le corresponda.
7. **Los otros cuatro dominios** (proveedores, regulatorio, publicidad,
   marketplaces) siguen solo con mock.

Ninguno de estos cuatro se tapa rellenando con datos inventados: una señal que
falta se queda **ausente**, que es la regla que sostiene todo lo demás.
