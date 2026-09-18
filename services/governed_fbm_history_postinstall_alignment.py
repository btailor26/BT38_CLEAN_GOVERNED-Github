"""Retired FBM History post-install compatibility module.

History controls now have one active owner. The former all-orders Health
installer is a no-op compatibility shim and is not installed from main.py, so
this module must not monkey-patch that retired installer back into the runtime.
"""
from __future__ import annotations


def install_governed_fbm_history_postinstall_alignment(app):
    """Compatibility no-op; installs no reader, controls or runtime authority."""
    return app
