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

    # The pre-deploy DB proof must use the exact candidate image in a temporary
    # same-app Machine, then execute the proof through Fly's command-execution
    # interface so stdout and exit status are authoritative.
    assert '--build-only' in workflow
    assert '--push' in workflow
    assert '--image-label "$LABEL"' in workflow
    assert 'flyctl machine run' in workflow
    assert '"$CANDIDATE_IMAGE"' in workflow
    assert 'sleep infinity' in workflow
    assert '--app bt38-prod' in workflow
    assert '--detach' in workflow
    assert '--restart no' in workflow
    assert '--file-local /tmp/bt38-db-contract.py=scripts/verify_production_db_contract.py' in workflow
    assert 'flyctl machine exec "$MACHINE_ID"' in workflow
    assert '"sh -lc \'cd /app && .venv/bin/python /tmp/bt38-db-contract.py\'"' in workflow
    assert '--timeout 120' in workflow
    assert 'flyctl machine destroy "$MACHINE_ID" --app bt38-prod --force' in workflow
    assert 'trap cleanup_candidate_machine EXIT' in workflow
    assert 'PREDEPLOY_CANDIDATE_DB_CONTRACT_OK' in workflow

    # Fly can briefly return MANIFEST_UNKNOWN immediately after a two-stage
    # build+push. Only creation is retried for that exact registry race. The
    # DB contract itself executes once and must return an explicit result.
    assert 'for ATTEMPT in 1 2 3 4 5; do' in workflow
    assert "grep -q 'MANIFEST_UNKNOWN\\|manifest unknown'" in workflow
    assert 'sleep 15' in workflow
    assert 'Fly registry has not propagated the exact candidate manifest yet' in workflow
    assert "grep -q '^DB_CONTRACT_BLOCKED'" in workflow
    assert "grep -q '^DB_CONTRACT_OK:'" in workflow
    assert 'candidate verifier Machine could not be created for a reason other than the proven Fly registry propagation race' in workflow
    assert 'exact candidate Machine executed the DB proof but did not return DB_CONTRACT_OK' in workflow

    # Production rollout must promote the same already-proven image rather than
    # silently rebuilding a second image after the candidate proof.
    assert '--image "$CANDIDATE_IMAGE"' in workflow
    assert 'scripts/verify_production_db_contract.py' in workflow

    # Browser proof must be mandatory after promotion because pre-deploy live
    # Playwright can be deferred while the old production runtime is down.
    assert 'Verify deployed application with Playwright' in workflow
    assert workflow.index(deploy) < workflow.index('Verify deployed application with Playwright')


def test_db_contract_is_targeted_not_full_schema_equality():
    source = Path('scripts/verify_production_db_contract.py').read_text(encoding='utf-8')

    assert 'REQUIRED_COLUMNS' in source
    assert 'Extra tables/columns do not fail the release' in source
    assert 'DB_CONTRACT_WARNING' in source
    assert 'marketplace_orders' in source
    assert 'fbm_shipments' in source
    assert 'warehouse_stock' in source


def test_db_contract_includes_schema_required_by_package_runtime_overlay():
    source = Path('scripts/verify_production_db_contract.py').read_text(encoding='utf-8')
    assert '"subscription_packages"' in source
    assert '"list_price_pence"' in source
    assert '"discount_percent"' in source
    assert '"account_package_assignments"' in source
