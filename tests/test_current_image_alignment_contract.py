from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (ROOT / "Dockerfile.current-image-alignment").read_text(encoding="utf-8")
FLY = (ROOT / "fly.toml").read_text(encoding="utf-8")

BASE_COMMIT = "bac23966655e2486799f79b7c6518c825a675be8"
BASE_IMAGE = (
    "registry.fly.io/bt38-prod:deployment-01M2BK6REHCGKJQ34796T3WK8P"
    "@sha256:3f7ca913f010fea40a0b8fe20354cae7c010f802328fa0e1eb41258f32168a8b"
)


def test_candidate_alignment_reuses_exact_current_production_runtime_stack():
    assert f"FROM {BASE_IMAGE}" in OVERLAY
    assert 'dockerfile = "Dockerfile.current-image-alignment"' in FLY
    assert '^[[:space:]]*image' not in FLY
    assert "not a recovery-mode runtime" in OVERLAY


def test_alignment_layer_does_not_rebuild_dependencies_or_runtime_stack():
    forbidden = (
        "apt-get ",
        "pip install",
        "uv sync",
        "npm install",
        "npm ci",
        "python:3.11-slim",
    )
    for token in forbidden:
        assert token not in OVERLAY


def test_alignment_layer_contains_complete_audited_runtime_delta_and_proof_files():
    copy_lines = [line.strip() for line in OVERLAY.splitlines() if line.strip().startswith("COPY ")]
    assert copy_lines == [
        "COPY services/support_notification_alignment.py /app/services/support_notification_alignment.py",
        "COPY services/package_catalog_alignment.py /app/services/package_catalog_alignment.py",
        "COPY templates/admin/packages.html /app/templates/admin/packages.html",
        "COPY migrations/manual/20260912-package-pricing-discount.sql /app/migrations/manual/20260912-package-pricing-discount.sql",
        "COPY scripts/verify_production_db_contract.py /app/scripts/verify_production_db_contract.py",
        "COPY fly.toml /app/fly.toml",
        "COPY Dockerfile.current-image-alignment /app/Dockerfile.current-image-alignment",
    ]


def _runtime_delta_path(path: str) -> bool:
    """Return True for branch files that can affect the deployed /app runtime.

    Workflow, test, and governance-only files intentionally remain outside the
    image. Runtime source/config/schema/static changes must be overlaid onto the
    pinned production image explicitly so the candidate is a truthful rendering
    of the exact GitHub head.
    """
    runtime_prefixes = (
        "services/",
        "templates/",
        "static/",
        "migrations/",
        "scripts/",
    )
    if path.startswith(runtime_prefixes):
        return True
    if "/" not in path and path.endswith((".py", ".toml")):
        return True
    return path in {"Dockerfile.current-image-alignment"}


def test_every_changed_runtime_file_since_image_base_is_overlaid_into_candidate():
    result = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    runtime_changed = [path for path in changed if _runtime_delta_path(path)]

    missing = []
    for path in runtime_changed:
        expected = f"COPY {path} /app/{path}"
        if expected not in OVERLAY:
            missing.append(path)

    assert not missing, (
        "Current-image candidate is missing changed runtime files from GitHub head: "
        + ", ".join(missing)
    )


def test_support_startup_fix_remains_in_candidate_runtime_delta():
    support = (ROOT / "services" / "support_notification_alignment.py").read_text(encoding="utf-8")
    assert 'if original is None:\n        return False' in support
    assert 'raise RuntimeError("governed notification endpoint is not registered")' not in support
    assert "_install_when_ready()" in support


def test_package_runtime_and_schema_delta_are_carried_together():
    package_service = (ROOT / "services" / "package_catalog_alignment.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations" / "manual" / "20260912-package-pricing-discount.sql").read_text(encoding="utf-8")
    db_contract = (ROOT / "scripts" / "verify_production_db_contract.py").read_text(encoding="utf-8")
    assert "list_price_pence" in package_service
    assert "discount_percent" in package_service
    assert "ADD COLUMN IF NOT EXISTS list_price_pence" in migration
    assert "ADD COLUMN IF NOT EXISTS discount_percent" in migration
    assert '"subscription_packages"' in db_contract
    assert '"list_price_pence"' in db_contract
    assert '"discount_percent"' in db_contract
