"""El módulo de claves de intención del frontend, contra el backend de verdad (Milestone 44, ADR 0025 y 0028 §9).

`apps/control-center/lib/intent-key.ts` conserva una `Idempotency-Key` por intención. Sus pruebas unitarias dicen que
reutiliza la clave; esta dice que **el backend, con esa clave, produce un solo efecto**, de punta a punta: arranca el
backend de verdad (uvicorn) sobre una base PostgreSQL efímera, ejecuta `scripts/intent-e2e.ts` con Node (el módulo real,
`fetch` real) y cuenta los pedidos **en la base de datos**, no en lo que el script cuenta de sí mismo.

Se omite si no hay Node con soporte de TypeScript o un PostgreSQL local (el CI de backend no instala Node): es una
verificación local que forma parte de la suite, no una dependencia nueva. Nada sale de la máquina: el backend escucha
solo en 127.0.0.1 y se lanza desde un directorio sin `.env`, así que no conoce la base real.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from order_test_support import add_product
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.order import Order

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND.parent / "apps" / "control-center" / "scripts" / "intent-e2e.ts"


def node_with_typescript() -> str | None:
    node = shutil.which("node")
    if node is None or not SCRIPT.exists():
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+", version)
    if match is None:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return node if (major, minor) >= (22, 18) else None


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def orders_of(engine, customer_ref: str) -> int:
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(Order).where(Order.customer_ref == customer_ref)) or 0


def test_the_real_frontend_module_and_the_real_backend_make_one_effect_per_intention():
    node = node_with_typescript()
    if node is None:
        pytest.skip("needs Node >= 22.18 (TypeScript without a build step) and the Control Center scripts")
    with ephemeral_postgres() as engine, tempfile.TemporaryDirectory() as workdir:
        with Session(engine) as db:
            product_id = add_product(db).id
        port = free_port()
        env = {
            **os.environ,
            "DATABASE_URL": engine.url.render_as_string(hide_password=False),
            "PYTHONPATH": str(BACKEND),
        }
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=workdir,  # sin `.env`: el backend solo conoce la base efímera
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 60
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                        break
                except OSError:
                    if server.poll() is not None or time.time() > deadline:
                        pytest.fail("the backend did not start")
                    time.sleep(0.3)

            done = subprocess.run(
                [node, str(SCRIPT)],
                cwd=SCRIPT.parent.parent,
                env={**os.environ, "AMAZONA_API_URL": f"http://127.0.0.1:{port}", "PRODUCT_ID": product_id},
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert done.returncode == 0, done.stderr[-2000:]
            report = json.loads(done.stdout.strip().splitlines()[-1])
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()

        # A. veinte clics iguales a la vez: una petición y un pedido.
        assert report["burst"] == {"requests": 1, "distinctOrders": 1}
        assert orders_of(engine, "sim_e2e_burst") == 1

        # B-D. la petición salió y el cliente no recibió respuesta (timeout, red, 502): el reintento lleva la misma
        # clave
        #      y sigue habiendo un solo pedido en la base de datos.
        for loss in ("timeout", "network", "gateway"):
            assert report[loss] == {
                "firstFailed": True,
                "sameKeyKept": True,
                "requests": 2,
                "answeredWithOriginal": True,
            }, loss
            assert orders_of(engine, f"sim_e2e_{loss}") == 1, loss

        # J. dos formularios independientes son dos intenciones.
        assert report["twoForms"] == {"distinctOrders": 2}
        assert orders_of(engine, "sim_e2e_twoforms") == 2

        # F. parámetros distintos, otra intención: el primero (reintentado) y el cambiado.
        assert report["changed"] == {"distinctOrders": 2}
        assert orders_of(engine, "sim_e2e_changed") == 2, "the retried one and the changed one, nothing else"

        # I. tras un éxito, una acción deliberada nueva es otro pedido.
        assert report["again"] == {"distinctOrders": 2}
        assert orders_of(engine, "sim_e2e_again") == 2

        # Contraste: sin conservar la clave, el reintento tras perder la respuesta duplica el pedido.
        assert report["withoutKeeper"] == {"requests": 2}
        assert orders_of(engine, "sim_e2e_nokeeper") == 2, "this is the bug the intent keys prevent"
