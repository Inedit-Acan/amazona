"""Varias fuentes para un mismo dominio (Milestone 34, ADR 0012).

La regla del proyecto y la ADR 0008: **lo real se usa siempre que exista y lo
simulado solo como relleno, diciendo que lo es**. Eso es todo lo que hace este
componente.

El orden importa y es el declarado: los proveedores van de más fiable a menos, y
un proveedor posterior solo aporta las señales que ninguno anterior dio para ese
candidato. Ningún número se promedia ni se mezcla: cada señal sigue siendo de
quien la produjo, con su procedencia intacta.

Un candidato que solo conoce el relleno **no se inventa**: si la fuente real no
encontró nada para un término, no aparece un candidato de fixtures en su lugar
—eso convertiría un fallo de red en un descubrimiento—. El relleno completa
señales de candidatos que la fuente real sí encontró; solo cuando ninguna fuente
real da candidato alguno se usan los del relleno, y entonces todas sus señales
van marcadas como simuladas, que es justo lo que se ve hoy con el mock a solas.
"""

from app.integrations.ports import CandidateSignals, ProductSignalProvider, Signal, SignalKind


def _key(name: str) -> str:
    return name.strip().casefold()


class CompositeProductSignalProvider(ProductSignalProvider):
    name = "composite"

    def __init__(self, providers: list[ProductSignalProvider]) -> None:
        if not providers:
            raise ValueError("a composite provider needs at least one provider")
        self._providers = providers

    def supports(self) -> frozenset[SignalKind]:
        supported: set[SignalKind] = set()
        for provider in self._providers:
            supported |= provider.supports()
        return frozenset(supported)

    def discover(
        self, *, category: str, keywords: list[str], market: str, max_results: int
    ) -> list[CandidateSignals]:
        merged: dict[str, CandidateSignals] = {}
        order: list[str] = []
        first_real_ran = False

        for provider in self._providers:
            found = provider.discover(
                category=category, keywords=keywords, market=market, max_results=max_results
            )
            fills_only = first_real_ran and self._is_filler(found)
            for candidate in found:
                key = _key(candidate.name)
                if key not in merged:
                    if fills_only:
                        # Relleno para un candidato que nadie encontró: eso
                        # sería inventarse el hallazgo, no completarlo.
                        continue
                    merged[key] = candidate
                    order.append(key)
                    continue
                merged[key] = self._complete(merged[key], candidate)
            if found and not self._is_filler(found):
                first_real_ran = True

        return [merged[key] for key in order][:max_results]

    @staticmethod
    def _is_filler(candidates: list[CandidateSignals]) -> bool:
        """Un proveedor es relleno en esta vuelta si todo lo que trajo es
        simulado. Se mira lo que trajo, no cómo se llama."""
        return all(signal.simulated for candidate in candidates for signal in candidate.signals)

    @staticmethod
    def _complete(base: CandidateSignals, extra: CandidateSignals) -> CandidateSignals:
        """Añade solo las señales que faltaban. Lo que ya venía de una fuente
        anterior no se pisa: el primero que la da, manda."""
        present = {signal.kind for signal in base.signals}
        added: list[Signal] = [signal for signal in extra.signals if signal.kind not in present]
        if not added:
            return base
        return CandidateSignals(
            name=base.name,
            category=base.category,
            signals=[*base.signals, *added],
            rationale=base.rationale or extra.rationale,
        )
