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


def test_fly_uses_remote_builder_and_promotes_the_exact_proven_candidate():
    assert "actions/checkout@v4" in WORKFLOW
    assert "--remote-only" in WORKFLOW
    assert "--app bt38-prod" in WORKFLOW
    assert "--strategy rolling" in WORKFLOW
    assert "approved_image" not in WORKFLOW

    build = WORKFLOW.index("Build exact candidate image without deploying")
    verify = WORKFLOW.index("Verify candidate image DB contract against production Neon")
    deploy = WORKFLOW.index("Deploy exact audited candidate image")
    assert build < verify < deploy

    assert "--build-only" in WORKFLOW
    assert "--push" in WORKFLOW
    assert 'CANDIDATE_IMAGE="${{ steps.candidate_image.outputs.image }}"' in WORKFLOW
    assert 'flyctl machine run' in WORKFLOW
    assert '--rm' in WORKFLOW
    assert '--file-local /tmp/bt38-db-contract.py=scripts/verify_production_db_contract.py' in WORKFLOW
    assert '--image "$CANDIDATE_IMAGE"' in WORKFLOW


def test_source_integrity_is_checked_before_candidate_build_and_deploy():
    integrity = WORKFLOW.index("Reject corrupt production source files")
    build = WORKFLOW.index("Build exact candidate image without deploying")
    deploy = WORKFLOW.index("Deploy exact audited candidate image")
    assert integrity < build < deploy
    assert "Null bytes found in production source" in WORKFLOW
