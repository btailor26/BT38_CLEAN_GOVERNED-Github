#!/usr/bin/env python3
"""Record runtime registration names only for governed deployment evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

modules_out = Path(os.getenv("BT38_LOADED_MODULES_FILE", "loaded-bt38-modules.txt"))
routes_out = Path(os.getenv("BT38_REGISTERED_ROUTES_FILE", "registered-routes.txt"))

# Import the deployed application exactly as production does. Do not inspect config,
# environment values, request bodies, sessions, credentials, or database rows.
import main  # noqa: E402

app = main.app
modules = sorted(name for name in sys.modules if name.startswith(("services.", "governed_")))
routes = sorted(f"{','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))} {rule.rule} -> {rule.endpoint}" for rule in app.url_map.iter_rules())
modules_out.write_text("\n".join(modules) + "\n", encoding="utf-8")
routes_out.write_text("\n".join(routes) + "\n", encoding="utf-8")
print(f"RUNTIME_REGISTRATION_OK modules={len(modules)} routes={len(routes)}")
