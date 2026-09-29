"""Compteurs d'observabilité à cardinalité bornée."""

import pytest

from apps.core.metrics import increment_metric, metrics_snapshot, record_api_request, reset_metrics


@pytest.fixture(autouse=True)
def isolate_metrics():
    reset_metrics()
    yield
    reset_metrics()


def test_api_metrics_and_named_counters_are_exposed_without_high_cardinality_labels():
    record_api_request("get", "/api/projects/<int:pk>/", 200, 12.5)
    record_api_request("GET", "/api/projects/<int:pk>/", 500, 37.5)
    increment_metric("sync_failed_total", 2)
    increment_metric("unsafe-name;ignored", 1)

    snapshot = metrics_snapshot()

    assert snapshot["requests_total"] == 2
    assert snapshot["errors_total"] == 1
    assert snapshot["server_errors_total"] == 1
    assert snapshot["routes"] == [
        {
            "method": "GET",
            "route": "/api/projects/<int:pk>/",
            "requests": 2,
            "errors": 1,
            "server_errors": 1,
            "avg_duration_ms": 25.0,
            "p95_duration_ms": 50,
        }
    ]
    assert snapshot["counters"] == {"sync_failed_total": 2, "unsafenameignored": 1}
