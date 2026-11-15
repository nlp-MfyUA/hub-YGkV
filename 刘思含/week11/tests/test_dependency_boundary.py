"""AST-based dependency boundary checks (C-DEP-001 ~ C-DEP-011).

The checks are intentionally static: they parse every Python file under
``pipeline/`` and ``app/`` and inspect its import statements.  Missing
directories are treated as empty, so the suite passes on a fresh skeleton.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = ROOT / "pipeline"
APP_DIR = ROOT / "app"
COMMON_TYPES = "pipeline.common.types"
REQUIREMENTS_PATH = ROOT / "requirements.txt"

LLM_SDK_ROOTS = frozenset(
    {
        "openai",
        "agents",
        "anthropic",
        "cohere",
        "litellm",
        "ollama",
        "langchain",
        "llama_index",
        "transformers",
        "google",
    }
)
PDF_IMAGE_ROOTS = frozenset(
    {
        "pdfplumber",
        "pdfminer",
        "fitz",
        "PIL",
        "mineru",
        "pypdf",
        "PyPDF2",
        "cv2",
        "paddleocr",
        "pytesseract",
        "imageio",
        "skimage",
    }
)
PHASE_PATTERN = re.compile(r"(?:^|\.)phase(?P<number>\d+)_")
PINNED_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.\-\[\]]+==[A-Za-z0-9_.\-+!]+$")
FORBIDDEN_APP_PATHS = ("data/images", "data/parsed_output")


@dataclass(frozen=True)
class ImportStatement:
    """One import statement together with its resolved module names."""

    file: Path
    line: int
    modules: tuple[str, ...]


def _python_files(base: Path) -> list[Path]:
    """Return all Python files below *base*, excluding caches."""
    if not base.is_dir():
        return []
    return sorted(
        path for path in base.rglob("*.py") if "__pycache__" not in path.parts
    )


def _package_parts(path: Path) -> tuple[str, ...]:
    """Return the package parts of *path* relative to the project root."""
    relative = path.relative_to(ROOT)
    return relative.parent.parts


def _resolved_modules(path: Path, node: ast.AST) -> tuple[str, ...]:
    """Resolve an Import/ImportFrom node into absolute module names."""
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    assert isinstance(node, ast.ImportFrom)
    if node.level:
        parts = list(_package_parts(path))
        up = node.level - 1
        if up:
            parts = parts[: len(parts) - up] if up <= len(parts) else []
        if node.module:
            parts.append(node.module)
        base = ".".join(parts)
    else:
        base = node.module or ""

    modules = [base] if base else []
    for alias in node.names:
        if alias.name != "*":
            modules.append(f"{base}.{alias.name}" if base else alias.name)
    return tuple(dict.fromkeys(modules))


def _imports(paths: list[Path]) -> list[ImportStatement]:
    """Parse *paths* and yield every import statement."""
    statements: list[ImportStatement] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                statements.append(
                    ImportStatement(
                        file=path,
                        line=node.lineno,
                        modules=_resolved_modules(path, node),
                    )
                )
    return statements


def _under(module: str, package: str) -> bool:
    """Return True when *module* is *package* or one of its children."""
    return module == package or module.startswith(package + ".")


def _root(module: str) -> str:
    """Return the top-level name of a dotted module."""
    return module.split(".", 1)[0]


def _describe(statements: list[ImportStatement]) -> str:
    """Format violations for assertion messages."""
    return "\n".join(
        f"{stmt.file.relative_to(ROOT)}:{stmt.line} -> " f"{', '.join(stmt.modules)}"
        for stmt in statements
    )


def _has_root(statement: ImportStatement, roots: frozenset[str]) -> bool:
    """Return True when any module of the statement has a banned root."""
    return any(_root(module) in roots for module in statement.modules)


def _phase_number(path: Path) -> int | None:
    """Extract N from a ``phase{N}_*`` path segment."""
    for part in path.relative_to(ROOT).parts:
        match = PHASE_PATTERN.search(part)
        if match:
            return int(match.group("number"))
    return None


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Collect ids of docstring constants, which must not be scanned."""
    ids: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _string_constants(paths: list[Path]) -> list[tuple[Path, int, str]]:
    """Yield non-docstring string constants with their locations."""
    found: list[tuple[Path, int, str]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        excluded = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in excluded
            ):
                found.append((path, node.lineno, node.value))
    return found


def test_pipeline_does_not_import_app() -> None:
    """C-DEP-001: nothing under pipeline/ may import app."""
    violations = [
        statement
        for statement in _imports(_python_files(PIPELINE_DIR))
        if any(_under(module, "app") for module in statement.modules)
    ]
    assert not violations, _describe(violations)


def test_app_only_imports_common_types_from_pipeline() -> None:
    """C-DEP-002: app/ may only use pipeline/common/types.py."""
    violations: list[ImportStatement] = []
    for statement in _imports(_python_files(APP_DIR)):
        pipeline_modules = [
            module for module in statement.modules if _under(module, "pipeline")
        ]
        if not pipeline_modules:
            continue
        if any(_under(module, COMMON_TYPES) for module in statement.modules):
            continue
        violations.append(statement)
    assert not violations, _describe(violations)


def test_pipeline_has_no_forward_phase_dependencies() -> None:
    """C-DEP-003: phase{N} must not import phase{M} when M > N."""
    violations: list[ImportStatement] = []
    for statement in _imports(_python_files(PIPELINE_DIR)):
        current = _phase_number(statement.file)
        if current is None:
            continue
        for module in statement.modules:
            match = PHASE_PATTERN.search(module)
            if match and int(match.group("number")) > current:
                violations.append(statement)
                break
    assert not violations, _describe(violations)


def test_common_types_is_a_leaf_module() -> None:
    """C-DEP-004: pipeline/common/types.py imports no phase or app module."""
    types_path = ROOT / "pipeline" / "common" / "types.py"
    violations = [
        statement
        for statement in _imports([types_path] if types_path.is_file() else [])
        if any(
            _under(module, "app") or PHASE_PATTERN.search(module)
            for module in statement.modules
        )
    ]
    assert not violations, _describe(violations)


def test_parsing_layers_do_not_import_llm_sdks() -> None:
    """C-DEP-005: parsing layers must not import LLM SDKs."""
    layers = [
        _python_files(PIPELINE_DIR / "phase2_parse"),
        _python_files(PIPELINE_DIR / "phase3_load"),
    ]
    violations = [
        statement
        for statement in _imports([path for layer in layers for path in layer])
        if _has_root(statement, LLM_SDK_ROOTS)
    ]
    assert not violations, _describe(violations)


def test_app_does_not_import_pdf_or_image_libraries() -> None:
    """C-DEP-008: app/ must not import PDF or image libraries."""
    violations = [
        statement
        for statement in _imports(_python_files(APP_DIR))
        if _has_root(statement, PDF_IMAGE_ROOTS)
    ]
    assert not violations, _describe(violations)


def test_app_does_not_touch_data_directories() -> None:
    """C-DEP-009/010: app/ must not read images or parsed outputs."""
    violations = [
        (path, line, value)
        for path, line, value in _string_constants(_python_files(APP_DIR))
        if any(
            forbidden in value.replace("\\", "/") for forbidden in FORBIDDEN_APP_PATHS
        )
    ]
    message = "\n".join(
        f"{path.relative_to(ROOT)}:{line} -> {value}"
        for path, line, value in violations
    )
    assert not violations, message


def test_requirements_are_exactly_pinned() -> None:
    """C-DEP-011: every requirement must use an ``==`` exact pin."""
    assert REQUIREMENTS_PATH.is_file(), "requirements.txt is missing"
    lines: list[str] = []
    for raw in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        lines.append(line)
    assert lines, "requirements.txt has no requirements"
    violations = [line for line in lines if not PINNED_REQUIREMENT.match(line)]
    assert not violations, "unpinned requirements:\n" + "\n".join(violations)
