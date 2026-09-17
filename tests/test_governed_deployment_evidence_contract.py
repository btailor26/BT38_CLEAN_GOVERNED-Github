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


def test_source_manifest_is_event_driven_and_secret_safe():
    text = Path("scripts/verify_governed_production_source.py").read_text(encoding="utf-8")
    assert "deployment-evidence/changed-files.txt" in text
    assert "BT38_CHANGED_FILES_FILE" in text
    assert 'return EVENT_LIST, "deploy-event"' in text
    assert "tracked-production-files.txt" in text  # local/CI fallback only
    assert "source-production-hashes.txt" in text
    assert '".github/"' in text
    assert '"tests/"' in text
    assert '"_retired_tests/"' in text
    assert '"env/"' in text
    assert '"fake_db/"' in text
    assert '"audit/"' in text
    assert '"_bt38_backups/"' in text
    assert '"recovery_reports/"' in text
    assert '"reports/"' in text
    assert '"attached_assets/"' in text
    assert '".env"' in text
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
    for excluded in (
        "tests/",
        "_retired_tests/",
        "env/",
        "instance/",
        "static/uploads/",
        "fake_db/",
        "audit/",
        "_bt38_backups/",
        "recovery_reports/",
        "reports/",
        "attached_assets/",
    ):
        assert excluded in dockerignore
        assert f'"{excluded}"' in source


def test_runtime_registration_records_names_only():
    text = Path("scripts/verify_governed_runtime_registration.py").read_text(encoding="utf-8")
    assert "loaded-bt38-modules.txt" in text
    assert "registered-routes.txt" in text
    assert "app.url_map.iter_rules()" in text
    assert "app.config" not in text


def test_deploy_workflow_must_wire_event_evidence_recorder():
    workflow = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")
    assert "verify_governed_production_source.py" in workflow
    assert "verify_governed_runtime_registration.py" in workflow
    assert "record_governed_deployment_evidence.py" in workflow
    assert "deployment-evidence/changed-files.txt" in workflow
    # flyctl must not inherit the manifest loop's stdin: otherwise it consumes
    # the remaining hash lines and falsely reports success after one file.
    assert 'flyctl ssh console --app bt38-prod --command "sh -lc \'sha256sum /app/$FILE\'" </dev/null' in workflow
    assert 'EXPECTED_SOURCE_COUNT="$(wc -l < deployment-evidence/source-production-hashes.txt)"' in workflow
    assert 'test "$PRODUCTION_SOURCE_COUNT" = "$EXPECTED_SOURCE_COUNT"' in workflow
