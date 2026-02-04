# portfolio_cloud.py
# - Läser innehav från holdings.json (default: holdings.json i samma mapp, kan styras med HOLDINGS_PATH)
# - Hämtar kurser via yfinance
# - Räknar portföljvärde + förändring vs föregående stängning
# - Skickar mail via SMTP (Gmail funkar bra med app-lösenord)
#
# Env (GitHub Actions / Secrets -> mappas i workflow):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO
# Valfritt:
#   EMAIL_FROM (default = SMTP_USER)
#   SUBJECT_PREFIX (default = "Portfölj")
#   BASE_CCY (default = "SEK")
#   HOLDINGS_PATH (default = "holdings.json")
#   SORT_BY (default = "value_desc")  # value_desc | name_asc | change_desc
#
# holdings.json:
# [
#   {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
#   {"name": "Elemental (CAD)", "symbol": "ELE.V", "shares": 249}
# ]

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


DEFAULT_HOLDINGS_PATH = Path(os.getenv("HOLDINGS_PATH", "holdings.json")).expanduser()


def getenv_required(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


def safe_float(x, default=math.nan) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def is_nan(x: float) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def fmt_money(amount: float, ccy: str = "SEK") -> str:
    if is_nan(amount):
        return "-"
    s = f"{amount:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} {ccy}"


def fmt_number(amount: float) -> str:
    if is_nan(amount):
        return "-"
    s = f"{amount:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return s


def fmt_pct(p: float) -> str:
    if is_nan(p):
        return "-"
    return f"{p:.2f}%"


def guess_ccy_from_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.endswith(".ST"):
        return "SEK"
    # Kanada: TSX (.TO) och TSX Venture (.V)
    if s.endswith(".TO") or s.endswith(".V"):
        return "CAD"
    # USA (oftast utan suffix) – bästa gissning
    return "USD"


def load_holdings() -> list[dict]:
    path = DEFAULT_HOLDINGS_PATH
    if not path.exists():
        raise RuntimeError(f"Hittar inte holdings-filen: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("holdings.json måste vara en lista []")

    cleaned: list[dict] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip() or "Unknown"
        symbol = str(item.get("symbol", "")).strip()
        shares = item.get("shares", 0)
        if not symbol:
            continue
        try:
            shares_f = float(shares)
        except Exception:
            continue
        cleaned.append({"name": name, "symbol": symbol, "shares": shares_f})
    return cleaned


def download_quotes(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not symbols:
        return out

    tickers = yf.Tickers(" ".join(symbols))
    for sym in symbols:
        t = tickers.tickers.get(sym)
        if t is None:
            out[sym] = {"last": math.nan, "prev": math.nan, "currency": None}
            continue

        last = math.nan
        prev = math.nan
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
                inf = t.info
                if is_nan(last):
                    last = safe_float(inf.get("regularMarketPrice"_
