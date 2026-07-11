# -*- coding: utf-8 -*-
"""Chamadas seguras à API do Google Sheets (evita erro 429 / quota exceeded)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# Margem abaixo do limite oficial (~60 leituras/min por usuário).
# Com batchGet o bot faz poucas chamadas; limite um pouco mais folgado evita espera de ~1 min.
_READS_PER_MINUTE = 55
_WRITES_PER_MINUTE = 55
_MAX_RETRIES = 4
_BASE_BACKOFF_SEC = 1.0

_lock = threading.Lock()
_read_timestamps: list[float] = []
_write_timestamps: list[float] = []


class GoogleSheetsQuotaError(RuntimeError):
    """Planilha temporariamente indisponível por excesso de requisições."""


def _prune(timestamps: list[float], now: float) -> None:
    cutoff = now - 60.0
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)


def _wait_for_slot(*, is_write: bool) -> None:
    limit = _WRITES_PER_MINUTE if is_write else _READS_PER_MINUTE
    bucket = _write_timestamps if is_write else _read_timestamps
    while True:
        with _lock:
            now = time.monotonic()
            _prune(bucket, now)
            if len(bucket) < limit:
                bucket.append(now)
                return
            wait = 60.0 - (now - bucket[0]) + 0.05
        time.sleep(max(0.1, wait))


def _is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "rate limit" in msg or "resource_exhausted" in msg


def sheets_call(fn: Callable[[], T], *, is_write: bool = False) -> T:
    """
    Executa uma chamada à API com limite de taxa e retry exponencial em 429.
    Uma operação típica deve usar poucas chamadas (export/batch_get + batch_update).
    """
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        _wait_for_slot(is_write=is_write)
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not _is_quota_error(exc) or attempt >= _MAX_RETRIES - 1:
                break
            time.sleep(min(60.0, _BASE_BACKOFF_SEC * (2**attempt)))
    if last_exc and _is_quota_error(last_exc):
        raise GoogleSheetsQuotaError(
            "Google Sheets temporariamente sobrecarregado (limite de leituras). "
            "Aguarde ~1 minuto e tente novamente."
        ) from last_exc
    assert last_exc is not None
    raise last_exc
