#!/usr/bin/env python3
"""Create deterministic hashes for tracked BT38 runtime source paths.

Input is the repository's tracked-file list. Output contains only hashes and paths;
file contents and environment/configuration values are never emitted.

The runtime manifest must not select paths that the production Docker context
explicitly excludes. Keep these exclusions aligned with .dockerignore so the
post-deploy fingerprint check proves files that can actually exist under /app.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(os.getenv("BT38_SOURCE_ROOT", ".")).resolve()
LIST = Path(os.getenv("BT38_TRACKED_FILES_FILE", "tracked-production-files.txt"))
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

entries: list[tuple[str, str]] = []
for raw in LIST.read_text(encoding="utf-8").splitlines():
    rel = raw.strip().replace("\\", "/")
    if not allowed(rel):
        continue
    target = (ROOT / rel).resolve()
    if ROOT not in target.parents and target != ROOT:
        raise SystemExit(f"Refusing path outside source root: {rel}")
    if not target.is_file():
        raise SystemExit(f"Tracked runtime source missing: {rel}")
    entries.append((rel, hashlib.sha256(target.read_bytes()).hexdigest()))

if not entries:
    raise SystemExit("No tracked runtime source files selected")
OUT.write_text("".join(f"{digest}  {rel}\n" for rel, digest in sorted(entries)), encoding="utf-8")
print(f"SOURCE_MANIFEST_OK files={len(entries)} path={OUT}")
