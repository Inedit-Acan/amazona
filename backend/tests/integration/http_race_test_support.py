"""Un cliente HTTP para carreras (Milestone 44).

Módulo auxiliar de tests, **no** un test. `Api` apunta la aplicación a una base de datos concreta (una sesión por
petición, como en producción) y `together` lanza N peticiones **a la vez**, cada una con su propio cliente, detrás de
una barrera.
"""

import threading

from fastapi.testclient import TestClient
from order_test_support import session_factory

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app

CLICKS = 20


class Api:
    """Un `TestClient` por hilo: cada «clic» es su propia petición, con su propia sesión de base de datos."""

    def __init__(self, engine) -> None:
        self.factory = session_factory(engine)

        def override_get_db():
            session = self.factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db

    def close(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)

    def together(self, send, count: int = CLICKS) -> list:
        barrier = threading.Barrier(count)
        results: list = [None] * count

        def worker(index: int) -> None:
            client = TestClient(app, raise_server_exceptions=False)
            barrier.wait(timeout=20)
            results[index] = send(client, index)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        return results
