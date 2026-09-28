from pathlib import Path


SERVICE_WORKER = Path("static/service-worker.js").read_text(encoding="utf-8")


def test_service_worker_never_cache_intercepts_governed_fbm_page():
    assert "const isScannerCacheTarget" in SERVICE_WORKER
    assert "if (!isScannerCacheTarget)" in SERVICE_WORKER
    assert "return;" in SERVICE_WORKER
    assert "urlsToCache.includes(requestUrl.pathname)" in SERVICE_WORKER
    assert "'/fbm'" not in SERVICE_WORKER
    assert "'/dashboard'" not in SERVICE_WORKER


def test_service_worker_cache_version_retires_old_dynamic_cache():
    assert "bt38-scanner-v3" in SERVICE_WORKER
    assert "cacheName !== CACHE_NAME" in SERVICE_WORKER
