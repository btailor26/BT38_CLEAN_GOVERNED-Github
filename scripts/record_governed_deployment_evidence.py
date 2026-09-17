#!/usr/bin/env python3
"""Build an append-only, secret-free BT38 governed deployment evidence record."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(os.getenv("BT38_EVIDENCE_OUT", "deployment-evidence.json"))


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_alias(primary: str, legacy: str = "", default: str = "") -> str:
    value = env(primary)
    if value:
        return value
    return env(legacy, default) if legacy else default


def read_lines_path(path_value: str) -> list[str]:
    if not path_value or not Path(path_value).exists():
        return []
    return [line.rstrip("\n") for line in Path(path_value).read_text(encoding="utf-8").splitlines() if line.strip()]


def read_lines(name: str) -> list[str]:
    return read_lines_path(env(name))


def parse_hashes(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2:
            result[parts[1].lstrip("*")] = parts[0]
    return result


# The deploy workflow uses explicit expected/production names. Keep the older
# aliases only for local/older evidence callers.
source = parse_hashes(read_lines_path(env_alias("BT38_EXPECTED_SOURCE_HASH_FILE", "BT38_SOURCE_HASH_FILE")))
production = parse_hashes(read_lines_path(env_alias("BT38_PRODUCTION_SOURCE_HASH_FILE", "BT38_PRODUCTION_HASH_FILE")))
changed = read_lines("BT38_CHANGED_FILES_FILE")
missing = sorted(set(source) - set(production))
mismatched = sorted(path for path in set(source) & set(production) if source[path] != production[path])
source_verified = bool(source) and len(source) == len(production) and not missing and not mismatched
runtime_verified = (
    env_alias("BT38_DB_CONTRACT_RESULT", "BT38_DB_CONTRACT") == "PASS"
    and env_alias("BT38_PUBLIC_SMOKE_RESULT", "BT38_PUBLIC_SMOKE") == "PASS"
)
verified = source_verified and runtime_verified

record = {
    "schema": "bt38.governed-deployment-evidence.v1",
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "repository": env("GITHUB_REPOSITORY"),
    "workflow_run_id": env("GITHUB_RUN_ID"),
    "workflow_run_attempt": env("GITHUB_RUN_ATTEMPT"),
    "branch": env("GITHUB_REF_NAME"),
    "commit": env("BT38_DEPLOY_COMMIT", env("GITHUB_SHA")),
    "previous_deployed_commit": env("BT38_PREVIOUS_DEPLOY_COMMIT"),
    "verified": verified,
    "fly": {
        "app": env("BT38_FLY_APP", "bt38-prod"),
        "machine_before": env("BT38_MACHINE_BEFORE"),
        "machine_after": env("BT38_MACHINE_AFTER"),
        "image_before": env("BT38_IMAGE_BEFORE"),
        "image_after": env("BT38_IMAGE_AFTER"),
    },
    "movement": {"changed_files": changed, "changed_file_count": len(changed)},
    "production_source": {
        "tracked_file_count": len(source),
        "production_file_count": len(production),
        "missing": missing,
        "mismatched": mismatched,
        "verified": source_verified,
        "source_manifest_sha256": hashlib.sha256("\n".join(f"{source[k]}  {k}" for k in sorted(source)).encode()).hexdigest() if source else "",
        "production_manifest_sha256": hashlib.sha256("\n".join(f"{production[k]}  {k}" for k in sorted(production)).encode()).hexdigest() if production else "",
    },
    "runtime": {
        "loaded_bt38_modules": read_lines("BT38_LOADED_MODULES_FILE"),
        "registered_routes": read_lines("BT38_REGISTERED_ROUTES_FILE"),
        "db_contract": env_alias("BT38_DB_CONTRACT_RESULT", "BT38_DB_CONTRACT"),
        "public_smoke": env_alias("BT38_PUBLIC_SMOKE_RESULT", "BT38_PUBLIC_SMOKE"),
        "verified": runtime_verified,
    },
    "boundaries": {"no_merge_performed": True, "secrets_recorded": False, "customer_payloads_recorded": False},
}

OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"DEPLOYMENT_EVIDENCE_WRITTEN path={OUT} commit={record['commit']} verified={record['verified']}")
if not source_verified:
    raise SystemExit(f"Production source evidence failed: missing={missing} mismatched={mismatched} source={len(source)} production={len(production)}")
if not runtime_verified:
    raise SystemExit("Runtime deployment evidence failed: DB/public smoke contract is not PASS")
