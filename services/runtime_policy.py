# BT38 Unified Runtime Policy Layer
# SINGLE SOURCE OF TRUTH FOR PUSH / SYNC / IMPORT

from dataclasses import dataclass

@dataclass
class RuntimePolicy:
    push_allowed: bool
    import_allowed: bool
    sync_allowed: bool
    auto_push_allowed: bool
    blocked_reason: str | None = None


def build_runtime_policy(config):
    """
    Centralised decision engine.
    Replaces scattered _config_on logic across runtime.
    """

    push_allowed = (
        getattr(config, "push_enabled", False)
        and getattr(config, "runtime_push_enabled", False)
        and getattr(config, "marketplace_push_enabled", False)
    )

    import_allowed = (
        getattr(config, "import_enabled", False)
        and getattr(config, "runtime_import_enabled", False)
        and getattr(config, "marketplace_import_enabled", False)
    )

    sync_allowed = (
        getattr(config, "sync_enabled", False)
        and getattr(config, "runtime_sync_enabled", False)
        and getattr(config, "sync_worker_enabled", False)
    )

    auto_push_allowed = (
        getattr(config, "auto_push_enabled", False)
        and push_allowed
    )

    return RuntimePolicy(
        push_allowed=push_allowed,
        import_allowed=import_allowed,
        sync_allowed=sync_allowed,
        auto_push_allowed=auto_push_allowed,
    )
