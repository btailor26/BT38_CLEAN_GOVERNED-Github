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


def test_deploy_workflow_must_wire_evidence_recorder():
    workflow = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")
    # This intentionally fails until the workflow is wired. It prevents the recorder
    # from being mistaken for active protection merely because the script exists.
    assert "record_governed_deployment_evidence.py" in workflow
