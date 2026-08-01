"""E3 (flywheel plan Phase E residual): compliance grants for domain-scoped agents.

Loads frozen-config/compliance_grants.json and provides static SQL-table
extraction so CI (test_ln7_compliance_grants.py) can verify that the
marketing/growth domain never queries a table outside its explicit grant
(i.e. never touches clinical/PII tables like users, conversation_history,
nevedal_metrics, sensitive_bridge_*, client_metrics).

This module does no runtime enforcement (there is no query-interception
layer in asyncpg) — the ledger is the CI test itself, plus this module's
`extract_tables_from_sql()` which the test reuses so extraction logic
lives in exactly one place.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("ln7_compliance_grants")

# Deliberately duplicated (not imported) from ln7_frozen_config.frozen_config_dir()
# / load_json() so this module has zero cross-module import surface — keeps it
# safe to load standalone in offline CI fences (see test_ln7_compliance_grants.py
# header comment re: numpy FPE import-chain avoidance).
_REPO_DEFAULT = Path(__file__).resolve().parents[3] / "frozen-config"


def _frozen_config_dir() -> Path:
    env = os.getenv("FROZEN_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    if Path("/opt/ln7/frozen-config").is_dir():
        return Path("/opt/ln7/frozen-config")
    return _REPO_DEFAULT


def load_json(name: str, default: Optional[Any] = None) -> Any:
    path = _frozen_config_dir() / name
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("load_json %s failed: %s", name, e)
        return default


_SQL_TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
    re.IGNORECASE,
)
_DELETE_FROM_PATTERN = re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)

# Postgres/asyncpg keywords that can legally follow FROM/JOIN/INTO in ways
# that are not table names (subqueries, CTEs aliased inline, etc). Kept
# deliberately short — false positives here would silently widen the grant.
_NON_TABLE_TOKENS = {
    "unnest",
    "generate_series",
    "jsonb_each",
    "jsonb_array_elements",
    # Reserved-word false captures: "ON CONFLICT DO UPDATE SET ..." and
    # "FOR UPDATE SKIP LOCKED" both put a keyword immediately after UPDATE
    # where a table name would otherwise be expected.
    "set",
    "skip",
    "locked",
    "distinct",
    "only",
}

# A string literal is only treated as SQL (and scanned for table refs) if it
# actually opens with a SQL statement keyword once leading whitespace is
# stripped. This is what separates a real `conn.execute("""UPDATE users...""")`
# call from prose like "derived from policy config" or "removed from set of
# themes" inside a docstring/comment, which would otherwise false-positive on
# the bare FROM/INTO/UPDATE regex above.
_SQL_STATEMENT_START = re.compile(
    r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH)\b", re.IGNORECASE
)


def compliance_grants() -> Dict[str, dict]:
    """Return the {domain: {"paths": [...], "allowed_tables": [...]}} map."""
    data = load_json("compliance_grants.json", default={}) or {}
    return dict(data.get("domains") or {})


def allowed_tables_for(domain: str) -> Set[str]:
    domain_cfg = compliance_grants().get(domain) or {}
    return {t.split(".")[0].lower() for t in (domain_cfg.get("allowed_tables") or [])}


def domain_paths(domain: str) -> List[str]:
    domain_cfg = compliance_grants().get(domain) or {}
    return list(domain_cfg.get("paths") or [])


def _string_literals(source_text: str) -> List[str]:
    """Extract string-literal contents (regular + f-string static parts) via
    AST so the SQL-table regex only ever scans actual string bodies — never
    Python syntax like `from __future__ import annotations` / `import typing`,
    which would otherwise false-positive-match `FROM __future__`.

    If the text doesn't parse as Python (e.g. a bare SQL snippet passed
    directly in tests), fall back to scanning the raw text as-is.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return [source_text]

    literals: List[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
            if isinstance(node.value, str):
                literals.append(node.value)

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:  # noqa: N802
            parts = [
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            literals.append("".join(parts))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return literals


def extract_tables_from_sql(source_text: str) -> Set[str]:
    """Best-effort static extraction of table names referenced in SQL string
    literals within a Python source file (or a raw SQL snippet).

    Not a real SQL parser — intentionally conservative regex matching
    consistent with other CI static-analysis patterns in this repo
    (see auditor endpoint counters, sql-schema-verification.mdc).
    """
    tables: Set[str] = set()
    for literal in _string_literals(source_text):
        if not _SQL_STATEMENT_START.match(literal):
            continue
        for match in _SQL_TABLE_PATTERN.finditer(literal):
            name = match.group(1).split(".")[0].lower()
            if name not in _NON_TABLE_TOKENS:
                tables.add(name)
        for match in _DELETE_FROM_PATTERN.finditer(literal):
            tables.add(match.group(1).lower())
    return tables


def files_for_domain(domain: str, repo_root: Path) -> List[Path]:
    """Resolve the domain's configured paths into concrete .py files."""
    files: List[Path] = []
    for rel in domain_paths(domain):
        p = repo_root / rel
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        elif p.is_file():
            files.append(p)
    return files


def violations_for_domain(domain: str, repo_root: Path) -> Dict[str, Set[str]]:
    """Return {relative_file_path: {disallowed_table, ...}} for any file in
    the domain whose SQL references a table not in the domain's grant.
    Empty dict means fully compliant.
    """
    allowed = allowed_tables_for(domain)
    out: Dict[str, Set[str]] = {}
    for path in files_for_domain(domain, repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        referenced = extract_tables_from_sql(text)
        disallowed = {t for t in referenced if t not in allowed}
        if disallowed:
            out[str(path.relative_to(repo_root))] = disallowed
    return out
