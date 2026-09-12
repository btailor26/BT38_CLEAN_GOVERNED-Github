from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (ROOT / "Dockerfile.current-image-alignment").read_text(encoding="utf-8")
FLY = (ROOT / "fly.toml").read_text(encoding="utf-8")

BASE_IMAGE = (
    "registry.fly.io/bt38-prod:deployment-01M2BK6REHCGKJQ34796T3WK8P"
    "@sha256:3f7ca913f010fea40a0b8fe20354cae7c010f802328fa0e1eb41258f32168a8b"
)


def test_recovery_alignment_reuses_today_exact_production_image():
    assert f"FROM {BASE_IMAGE}" in OVERLAY
    assert 'dockerfile = "Dockerfile.current-image-alignment"' in FLY
    assert '^[[:space:]]*image' not in FLY


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


def test_alignment_layer_contains_only_the_audited_runtime_delta_and_proof_files():
    copy_lines = [line.strip() for line in OVERLAY.splitlines() if line.strip().startswith("COPY ")]
    assert copy_lines == [
        "COPY services/support_notification_alignment.py /app/services/support_notification_alignment.py",
        "COPY fly.toml /app/fly.toml",
        "COPY Dockerfile.current-image-alignment /app/Dockerfile.current-image-alignment",
    ]


def test_support_startup_fix_is_the_only_runtime_source_overlay():
    support = (ROOT / "services" / "support_notification_alignment.py").read_text(encoding="utf-8")
    assert 'if original is None:\n        return False' in support
    assert 'raise RuntimeError("governed notification endpoint is not registered")' not in support
    assert "_install_when_ready()" in support
