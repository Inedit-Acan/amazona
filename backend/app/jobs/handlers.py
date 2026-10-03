"""Los tipos de trabajo que el runtime sabe ejecutar.

Una investigación de producto (`research.run`, Milestone 31), una ejecución
completa del pipeline de Fase 3 (`pipeline.run`, Milestone 32), el refresco de tipos de cambio, uno de
diagnóstico para comprobar el runtime sin tocar datos de negocio, y los tres de reconciliación programada
(`reconcile.actions`, `reconcile.payment_events`, `reconcile.report`, Milestone 45, ADR 0029).

Importar este módulo es lo que registra los manejadores; `app/jobs/worker.py` y
la API lo importan por ese efecto.
"""

import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import PipelineDisabledError, PipelineOutcomeUnknownError
from app.costs.service import ApiBudgetExceededError
from app.jobs.recurring import RECONCILE_ACTIONS, RECONCILE_PAYMENT_EVENTS, RECONCILE_REPORT
from app.jobs.registry import register
from app.jobs.schemas import JobBlockedError, JobContext, JobResult
from app.money.fx_refresh import FxRefreshService, FxSourceNotConfiguredError
from app.pipeline.service import PIPELINE_RUN_JOB, PipelineOrchestrator
from app.reconciliation.actions import ActionReconciler
from app.reconciliation.events import EventReconciler
from app.reconciliation.report import build_status
from app.research.service import ResearchService

#: Tipos, como constantes, para que el que encola y el que ejecuta no dependan
#: de que una cadena esté bien escrita en dos sitios.
RESEARCH_RUN = "research.run"
PIPELINE_RUN = PIPELINE_RUN_JOB
DIAGNOSTIC_ECHO = "diagnostic.echo"
FX_REFRESH = "fx.refresh"


@register(RESEARCH_RUN)
def run_research(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Ejecuta una investigación de producto fuera de la petición HTTP.

    Es la misma llamada que `POST /api/research/runs` hace de forma síncrona. La
    diferencia es dónde ocurre: aquí el navegador no espera, y si falla se
    reintenta con espera en vez de devolver un 500.

    Devuelve el `correlation_id` como referencia: el resultado vive en
    `product_analyses`, no en la fila del trabajo.
    """
    category = payload.get("category")
    if not category:
        raise ValueError("research.run requires a 'category' in its payload")

    products = ResearchService(db).run_research(
        category=category,
        keywords=payload.get("keywords") or [],
        max_results=int(payload.get("max_results") or 5),
        correlation_id=context.correlation_id,
    )

    return JobResult(reference=context.correlation_id, detail={"candidates": len(products)})


@register(PIPELINE_RUN)
def run_pipeline(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Ejecuta (o continúa) una ejecución del pipeline de Fase 3 fuera de la
    petición HTTP (Milestone 32, ADR 0010).

    El manejador no sabe nada de los nueve pasos: `execute_run` recorre las filas
    de `pipeline_steps`, salta las que ya están COMPLETED y persiste cada paso al
    empezar y al terminar. Por eso un reintento del runtime no repite trabajo ya
    válido: continúa por donde se quedó.

    Un kill switch apagado no es un fallo que el tiempo arregle, así que el
    trabajo queda BLOCKED en vez de gastar intentos: vuelve a la cola cuando un
    operador lo reactiva y alguien lo reencola.
    """
    run_id = payload.get("pipeline_run_id")
    if not run_id:
        raise ValueError("pipeline.run requires a 'pipeline_run_id' in its payload")

    try:
        run = PipelineOrchestrator(db).execute_run(str(run_id), context)
    except (PipelineDisabledError, PipelineOutcomeUnknownError) as exc:
        # Un kill switch apagado, o una acción externa de resultado desconocido: esperar no lo arregla, así que el
        # trabajo queda BLOCKED sin gastar intentos hasta que una persona lo resuelva.
        raise JobBlockedError(str(exc)) from exc

    return JobResult(
        reference=run.correlation_id,
        detail={"status": run.status, "product_id": run.product_id, "needs_review": run.needs_review},
    )


@register(FX_REFRESH)
def run_fx_refresh(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Trae las referencias diarias del BCE y las guarda (Milestone 42, ADR 0020).

    Solo el fichero **diario**. El histórico de 90 días es recuperación explícita,
    la pide una persona por su endpoint y este trabajo no la hace nunca, ni siquiera
    como respaldo de un fallo: un fallo se reintenta con espera.

    Sin fuente real configurada, o sin presupuesto, se bloquea en vez de gastar
    intentos: esperar no lo arregla. Un fallo de red o de formato sí se reintenta.
    """
    mode = payload.get("mode", "daily")
    if mode != "daily":
        raise ValueError("fx.refresh only refreshes the daily file; backfill is an explicit request")
    try:
        result = FxRefreshService(db).refresh_daily(
            actor="system:fx.refresh", correlation_id=context.correlation_id
        )
    except (FxSourceNotConfiguredError, ApiBudgetExceededError) as exc:
        raise JobBlockedError(str(exc)) from exc
    return JobResult(reference=context.correlation_id, detail=result.summary())


@register(RECONCILE_ACTIONS)
def run_reconcile_actions(payload: dict, context: JobContext, db: Session) -> JobResult:
    """El barrido programado de acciones externas abandonadas (Milestone 45, ADR 0029). Libera lo que nunca salió y
    marca como desconocido lo que
    pudo salir; **no** toca un `UNKNOWN_OUTCOME`, no repite peticiones y no llama a `reconcile()`. Con la
    reconciliación apagada, un tick que ya
    estaba encolado **no hace nada**."""
    settings = get_settings()
    if not settings.reconciliation_enabled:
        return JobResult(reference=None, detail={"disabled": True})
    report = ActionReconciler(
        db, older_than=datetime.timedelta(minutes=settings.reconcile_actions_older_than_minutes)
    ).sweep(heartbeat=context.heartbeat)
    return JobResult(reference=None, detail=report.summary())


@register(RECONCILE_PAYMENT_EVENTS)
def run_reconcile_payment_events(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Reanuda los eventos de pago guardados y no aplicados, con el tope de intentos (Milestone 45, ADR 0029 §6).
    Aplicar un evento es la misma
    puerta de siempre (`PaymentService.apply`): no cobra, no llama al proveedor."""
    settings = get_settings()
    if not settings.reconciliation_enabled:
        return JobResult(reference=None, detail={"disabled": True})
    report = EventReconciler(
        db,
        older_than=datetime.timedelta(minutes=settings.reconcile_events_older_than_minutes),
        max_attempts=settings.reconcile_event_max_attempts,
    ).sweep(heartbeat=context.heartbeat)
    return JobResult(reference=None, detail=report.summary())


@register(RECONCILE_REPORT)
def run_reconcile_report(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Solo lectura: cuenta y envejece lo abierto, lo desconocido y los eventos topados, y lo deja en el resultado
    del trabajo. **Nunca cierra ni
    corrige nada.**"""
    settings = get_settings()
    if not settings.reconciliation_enabled:
        return JobResult(reference=None, detail={"disabled": True})
    status = build_status(db, settings)
    return JobResult(
        reference=None,
        detail={
            "open_actions": {state: item["count"] for state, item in status["actions"]["open"].items()},
            "unknown_outcome_oldest_age_seconds": status["actions"]["open"]["UNKNOWN_OUTCOME"]["oldest_age_seconds"],
            "events_waiting": status["events"]["waiting"]["count"],
            "events_capped": status["events"]["capped"]["count"],
            "revenue_ledger_divergences": status["revenue"]["ledger"]["divergences"]["count"],
            "revenue_outside_ledger": status["revenue"]["ledger"]["outside_ledger"]["count"],
            "pending_economic_evidence": status["revenue"]["pending_evidence"]["count"],
        },
    )


@register(DIAGNOSTIC_ECHO)
def echo(payload: dict, context: JobContext, db: Session) -> JobResult:
    """Devuelve su payload. Existe para comprobar que el runtime funciona de
    extremo a extremo sin tocar nada del negocio: encolar, reclamar, ejecutar y
    completar, en un despliegue recién levantado.

    Con `{"fail": true}` falla a propósito, que es como se prueban los
    reintentos en un entorno real.
    """
    context.heartbeat()
    if payload.get("fail"):
        raise RuntimeError(payload.get("message") or "diagnostic failure requested by payload")
    return JobResult(reference=context.correlation_id, detail={"echo": payload})
