from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
import smtplib

import yfinance as yf


# =========================
# Konfiguration
# =========================

HOLDINGS_PATH = Path(os.getenv("HOLDINGS_PATH", "holdings.json"))
BASE_CCY = os.getenv("BASE_CCY", "SEK").upper()
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "Portfölj")


# =========================
# Hjälpfunktioner
# =========================

def getenv_required(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


def safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan


def is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def fmt_money(v: float) -> str:
    if is_nan(v):
        return "-"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} {BASE_CCY}"


def guess_currency(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".ST"):
        return "SEK"
    if s.endswith(".TO") or s.endswith(".V"):
        return "CAD"
    return "USD"


# =========================
# Ladda innehav
# =========================

def load_holdings() -> list[dict]:
    if not HOLDINGS_PATH.exists():
