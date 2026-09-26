"""Los tipos de trabajo que el runtime sabe ejecutar.

Tres: una investigación de producto (`research.run`, Milestone 31), una ejecución
completa del pipeline de Fase 3 (`pipeline.run`, Milestone 32) y uno de
diagnóstico para comprobar el runtime sin tocar datos de negocio.

Importar este módulo es lo que registra los manejadores; `app/jobs/worker.py` y
la API lo importan por ese efecto.
"""

from sqlalchemy.orm import Session

from app.core.errors import PipelineDisabledError
from app.jobs.registry import register
from app.jobs.schemas import JobBlockedError, JobContext, JobResult
from app.pipeline.service import PIPELINE_RUN_JOB, PipelineOrchestrator
from app.research.service import ResearchService

#: Tipos, como constantes, para que el que encola y el que ejecuta no dependan
#: de que una cadena esté bien escrita en dos sitios.
RESEARCH_RUN = "research.run"
PIPELINE_RUN = PIPELINE_RUN_JOB
DIAGNOSTIC_ECHO = "diagnostic.echo"


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
    except PipelineDisabledError as exc:
        raise JobBlockedError(str(exc)) from exc

    return JobResult(
        reference=run.correlation_id,
        detail={"status": run.status, "product_id": run.product_id, "needs_review": run.needs_review},
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
