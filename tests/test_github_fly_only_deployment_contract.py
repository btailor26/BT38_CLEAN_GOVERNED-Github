from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "README_DEPLOY.md").read_text(encoding="utf-8")
WORKFLOW = (
    ROOT / ".github" / "workflows" / "deploy-fly.yml"
).read_text(encoding="utf-8")


def test_operator_pc_is_never_a_production_source_or_deploy_host():
    assert "Never clone, copy, overlay, build, test, or deploy application files" in AGENTS
    assert "from an operator's PC" in AGENTS
    assert "Direct `fly deploy` from an operator PC is" in AGENTS
    assert "prohibited." in AGENTS
    assert "operator's PC is never" in GUIDE
    assert "Do not clone BT38 to a PC for deployment" in GUIDE


def test_manual_workflow_requires_exact_github_commit_and_approval():
    assert "workflow_dispatch:" in WORKFLOW
    assert "DEPLOY_GITHUB_COMMIT_TO_BT38_PROD" in WORKFLOW
    assert "inputs.expected_commit" in WORKFLOW
    assert "github.sha" in WORKFLOW
    assert "git rev-parse HEAD" in WORKFLOW


def test_fly_uses_remote_builder_from_github_checkout_only():
    assert "actions/checkout@v4" in WORKFLOW
    assert "--remote-only" in WORKFLOW
    assert "--app bt38-prod" in WORKFLOW
    assert "--strategy rolling" in WORKFLOW
    assert "approved_image" not in WORKFLOW
    assert "--image" not in WORKFLOW


def test_source_integrity_is_checked_before_deploy():
    integrity = WORKFLOW.index("Reject corrupt production source files")
    deploy = WORKFLOW.index("Deploy exact GitHub commit with Fly remote builder")
    assert integrity < deploy
    assert "Null bytes found in production source" in WORKFLOW


def test_predeploy_db_contract_never_defers_success_when_machine_is_stopped():
    assert "DB_CHECK_DEFERRED" not in WORKFLOW
    assert "production DB compatibility was not proven" in WORKFLOW
    assert 'flyctl machine start "$MACHINE_ID" --app bt38-prod' in WORKFLOW


def test_deploy_never_uses_hard_coded_fly_machine_identity():
    assert "7849913cd19d28" not in WORKFLOW
    assert 'MACHINE_ID="$(cat deployment-evidence/machine-before.txt)"' in WORKFLOW
    assert 'MACHINE_ID="$(printf \'%s\' "$MACHINE_JSON" | jq -r \'.[0].id // empty\')"' in WORKFLOW
    assert 'flyctl machine start "$MACHINE_ID" --app bt38-prod || true' not in WORKFLOW
