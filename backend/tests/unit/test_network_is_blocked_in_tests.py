"""Invariante I12: ningún proveedor real puede ser llamado durante los tests (hardening pre-M44).

El guardia vive en `tests/conftest.py` y se aplica a **todos** los tests. Aquí se prueba el guardia: que bloquea lo que
sale de la máquina, que deja pasar lo local (la base PostgreSQL) y, sobre todo, que un test falla aunque el código bajo
prueba se trague el error de red —un adaptador que convierte «sin red» en «fuente no disponible» daría verde sin él—.
"""

import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2]
PUBLIC_ADDRESS = ("93.184.216.34", 443)  # una dirección pública de verdad: nada de esto llega a salir


def test_a_connection_to_a_public_address_is_refused_and_recorded(network_attempts):
    with pytest.raises(OSError, match="blocked in tests"):
        socket.create_connection(PUBLIC_ADDRESS, timeout=1)

    assert network_attempts == ["93.184.216.34:443"]
    network_attempts.clear()  # el intento era el objeto de este test


def test_connect_ex_reports_an_error_instead_of_connecting(network_attempts):
    with socket.socket() as sock:
        assert sock.connect_ex(PUBLIC_ADDRESS) != 0

    assert network_attempts == ["93.184.216.34:443"]
    network_attempts.clear()


def test_an_http_client_cannot_reach_a_provider_either(network_attempts):
    with pytest.raises(httpx.HTTPError):
        httpx.Client(timeout=1).get(f"http://{PUBLIC_ADDRESS[0]}/")

    assert network_attempts == ["93.184.216.34:80"]
    network_attempts.clear()


def test_loopback_is_not_blocked_because_the_local_database_lives_there(network_attempts):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass

    assert network_attempts == []


def test_a_unix_style_pair_of_sockets_is_not_blocked(network_attempts):
    left, right = socket.socketpair()
    left.close()
    right.close()

    assert network_attempts == []


def test_a_test_fails_even_if_the_code_under_test_swallows_the_network_error(tmp_path):
    (tmp_path / "conftest.py").write_text((BACKEND / "tests" / "conftest.py").read_text(encoding="utf-8"), "utf-8")
    (tmp_path / "test_swallows_the_error.py").write_text(
        textwrap.dedent(
            """
            import socket


            def test_a_provider_adapter_that_turns_no_network_into_a_graceful_answer():
                try:
                    socket.create_connection(("93.184.216.34", 443), timeout=1)
                except OSError:
                    pass  # «la fuente no está disponible»: el test creería que todo fue bien
            """
        ),
        "utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0
    assert "tried to reach outside the machine" in result.stdout + result.stderr
    assert "93.184.216.34:443" in result.stdout + result.stderr
