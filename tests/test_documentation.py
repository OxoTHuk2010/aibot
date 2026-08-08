"""Защищает обязательный контракт русской документации runtime-кода.

Аудит охватывает приложение и исполняемые Alembic-модули, но не требует
дублировать самодокументируемые имена каждого теста отдельным docstring.
"""

import ast
import io
import tokenize
from pathlib import Path

RUNTIME_ROOTS = (Path("app"), Path("alembic"))
DOCUMENTED_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _runtime_files() -> list[Path]:
    """Возвращает стабильный список Python-модулей приложения и Alembic."""
    return sorted(path for root in RUNTIME_ROOTS for path in root.rglob("*.py"))


def _contains_cyrillic(text: str) -> bool:
    """Определяет наличие русской буквы в документационном тексте."""
    return any("а" <= character.lower() <= "я" or character.lower() == "ё" for character in text)


def test_runtime_python_nodes_have_russian_docstrings() -> None:
    """Проверяет русские docstring каждого module, class, function и method."""
    violations: list[str] = []

    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, DOCUMENTED_NODES):
                continue
            docstring = ast.get_docstring(node, clean=False)
            name = getattr(node, "name", "<module>")
            line = getattr(node, "lineno", 1)
            if docstring is None:
                violations.append(f"{path}:{line}: отсутствует docstring у {name}")
            elif not _contains_cyrillic(docstring):
                violations.append(f"{path}:{line}: docstring {name} написан не по-русски")

    assert not violations, "\n".join(violations)


def test_runtime_prose_comments_are_russian() -> None:
    """Проверяет русский язык prose-комментариев, исключая директивы инструментов."""
    violations: list[str] = []

    for path in _runtime_files():
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            comment = token.string.removeprefix("#").strip()
            if not comment or "noqa" in comment or "type: ignore" in comment:
                continue
            if not _contains_cyrillic(comment):
                violations.append(f"{path}:{token.start[0]}: {comment}")

    assert not violations, "\n".join(violations)
