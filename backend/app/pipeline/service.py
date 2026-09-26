"""El orquestador del pipeline, ahora asíncrono y reanudable (Milestone 32, ADR 0010).

Hasta el Milestone 31 los nueve pasos de Fase 3 se ejecutaban **dentro de la
petición HTTP**: el navegador esperaba, un fallo a mitad devolvía un 500 y lo que
los servicios ya habían comprometido quedaba huérfano. Ahora:

- `enqueue_run()` crea la fila de la ejecución, sus nueve pasos en PENDING y un
  trabajo del runtime (`pipeline.run`). Devuelve en milisegundos.
- `execute_run()` es lo que corre dentro del worker: recorre los pasos, **salta
  los que ya están COMPLETED** y persiste cada uno al empezar y al terminar.
- `resume_run()` y `cancel_run()` son los dos controles que eso hace posibles.

Lo que **no** cambia: la selección de mejor candidato/mejor cotización (ADR 0005)
y que un `NO_GO`/`BLOCKED` intermedio no detiene la cadena (ADR 0005 §Decisión,
ADR 0006 §1). Sigue siendo pura secuenciación: ninguna lógica de agente vive aquí.
"""

import datetime
from collections.abc import Sequence
from dataclasses import MISSING, dataclass, fields

from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.cfo.service import CFOService
from app.core.errors import NotFoundError, PipelineDisabledError, PipelineRunStateError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.job import Job
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep, PipelineStepAttempt
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier_quote import SupplierQuote
from app.ecommerce.service import EcommerceStorefrontService
from app.economics.service import EconomicAnalysisService
from app.jobs.queue import JobQueue
from app.jobs.schemas import JobCancelledError, JobContext, JobStatus
from app.legal.service import LegalComplianceService
from app.marketing.service import MarketingCampaignService
from app.marketplace.service import MarketplaceListingService
from app.operations.service import OperationsService
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.review import assess_pipeline_run
from app.pipeline.schemas import (
    CANCELLABLE,
    RESUMABLE,
    STEP_ORDER,
    PipelineRunStatus,
    PipelineStepStatus,
    step_ordinal,
)
from app.research.service import ResearchService
from app.sourcing.service import SourcingService

PIPELINE_ACTOR = "pipeline-orchestrator-1"

#: El tipo de trabajo con el que el runtime ejecuta una ejecución del pipeline.
#: Vive aquí y no en `app/jobs/handlers.py` para que el que encola y el que
#: ejecuta no dependan de que una cadena esté bien escrita en dos sitios.
PIPELINE_RUN_JOB = "pipeline.run"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass
class PipelineRequest:
    category: str
    sale_price: float
    destination_region: str
    market: str = "us"
    marketplace_platform: str = "amazon"
    marketing_platform: str = "meta"
    daily_budget: float = 20.0
    monthly_fixed_costs: float = 500.0
    certification_available: bool = False
    max_results: int = 5

    def to_payload(self) -> dict:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_payload(cls, payload: dict) -> "PipelineRequest":
        """Reconstruye la petición guardada en `pipeline_runs.request`.

        Ignora claves que no conoce: una ejecución encolada por una versión
        anterior del código tiene que seguir siendo reanudable."""
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in known})

    @classmethod
    def missing_from(cls, payload: dict) -> list[str]:
        """Qué parámetros obligatorios no están. Una ejecución anterior al
        Milestone 32 no guardó ninguno: se dice cuáles faltan en vez de
        inventarlos."""
        return [
            field.name
            for field in fields(cls)
            if field.default is MISSING and field.default_factory is MISSING and field.name not in payload
        ]


@dataclass
class StepOutcome:
    """Lo que un paso deja: su propio `correlation_id`, la fila que produjo y lo
    que expone del negocio (`recommendation`, `status`, `candidate_count`)."""

    correlation_id: str
    entity_id: str | None = None
    detail: dict | None = None
    #: El paso no pudo entregar nada al siguiente (research sin candidatos). No
    #: es un fallo técnico: la ejecución queda PARTIAL y no se reintenta sola.
    halted: bool = False
    halt_reason: str | None = None


def pick_best_candidate(products: list[Product], score_by_product_id: dict[str, float]) -> Product:
    """Same ranking ResearchService/ProductResearchAgent already apply
    internally (opportunity_score descending) — the pipeline just needs
    to pick one instead of a human eyeballing the list."""
    return max(products, key=lambda p: score_by_product_id.get(p.id, 0.0))


def pick_best_quote(quotes: list[SupplierQuote]) -> SupplierQuote:
    """Same ranking SupplierSourcingAgent/`/suppliers` endpoint already
    apply internally (total_landed_cost_per_unit ascending)."""
    return min(quotes, key=lambda q: q.total_landed_cost_per_unit)


# --- Modelo de lectura -----------------------------------------------------


def steps_view(steps: Sequence[PipelineStep]) -> dict[str, dict]:
    """Reconstruye el JSON `steps` que la API viene devolviendo desde el
    Milestone 12, ahora a partir de las filas (ADR 0010: una sola verdad).

    `status` sigue siendo el estado de **negocio** que el paso expone —es lo que
    `assess_pipeline_run` lee para decidir si hace falta revisión humana— y el
    estado de **ejecución** del paso viaja aparte, en `step_status`. Mezclarlos
    rompería la evaluación de riesgo de la ADR 0006.
    """
    view: dict[str, dict] = {}
    for step in sorted(steps, key=lambda s: s.ordinal):
        entry: dict = {"correlation_id": step.correlation_id}
        if step.entity_id is not None:
            entry["entity_id"] = step.entity_id
        entry.update(step.detail or {})
        entry["step_status"] = step.status
        entry["attempt"] = step.attempt
        if step.error is not None:
            entry["error"] = step.error
        view[step.name] = entry
    return view


def load_steps_views(db: Session, run_ids: Sequence[str]) -> dict[str, dict[str, dict]]:
    """Los pasos de varias ejecuciones en una sola consulta: el listado de
    ejecuciones no puede costar una consulta por fila."""
    if not run_ids:
        return {}
    rows = db.query(PipelineStep).filter(PipelineStep.pipeline_run_id.in_(list(run_ids))).all()
    grouped: dict[str, list[PipelineStep]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped.setdefault(row.pipeline_run_id, []).append(row)
    return {run_id: steps_view(steps) for run_id, steps in grouped.items()}


class PipelineOrchestrator:
    """Chains the 9 Fase 3 steps (research through CFO) in one invocation
    (Milestone 12, ADR 0005), replacing the manual "click through 9
    Control Center pages copying IDs" flow. Reuses the 9 existing
    services exactly as they are — no agent logic is duplicated here.

    Never modifies planner.py/decision_engine.py/CEOOrchestrator — this
    is a separate, parallel orchestration path for catalog discovery,
    not the Milestone-1 objective validation graph (ADR 0004).

    No step halts the chain on a NO_GO/BLOCKED outcome — every step's
    status is recorded regardless. Una ejecución solo se detiene cuando un paso
    no puede entregar nada al siguiente (PARTIAL), cuando un paso revienta
    (FAILED, reintentable), cuando el kill switch está apagado (BLOCKED) o
    cuando una persona la cancela (CANCELLED)."""

    def __init__(self, db: Session, kill_switch: PipelineKillSwitchService | None = None) -> None:
        self._db = db
        self._kill_switch = kill_switch or PipelineKillSwitchService(db)

    # --- Encolar -----------------------------------------------------------

    def enqueue_run(self, request: PipelineRequest, *, created_by: str | None = None) -> PipelineRun:
        """Crea la ejecución, sus nueve pasos y el trabajo que la ejecutará.

        No ejecuta nada: de eso se encarga un worker. El kill switch se consulta
        aquí —igual que antes de tocar cualquier servicio (ADR 0006 §3)— para que
        quien llama se entere en el acto en vez de que el trabajo muera después.
        """
        if not self._kill_switch.is_enabled():
            raise PipelineDisabledError("pipeline runs are currently disabled by an operator")

        correlation_id = new_correlation_id()
        run = PipelineRun(
            product_id=None,
            category=request.category,
            market=request.market,
            status=PipelineRunStatus.QUEUED,
            failed_step=None,
            needs_review=False,
            correlation_id=correlation_id,
            request=request.to_payload(),
        )
        self._db.add(run)
        self._db.flush()

        for ordinal, name in enumerate(STEP_ORDER):
            self._db.add(
                PipelineStep(
                    pipeline_run_id=run.id,
                    name=name,
                    ordinal=ordinal,
                    status=PipelineStepStatus.PENDING,
                )
            )

        job = JobQueue(self._db).enqueue(
            job_type=PIPELINE_RUN_JOB,
            payload={"pipeline_run_id": run.id},
            correlation_id=correlation_id,
            # Una ejecución tiene un trabajo y solo uno, para siempre: reanudar
            # reencola ese mismo trabajo, así que toda su historia queda junta.
            idempotency_key=f"pipeline-run:{run.id}",
            created_by=created_by,
        )
        run.job_id = job.id
        self._audit(
            "pipeline.enqueue",
            run,
            actor=created_by or PIPELINE_ACTOR,
            after={"job_id": job.id, "category": request.category, "market": request.market},
        )
        self._db.commit()
        self._db.refresh(run)
        return run

    # --- Ejecutar ----------------------------------------------------------

    def execute_run(self, pipeline_run_id: str, context: JobContext | None = None) -> PipelineRun:
        """Ejecuta (o continúa) una ejecución. Es lo que corre en el worker.

        Los pasos ya `COMPLETED` no se repiten: eso es lo que hace que reanudar
        conserve el trabajo válido en vez de empezar de cero.
        """
        run = self._db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise NotFoundError(f"pipeline run {pipeline_run_id} not found")
        if run.status == PipelineRunStatus.CANCELLED:
            # La cancelaron entre encolar y reclamar: no hay nada que hacer.
            return run
        if not self._kill_switch.is_enabled():
            # Ningún paso se ha tocado. El trabajo queda BLOCKED (no gasta
            # intentos) y se reanuda cuando un operador reactive el switch.
            run.status = PipelineRunStatus.BLOCKED
            self._db.commit()
            raise PipelineDisabledError("pipeline runs are currently disabled by an operator")

        request = self._request_of(run)
        run.status = PipelineRunStatus.RUNNING
        self._db.commit()

        for step in self._steps(run):
            if step.status == PipelineStepStatus.COMPLETED:
                continue
            try:
                if self._taken_away(run, context):
                    return run
            except JobCancelledError:
                # Nos quitaron el trabajo entre dos pasos. Si fue una
                # cancelación, la ejecución termina; si fue el arriendo, otro
                # worker seguirá por aquí mismo.
                self._reconcile_lost(run)
                raise

            self._start_step(step, context)
            try:
                outcome = self._dispatch(step.name, run, request)
            except JobCancelledError:
                self._release_step(run, step)
                raise
            except Exception as exc:  # noqa: BLE001 - cualquier fallo del paso es un intento fallido
                message = f"{type(exc).__name__}: {exc}"
                self._finish_step(step, PipelineStepStatus.FAILED, error=message)
                run.status = PipelineRunStatus.FAILED
                run.failed_step = step.name
                self._db.commit()
                raise

            if outcome.halted:
                self._finish_step(
                    step,
                    PipelineStepStatus.FAILED,
                    correlation_id=outcome.correlation_id,
                    detail=outcome.detail,
                    error=outcome.halt_reason,
                )
                self._skip_remaining(run, after=step.ordinal)
                return self._settle(run, PipelineRunStatus.PARTIAL, failed_step=step.name)

            self._finish_step(
                step,
                PipelineStepStatus.COMPLETED,
                correlation_id=outcome.correlation_id,
                entity_id=outcome.entity_id,
                detail=outcome.detail,
            )

        return self._settle(run, PipelineRunStatus.COMPLETED, failed_step=None)

    def _request_of(self, run: PipelineRun) -> PipelineRequest:
        payload = run.request or {}
        missing = PipelineRequest.missing_from(payload)
        if missing:
            raise PipelineRunStateError(
                f"pipeline run {run.correlation_id} does not record {', '.join(missing)}:"
                " it predates Milestone 32 and cannot be executed again"
            )
        return PipelineRequest.from_payload(payload)

    # --- Controlar ---------------------------------------------------------

    def resume_run(
        self,
        run: PipelineRun,
        *,
        actor: str,
        identity: Actor | None = None,
        from_step: str | None = None,
    ) -> PipelineRun:
        """Devuelve una ejecución parada a la cola, conservando lo ya válido.

        Sin `from_step` continúa por el primer paso que no esté `COMPLETED` —que
        es el que falló—, así que reanudar una ejecución y reintentar su paso
        fallido son la misma cosa, y solo vale para una ejecución parada.

        Con `from_step` se fuerza el punto de partida: ese paso y los siguientes
        se vuelven a ejecutar aunque ya hubieran terminado, porque su resultado
        depende del que se va a rehacer. Eso sí vale también sobre una ejecución
        COMPLETED —es el «retry step» del plan maestro §21—, y lo único que nunca
        se puede es pisar una ejecución que un worker tiene entre manos.
        """
        if from_step is not None and from_step not in STEP_ORDER:
            raise NotFoundError(f"unknown pipeline step {from_step}")
        if run.status == PipelineRunStatus.RUNNING:
            raise PipelineRunStateError(
                f"pipeline run {run.correlation_id} is still running; cancel it first"
            )
        if from_step is None and run.status not in RESUMABLE:
            # Continuar una ejecución que terminó bien no significa nada. Rehacer
            # a propósito uno de sus pasos, sí: eso se pide con `from_step`.
            raise PipelineRunStateError(
                f"pipeline run {run.correlation_id} is not resumable (status={run.status});"
                " name a step to redo it on purpose"
            )
        # Se comprueba aquí y no en el worker: quien reanuda se entera en el acto
        # de que esa ejecución no guarda con qué.
        self._request_of(run)

        steps = self._steps(run)
        if from_step is not None:
            start = step_ordinal(from_step)
        else:
            pending = [s for s in steps if s.status != PipelineStepStatus.COMPLETED]
            if not pending:
                raise PipelineRunStateError(
                    f"pipeline run {run.correlation_id} has no step left to resume"
                )
            start = pending[0].ordinal

        for step in steps:
            if step.ordinal >= start:
                self._reset_step(step)
        if start <= step_ordinal("research"):
            # Se va a elegir otro candidato: el producto de la ejecución deja de
            # ser el de antes, y decirlo ahora evita enseñar uno que ya no aplica.
            run.product_id = None

        run.status = PipelineRunStatus.QUEUED
        run.failed_step = None
        job = self._requeue_job(run, actor=actor)
        self._audit(
            "pipeline.resume",
            run,
            actor=actor,
            identity=identity,
            after={"from_step": STEP_ORDER[start], "job_id": job.id},
        )
        self._db.commit()
        self._db.refresh(run)
        return run

    def cancel_run(self, run: PipelineRun, *, actor: str, identity: Actor | None = None) -> PipelineRun:
        """Para una ejecución. Si está en marcha, el worker se entera en su
        siguiente latido y deja el paso en curso en CANCELLED; los pasos que no
        llegaron a empezar se quedan como estaban, que es lo que permite
        reanudarla después."""
        if run.status not in CANCELLABLE:
            raise PipelineRunStateError(
                f"pipeline run {run.correlation_id} cannot be cancelled (status={run.status})"
            )

        run.status = PipelineRunStatus.CANCELLED
        if run.job_id:
            JobQueue(self._db).cancel(run.job_id, actor=actor)
        self._audit("pipeline.cancel", run, actor=actor, identity=identity, after={"status": run.status})
        self._db.commit()
        self._db.refresh(run)
        return run

    # --- Los nueve pasos ---------------------------------------------------

    def _dispatch(self, name: str, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        return getattr(self, f"_step_{name}")(run, request)

    def _step_research(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        products = ResearchService(self._db).run_research(
            category=request.category,
            keywords=None,
            max_results=request.max_results,
            correlation_id=correlation_id,
        )
        if not products:
            return StepOutcome(
                correlation_id=correlation_id,
                detail={"candidate_count": 0},
                halted=True,
                halt_reason=f"research found no candidates for category {request.category}",
            )

        analyses = (
            self._db.query(ProductAnalysis)
            .filter(
                ProductAnalysis.product_id.in_([p.id for p in products]),
                ProductAnalysis.correlation_id == correlation_id,
            )
            .all()
        )
        score_by_product_id = {a.product_id: (a.opportunity_score or 0.0) for a in analyses}
        product = pick_best_candidate(products, score_by_product_id)
        run.product_id = product.id
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=product.id,
            detail={"candidate_count": len(products)},
        )

    def _step_sourcing(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        quotes = SourcingService(self._db).run_sourcing(
            product_id=self._product_id(run),
            category=request.category,
            destination_region=request.destination_region,
            max_results=request.max_results,
            correlation_id=correlation_id,
        )
        if not quotes:
            return StepOutcome(
                correlation_id=correlation_id,
                detail={"candidate_count": 0},
                halted=True,
                halt_reason="sourcing found no supplier quotes",
            )

        quote = pick_best_quote(quotes)
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=quote.id,
            detail={"candidate_count": len(quotes)},
        )

    def _step_economics(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        analysis = EconomicAnalysisService(self._db).run_analysis(
            product_id=self._product_id(run),
            supplier_quote_id=self._quote_id(run),
            sale_price=request.sale_price,
            monthly_fixed_costs=request.monthly_fixed_costs,
            correlation_id=correlation_id,
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=analysis.id,
            detail={"recommendation": analysis.recommendation},
        )

    def _step_legal(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        analysis = LegalComplianceService(self._db).run_analysis(
            product_id=self._product_id(run),
            market=request.market,
            certification_available=request.certification_available,
            correlation_id=correlation_id,
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=analysis.id,
            detail={"recommendation": analysis.recommendation},
        )

    def _step_ecommerce(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        storefront = EcommerceStorefrontService(self._db).run_generation(
            product_id=self._product_id(run), market=request.market, correlation_id=correlation_id
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=storefront.id,
            detail={"status": storefront.launch_status},
        )

    def _step_marketplace(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        listing = MarketplaceListingService(self._db).run_generation(
            product_id=self._product_id(run),
            market=request.market,
            platform=request.marketplace_platform,
            correlation_id=correlation_id,
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=listing.id,
            detail={"status": listing.listing_status},
        )

    def _step_marketing(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        campaign = MarketingCampaignService(self._db).run_generation(
            product_id=self._product_id(run),
            market=request.market,
            platform=request.marketing_platform,
            daily_budget=request.daily_budget,
            correlation_id=correlation_id,
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=campaign.id,
            detail={"status": campaign.campaign_status},
        )

    def _step_operations(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        record = OperationsService(self._db).run_generation(
            product_id=self._product_id(run), market=request.market, correlation_id=correlation_id
        )
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=record.id,
            detail={"status": record.operations_status},
        )

    def _step_cfo(self, run: PipelineRun, request: PipelineRequest) -> StepOutcome:
        correlation_id = new_correlation_id()
        report = CFOService(self._db).run_generation(correlation_id=correlation_id)
        return StepOutcome(
            correlation_id=correlation_id,
            entity_id=report.id,
            detail={"status": report.financial_health_status},
        )

    # --- Estado de los pasos ----------------------------------------------

    def _steps(self, run: PipelineRun) -> list[PipelineStep]:
        return (
            self._db.query(PipelineStep)
            .filter_by(pipeline_run_id=run.id)
            .order_by(PipelineStep.ordinal)
            .all()
        )

    def _start_step(self, step: PipelineStep, context: JobContext | None) -> None:
        step.status = PipelineStepStatus.RUNNING
        step.attempt += 1
        step.started_at = _utcnow()
        step.finished_at = None
        step.error = None
        self._db.add(
            PipelineStepAttempt(
                pipeline_step_id=step.id,
                job_id=context.job_id if context else None,
                number=step.attempt,
                status=PipelineStepStatus.RUNNING,
                started_at=step.started_at,
            )
        )
        self._db.commit()

    def _finish_step(
        self,
        step: PipelineStep,
        status: PipelineStepStatus,
        *,
        correlation_id: str | None = None,
        entity_id: str | None = None,
        detail: dict | None = None,
        error: str | None = None,
    ) -> None:
        now = _utcnow()
        step.status = status
        step.finished_at = now
        if correlation_id is not None:
            step.correlation_id = correlation_id
        if entity_id is not None:
            step.entity_id = entity_id
        if detail is not None:
            step.detail = detail
        step.error = error[:2000] if error else None

        attempt = (
            self._db.query(PipelineStepAttempt)
            .filter_by(pipeline_step_id=step.id, number=step.attempt)
            .first()
        )
        if attempt is not None:
            attempt.status = status
            attempt.error = step.error
            attempt.finished_at = now
        self._db.commit()

    def _reset_step(self, step: PipelineStep) -> None:
        """Deja un paso listo para volver a ejecutarse. Su historia de intentos
        se conserva —es lo que explica por qué hubo que reanudar—, pero su
        resultado deja de contar: el nuevo intento producirá otro."""
        step.status = PipelineStepStatus.PENDING
        step.correlation_id = None
        step.entity_id = None
        step.detail = None
        step.error = None
        step.started_at = None
        step.finished_at = None

    def _skip_remaining(self, run: PipelineRun, *, after: int) -> None:
        """Los pasos a los que ya no les va a tocar quedan SKIPPED, no PENDING:
        decir «no se ejecutó a propósito» es distinto de «todavía le puede tocar»."""
        for step in self._steps(run):
            if step.ordinal > after and step.status == PipelineStepStatus.PENDING:
                step.status = PipelineStepStatus.SKIPPED
        self._db.commit()

    def _release_step(self, run: PipelineRun, step: PipelineStep) -> None:
        """El trabajo dejó de ser nuestro a mitad de un paso. Hay dos motivos y
        no significan lo mismo: si lo cancelaron, la ejecución termina; si
        perdimos el arriendo, otro worker va a reclamarlo y el paso tiene que
        quedar listo para que lo repita."""
        if self._reconcile_lost(run):
            self._finish_step(step, PipelineStepStatus.CANCELLED, error="cancelled while running")
        else:
            self._reset_step(step)
            self._db.commit()

    def _reconcile_lost(self, run: PipelineRun) -> bool:
        """¿Nos lo quitaron para siempre o solo por ahora? Devuelve True si el
        trabajo está cancelado —la ejecución termina— y False si simplemente
        perdimos el arriendo, que es recuperable por definición."""
        job = self._db.get(Job, run.job_id) if run.job_id else None
        cancelled = (job is not None and job.status == JobStatus.CANCELLED) or (
            run.status == PipelineRunStatus.CANCELLED
        )
        if cancelled:
            run.status = PipelineRunStatus.CANCELLED
            self._db.commit()
        return cancelled

    def _taken_away(self, run: PipelineRun, context: JobContext | None) -> bool:
        """Antes de cada paso: extiende el arriendo y comprueba que la ejecución
        sigue siendo nuestra. Es también el punto por el que una cancelación
        llega a una ejecución en marcha."""
        if context is not None:
            context.heartbeat()
        self._db.refresh(run)
        return run.status == PipelineRunStatus.CANCELLED

    def _product_id(self, run: PipelineRun) -> str:
        if run.product_id is None:
            raise PipelineRunStateError(f"pipeline run {run.correlation_id} has no product yet")
        return run.product_id

    def _quote_id(self, run: PipelineRun) -> str:
        """La cotización elegida vive en el paso de sourcing: al reanudar es de
        ahí de donde se recupera el hilo, no de un estado en memoria."""
        step = self._db.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="sourcing").first()
        if step is None or step.entity_id is None:
            raise PipelineRunStateError(f"pipeline run {run.correlation_id} has no supplier quote yet")
        return step.entity_id

    # --- Cierre ------------------------------------------------------------

    def _settle(self, run: PipelineRun, status: PipelineRunStatus, *, failed_step: str | None) -> PipelineRun:
        """Cierra la ejecución: estado final, evaluación de riesgo (ADR 0006) y
        auditoría. La evaluación vuelve a hacerse al reanudar, porque el
        resultado puede haber cambiado."""
        view = steps_view(self._steps(run))
        assessment = assess_pipeline_run(status=status.value, steps=view)

        run.status = status
        run.failed_step = failed_step
        run.needs_review = assessment.needs_review

        if assessment.needs_review:
            pending = (
                self._db.query(PipelineReview)
                .filter_by(pipeline_run_id=run.id, status="PENDING")
                .first()
            )
            if pending is None:
                self._db.add(
                    PipelineReview(
                        pipeline_run_id=run.id,
                        reasons=assessment.reasons,
                        status="PENDING",
                        correlation_id=run.correlation_id,
                    )
                )
            else:
                pending.reasons = assessment.reasons

        self._audit(
            "pipeline.run",
            run,
            actor=PIPELINE_ACTOR,
            after={
                "category": run.category,
                "status": status.value,
                "steps": list(view.keys()),
                "needs_review": assessment.needs_review,
            },
        )
        self._db.commit()
        self._db.refresh(run)
        return run

    def _requeue_job(self, run: PipelineRun, *, actor: str) -> Job:
        """Reanudar reencola **el mismo trabajo**: sus intentos y su bitácora son
        la historia de la ejecución, y repartirla entre varios trabajos la
        volvería ilegible. Si no lo hay (una ejecución anterior al Milestone 32),
        se encola uno nuevo."""
        queue = JobQueue(self._db)
        if run.job_id:
            job = self._db.get(Job, run.job_id)
            if job is not None:
                if job.status == JobStatus.RUNNING:
                    raise PipelineRunStateError(
                        f"pipeline run {run.correlation_id} is still held by a worker"
                    )
                return queue.requeue(job.id, actor=actor)

        job = queue.enqueue(
            job_type=PIPELINE_RUN_JOB,
            payload={"pipeline_run_id": run.id},
            correlation_id=run.correlation_id,
            idempotency_key=f"pipeline-run:{run.id}",
            created_by=actor,
        )
        run.job_id = job.id
        return job

    def _audit(
        self,
        action: str,
        run: PipelineRun,
        *,
        actor: str,
        identity: Actor | None = None,
        after: dict | None = None,
    ) -> None:
        self._db.add(
            AuditLog(
                actor=actor,
                actor_role=identity.role if identity else None,
                actor_source=identity.source if identity else None,
                action=action,
                resource=f"pipeline:{run.correlation_id}",
                before=None,
                after=after,
                correlation_id=run.correlation_id,
            )
        )
