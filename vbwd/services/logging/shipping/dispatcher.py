"""``LogShipDispatcher`` — the buffer + ship scheduler (Sprint 106, Phase 2).

The router's hot path (`VbwdLogRouter.emit`) calls :meth:`enqueue` for every
emitted record: a cheap, lock-guarded append into a bounded ring buffer (drops
the OLDEST and counts the drop when full — newest wins, so a burst never blocks
the app or grows memory). No config file is read on the hot path; the cached
config is refreshed by the scheduler tick.

A TESTING-guarded background job (`start_log_ship_scheduler`, mirroring the
outbound-webhook scheduler) periodically drains a batch and fans it to every
**ready** registered shipper. Per-shipper exponential backoff + auto-disable
(also mirroring the webhook delivery service) isolates one failing backend:

* success → reset failures, clear backoff;
* failure → ``next_attempt = now + min(base * 2**(failures-1), cap)``;
* ``failures >= auto_disable_threshold`` → disable the shipper (until it is
  re-registered, e.g. on plugin re-enable, which resets its state).

When NO shipper is ready (all backing off / disabled) the batch is NOT drained,
so records buffer (up to capacity) through a short backend outage. Shipping is
best-effort by design — the on-disk logs are the durable source of truth.
"""
from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from ..reader import level_to_value, parse_min_level
from .port import ShipResult
from .registry import LogShipperRegistry, log_shipper_registry

logger = logging.getLogger(__name__)

# var/core/logging.json — the same ops-override file the reader caps live in;
# shipping config is its ``shipping`` block. Code defaults are the fallback.
_CORE_NAMESPACE = "core"
_CONFIG_FILE = "logging.json"
_SHIPPING_KEY = "shipping"

DEFAULT_FLUSH_INTERVAL_SECONDS = 10


@dataclass(frozen=True)
class ShippingConfig:
    """Ops-tunable shipping policy (``var/core/logging.json`` ``shipping`` block)."""

    enabled: bool = True
    flush_interval_seconds: int = DEFAULT_FLUSH_INTERVAL_SECONDS
    max_batch: int = 500
    buffer_capacity: int = 10000
    min_level: str = "info"
    backoff_base_seconds: int = 30
    backoff_cap_seconds: int = 6 * 60 * 60
    auto_disable_threshold: int = 5


def load_shipping_config(filesystem_manager: Any) -> ShippingConfig:
    """Read the ``shipping`` block from ``var/core/logging.json`` (defaults fallback)."""
    raw = filesystem_manager.read_json(_CORE_NAMESPACE, _CONFIG_FILE, default={})
    block = raw.get(_SHIPPING_KEY, {}) if isinstance(raw, dict) else {}
    if not isinstance(block, dict):
        block = {}
    defaults = ShippingConfig()
    return ShippingConfig(
        enabled=bool(block.get("enabled", defaults.enabled)),
        flush_interval_seconds=int(
            block.get("flush_interval_seconds", defaults.flush_interval_seconds)
        ),
        max_batch=int(block.get("max_batch", defaults.max_batch)),
        buffer_capacity=int(block.get("buffer_capacity", defaults.buffer_capacity)),
        min_level=str(block.get("min_level", defaults.min_level)),
        backoff_base_seconds=int(
            block.get("backoff_base_seconds", defaults.backoff_base_seconds)
        ),
        backoff_cap_seconds=int(
            block.get("backoff_cap_seconds", defaults.backoff_cap_seconds)
        ),
        auto_disable_threshold=int(
            block.get("auto_disable_threshold", defaults.auto_disable_threshold)
        ),
    )


@dataclass
class _ShipperRuntimeState:
    """In-memory per-shipper backoff/disable state (resets on re-register)."""

    consecutive_failures: int = 0
    disabled: bool = False
    next_attempt_ts: float = 0.0


@dataclass
class DispatcherStats:
    buffered: int
    dropped: int
    shippers: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class LogShipDispatcher:
    """Bounded buffer + fan-out-to-shippers with per-shipper backoff."""

    def __init__(
        self,
        registry: Optional[LogShipperRegistry] = None,
        config: Optional[ShippingConfig] = None,
    ) -> None:
        self._registry = registry or log_shipper_registry
        self._config = config or ShippingConfig()
        self._floor = parse_min_level(self._config.min_level)
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=self._config.buffer_capacity)
        self._lock = threading.Lock()
        self._states: Dict[str, _ShipperRuntimeState] = {}
        self._dropped = 0

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def refresh_config(self, config: ShippingConfig) -> None:
        """Swap the cached config (called by the scheduler tick), preserving
        any buffered records when the capacity changes."""
        with self._lock:
            self._config = config
            self._floor = parse_min_level(config.min_level)
            if self._buffer.maxlen != config.buffer_capacity:
                self._buffer = deque(self._buffer, maxlen=config.buffer_capacity)

    # ------------------------------------------------------------------
    # Hot path — called per emitted record
    # ------------------------------------------------------------------

    def enqueue(self, payload: Dict[str, Any]) -> None:
        """Buffer one record for shipping. Cheap, lock-guarded, never raises.

        No-op when disabled or when no shipper is registered (so core pays
        nothing until a shipper plugin is enabled), or when the record is below
        the shipping floor.
        """
        try:
            if not self._config.enabled or not self._registry.all():
                return
            level = level_to_value(payload.get("level"))
            if self._floor is not None and level is not None and level < self._floor:
                return
            with self._lock:
                if (
                    self._buffer.maxlen is not None
                    and len(self._buffer) == self._buffer.maxlen
                ):
                    self._dropped += 1
                self._buffer.append(payload)
        except Exception:  # noqa: BLE001 — shipping must never crash logging
            pass

    # ------------------------------------------------------------------
    # Scheduler tick
    # ------------------------------------------------------------------

    def run_once(self, now: float) -> int:
        """Drain a batch and ship it to every ready shipper. Returns the batch
        size (0 when nothing was drained)."""
        shippers = self._registry.all()
        if not shippers:
            return 0
        ready = [shipper for shipper in shippers if self._is_ready(shipper.name, now)]
        if not ready:
            return 0
        with self._lock:
            if not self._buffer:
                return 0
            batch: List[Dict[str, Any]] = list(
                itertools.islice(self._buffer, 0, self._config.max_batch)
            )
            for _ in range(len(batch)):
                self._buffer.popleft()
        for shipper in ready:
            try:
                result = shipper.ship(batch)
            except Exception as ship_error:  # noqa: BLE001 — guard every shipper
                result = ShipResult.failure(
                    f"{type(ship_error).__name__}: {ship_error}"
                )
            self._apply_result(shipper.name, result, now)
        return len(batch)

    def reset_shipper(self, name: str) -> None:
        """Clear a shipper's backoff/disable state (call on (re)register)."""
        with self._lock:
            self._states.pop(name, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_ready(self, name: str, now: float) -> bool:
        state = self._states.get(name)
        if state is None:
            return True
        if state.disabled:
            return False
        return now >= state.next_attempt_ts

    def _apply_result(self, name: str, result: ShipResult, now: float) -> None:
        state = self._states.setdefault(name, _ShipperRuntimeState())
        if result.ok:
            state.consecutive_failures = 0
            state.next_attempt_ts = 0.0
            state.disabled = False
            return
        state.consecutive_failures += 1
        delay = min(
            self._config.backoff_base_seconds * (2 ** (state.consecutive_failures - 1)),
            self._config.backoff_cap_seconds,
        )
        state.next_attempt_ts = now + delay
        if state.consecutive_failures >= self._config.auto_disable_threshold:
            state.disabled = True
            logger.warning(
                "[log-shipping] shipper '%s' auto-disabled after %d consecutive "
                "failures (last: %s)",
                name,
                state.consecutive_failures,
                result.detail,
            )
        else:
            logger.warning(
                "[log-shipping] shipper '%s' failed (%d/%d), backing off %ds: %s",
                name,
                state.consecutive_failures,
                self._config.auto_disable_threshold,
                int(delay),
                result.detail,
            )

    def stats(self) -> DispatcherStats:
        with self._lock:
            shipper_states = {
                name: {
                    "consecutive_failures": state.consecutive_failures,
                    "disabled": state.disabled,
                    "next_attempt_ts": state.next_attempt_ts,
                }
                for name, state in self._states.items()
            }
            return DispatcherStats(
                buffered=len(self._buffer),
                dropped=self._dropped,
                shippers=shipper_states,
            )


# Module-level singleton fed by the router and drained by the scheduler.
log_ship_dispatcher = LogShipDispatcher()


# ----------------------------------------------------------------------
# Background scheduler (caller TESTING-guards, exactly like the webhook one)
# ----------------------------------------------------------------------


def run_log_ship_job(app) -> None:
    """Scheduler tick: refresh config + drain one batch inside an app context.

    The app context is needed because a shipper may read its plugin config
    (`current_app.config_store`) at ship time.
    """
    import time

    from vbwd.services.filesystem import LocalFilesystemManager

    try:
        with app.app_context():
            log_ship_dispatcher.refresh_config(
                load_shipping_config(LocalFilesystemManager())
            )
            shipped = log_ship_dispatcher.run_once(time.time())
            if shipped:
                logger.debug("[log-shipping] shipped %d records", shipped)
    except Exception as job_error:  # noqa: BLE001 — never let the job thread die
        logger.warning("[log-shipping] ship job failed: %s", job_error)


def start_log_ship_scheduler(app, interval_seconds: Optional[int] = None):
    """Start the background drain job (caller must TESTING-guard)."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from vbwd.services.filesystem import LocalFilesystemManager

    if interval_seconds is None:
        interval_seconds = load_shipping_config(
            LocalFilesystemManager()
        ).flush_interval_seconds

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_log_ship_job,
        "interval",
        seconds=interval_seconds,
        args=[app],
        id="log_ship_delivery",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[log-shipping] ship scheduler started (interval=%ds)", interval_seconds
    )
    return scheduler
