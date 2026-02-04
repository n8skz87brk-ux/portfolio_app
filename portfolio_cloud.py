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


# ==================================================
# Grundinställningar
# ==================================================

BASE_CCY = os.getenv("BASE_CCY", "SEK").upper()
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "Portfölj")
HOLDINGS_PATH = Path(os.getenv("HOLDINGS_PATH", "holdings.json"))


# ==================================================
# Hjälpfunktioner
# ==================================================

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


# ==================================================
# Läs innehav
# ==================================================

def load_holdings() -> list[dict]:
    if not HOLDINGS_PATH.exists():
        raise RuntimeError(f"Hittar inte holdings.json: {HOLDINGS_PATH}")

    raw = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    holdings = []

    for row in raw:
        holdings.append({
            "name": row["name"],
            "symbol": row["symbol"],
            "shares": float(row["shares"]),
        })

    return holdings


# ==================================================
# Marknadsdata
# ==================================================

def download_quotes(symbols: list[str]) -> dict:
    tickers = yf.Tickers(" ".join(symbols))
    quotes = {}

    for sym in symbols:
        t = tickers.tickers.get(sym)
        last = prev = math.nan
        ccy = None

        try:
            fi = t.fast_info
            last = safe_float(fi.get("last_price"))
            prev = safe_float(fi.get("previous_close"))
            ccy = fi.get("currency")
        except Exception:
            pass

        if is_nan(last) or is_nan(prev) or not ccy:
            try:
                info = t.info
                if is_nan(last):
                    last = safe_float(info.get("regularMarketPrice"))
                if is_nan(prev):
                    prev = safe_float(info.get("regularMarketPreviousClose"))
                if not ccy:
                    ccy = info.get("currency")
            except Exception:
                pass

        quotes[sym] = {
            "last": last,
            "prev": prev,
            "currency": ccy,
        }

    return quotes


def get_fx_rate(pair: str) -> float:
    q = yf.Ticker(pair).fast_info
    return safe_float(q.get("last_price"))


# ==================================================
# Beräkningar
# ==================================================

def build_rows(holdings: list[dict]):
    symbols = [h["symbol"] for h in holdings]
    quotes = download_quotes(symbols)

    currencies = set()
    for s in symbols:
        currencies.add(quotes[s]["currenc]()
