"""Compteurs API à faible cardinalité dans Redis, avec repli mémoire pour les tests."""

from __future__ import annotations

import hashlib
import math
import threading
from collections import defaultdict

from django.conf import settings

BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000)
_LOCAL_LOCK = threading.Lock()
_LOCAL_ROUTES: dict[tuple[str, str], dict] = defaultdict(
    lambda: {
        "requests": 0,
        "errors": 0,
        "server_errors": 0,
        "latency_sum_ms": 0.0,
        "latency_buckets": defaultdict(int),
    }
)
_LOCAL_COUNTERS: dict[str, int] = defaultdict(int)
_REDIS = None
_REDIS_UNAVAILABLE = False


def _redis_client():
    global _REDIS, _REDIS_UNAVAILABLE
    if settings.ENV == "test" or _REDIS_UNAVAILABLE:
        return None
    if _REDIS is None:
        import redis

        _REDIS = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.01,
            socket_timeout=0.01,
            retry_on_timeout=False,
        )
    return _REDIS


def _route_key(method: str, route: str) -> str:
    digest = hashlib.sha256(f"{method}:{route}".encode()).hexdigest()[:24]
    return f"kemta:metrics:api:{digest}"


def _record_local(method, route, status_code, duration_ms):
    with _LOCAL_LOCK:
        metric = _LOCAL_ROUTES[(method, route)]
        metric["requests"] += 1
        metric["errors"] += int(status_code >= 400)
        metric["server_errors"] += int(status_code >= 500)
        metric["latency_sum_ms"] += duration_ms
        for bucket in BUCKETS_MS:
            if duration_ms <= bucket:
                metric["latency_buckets"][str(bucket)] += 1
        metric["latency_buckets"]["+Inf"] += 1


def record_api_request(method: str, route: str, status_code: int, duration_ms: float) -> None:
    """Enregistre une requête API sans URL brute, query-string, utilisateur ni corps."""
    method = method.upper()[:8]
    route = route[:180]
    client = _redis_client()
    if client is None:
        _record_local(method, route, status_code, duration_ms)
        return

    key = _route_key(method, route)
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hincrby(key, "requests", 1)
        pipe.hincrby(key, "errors", int(status_code >= 400))
        pipe.hincrby(key, "server_errors", int(status_code >= 500))
        pipe.hincrbyfloat(key, "latency_sum_ms", round(duration_ms, 3))
        for bucket in BUCKETS_MS:
            if duration_ms <= bucket:
                pipe.hincrby(key, f"le_{bucket}", 1)
        pipe.hincrby(key, "le_inf", 1)
        pipe.hset(key, mapping={"method": method, "route": route})
        pipe.sadd("kemta:metrics:api:routes", key)
        pipe.expire(key, 30 * 24 * 60 * 60)
        pipe.expire("kemta:metrics:api:routes", 30 * 24 * 60 * 60)
        pipe.execute()
    except Exception:  # observabilité non-bloquante si Redis est indisponible
        global _REDIS_UNAVAILABLE
        _REDIS_UNAVAILABLE = True
        _record_local(method, route, status_code, duration_ms)


def increment_metric(name: str, amount: int = 1) -> None:
    """Compteur applicatif nommé (ex. sync_failed_total), sans étiquette à cardinalité libre."""
    safe_name = "".join(character for character in name if character.isalnum() or character == "_")[
        :80
    ]
    if not safe_name or amount <= 0:
        return
    client = _redis_client()
    if client is None:
        with _LOCAL_LOCK:
            _LOCAL_COUNTERS[safe_name] += amount
        return
    try:
        client.incrby(f"kemta:metrics:counter:{safe_name}", amount)
        client.expire(f"kemta:metrics:counter:{safe_name}", 30 * 24 * 60 * 60)
    except Exception:
        global _REDIS_UNAVAILABLE
        _REDIS_UNAVAILABLE = True
        with _LOCAL_LOCK:
            _LOCAL_COUNTERS[safe_name] += amount


def _percentile_bucket(histogram: dict[str, int], count: int, percentile: float) -> int | None:
    if count <= 0:
        return None
    target = math.ceil(count * percentile)
    cumulative = 0
    for bucket in BUCKETS_MS:
        cumulative += histogram.get(str(bucket), 0)
        if cumulative >= target:
            return bucket
    return None


def metrics_snapshot() -> dict:
    """Snapshot destiné aux administrateurs ; les routes sont des templates Django stables."""
    client = _redis_client()
    routes: list[dict] = []
    counters: dict[str, int] = {}
    if client is None:
        with _LOCAL_LOCK:
            for (method, route), metric in _LOCAL_ROUTES.items():
                count = metric["requests"]
                histogram = dict(metric["latency_buckets"])
                routes.append(
                    {
                        "method": method,
                        "route": route,
                        "requests": count,
                        "errors": metric["errors"],
                        "server_errors": metric["server_errors"],
                        "avg_duration_ms": round(metric["latency_sum_ms"] / count, 2)
                        if count
                        else 0,
                        "p95_duration_ms": _percentile_bucket(histogram, count, 0.95),
                    }
                )
            counters = dict(_LOCAL_COUNTERS)
    else:
        try:
            keys = sorted(client.smembers("kemta:metrics:api:routes"))[:200]
            for key in keys:
                values = client.hgetall(key)
                count = int(values.get("requests", 0))
                histogram = {
                    str(bucket): int(values.get(f"le_{bucket}", 0)) for bucket in BUCKETS_MS
                }
                routes.append(
                    {
                        "method": values.get("method", "GET"),
                        "route": values.get("route", "unknown"),
                        "requests": count,
                        "errors": int(values.get("errors", 0)),
                        "server_errors": int(values.get("server_errors", 0)),
                        "avg_duration_ms": round(float(values.get("latency_sum_ms", 0)) / count, 2)
                        if count
                        else 0,
                        "p95_duration_ms": _percentile_bucket(histogram, count, 0.95),
                    }
                )
            for key in client.scan_iter("kemta:metrics:counter:*"):
                counters[key.rsplit(":", 1)[-1]] = int(client.get(key) or 0)
        except Exception:
            return metrics_snapshot_local()

    routes.sort(key=lambda row: (row["route"], row["method"]))
    return {
        "requests_total": sum(row["requests"] for row in routes),
        "errors_total": sum(row["errors"] for row in routes),
        "server_errors_total": sum(row["server_errors"] for row in routes),
        "routes": routes,
        "counters": counters,
    }


def metrics_snapshot_local() -> dict:
    """Snapshot mémoire si Redis devient indisponible pendant une lecture."""
    with _LOCAL_LOCK:
        routes = []
        for (method, route), metric in _LOCAL_ROUTES.items():
            count = metric["requests"]
            routes.append(
                {
                    "method": method,
                    "route": route,
                    "requests": count,
                    "errors": metric["errors"],
                    "server_errors": metric["server_errors"],
                    "avg_duration_ms": round(metric["latency_sum_ms"] / count, 2) if count else 0,
                    "p95_duration_ms": _percentile_bucket(
                        dict(metric["latency_buckets"]), count, 0.95
                    ),
                }
            )
        counters = dict(_LOCAL_COUNTERS)
    routes.sort(key=lambda row: (row["route"], row["method"]))
    return {
        "requests_total": sum(row["requests"] for row in routes),
        "errors_total": sum(row["errors"] for row in routes),
        "server_errors_total": sum(row["server_errors"] for row in routes),
        "routes": routes,
        "counters": counters,
    }


def reset_metrics() -> None:
    """Vide les métriques locales (test seulement)."""
    with _LOCAL_LOCK:
        _LOCAL_ROUTES.clear()
        _LOCAL_COUNTERS.clear()


class MetricsMiddleware:
    """Mesure le temps et le statut par route Django, sans journaliser les données utilisateur."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import time

        started = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - started) * 1000
        if request.path.startswith("/api/") and request.path != "/api/metrics/":
            match = getattr(request, "resolver_match", None)
            route = getattr(match, "route", None)
            if route:
                record_api_request(request.method, route, response.status_code, duration_ms)
        return response
