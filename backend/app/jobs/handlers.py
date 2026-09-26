"""Los tipos de trabajo que el runtime sabe ejecutar.

El plan maestro pide empezar por «una tarea simple async» (§32) y **no** migrar
todavía el pipeline: eso es el Milestone 32. Así que aquí hay uno de verdad —una
investigación de producto, el mismo trabajo que hoy hace `POST /api/research/runs`
de forma síncrona— y uno de diagnóstico para poder comprobar el runtime sin
tocar datos de negocio.

Importar este módulo es lo que registra los manejadores; `app/jobs/worker.py` y
la API lo importan por ese efecto.
"""

from sqlalchemy.orm import Session

from app.jobs.registry import register
from app.jobs.schemas import JobContext, JobResult
from app.research.service import ResearchService

#: Tipos, como constantes, para que el que encola y el que ejecuta no dependan
#: de que una cadena esté bien escrita en dos sitios.
RESEARCH_RUN = "research.run"
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
