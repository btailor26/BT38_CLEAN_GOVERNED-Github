#!/usr/bin/env python3
"""Create deterministic hashes for the runtime source touched by this deploy event.

The governed deploy writes deployment-evidence/changed-files.txt immediately before
this script runs.  When that event file is present it is the authority: only runtime
paths changed by the current deploy stage are fingerprinted.  The tracked-file list
remains a local/CI fallback so this helper can still be exercised outside deployment.

Output contains only hashes and paths; file contents and environment/configuration
values are never emitted.  Paths excluded from the production Docker context are
also excluded here.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(os.getenv("BT38_SOURCE_ROOT", ".")).resolve()
TRACKED_LIST = Path(os.getenv("BT38_TRACKED_FILES_FILE", "tracked-production-files.txt"))
EVENT_LIST = Path(os.getenv("BT38_CHANGED_FILES_FILE", "deployment-evidence/changed-files.txt"))
OUT = Path(os.getenv("BT38_SOURCE_HASH_FILE", "source-production-hashes.txt"))

EXCLUDED_PREFIXES = (
    ".git/", ".github/", "docs/", "tests/", "_retired_tests/",
    ".venv/", "venv/", "env/", "node_modules/",
    "static/uploads/", "instance/", "fake_db/",
    "audit/", "_bt38_backups/", "recovery_reports/", "reports/", "attached_assets/",
)
EXCLUDED_NAMES = {
    ".env", ".env.production", ".env.local", "PR_DESCRIPTION.md", "nul", "idle",
}
ALLOWED_SUFFIXES = {".py", ".html", ".js", ".css", ".toml", ".json"}
ALLOWED_NAMES = {"Dockerfile", "Procfile"}


def allowed(path: str) -> bool:
    clean = path.replace("\\", "/").lstrip("./")
    if not clean or clean in EXCLUDED_NAMES or any(clean.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    p = Path(clean)
    return p.name in ALLOWED_NAMES or p.suffix.lower() in ALLOWED_SUFFIXES


def input_list() -> tuple[Path, str]:
    explicit = os.getenv("BT38_CHANGED_FILES_FILE")
    if explicit:
        event = Path(explicit)
        if not event.is_file():
            raise SystemExit(f"Deploy event file missing: {event}")
        return event, "deploy-event"
    if EVENT_LIST.is_file():
        return EVENT_LIST, "deploy-event"
    if not TRACKED_LIST.is_file():
        raise SystemExit(f"Tracked source list missing: {TRACKED_LIST}")
    return TRACKED_LIST, "tracked-fallback"


LIST, MODE = input_list()
entries: list[tuple[str, str]] = []
selected_runtime_paths = 0
for raw in LIST.read_text(encoding="utf-8").splitlines():
    rel = raw.strip().replace("\\", "/")
    if not allowed(rel):
        continue
    target = (ROOT / rel).resolve()
    if ROOT not in target.parents and target != ROOT:
        raise SystemExit(f"Refusing path outside source root: {rel}")
    # A deleted runtime path is intentionally absent from the new image and cannot
    # have a source hash.  Deployment rebuild + runtime/smoke contracts remain the
    # authority for deletion.  Existing changed runtime files are fingerprinted.
    if not target.exists():
        continue
    if not target.is_file():
        raise SystemExit(f"Changed runtime source is not a file: {rel}")
    selected_runtime_paths += 1
    entries.append((rel, hashlib.sha256(target.read_bytes()).hexdigest()))

# A deploy event may contain only workflow/tests/docs changes.  That is valid and
# must not trigger a repository-wide fallback scan.
OUT.write_text("".join(f"{digest}  {rel}\n" for rel, digest in sorted(entries)), encoding="utf-8")
print(f"SOURCE_MANIFEST_OK mode={MODE} files={len(entries)} path={OUT}")
