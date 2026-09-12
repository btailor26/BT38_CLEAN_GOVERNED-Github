from pathlib import Path


def test_deploy_workflow_checks_db_on_exact_candidate_before_and_after_rollout():
    workflow = Path('.github/workflows/deploy-fly.yml').read_text(encoding='utf-8')
    build = 'Build exact candidate image without deploying'
    pre = 'Verify candidate image DB contract against production Neon'
    deploy = 'Deploy exact audited candidate image'
    post = 'Verify deployed image DB contract against production Neon'

    assert build in workflow
    assert pre in workflow
    assert post in workflow
    assert workflow.index(build) < workflow.index(pre) < workflow.index(deploy) < workflow.index(post)

    # The pre-deploy DB proof must run inside the exact candidate image, not
    # inside the already-running production Machine that the deployment is
    # intended to replace.
    assert '--build-only' in workflow
    assert '--push' in workflow
    assert '--image-label "$LABEL"' in workflow
    assert 'flyctl machine run' in workflow
    assert '"$CANDIDATE_IMAGE"' in workflow
    assert '--app bt38-prod' in workflow
    assert '--rm' in workflow
    assert '--restart no' in workflow
    assert '--file-local /tmp/bt38-db-contract.py=scripts/verify_production_db_contract.py' in workflow
    assert 'PREDEPLOY_CANDIDATE_DB_CONTRACT_OK' in workflow

    # Production rollout must promote the same already-proven image rather than
    # silently rebuilding a second image after the candidate proof.
    assert '--image "$CANDIDATE_IMAGE"' in workflow
    assert 'scripts/verify_production_db_contract.py' in workflow


def test_db_contract_is_targeted_not_full_schema_equality():
    source = Path('scripts/verify_production_db_contract.py').read_text(encoding='utf-8')

    assert 'REQUIRED_COLUMNS' in source
    assert 'Extra tables/columns do not fail the release' in source
    assert 'DB_CONTRACT_WARNING' in source
    assert 'marketplace_orders' in source
    assert 'fbm_shipments' in source
    assert 'warehouse_stock' in source
