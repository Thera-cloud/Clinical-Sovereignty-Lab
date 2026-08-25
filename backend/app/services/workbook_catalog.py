"""Shared coaching-workbook catalog for LN, AlphaLN, and Queens.

Workbooks are coaching methods clients may consider — not therapy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence

COACHING_STANCE = (
    "Workbooks are coaching methods and structured exercises a client may consider. "
    "They are not therapy, diagnosis, or medical treatment. Offer them as optional tools. "
    "Cite the source file. Walk the client through steps only with their consent."
)

_TEXT_EXT = {".txt", ".md", ".pdf"}
_SKIP_NAMES = {".ds_store"}


def resolve_workbook_roots() -> List[Path]:
    roots: List[Path] = []
    env = (os.getenv("WORKBOOKS_DIR") or "").strip()
    if env:
        roots.append(Path(env))
    here = Path(__file__).resolve()
    repo = here.parents[3] if len(here.parents) >= 4 else here.parents[-1]
    backend = here.parents[2] if len(here.parents) >= 3 else repo
    roots.extend(
        [
            repo / "Workbooks",
            Path("/Workbooks"),
            Path("/app/workbooks"),
            backend / "resources" / "therapeutic_library" / "protocol_workbooks",
        ]
    )
    seen = set()
    out: List[Path] = []
    for p in roots:
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.exists() and p.is_dir():
            out.append(p)
    return out


def iter_workbook_files(roots: Sequence[Path] | None = None) -> List[Path]:
    files: List[Path] = []
    for root in roots or resolve_workbook_roots():
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if p.name.lower() in _SKIP_NAMES:
                    continue
                if p.suffix.lower() not in _TEXT_EXT:
                    continue
                files.append(p)
        except OSError:
            continue
    files.sort(key=lambda x: x.name.lower())
    return files


def catalog_titles(max_files: int = 24) -> List[str]:
    titles: List[str] = []
    seen = set()
    for p in iter_workbook_files():
        name = p.name
        if name in seen:
            continue
        seen.add(name)
        titles.append(name)
        if len(titles) >= max_files:
            break
    return titles


def coaching_system_block(max_files: int = 20) -> str:
    titles = catalog_titles(max_files=max_files)
    if not titles:
        return (
            f"COACHING WORKBOOK LIBRARY: empty or unmounted. {COACHING_STANCE}"
        )
    listing = "; ".join(titles)
    return (
        f"COACHING WORKBOOK LIBRARY (tools, not therapy): {COACHING_STANCE} "
        f"Available files: {listing}. When a client wants a method, pick the matching "
        f"workbook, name it, and coach them through it as a suggested exercise."
    )


def relative_label(path: Path, roots: Iterable[Path] | None = None) -> str:
    for root in roots or resolve_workbook_roots():
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            continue
    return path.name
