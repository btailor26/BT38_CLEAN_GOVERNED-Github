#!/usr/bin/env python3
"""Record runtime registration names only for governed deployment evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

modules_out = Path(os.getenv("BT38_LOADED_MODULES_FILE", "loaded-bt38-modules.txt"))
routes_out = Path(os.getenv("BT38_REGISTERED_ROUTES_FILE", "registered-routes.txt"))

# This verifier is copied to /tmp on the Fly machine. Explicitly point Python at
# the deployed application root before importing main; cwd alone does not change
# sys.path for a script executed by absolute /tmp path.
app_root = Path(os.getenv("BT38_APP_ROOT", "/app")).resolve()
if not (app_root / "main.py").is_file():
    raise SystemExit(f"RUNTIME_REGISTRATION_FAIL missing={app_root / 'main.py'}")
sys.path.insert(0, str(app_root))

# Runtime evidence must be read-only with respect to marketplace startup
# alignment. main.py honours this flag only for the diagnostic import.
os.environ["BT38_RUNTIME_EVIDENCE_IMPORT"] = "1"

# Prefer the names-only snapshot written by the already-loaded production app.
# Importing a second complete BT38 application inside the same Fly machine can
# duplicate the runtime graph and exhaust the machine while evidence is being
# collected. The live worker snapshot is therefore the production authority.
live_modules = Path("/tmp/bt38-live-loaded-modules.txt")
live_routes = Path("/tmp/bt38-live-registered-routes.txt")
if live_modules.is_file() and live_routes.is_file():
    modules_out.write_text(live_modules.read_text(encoding="utf-8"), encoding="utf-8")
    routes_out.write_text(live_routes.read_text(encoding="utf-8"), encoding="utf-8")
    modules_count = len([line for line in modules_out.read_text(encoding="utf-8").splitlines() if line])
    routes_count = len([line for line in routes_out.read_text(encoding="utf-8").splitlines() if line])
    if modules_count <= 0 or routes_count <= 0:
        raise SystemExit("RUNTIME_REGISTRATION_FAIL empty_live_snapshot")
    print(f"RUNTIME_REGISTRATION_OK source=live-worker modules={modules_count} routes={routes_count}")
    raise SystemExit(0)

# Do not fall back to importing main here. This script runs as a second process
# inside the 512 MB production machine; a second full application graph is not
# runtime evidence and can terminate under resource pressure. Absence of the
# worker-owned snapshot is therefore an explicit, cheap, fail-closed condition.
raise SystemExit("RUNTIME_REGISTRATION_FAIL missing_live_worker_snapshot")
