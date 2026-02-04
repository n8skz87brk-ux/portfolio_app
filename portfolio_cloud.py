# portfolio_cloud.py
# Skickar daglig portföljrapport via email (HTML + text)
# Krav:
# - Ingen ticker i tabellen
# - Endast värde, förändring (kr), förändring (%)
# - Hela kronor, inga ören
# - SEK visas bara i sammanfattningen
# - Blått vid uppgång, rött vid nedgång (HTML-mail)

from __future__ import annotations

import os
import sys
from datetime import datetime
import smtplib
from email.message import EmailMessage
from typing import Any

import yfinance as yf


# =========================================================
# 1) DINA INNEHAV
# =========================================================
HOLDINGS = [
    {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
    {"name": "Nelly Group", "symbol": "NELLY.ST", "shares": 98},
]


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

SMTP_USER = _getenv_any(
    "SMTP_USER",
    "EMAIL_USER",
    "MAIL_USER",
    "FROM_EMAIL",
    "SENDER_EMAIL",
)

SMTP_PASS = _getenv_any(
    "SMTP_PASS",
    "EMAIL_PASS",
    "MAIL_PASS",
    "APP_PASSWORD",
    "EMAIL_APP_PASSWORD",
)

MAIL_TO = _getenv_any(
    "MAIL_TO",
    "TO_EMAIL",
    "EMAIL_TO",
    "RECIPIENT_EMAIL",
)

MAIL_FROM = _getenv_any(
    "MAIL_FROM",
    "FROM_EMAIL",
    "SENDER_EMAIL",
    default=SMTP_USER,
)

SUBJECT_PREFIX = _getenv_any("SUBJECT_PREFIX", default="Portföljrapport")


# =========================================================
# 3) FORMATTERING
# =========================================================
def _fmt_int(x: Any) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", " ")
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
# 4) HÄMTA KURSER
# =========================================================
def fetch_quote(symbol: str) -> dict[str, float | None]:
    t = yf.Ticker(symbol)

    price = None
    prev_close = None

    try:
        fi = t.fast_info or {}
        price = _safe_float(fi.get("last_price"))
        prev_close = _safe_float(fi.get("previous_close"))
    except Exception:
        pass

    if price is None or prev_close is None:
        try:
            info = t.info or {}
            price = price or _safe_float(info.get("regularMarketPrice"))
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
        except Exception:
            pass

    return {"price": price, "prev_close": prev_close}


# =========================================================
# 5) BERÄKNINGAR
# =========================================================
def compute_portfolio(holdings):
    rows = []
    total_value = 0.0
    total_prev = 0.0

    for h in holdings:
        name = h["name"]
        symbol = h["symbol"]
        shares = float(h["shares"])

        q = fetch_quote(symbol)
        price = q["price"]
        prev = q["prev_close"]

        if price is None or prev is None:
            continue

        value = shares * price
        prev_value = shares * prev
        change = value - prev_value
        pct = (change / prev_value * 100) if prev_value else 0.0

        total_value += value
        total_prev += prev_value

        rows.append(
            {
                "name": name,
                "value": value,
                "change": change,
                "pct": pct,
            }
        )

    total_change = total_value - total_prev
    total_pct = (total_change / total_prev * 100) if total_prev else 0.0

    return rows, total_value, total_change, total_pct


# =========================================================
# 6) HTML + TEXT MAIL
# =========================================================
def build_html(rows, total_value, total_change, total_pct, title, timestamp):
    row_html = ""
    for r in sorted(rows, key=lambda x: x["value"], reverse=True):
        color = _color_for_change(r["change"])
        row_html += f"""
        <tr>
          <td style="padding:10px">{r['name']}</td>
          <td style="padding:10px;text-align:right">{_fmt_int(r['value'])}</td>
          <td style="padding:10px;text-align:right;color:{color};font-weight:600">
            {_fmt_int(r['change'])}
          </td>
          <td style="padding:10px;text-align:right;color:{color};font-weight:600">
            {_fmt_pct(r['pct'])}
          </td>
        </tr>
        """

    total_color = _color_for_change(total_change)

    return f"""
    <div style="font-family:Arial;max-width:760px;margin:auto">
      <h2>{title}</h2>
      <div style="color:#666;font-size:12px">{timestamp}</div>

      <div style="margin:15px 0;padding:12px;border:1px solid #ddd;border-radius:8px">
        <b>Totalt värde:</b> {_fmt_int(total_value)} SEK<br>
        <b>Förändring:</b>
        <span style="color:{total_color};font-weight:700">
          {_fmt_int(total_change)} SEK ({_fmt_pct(total_pct)})
        </span>
      </div>

      <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
        <tr style="background:#f4f4f4">
          <th align="left">Bolag</th>
          <th align="right">Värde</th>
          <th align="right">Förändring</th>
          <th align="right">%</th>
        </tr>
        {row_html}
      </table>
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
    ]
    for r in rows:
        lines.append(
            f"{r['name']}: {_fmt_int(r['value'])} | {_fmt_int(r['change'])} | {_fmt_pct(r['pct'])}"
        )
    return "\n".join(lines)


# =========================================================
# 7) SKICKA MAIL
# =========================================================
def send_email(subject, html, text):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO]):
        raise RuntimeError("SMTP-inställningar saknas")

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg["Subject"] = subject

    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


# =========================================================
# 8) MAIN
# =========================================================
def main():
    now = datetime.now()
    title = f"{SUBJECT_PREFIX} – {now:%Y-%m-%d}"
    timestamp = f"Skapad {now:%Y-%m-%d %H:%M}"

    rows, total_value, total_change, total_pct = compute_portfolio(HOLDINGS)

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
