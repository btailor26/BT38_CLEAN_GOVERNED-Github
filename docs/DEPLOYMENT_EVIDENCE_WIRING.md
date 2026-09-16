# BT38 governed deployment evidence wiring

Status: recorder and fail-closed contract are staged on PR #528; production workflow wiring is intentionally not claimed complete.

The governed deployment flow must, on every deployment movement:

1. Capture exact commit, workflow run/attempt, previous deployed commit, Fly machine/image before and after.
2. Derive changed files from Git rather than a hand-maintained list.
3. Build a deterministic source hash manifest for tracked runtime files and compare it with the same paths inside the running Fly machine.
4. Capture BT38 loaded modules and registered routes as names only; never values from configuration, credentials, request bodies, customer data, OAuth tokens, labels, or environment secrets.
5. Record DB-contract and public-smoke outcomes.
6. Run `scripts/record_governed_deployment_evidence.py` to emit the evidence JSON.
7. Fail the deployment evidence stage if a tracked production file is missing or mismatched.
8. Upload the evidence JSON as a GitHub Actions artifact so the movement remains inspectable after runner teardown.

The contract test intentionally stays red until `.github/workflows/deploy-fly.yml` invokes the recorder. This prevents a false green state where the recorder exists but is not active.

No marketplace write, polling loop, webhook registration, database mutation, merge, or production deploy is part of this evidence change.
