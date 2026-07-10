# -*- coding: utf-8 -*-
"""Datas locais do negócio (fuso horário configurável, padrão Brasil)."""
from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Sao_Paulo"


@lru_cache(maxsize=1)
def local_timezone() -> ZoneInfo:
    name = (os.getenv("TIMEZONE") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def today_local() -> date:
    """Data de 'hoje' no fuso do negócio (ex.: America/Sao_Paulo)."""
    return datetime.now(local_timezone()).date()


def now_local() -> datetime:
    """Data/hora atual no fuso do negócio."""
    return datetime.now(local_timezone())
