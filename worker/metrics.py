from __future__ import annotations

import logging
import os
import threading
import time
from typing import Literal

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    REGISTRY,
    multiprocess,
    start_http_server,
)

logger = logging.getLogger(__name__)

_PROM_DIR = os.getenv("PROMETHEUS_MULTIPROC_DIR")
_registry: CollectorRegistry

if _PROM_DIR:
    os.makedirs(_PROM_DIR, exist_ok=True)
    _registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(_registry)
else:
    _registry = REGISTRY

_METRICS_SERVER_STARTED = False
_METRICS_LOCK = threading.Lock()

_DEFAULT_PORT = int(os.getenv("METRICS_PORT", "9464"))
_REPORT_INTERVAL = float(os.getenv("PUBLISH_STATS_INTERVAL", "60"))
_REPORT_SAMPLE = int(os.getenv("PUBLISH_STATS_SAMPLE", "50"))

# Guard against invalid configuration values.
if _DEFAULT_PORT <= 0:
    _DEFAULT_PORT = 9464
if _REPORT_INTERVAL <= 0:
    _REPORT_INTERVAL = 60.0
if _REPORT_SAMPLE <= 0:
    _REPORT_SAMPLE = 50


publish_total = Counter(
    "smetabot_publish_total",
    "Total number of Telegram publication attempts grouped by outcome.",
    ["outcome"],
    registry=_registry,
)
publish_duration = Histogram(
    "smetabot_publish_duration_seconds",
    "Latency of Telegram publication attempts.",
    buckets=(0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
    registry=_registry,
)
publish_retries = Histogram(
    "smetabot_publish_retry_count",
    "Retry count for Telegram publication attempts.",
    buckets=(0, 1, 2, 3, 5, 8, 13),
    registry=_registry,
)
publish_payload_size = Histogram(
    "smetabot_publish_payload_bytes",
    "Size of payloads sent to Telegram (bytes).",
    buckets=(64 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024, 3 * 1024 * 1024, 6 * 1024 * 1024, 10 * 1024 * 1024),
    registry=_registry,
)


class _PublishStatsAggregator:
    """Aggregates publication stats and emits periodic summaries to logs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_report = time.monotonic()
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.count = 0
        self.success = 0
        self.failure = 0
        self.total_duration = 0.0
        self.total_size = 0
        self.total_retries = 0

    def record(self, ok: bool, duration: float, retries: int, size_bytes: int) -> None:
        now = time.monotonic()
        with self._lock:
            self.count += 1
            self.total_duration += duration
            self.total_size += size_bytes
            self.total_retries += retries
            if ok:
                self.success += 1
            else:
                self.failure += 1

            should_report = (
                self.count >= _REPORT_SAMPLE
                or (now - self._last_report) >= _REPORT_INTERVAL
            )
            if should_report:
                self._emit_report(now)

    def force_report(self) -> None:
        with self._lock:
            if self.count > 0:
                self._emit_report(time.monotonic())

    def _emit_report(self, timestamp: float) -> None:
        avg_duration = self.total_duration / self.count if self.count else 0.0
        avg_size = self.total_size / self.count if self.count else 0
        avg_retries = self.total_retries / self.count if self.count else 0.0
        success_rate = (self.success / self.count) * 100 if self.count else 0.0
        logger.info(
            "[publish] summary count=%d success=%d failure=%d success_rate=%.1f%% "
            "avg_duration=%.3fs avg_size=%s avg_retries=%.2f window=%.1fs",
            self.count,
            self.success,
            self.failure,
            success_rate,
            avg_duration,
            _format_size(avg_size),
            avg_retries,
            timestamp - self._last_report,
        )
        self._last_report = timestamp
        self._reset_counters()


_aggregator = _PublishStatsAggregator()


def _format_size(size_bytes: float) -> str:
    if size_bytes < 1024:
        return f"{size_bytes:.0f}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def record_publish(outcome: Literal["success", "failure"], duration: float, retries: int, size_bytes: int) -> None:
    """Track metrics for a single publication attempt and update aggregates."""
    publish_total.labels(outcome=outcome).inc()
    publish_duration.observe(duration)
    publish_retries.observe(retries)
    publish_payload_size.observe(size_bytes)
    _aggregator.record(outcome == "success", duration, retries, size_bytes)


def start_metrics_server() -> None:
    """Start the Prometheus HTTP server once."""
    global _METRICS_SERVER_STARTED
    with _METRICS_LOCK:
        if _METRICS_SERVER_STARTED:
            return
        port = _DEFAULT_PORT
        start_http_server(port, registry=_registry)
        _METRICS_SERVER_STARTED = True
        logger.info("Prometheus metrics server listening on 0.0.0.0:%s", port)


def flush_aggregates() -> None:
    """Force log aggregation summary, used on shutdown."""
    _aggregator.force_report()


def setup_celery_signal_handlers() -> None:
    """Attach Celery worker lifecycle hooks."""
    from celery import signals  # Imported lazily to avoid circular deps.

    @signals.worker_ready.connect  # type: ignore[arg-type]
    def _on_worker_ready(**_: object) -> None:
        start_metrics_server()

    @signals.worker_process_shutdown.connect  # type: ignore[arg-type]
    def _on_worker_process_shutdown(**_: object) -> None:
        flush_aggregates()

    @signals.worker_shutdown.connect  # type: ignore[arg-type]
    def _on_worker_shutdown(**_: object) -> None:
        flush_aggregates()
