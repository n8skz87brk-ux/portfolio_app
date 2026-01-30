import json
import yfinance as yf
from pathlib import Path
from datetime import datetime
from email.message import EmailMessage
import smtplib
import os

# ===============================
# LÄS HOLDINGS FRÅN holdings.json
# ===============================

HOLDINGS_FILE = Path(__file__).with_name("holdings.json")

def load_holdings():
    if not HOLDINGS_FILE.exists():
        raise FileNotFoundError(
            f"Hittar inte {HOLDINGS_FILE}. Kör holdings_gui.py och spara innehav först."
        )

    data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))

    # Stöd både lista och {"holdings": [...]}
    if isinstance(data, dict) and "holdings" in data:
        raw = data["holdings"]
    elif isinstance(data, list):
        raw = data
    else:
        raise ValueError("Fel format i holdings.json")

    holdings = []
    for h in raw:
        name = str(h.get("name", "")).strip()
        symbol = str(h.get("symbol", "")).strip()
        shares = h.get("shares", 0)

        if not name or not symbol:
            continue

        try:
            shares = int(shares)
        except Exception:
            shares = 0

        holdings.append(
            {
                "name": name,
                "symbol": symbol,
                "shares": shares,
            }
        )

    return holdings


# ===============================
# HÄMTA HOLDINGS
# ===============================

HOLDINGS = load_holdings()


# ===============================
# PORTFÖLJLOGIK
# ===============================

def fetch_prices(holdings):
    rows = []
    total_value = 0.0

    for h in holdings:
        symbol = h["symbol"]
        shares = h["shares"]

        try:
            ticker = yf.Ticker(symbol)
            price = ticker.fast_info["last_price"]
        except Exception:
            price = None

        value = price * shares if price else 0
        total_value += value

        rows.append(
            {
                "name": h["name"],
                "symbol": symbol,
                "shares": shares,
                "price": price,
                "value": value,
            }
        )

    return rows, total_value


def build_report(rows, total_value):
    lines = []
    lines.append("Din portfölj\n")
    lines.append(f"Datum: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    for r in rows:
        if r["price"] is None:
            price_txt = "–"
        else:
            price_txt = f"{r['price']:.2f}"

        lines.append(
            f"{r['name']:<30} {r['symbol']:<10} "
            f"{r['shares']:>5} st  "
            f"{price_txt:>8}  "
            f"{r['value']:>10.0f} kr"
        )

    lines.append("\n")
    lines.append(f"Totalt värde: {total_value:,.0f} kr")

    return "\n".join(lines)


# ===============================
# MAIL
# ===============================

def send_mail(body):
    msg = EmailMessage()
    msg["Subject"] = "Portföljuppdatering"
    msg["From"] = os.environ["MAIL_FROM"]
    msg["To"] = os.environ["MAIL_TO"]
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(os.environ["MAIL_FROM"], os.environ["MAIL_PASSWORD"])
        smtp.send_message(msg)


# ===============================
# MAIN
# ===============================

def main():
    rows, total_value = fetch_prices(HOLDINGS)
    report = build_report(rows, total_value)
    print(report)
    send_mail(report)


if __name__ == "__main__":
    main()
