"""Text-source allowlist used by static policy tests (never decodes bytecode)."""

from __future__ import annotations

from pathlib import Path


TEXT_SUFFIXES = frozenset({".py", ".md", ".json", ".txt"})
TEXT_BASENAMES = frozenset({".env.example"})


def text_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and (path.suffix.casefold() in TEXT_SUFFIXES or path.name in TEXT_BASENAMES):
            yield path
