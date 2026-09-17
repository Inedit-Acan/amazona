# Milestone 26 Demo

**Origen:** `docs/design/AMAZONA_handoff_backend_paneles_pendientes.md`
§3 — la pieza más invasiva de las 4 (toca el agente de investigación),
dejada para el final según el orden sugerido. Ivan confirmó
explícitamente la opción de **5 ejes completos** (no la alternativa
barata de 2 ejes que la nota también ofrecía). **Sin ADR nueva.**

## Qué se entrega

### Backend — 3 ejes nuevos en `MockTrendsProvider` + `ProductResearchAgent`

`future_outlook_signal`, `regulatory_risk_signal`, `scalability_signal`
(0-1, mismo patrón fixture-driven determinista que `demand_signal`) se
añaden a los 9 candidatos del dataset (`ai/mock_trends_provider.py`) y
al `candidate` que construye `ProductResearchAgent.run()` — **sin
tocar** el cálculo de `opportunity_score` ni el umbral GO/REVIEW: los 3
ejes nuevos son puramente informativos para el radar, no alimentan la
recomendación (evita cambiar comportamiento ya probado). `data:
dict` sin schema estricto en `api/research.py`/`ResearchService`
significa que los ejes nuevos fluyen automáticamente hasta el frontend
sin tocar la capa de API ni el modelo de persistencia — igual que ya
ocurre con `demand_signal`/`competition_level`.

2 tests existentes actualizados (`test_mock_trends_provider.py`,
`test_product_research_agent.py`: aserciones de forma exacta del
diccionario de candidato); sin tests nuevos porque no hay comportamiento
nuevo que verificar más allá de "el campo está en el rango 0-1", ya
cubierto al extender esas mismas aserciones.

### Frontend — `RadarChart` en `/research`

- **`RadarChart`** (nuevo, `components/radar-chart.tsx`): siguiendo la
  skill de dataviz del proyecto — patrón "emphasis" (2 series máximo:
  el candidato en acento esmeralda, la media en gris de
  desénfasis — nunca una rampa categórica generada), leyenda siempre
  presente (2 series), tooltip por eje con hit-target ampliado, y
  toggle **"Ver tabla"** (view accesible obligatoria).
- **5 ejes**, no los 6 originales de `v0.5.md` §5.4: Demanda,
  Competencia, Futuro, Regulación, Escalabilidad — sustituyendo
  Rentabilidad/Logística (datos de Economía/Proveedores, fuera del
  alcance de esta nota) por Competencia, que sí tiene dato real
  (`competition_level`) desde Milestone 1. Cada eje normalizado a
  "más alto = más favorable" **antes** de llegar al componente
  (`radarValues()` en `research/page.tsx` invierte `competition_level`
  y `regulatory_risk_signal`) — `RadarChart` en sí nunca sabe qué señal
  apunta "al revés".
- **"Media de mercado"** = promedio real de los candidatos devueltos en
  ese mismo run de investigación (no un promedio histórico/global
  fabricado — el research run no tiene un feed agregado, como ya
  documentó Milestone 19).
- Por candidato, un desplegable "Radar de oportunidad" (colapsado por
  defecto, mismo patrón que `showEvidence` de `ApprovalCard`) con
  `DataProvenanceBadge status="estimated"` — **no** `status="simulated"`
  como decía literalmente la nota: `DataProvenance` es un vocabulario
  cerrado de 4 estados ya establecido en Milestone 18
  (verificado/tercero/estimado/pendiente); añadir un 5º estado solo
  para este radar habría fragmentado un vocabulario ya compartido por
  toda la app. Dato simulado por fixture determinista es exactamente lo
  que ya significa "estimated" en el resto del sistema (p. ej.
  `competition_analysis` en `/ecommerce`, `performance_estimate` en
  `/marketing`).

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 498 tests, sin regresiones (2 aserciones actualizadas, no rotas)
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

**Verificado visualmente** (paso 7 de la skill de dataviz), mismo método
que Milestone 24: ruta de desarrollo temporal
(`app/preview-radar/page.tsx`, **eliminada antes de cerrar el
milestone** — confirmado con `git status`) importando el `RadarChart`
real con datos de muestra. Capturado por screenshot: pentágono con grid
de anillos, 2 polígonos (candidato/media) correctamente diferenciados
por color, etiquetas de los 5 ejes sin solapamiento. Hover confirmado
(`get_page_text` mostró el tooltip con ambos valores — 82%/62% en
Demanda, coincidiendo con los datos de muestra). Toggle "Ver tabla"
confirmado (las 5 filas con los mismos valores exactos).

## Cierre de la nota de handoff

Con este milestone quedan resueltas las 4 piezas construibles de
`docs/design/AMAZONA_handoff_backend_paneles_pendientes.md`
(Milestones 23-26). `QueueStatus` (§5) queda sin construir, tal como
recomendaba la nota — no hay infraestructura de colas real en el
backend, y forzar el widget habría significado fabricar sus datos o
introducir infraestructura solo para alimentarlo.
