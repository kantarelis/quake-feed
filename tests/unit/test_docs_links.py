"""Guards documentation links against rot.

The repo's entry-point docs — ``README.md`` and ``CLAUDE.md`` — link to the
subsystem deep-dives under ``docs/`` and to embedded assets (the demo GIF, the
coverage badge). Epic 9 began from exactly the failure these tests catch:
both files referenced ``docs/architecture.md``, ``docs/database-migrations.md``,
and ``docs/task-scheduler.md`` while none of those files existed.

Two directions are checked:

* every *local* link in ``README.md`` / ``CLAUDE.md`` resolves to a real path
  (dead-link guard), and
* every subsystem doc under ``docs/*.md`` is referenced by at least one of them
  (orphan guard — ``docs/frontend.md`` was orphaned before Epic 9 Task 4).

External (``http``/``https``/``mailto``) links and in-page ``#`` anchors are out
of scope, as are links to the planning docs (``MASTER_PLAN.md`` / ``PLAN.md``):
those were removed from the tree and live only in git history, while ``CLAUDE.md``
still documents the workflow that names them — so a link to either is expected
*not* to resolve on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_ENTRY_DOCS = (_ROOT / "README.md", _ROOT / "CLAUDE.md")

# Markdown `](target)` plus HTML `src="…"` / `href="…"`.
_MD_LINK_RE = re.compile(r"\]\(([^)\s]+)")
_HTML_ATTR_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')

_SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")


def _local_targets(text: str) -> set[str]:
    """Relative repo paths referenced by a doc, minus externals and anchors."""
    targets: set[str] = set()
    for target in _MD_LINK_RE.findall(text) + _HTML_ATTR_RE.findall(text):
        if target.startswith(_SKIP_PREFIXES):
            continue
        # Drop any #fragment / ?query, keep the path.
        path = target.split("#", 1)[0].split("?", 1)[0]
        if path:
            targets.add(path)
    return targets


def test_subsystem_docs_are_referenced() -> None:
    """Every docs/*.md deep-dive is linked from README.md or CLAUDE.md."""
    referenced = set().union(*(_local_targets(doc.read_text()) for doc in _ENTRY_DOCS))
    orphans = [
        md.relative_to(_ROOT).as_posix()
        for md in sorted(_ROOT.glob("docs/*.md"))
        if md.relative_to(_ROOT).as_posix() not in referenced
    ]
    assert not orphans, f"docs not linked from README/CLAUDE: {orphans}"
