from pathlib import Path


def test_deployment_evidence_recorder_is_secret_free_and_fail_closed():
    text = Path("scripts/record_governed_deployment_evidence.py").read_text(encoding="utf-8")
    assert "bt38.governed-deployment-evidence.v1" in text
    assert '"changed_files"' in text
    assert '"loaded_bt38_modules"' in text
    assert '"registered_routes"' in text
    assert '"secrets_recorded": False' in text
    assert "Production source evidence failed" in text
    forbidden = ("FLY_API_TOKEN", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "DATABASE_URL")
    for name in forbidden:
        assert name not in text


def test_source_manifest_is_automatic_and_secret_safe():
    text = Path("scripts/verify_governed_production_source.py").read_text(encoding="utf-8")
    assert "tracked-production-files.txt" in text
    assert "source-production-hashes.txt" in text
    assert '".github/"' in text
    assert '"tests/"' in text
    assert '".env"' in text
    assert "sha256" in text


def test_deploy_workflow_must_wire_evidence_recorder():
    workflow = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")
    # Intentionally red until the production workflow invokes both components.
    # This prevents passive files from being mistaken for active protection.
    assert "verify_governed_production_source.py" in workflow
    assert "record_governed_deployment_evidence.py" in workflow
