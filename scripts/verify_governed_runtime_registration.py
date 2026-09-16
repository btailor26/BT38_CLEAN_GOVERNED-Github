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

# Import the deployed application registration graph. Do not inspect config,
# environment values, request bodies, sessions, credentials, or database rows.
import main  # noqa: E402

app = main.app
modules = sorted(name for name in sys.modules if name.startswith(("services.", "governed_")))
routes = sorted(f"{','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))} {rule.rule} -> {rule.endpoint}" for rule in app.url_map.iter_rules())
modules_out.write_text("\n".join(modules) + "\n", encoding="utf-8")
routes_out.write_text("\n".join(routes) + "\n", encoding="utf-8")
print(f"RUNTIME_REGISTRATION_OK modules={len(modules)} routes={len(routes)}")
