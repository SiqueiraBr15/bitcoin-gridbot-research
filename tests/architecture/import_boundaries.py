"""Resolve static import targets without importing or executing inspected modules."""

import ast
from importlib.util import resolve_name
from pathlib import Path


def imported_targets(tree: ast.AST, path: Path, source_root: Path) -> set[str]:
    package = ".".join(path.relative_to(source_root).parts[:-1])
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names)
    return targets
