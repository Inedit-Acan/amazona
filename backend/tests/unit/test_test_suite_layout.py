"""La estructura de los tests no depende de cómo se lance pytest (hardening pre-M44).

`tests/` no es un paquete (no hay `__init__.py`): pytest mete en `sys.path` el directorio
de cada fichero de test. Por eso un test que importa a otro, o un helper que solo
resuelve desde otro directorio, o dos ficheros con el mismo nombre, funcionan con
`python -m pytest` (que añade el cwd) y fallan con `pytest` a secas, o al revés. Ya
ocurrió en el Milestone 41. Estas reglas lo impiden:

1. ningún test importa a otro test;
2. un helper compartido (`*_test_support.py`) solo se importa desde su propio directorio;
3. no hay dos ficheros de test con el mismo nombre en directorios distintos.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def _py_files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_no_test_module_imports_another_test_module():
    offenders = {
        str(path.relative_to(TESTS)): sorted(m for m in _imported_top_level_modules(path) if m.startswith("test_"))
        for path in _py_files()
    }
    offenders = {file: modules for file, modules in offenders.items() if modules}

    assert offenders == {}, "shared code belongs in a *_test_support.py module, not in a test"


def test_a_support_module_is_only_imported_from_its_own_directory():
    support = {p.stem: p.parent for p in _py_files() if p.stem.endswith("_test_support")}
    misplaced = []
    for path in _py_files():
        for module in _imported_top_level_modules(path) & support.keys():
            if path.parent != support[module]:
                misplaced.append(f"{path.relative_to(TESTS)} imports {module}")

    assert misplaced == []


def test_test_file_names_are_unique_across_directories():
    by_name: dict[str, list[str]] = {}
    for path in _py_files():
        if path.name.startswith("test_"):
            by_name.setdefault(path.name, []).append(str(path.parent.relative_to(TESTS)))
    duplicated = {name: dirs for name, dirs in by_name.items() if len(dirs) > 1}

    assert duplicated == {}, "two test files with the same name collide under pytest's default import mode"
