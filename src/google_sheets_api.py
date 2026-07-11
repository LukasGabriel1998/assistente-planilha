# -*- coding: utf-8 -*-
"""Chamadas à API do Google Sheets com retry só em 429 real (sem espera artificial)."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# Só backoff quando o Google devolve 429 de verdade.
# (O limitador preventivo de ~60s fazia o bot “travar” 1 minuto sem necessidade —
#  o Assistente_Line não tem isso e por isso salva rápido.)
_MAX_RETRIES = 4
_BASE_BACKOFF_SEC = 0.4


class GoogleSheetsQuotaError(RuntimeError):
    """Planilha temporariamente indisponível por excesso de requisições."""


def _is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "rate limit" in msg or "resource_exhausted" in msg


def sheets_call(fn: Callable[[], T], *, is_write: bool = False) -> T:
    """
    Executa uma chamada à API. Retry curto só em erro 429/quota.
    `is_write` mantido por compatibilidade com os call sites.
    """
    del is_write  # API pública estável; não usamos mais bucket preventivo
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not _is_quota_error(exc) or attempt >= _MAX_RETRIES - 1:
                break
            time.sleep(min(8.0, _BASE_BACKOFF_SEC * (2**attempt)))
    if last_exc and _is_quota_error(last_exc):
        raise GoogleSheetsQuotaError(
            "Google Sheets temporariamente sobrecarregado (limite da API). "
            "Aguarde alguns segundos e tente novamente."
        ) from last_exc
    assert last_exc is not None
    raise last_exc
