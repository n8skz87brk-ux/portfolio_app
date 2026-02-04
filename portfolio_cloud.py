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


BASE_CCY = os.getenv("BASE_CCY", "SEK")
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "Portfölj")
HOLDINGS_PATH = Path(os.getenv("HOLDINGS_PATH", "holdings.json"))


def getenv_required(key: str) -> str:
    v = os.getenv(key, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return v


def safe(x):
    try:
        return float(x)
    except Exception:
        return math.nan


def fmt(v):
    if math.isnan(v):
        return "-"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} {BASE_CCY}"


def load_holdings():
    if not HOLDINGS_PATH.exists():
        raise RuntimeError("holdings.json saknas")

    return json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))


def main():
    holdings = load_holdings()
    symbols = [h["symbol"] for h in holdings]

    quotes = yf.Tickers(" ".join(symbols))
    rows = []
    total = 0.0
    change = 0.0

    for h in holdings:
        t = quotes.tickers[h["symbol"]]
        fi = t.fast_info

        last = safe(fi.get("last_price"))
        prev = safe(fi.get("previous_close"))

        if math.isnan(last) or math.isnan(prev):
            continue

        value = h["shares"] * last
        delta = h["shares"] * (last - prev)

        total += value
        change += delta

        rows.append((h["name"], h["symbol"], value, delta))

    rows.sort(key=lambda r: -r[2])

    now = datetime.now(ZoneInfo("Europe/Stockholm")).strftime("%Y-%m-%d %H:%M")
    arrow = "▲" if change >= 0 else "▼"

    subject = f"{SUBJECT_PREFIX} {arrow} {fmt(total)} ({fmt(change)})"

    lines = [f"Portföljrapport {now}", ""]
    for r in rows:
        lines.append(f"{r[0]:22} {r[1]:10} {fmt(r[2]):>14} {fmt(r[3]):>14}")

    body = "\n".join(lines)

    print(subject)
    print(body)

    msg = EmailMessage()
    msg["From"] = getenv_required("EMAIL_FROM")
    msg["To"] = getenv_required("EMAIL_TO")
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(getenv_required("SMTP_HOST"), int(getenv_required("SMTP_PORT"))) as s:
        s.starttls()
        s.login(getenv_required("SMTP_USER"), getenv_required("SMTP_PASS"))
        s.send_message(msg)


if __name__ == "__main__":
    main()
