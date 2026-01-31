# portfolio_cloud.py
# Läser innehav från data/holdings.json (uppdateras av ditt formulär),
# hämtar kurser via yfinance och skickar mail med portföljvärde + förändring vs prev close.
#
# Kräver:
#   pip install yfinance
#
# GitHub Secrets / miljövariabler:
#   SMTP_HOST            ex: smtp.gmail.com
#   SMTP_PORT            ex: 587
#   SMTP_USER            ex: dittkonto@gmail.com
#   SMTP_PASS            ex: app-lösenord eller smtp-lösenord
#   EMAIL_TO             ex: dinadress@gmail.com (kan vara flera separerade med komma)
#
# Valfritt:
#   EMAIL_FROM           annars SMTP_USER
#   SUBJECT_PREFIX       ex: "Portfölj"
#   BASE_CCY             default "SEK"
#   HOLDINGS_PATH        default "data/holdings.json"
#
# holdings.json-format (lista):
# [
#   {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
#   {"name": "Microsoft", "symbol": "MSFT", "shares": 5}
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


# ====== 1) Backup-innehav (används bara om holdings-filen saknas/är trasig) ======
HOLDINGS = [
    # {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
]

DEFAULT_HOLDINGS_PATH = Path("holdings.json")


# ====== 2) Utility ======

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


def fmt_money(amount: float, ccy: str = "SEK") -> str:
    if math.isnan(amount):
        return "-"
    s = f"{amount:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} {ccy}"


def fmt_pct(p: float) -> str:
    if math.isnan(p):
        return "-"
    return f"{p:.2f}%"


def is_sek_symbol(symbol: str) -> bool:
    return symbol.upper().endswith(".ST")


def load_holdings() -> list[dict]:
    """
    Läser innehav från holdingsfil (default data/holdings.json).
    Faller tillbaka till hårdkodad HOLDINGS om filen saknas/är trasig/ger tomt resultat.
    """
    path_str = os.getenv("HOLDINGS_PATH", str(DEFAULT_HOLDINGS_PATH)).strip()
    path = Path(path_str)

    if not path.exists():
        print(f"[INFO] Ingen holdings-fil hittades ({path}). Använder backup HOLDINGS.")
        return HOLDINGS

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("holdings.json måste vara en lista []")

        cleaned: list[dict] = []
        for i, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                print(f"[WARN] Rad {i} är inte ett objekt, hoppar över.")
                continue

            name = str(item.get("name", "")).strip() or "Unknown"
            symbol = str(item.get("symbol", "")).strip()
            shares = item.get("shares", 0)

            if not symbol:
                print(f"[WARN] Saknar 'symbol' på rad {i}, hoppar över.")
                continue

            try:
                shares_f = float(shares)
            except Exception:
                print(f"[WARN] Ogiltigt 'shares' för {symbol} (rad {i}), hoppar över.")
                continue

            cleaned.append({"name": name, "symbol": symbol, "shares": shares_f})

        if not cleaned:
            print(f"[WARN] {path} gav inga giltiga innehav. Använder backup HOLDINGS.")
            return HOLDINGS

        return cleaned

    except Exception as e:
        print(f"[WARN] Kunde inte läsa {path}: {e}. Använder backup HOLDINGS.")
        return HOLDINGS


def download_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Hämtar last och previous_close (snabbt via fast_info, med fallback).
    Return: symbol -> {"last":..., "prev":..., "currency":...}
    """
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

        # Försök: fast_info
        try:
            fi = t.fast_info
            last = safe_float(fi.get("last_price"))
            prev = safe_float(fi.get("previous_close"))
            ccy = fi.get("currency")
        except Exception:
            pass

        # Fallback: info
        if math.isnan(last) or math.isnan(prev) or not ccy:
            try:
                inf = t.info
                if math.isnan(last):
                    last = safe_float(inf.get("regularMarketPrice"))
                if math.isnan(prev):
                    prev = safe_float(inf.get("regularMarketPreviousClose"))
                if not ccy:
                    ccy = inf.get("currency")
            except Exception:
                pass

        out[sym] = {"last": last, "prev": prev, "currency": ccy}

    return out


def get_fx_rate(pair_symbol: str) -> float:
    q = download_quotes([pair_symbol]).get(pair_symbol, {})
    return safe_float(q.get("last"))


def find_problem_tickers(holdings: list[dict], quotes: dict[str, dict]) -> list[str]:
    """
    Returnerar tickers som saknar prisdata (last eller prev = NaN).
    """
    problems: list[str] = []
    for h in holdings:
        sym = str(h.get("symbol", "")).strip()
        q = quotes.get(sym, {})
        last = safe_float(q.get("last"))
        prev = safe_float(q.get("prev"))
        if math.isnan(last) or math.isnan(prev):
            problems.append(sym)
    return problems


def build_report(holdings: list[dict], base_ccy: str = "SEK") -> tuple[str, str]:
    tz = ZoneInfo("Europe/Stockholm")
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d %H:%M")

    if not holdings:
        subject = "Portfölj – inga innehav"
        body = (
            f"Portföljrapport {date_str}\n\n"
            "Inga innehav hittades.\n"
            "- Kontrollera att data/holdings.json finns och har rätt format.\n"
            "- Eller fyll i backup-listan HOLDINGS i portfolio_cloud.py.\n"
        )
        return subject, body

    symbols = [h["symbol"] for h in holdings]
    quotes = download_quotes(symbols)
    problem_tickers = find_problem_tickers(holdings, quotes)

    # FX (enkel): USD->SEK om base_ccy=SEK och vi ser USD-innehav
    usdsek = math.nan
    if base_ccy.upper() == "SEK":
        any_usd = any(
            ((quotes.get(h["symbol"], {}).get("currency") or "").upper() == "USD")
            or (not is_sek_symbol(h["symbol"]))
            for h in holdings
        )
        if any_usd:
            usdsek = get_fx_rate("USDSEK=X")

    lines: list[str] = []
    lines.append(f"Portföljrapport {date_str} (basvaluta: {base_ccy})")
    lines.append("")

    header = (
        f"{'Innehav':24} {'Ticker':12} {'Antal':>8} "
        f"{'Senast':>14} {'Stängn-1':>14} {'Värde':>16} {'Δ idag':>16}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    total_value = 0.0
    total_change = 0.0

    for h in holdings:
        name = str(h.get("name", "")).strip()[:24]
        sym = str(h.get("symbol", "")).strip()
        shares = safe_float(h.get("shares", 0.0), default=0.0)

        q = quotes.get(sym, {})
        last = safe_float(q.get("last"))
        prev = safe_float(q.get("prev"))
        ccy = (q.get("currency") or "").upper()

        if not ccy:
            ccy = "SEK" if is_sek_symbol(sym) else "USD"

        fx = 1.0
        if base_ccy.upper() == "SEK" and ccy == "USD":
            fx = usdsek
        elif base_ccy.upper() != ccy:
            fx = math.nan  # bygg ut fler FX-par vid behov

        last_base = last * fx
        prev_base = prev * fx
        value = shares * last_base
        change = shares * (last_base - prev_base)

        if not math.isnan(value):
            total_value += value
        if not math.isnan(change):
            total_change += change

        lines.append(
            f"{name:24} {sym:12} {shares:8.2f} "
            f"{fmt_money(last_base, base_ccy):>14} {fmt_money(prev_base, base_ccy):>14} "
            f"{fmt_money(value, base_ccy):>16} {fmt_money(change, base_ccy):>16}"
        )

    lines.append("")
    lines.append(f"Totalt värde: {fmt_money(total_value, base_ccy)}")
    lines.append(f"Förändring vs föregående stängning: {fmt_money(total_change, base_ccy)}")

    denom = (total_value - total_change)
    pct = (total_change / denom * 100.0) if denom not in (0, 0.0) else math.nan
    lines.append(f"Förändring i % (approx): {fmt_pct(pct)}")

    if base_ccy.upper() == "SEK" and not math.isnan(usdsek):
        lines.append(f"USD/SEK (senast): {usdsek:.4f}")

    # ====== VARNINGAR ======
    if problem_tickers:
        lines.append("")
        lines.append("⚠️ VARNING – saknar prisdata för:")
        for sym in problem_tickers:
            lines.append(f"  - {sym}")
        lines.append("Kontrollera ticker-formatet på Yahoo Finance (eller att instrumentet handlas just nu).")

    subject_prefix = os.getenv("SUBJECT_PREFIX", "Portfölj").strip() or "Portfölj"
    arrow = "▲" if total_change >= 0 else "▼"
    subject = f"{subject_prefix} {arrow} {fmt_money(total_value, base_ccy)} ({fmt_money(total_change, base_ccy)})"

    body = "\n".join(lines)
    return subject, body


def send_email(subject: str, body: str) -> None:
    smtp_host = getenv_required("SMTP_HOST")
    smtp_port = int(getenv_required("SMTP_PORT"))
    smtp_user = getenv_required("SMTP_USER")
    smtp_pass = getenv_required("SMTP_PASS")

    email_to = getenv_required("EMAIL_TO")
    email_from = os.getenv("EMAIL_FROM", "").strip() or smtp_user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def main() -> int:
    base_ccy = os.getenv("BASE_CCY", "SEK").strip().upper() or "SEK"

    holdings = load_holdings()
    subject, body = build_report(holdings, base_ccy=base_ccy)

    # Alltid logg i Actions
    print(subject)
    print(body)

    if "⚠️ VARNING" in body:
        print("[WARN] En eller flera tickers saknar prisdata (se rapporten ovan).")

    # Skicka mail
    send_email(subject, body)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
