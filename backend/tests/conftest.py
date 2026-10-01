"""Configuración común de las pruebas.

Los tests no leen `backend/.env`. En CI ese fichero no existe y `DATABASE_URL` llega
del entorno (el servicio PostgreSQL efímero del workflow); en local sí existe y apunta a
la base real, así que un `pytest` a secas ejecutaba los tests de conectividad contra
ella, y cualquier test que escribiera en «la base configurada» habría escrito allí.

Quitar el `.env` de la lectura hace que local y CI vean los mismos valores por
defecto. Quien quiera probar contra una base concreta sigue pudiendo: exporta
`DATABASE_URL` en el entorno (las variables de entorno no se tocan aquí).

**Ningún test sale de la máquina** (invariante I12, hardening pre-M44). Un fixture automático
intercepta `socket.connect`: solo deja pasar `127.0.0.0/8`, `::1` y los sockets de Unix (la base
PostgreSQL local o efímera, el servicio del CI). Cualquier otro destino se **registra y se
rechaza**, y el test **falla al terminar** aunque el código bajo prueba se haya tragado el error
(un adaptador que convierte «sin red» en «fuente no disponible» seguiría dando verde). Así un
proveedor real no puede llamarse por descuido: ni con una clave que sobró en el entorno, ni con un
adaptador real que se coló donde iba uno falso.
"""

import ipaddress
import socket

import pytest

from app.core.config import Settings

Settings.model_config["env_file"] = None


def _is_local(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped and mapped.is_loopback)


@pytest.fixture(autouse=True)
def network_attempts(monkeypatch):
    """Los intentos de salir de la máquina durante este test. Vacía al terminar, o el test falla."""
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def blocked(address) -> bool:
        if not isinstance(address, tuple) or not address:
            return False  # un socket de Unix (o algo que no es un destino de red)
        host = str(address[0])
        if _is_local(host):
            return False
        attempts.append(f"{host}:{address[1] if len(address) > 1 else '?'}")
        return True

    def guarded_connect(self, address, *args, **kwargs):
        if blocked(address):
            raise OSError(f"network access is blocked in tests: {address[0]}")
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        if blocked(address):
            return 101  # ENETUNREACH
        return real_connect_ex(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield attempts
    if attempts:
        pytest.fail(
            "this test tried to reach outside the machine (a real provider must never be called from a test): "
            + ", ".join(attempts)
        )
