# portfolio_cloud.py
# Daglig portföljrapport via email (HTML + text)
# - Läser innehav från holdings.json (fallback: HOLDINGS)
# - Valutakonverterar till SEK (t.ex. CAD, USD)
# - Tabell: Bolag, Antal, Kurs, Värde, Idag, %
# - Hela kronor för värde/förändring, SEK bara i sammanfattningen
# - Blå = upp, röd = ner (HTML)
# - Layout finjusterad för stående mobil

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
# 1) INNEHAV
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

        out = []
        for h in holdings:
            name = str(h.get("name", "")).strip()
            symbol = str(h.get("symbol", "")).strip()
            shares = h.get("shares")
            if name and symbol and shares is not None:
                out.append({"name": name, "symbol": symbol, "shares": shares})
        return out or HOLDINGS

    except Exception:
        return HOLDINGS


# =========================================================
# 2) SMTP
# =========================================================
def _getenv_any(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return default


SMTP_HOST = _getenv_any("SMTP_HOST", "SMTP_SERVER", "MAIL_SERVER")
SMTP_PORT = int(_getenv_any("SMTP_PORT", default="587") or "587")
SMTP_USER = _getenv_any("SMTP_USER", "EMAIL_USER", "FROM_EMAIL")
SMTP_PASS = _getenv_any("SMTP_PASS", "EMAIL_PASS")
MAIL_TO = _getenv_any("MAIL_TO", "EMAIL_TO")
MAIL_FROM = _getenv_any("MAIL_FROM", "FROM_EMAIL", default=SMTP_USER)
SUBJECT_PREFIX = _getenv_any("SUBJECT_PREFIX", default="Portföljrapport")


# =========================================================
# 3) FORMATTERING
# =========================================================
def _fmt_int(x: Any) -> str:
    return f"{float(x):,.0f}".replace(",", " ") if x is not None else "-"


def _fmt_price(x: Any) -> str:
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",") if x is not None else "-"


def _fmt_shares(x: Any) -> str:
    v = float(x)
    return f"{int(v)}" if v.is_integer() else f"{v:.2f}".replace(".", ",")


def _fmt_pct(x: Any) -> str:
    return f"{float(x):+.1f}%" if x is not None else "-"


def _color(x: float) -> str:
    return "#0b63c7" if x > 0 else "#c4001a" if x < 0 else "#333333"


# =========================================================
# 4) DATA + FX
# =========================================================
_FX = {}


def fx_to_sek(cur: str) -> float:
    if cur == "SEK":
        return 1.0
    if cur in _FX:
        return _FX[cur]
    t = yf.Ticker(f"{cur}SEK=X")
    rate = float(t.history(period="5d")["Close"].iloc[-1])
    _FX[cur] = rate
    return rate


def fetch(symbol: str):
    t = yf.Ticker(symbol)
    fi = t.fast_info or {}
    price = fi.get("last_price")
    prev = fi.get("previous_close")
    cur = fi.get("currency") or "SEK"
    return float(price), float(prev), cur


# =========================================================
# 5) BERÄKNING
# =========================================================
def compute(holdings):
    rows, tot, prev_tot = [], 0.0, 0.0
    for h in holdings:
        p, pc, cur = fetch(h["symbol"])
        fx = fx_to_sek(cur)
        price = p * fx
        prev = pc * fx
        value = h["shares"] * price
        prev_val = h["shares"] * prev
        rows.append(
            {
                "name": h["name"],
                "shares": h["shares"],
                "price": price,
                "value": value,
                "chg": value - prev_val,
                "pct": (value - prev_val) / prev_val * 100 if prev_val else 0,
            }
        )
        tot += value
        prev_tot += prev_val
    return rows, tot, tot - prev_tot, (tot - prev_tot) / prev_tot * 100 if prev_tot else 0


# =========================================================
# 6) HTML
# =========================================================
def build_html(rows, tot, chg, pct, title, ts):
    body = ""
    for r in rows:
        c = _color(r["chg"])
        body += f"""
        <tr>
          <td>{r['name']}</td>
          <td>{_fmt_shares(r['shares'])}</td>
          <td>{_fmt_price(r['price'])}</td>
          <td>{_fmt_int(r['value'])}</td>
          <td style="color:{c};font-weight:600">{_fmt_int(r['chg'])}</td>
          <td style="color:{c};font-weight:600">{_fmt_pct(r['pct'])}</td>
        </tr>
        """

    return f"""
<div style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;padding:6px">
<h2>{title}</h2>
<div style="font-size:12px;color:#666">{ts}</div>

<table style="
  width:100%;
  border-collapse:collapse;
  table-layout:fixed;
  font-size:11.5px;">
<thead>
<tr style="background:#f6f7f9;font-size:11px">
  <th style="width:27%">Bolag</th>
  <th style="width:10%">Antal</th>
  <th style="width:17%">Kurs</th>
  <th style="width:18%">Värde</th>
  <th style="width:13%">Idag</th>
  <th style="width:15%">%</th>
</tr>
</thead>
<tbody>
{body}
</tbody>
</table>

<p style="font-size:12px;color:#777">
Totalt: {_fmt_int(tot)} SEK<br>
Förändring: <span style="color:{_color(chg)}">{_fmt_int(chg)} SEK ({_fmt_pct(pct)})</span>
</p>
</div>
"""


# =========================================================
# 7) TEXT
# =========================================================
def build_text(rows, tot, chg, pct, title, ts):
    out = [title, ts, "", f"Totalt: {_fmt_int(tot)} SEK",
           f"Förändring: {_fmt_int(chg)} SEK ({_fmt_pct(pct)})", ""]
    for r in rows:
        out.append(
            f"{r['name']} | {_fmt_shares(r['shares'])} | {_fmt_price(r['price'])} | "
            f"{_fmt_int(r['value'])} | {_fmt_int(r['chg'])} | {_fmt_pct(r['pct'])}"
        )
    return "\n".join(out)


# =========================================================
# 8) SEND
# =========================================================
def send(subject, html, text):
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
# 9) MAIN
# =========================================================
def main():
    now = datetime.now()
    title = f"{SUBJECT_PREFIX} – {now:%Y-%m-%d}"
    ts = f"{now:%Y-%m-%d %H:%M}"

    holdings = load_holdings()
    rows, tot, chg, pct = compute(holdings)

    html = build_html(rows, tot, chg, pct, title, ts)
    text = build_text(rows, tot, chg, pct, title, ts)

    send(title, html, text)
    print("OK – mail skickat")


if __name__ == "__main__":
    main()
