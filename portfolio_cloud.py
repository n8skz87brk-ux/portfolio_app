# portfolio_cloud.py
# Daglig portföljrapport via email (HTML + text)
# - Läser innehav från holdings.json (fallback: HOLDINGS)
# - Valutakonverterar till SEK (t.ex. CAD, USD) via USDSEK=X, CADSEK=X
# - Tabell: Bolag, Antal, Kurs, Värde, Idag, %
# - Hela kronor för värde/förändring, SEK bara i sammanfattningen
# - Blå = upp, röd = ner (HTML)
# - Bakåtkompatibel med olika secret-namn

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
import smtplib
from email.message import EmailMessage
from typing import Any

import yfinance as yf


# =========================================================
# 1) INNEHAV: holdings.json (fallback: HOLDINGS)
# =========================================================
HOLDINGS = [
    {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
    {"name": "Nelly Group", "symbol": "NELLY.ST", "shares": 98},
]

HOLDINGS_PATH = os.getenv("HOLDINGS_PATH", "holdings.json").strip()


def load_holdings() -> list[dict[str, Any]]:
    try:
        with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and isinstance(data.get("holdings"), list):
            holdings = data["holdings"]
        elif isinstance(data, list):
            holdings = data
        else:
            holdings = []

        cleaned: list[dict[str, Any]] = []
        for h in holdings:
            if not isinstance(h, dict):
                continue
            name = str(h.get("name", "")).strip()
            symbol = str(h.get("symbol", "")).strip()
            shares = h.get("shares")
            if name and symbol and shares is not None:
                cleaned.append({"name": name, "symbol": symbol, "shares": shares})

        if cleaned:
            return cleaned

    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"VARNING: kunde inte läsa {HOLDINGS_PATH}: {e}", file=sys.stderr)

    return HOLDINGS


# =========================================================
# 2) EMAIL / SMTP – BAKÅTKOMPATIBEL MED GAMLA SECRETS
# =========================================================
def _getenv_any(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return default


SMTP_HOST = _getenv_any("SMTP_HOST", "SMTP_SERVER", "MAIL_SERVER", "EMAIL_HOST")
SMTP_PORT = int(_getenv_any("SMTP_PORT", "MAIL_PORT", default="587") or "587")

SMTP_USER = _getenv_any("SMTP_USER", "EMAIL_USER", "MAIL_USER", "FROM_EMAIL", "SENDER_EMAIL")
SMTP_PASS = _getenv_any("SMTP_PASS", "EMAIL_PASS", "MAIL_PASS", "APP_PASSWORD", "EMAIL_APP_PASSWORD")

MAIL_TO = _getenv_any("MAIL_TO", "TO_EMAIL", "EMAIL_TO", "RECIPIENT_EMAIL")
MAIL_FROM = _getenv_any("MAIL_FROM", "FROM_EMAIL", "SENDER_EMAIL", default=SMTP_USER)

SUBJECT_PREFIX = _getenv_any("SUBJECT_PREFIX", default="Portföljrapport")


# =========================================================
# 3) FORMATTERING
# =========================================================
def _fmt_int(x: Any) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", " ")
    except Exception:
        return "-"


def _fmt_price(x: Any) -> str:
    """Kurs med 2 decimaler, svensk decimal-komma."""
    try:
        return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")
    except Exception:
        return "-"


def _fmt_shares(x: Any) -> str:
    try:
        v = float(x)
        if abs(v - round(v)) < 1e-9:
            return f"{int(round(v))}"
        return f"{v:.2f}".replace(".", ",")
    except Exception:
        return "-"


def _fmt_pct(x: Any, decimals: int = 1) -> str:
    try:
        return f"{float(x):+.{decimals}f}%"
    except Exception:
        return "-"


def _color_for_change(x: Any) -> str:
    try:
        x = float(x)
    except Exception:
        return "#333333"
    if x > 0:
        return "#0b63c7"  # blå
    if x < 0:
        return "#c4001a"  # röd
    return "#333333"


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


# =========================================================
# 4) FX – konvertera till SEK
# =========================================================
_FX_CACHE: dict[str, float] = {}


def get_fx_to_sek(currency: str) -> float | None:
    if not currency:
        return None
    cur = currency.upper().strip()
    if cur == "SEK":
        return 1.0
    if cur in _FX_CACHE:
        return _FX_CACHE[cur]

    fx_symbol = f"{cur}SEK=X"
    try:
        t = yf.Ticker(fx_symbol)

        rate = None
        try:
            fi = t.fast_info or {}
            rate = _safe_float(fi.get("last_price"))
        except Exception:
            rate = None

        if rate is None:
            hist = t.history(period="5d")
            closes = hist["Close"].dropna()
            if len(closes) >= 1:
                rate = float(closes.iloc[-1])

        if rate is None:
            return None

        _FX_CACHE[cur] = rate
        return rate
    except Exception:
        return None


# =========================================================
# 5) HÄMTA KURSER (+ valuta)
# =========================================================
def fetch_quote(symbol: str) -> dict[str, float | str | None]:
    t = yf.Ticker(symbol)

    price = None
    prev_close = None
    currency = None

    try:
        fi = t.fast_info or {}
        price = _safe_float(fi.get("last_price"))
        prev_close = _safe_float(fi.get("previous_close"))
        currency = fi.get("currency") or currency
    except Exception:
        pass

    try:
        info = t.info or {}
        currency = currency or info.get("currency")
        price = price or _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        prev_close = prev_close or _safe_float(info.get("previousClose"))
    except Exception:
        pass

    if price is None or prev_close is None:
        try:
            hist = t.history(period="5d")
            closes = hist["Close"].dropna()
            if len(closes) >= 2:
                price = price or float(closes.iloc[-1])
                prev_close = prev_close or float(closes.iloc[-2])
            elif len(closes) == 1:
                price = price or float(closes.iloc[-1])
        except Exception:
            pass

    return {"price": price, "prev_close": prev_close, "currency": currency}


# =========================================================
# 6) BERÄKNINGAR (allt i SEK)
# =========================================================
def compute_portfolio(holdings: list[dict[str, Any]]):
    rows = []
    total_value = 0.0
    total_prev = 0.0

    for h in holdings:
        name = str(h.get("name", "")).strip()
        symbol = str(h.get("symbol", "")).strip()
        shares = _safe_float(h.get("shares")) or 0.0
        if not name or not symbol or shares == 0:
            continue

        q = fetch_quote(symbol)
        price = q["price"]
        prev = q["prev_close"]
        currency = (q.get("currency") or "SEK").upper()

        if price is None or prev is None:
            continue

        fx = get_fx_to_sek(currency)
        if fx is None:
            print(f"VARNING: kunde inte hämta FX {currency}->SEK för {name} ({symbol})", file=sys.stderr)
            continue

        price_sek = float(price) * fx
        prev_sek = float(prev) * fx

        value = shares * price_sek
        prev_value = shares * prev_sek
        change = value - prev_value
        pct = (change / prev_value * 100.0) if prev_value else 0.0

        total_value += value
        total_prev += prev_value

        rows.append(
            {
                "name": name,
                "shares": shares,
                "price_sek": price_sek,
                "value": value,
                "change": change,
                "pct": pct,
            }
        )

    total_change = total_value - total_prev
    total_pct = (total_change / total_prev * 100.0) if total_prev else 0.0

    return rows, total_value, total_change, total_pct


# =========================================================
# 7) HTML + TEXT (mindre font i tabellen)
# =========================================================
def build_html(rows, total_value, total_change, total_pct, title, timestamp):
    total_color = _color_for_change(total_change)
    rows = sorted(rows, key=lambda r: r["value"], reverse=True)

    num_cell = (
        "text-align:right;white-space:nowrap;"
        "box-sizing:border-box;overflow:hidden;"
        "font-variant-numeric:tabular-nums;"
    )

    row_html = ""
    for r in rows:
        color = _color_for_change(r["change"])
        row_html += f"""
        <tr>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7">{r['name']}</td>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7;{num_cell}">{_fmt_shares(r['shares'])}</td>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7;{num_cell}">{_fmt_price(r['price_sek'])}</td>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7;{num_cell}">{_fmt_int(r['value'])}</td>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7;{num_cell}color:{color};font-weight:600">{_fmt_int(r['change'])}</td>
          <td style="padding:7px 9px;border-bottom:1px solid #e7e7e7;{num_cell}color:{color};font-weight:600">{_fmt_pct(r['pct'])}</td>
        </tr>
        """

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;padding:6px 10px">
      <h2 style="margin:10px 0 4px 0;font-size:18px;color:#111">{title}</h2>
      <div style="margin:0 0 12px 0;font-size:12px;color:#666">{timestamp}</div>

      <div style="margin:0 0 14px 0;padding:12px 14px;border:1px solid #e7e7e7;border-radius:10px;background:#ffffff">
        <div style="font-size:13px;color:#666;margin-bottom:6px">Sammanfattning</div>
        <div style="font-size:14px;color:#111;line-height:1.6">
          <div><b>Totalt värde:</b> {_fmt_int(total_value)} SEK</div>
          <div><b>Förändring:</b> <span style="color:{total_color};font-weight:700">{_fmt_int(total_change)} SEK ({_fmt_pct(total_pct)})</span></div>
        </div>
      </div>

      <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:10px">
        <table width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse;border:1px solid #e7e7e7;border-radius:10px;overflow:hidden;table-layout:fixed;font-size:12px">
          <colgroup>
            <col style="width:30%">
            <col style="width:10%">
            <col style="width:17%">
            <col style="width:18%">
            <col style="width:14%">
            <col style="width:11%">
          </colgroup>
          <thead>
            <tr style="background:#f6f7f9">
              <th align="left"  style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">Bolag</th>
              <th align="right" style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">Antal</th>
              <th align="right" style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">Kurs</th>
              <th align="right" style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">Värde</th>
              <th align="right" style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">Idag</th>
              <th align="right" style="padding:7px 9px;border-bottom:1px solid #e7e7e7;font-size:11px;color:#333">%</th>
            </tr>
          </thead>
          <tbody>
            {row_html if row_html else '<tr><td colspan="6" style="padding:12px">Inga innehav.</td></tr>'}
          </tbody>
        </table>
      </div>

      <div style="margin-top:10px;font-size:12px;color:#777">
        (Belopp i hela kronor. Blå = upp, röd = ner.)
      </div>
    </div>
    """


def build_text(rows, total_value, total_change, total_pct, title, timestamp):
    lines = [
        title,
        timestamp,
        "",
        f"Totalt värde: {_fmt_int(total_value)} SEK",
        f"Förändring:  {_fmt_int(total_change)} SEK ({_fmt_pct(total_pct)})",
        "",
        "Bolag | Antal | Kurs | Värde | Idag | %",
        "-" * 92,
    ]
    for r in sorted(rows, key=lambda r: r["value"], reverse=True):
        lines.append(
            f"{r['name']} | {_fmt_shares(r['shares'])} | {_fmt_price(r['price_sek'])} | {_fmt_int(r['value'])} | {_fmt_int(r['change'])} | {_fmt_pct(r['pct'])}"
        )
    return "\n".join(lines)


# =========================================================
# 8) SKICKA MAIL
# =========================================================
def send_email(subject, html, text):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO]):
        raise RuntimeError("SMTP-inställningar saknas (secrets/env matchar inte)")

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg["Subject"] = subject

    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


# =========================================================
# 9) MAIN
# =========================================================
def main():
    now = datetime.now()
    title = f"{SUBJECT_PREFIX} – {now:%Y-%m-%d}"
    timestamp = f"Skapad {now:%Y-%m-%d %H:%M}"

    holdings = load_holdings()
    rows, total_value, total_change, total_pct = compute_portfolio(holdings)

    html = build_html(rows, total_value, total_change, total_pct, title, timestamp)
    text = build_text(rows, total_value, total_change, total_pct, title, timestamp)

    send_email(title, html, text)
    print("OK – mail skickat")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        raise
