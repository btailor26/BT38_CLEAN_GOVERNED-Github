from pathlib import Path


def test_deployment_evidence_recorder_is_secret_free_and_fail_closed():
    text = Path("scripts/record_governed_deployment_evidence.py").read_text(encoding="utf-8")
    assert "bt38.governed-deployment-evidence.v1" in text
    assert '"verified": verified' in text
    assert '"changed_files"' in text
    assert '"loaded_bt38_modules"' in text
    assert '"registered_routes"' in text
    assert '"secrets_recorded": False' in text
    assert "Production source evidence failed" in text
    assert 'BT38_EXPECTED_SOURCE_HASH_FILE' in text
    assert 'BT38_PRODUCTION_SOURCE_HASH_FILE' in text
    assert 'BT38_DB_CONTRACT_RESULT' in text
    assert 'BT38_PUBLIC_SMOKE_RESULT' in text
    forbidden = ("FLY_API_TOKEN", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "DATABASE_URL")
    for name in forbidden:
        assert name not in text


def test_source_manifest_is_event_driven_and_secret_safe():
    text = Path("scripts/verify_governed_production_source.py").read_text(encoding="utf-8")
    assert "deployment-evidence/changed-files.txt" in text
    assert "BT38_CHANGED_FILES_FILE" in text
    assert 'return EVENT_LIST, "deploy-event"' in text
    assert "tracked-production-files.txt" in text
    assert "source-production-hashes.txt" in text
    for excluded in ('".github/"','"tests/"','"_retired_tests/"','"env/"','"fake_db/"','"audit/"','"_bt38_backups/"','"recovery_reports/"','"reports/"','"attached_assets/"','".env"'):
        assert excluded in text
    assert "sha256" in text


def test_governed_deploy_full_runtime_manifest_request_is_honoured_fail_closed():
    source = Path("scripts/verify_governed_production_source.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")
    sentinel = "__bt38_full_tracked_runtime_manifest__"
    assert sentinel in workflow
    assert f'FULL_TRACKED_SENTINEL = "{sentinel}"' in source
    assert 'os.getenv("BT38_CHANGED_FILES") == FULL_TRACKED_SENTINEL' in source
    assert 'return TRACKED_LIST, "full-tracked-runtime"' in source
    assert 'if MODE == "full-tracked-runtime" and not entries:' in source
    assert 'raise SystemExit("Full tracked runtime manifest resolved to zero files")' in source


def test_source_manifest_tracks_docker_runtime_exclusions():
    source = Path("scripts/verify_governed_production_source.py").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
    for excluded in ("tests/","_retired_tests/","env/","instance/","static/uploads/","fake_db/","audit/","_bt38_backups/","recovery_reports/","reports/","attached_assets/"):
        assert excluded in dockerignore
        assert f'"{excluded}"' in source


def test_runtime_registration_records_names_only():
    text = Path("scripts/verify_governed_runtime_registration.py").read_text(encoding="utf-8")
    assert "loaded-bt38-modules.txt" in text
    assert "registered-routes.txt" in text
    assert "app.url_map.iter_rules()" in text
    assert "app.config" not in text


def test_deploy_workflow_batches_full_fingerprint_verification_in_one_ssh_session():
    workflow = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")
    assert "verify_governed_production_source.py" in workflow
    assert "verify_governed_runtime_registration.py" in workflow
    assert "record_governed_deployment_evidence.py" in workflow
    assert "deployment-evidence/changed-files.txt" in workflow
    assert 'FILES_B64="$(awk' in workflow
    assert 'while IFS= read -r f; do sha256sum \\\"\\$f\\\"' in workflow
    assert 'sha256sum /app/$FILE' not in workflow
    assert 'EXPECTED_SOURCE_COUNT="$(wc -l < deployment-evidence/source-production-hashes.txt)"' in workflow
    assert 'test "$PRODUCTION_SOURCE_COUNT" = "$EXPECTED_SOURCE_COUNT"' in workflow
    assert 'diff -u deployment-evidence/source-production-hashes.txt deployment-evidence/production-source-hashes.txt' in workflow


def test_runtime_registration_uses_live_worker_snapshot_and_never_reimports_app():
    main = Path("main.py").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_governed_runtime_registration.py").read_text(encoding="utf-8")
    assert "_write_governed_runtime_registration_snapshot" in main
    assert "/tmp/bt38-live-loaded-modules.txt" in main
    assert "/tmp/bt38-live-registered-routes.txt" in main
    assert 'live_modules = Path("/tmp/bt38-live-loaded-modules.txt")' in verifier
    assert 'live_routes = Path("/tmp/bt38-live-registered-routes.txt")' in verifier
    assert "source=live-worker" in verifier
    assert "_write_runtime_registration_snapshot" in Path("gunicorn.conf.py").read_text(encoding="utf-8")
    assert "missing_live_worker_snapshot" in verifier
    assert "import main" not in verifier
