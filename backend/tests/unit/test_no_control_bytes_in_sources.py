"""Ningún fichero de código ni de prueba contiene un byte de control (Milestone 45, Commit 12).

Un `\\b` escrito a través de una herramienta que interpreta las barras se convierte en el carácter de retroceso
(0x08), y una expresión regular con `^H` en lugar de `\\b` **no casa con lo que dice casar, sin dar ningún error**. Pasó
dos veces: en el Commit 10 (dos pruebas del Control Center cuyas mutaciones «sobrevivían» sin motivo) y se descubrió
en el Commit 12 que `test_m44_architecture.py` llevaba cinco desde M44, así que su guarda de arquitectura apenas casaba
nada.

Un fallo así es el peor posible para una prueba: sigue en verde. Por eso se vigila **en todo el árbol de fuentes**.
Solo se permiten el tabulador, el salto de línea y el retorno de carro.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCANNED = [
    (REPO / "backend" / "app", {".py"}),
    (REPO / "backend" / "tests", {".py"}),
    (REPO / "backend" / "alembic", {".py"}),
    (REPO / "apps" / "control-center" / "app", {".ts", ".tsx"}),
    (REPO / "apps" / "control-center" / "components", {".ts", ".tsx"}),
    (REPO / "apps" / "control-center" / "lib", {".ts", ".tsx"}),
]
ALLOWED = {0x09, 0x0A, 0x0D}


def test_no_source_file_carries_a_control_byte():
    offenders: list[str] = []
    scanned = 0
    for root, suffixes in SCANNED:
        if not root.exists():  # un checkout sin el frontend (o sin el backend) no es un fallo de este test
            continue
        for path in root.rglob("*"):
            if path.suffix not in suffixes or "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            scanned += 1
            bad = sorted({b for b in path.read_bytes() if b < 0x20 and b not in ALLOWED})
            if bad:
                offenders.append(f"{path.relative_to(REPO)}: bytes {[hex(b) for b in bad]}")
    assert scanned > 100, f"the scan looked at only {scanned} files: the paths are wrong"
    assert offenders == [], "a `\\b` (or another escape) became a control character:\n" + "\n".join(offenders)
