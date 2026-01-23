# dev-test: branch setup ok

import os
from datetime import datetime
import smtplib
from email.message import EmailMessage

import yfinance as yf

HOLDINGS = [
    {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
    {"name": "Nelly Group", "symbol": "NELLY.ST", "shares": 98},
    {"name": "Nordea Bank", "symbol": "NDA-SE.ST", "shares": 6},
    {"name": "Plejd", "symbol": "PLEJD.ST", "shares": 132},
    {"name": "RevolutionRace", "symbol": "RVRC.ST", "shares": 79},
    {"name": "Saab B", "symbol": "SAAB-B.ST", "shares": 131},
    {"name": "Swedish Orphan Biovitrum", "symbol": "SOBI.ST", "shares": 86},
    {"name": "Elemental (CAD)", "symbol": "ELE.V", "shares": 249},
    {"name": "Mineros S.A. (CAD)", "symbol": "MSA.TO", "shares": 753},
]

FX_TICKERS = {"USD": "USDSEK=X", "CAD": "CADSEK=X", "SEK": None}


def fmt_sek(amount: float, signed: bool = False) -> str:
    s = f"{amount:+,.2f}" if signed else f"{amount:,.2f}"
    return s.replace(",", " ") + " kr"


def color_for(amount: float) -> str:
    if amount > 0:
        return "blue"
    if amount < 0:
        return "red"
    return "black"


def get_fx_to_sek(currency: str) -> tuple[float, float]:
    currency = (currency or "SEK").upper()
    if currency == "SEK":
        return 1.0, 1.0

    fx_symbol = FX_TICKERS.get(currency)
    if not fx_symbol:
        raise ValueError(f"Saknar FX-ticker för {currency}→SEK")

    t = yf.Ticker(fx_symbol)
    info = t.fast_info or {}

    fx_now = info.get("last_price")
    fx_prev = info.get("previous_close")

    if fx_now is None or fx_prev is None:
        hist = t.history(period="7d", interval="1d")
        if hist is None or hist.empty or len(hist) < 2:
            raise ValueError(f"Kunde inte hämta FX {fx_symbol}")
        fx_now = float(hist["Close"].iloc[-1])
        fx_prev = float(hist["Close"].iloc[-2])

    return float(fx_now), float(fx_prev)


def fetch_quote(symbol: str) -> tuple[float, float, str]:
    t = yf.Ticker(symbol)
    info = t.fast_info or {}

    last_price = info.get("last_price")
    prev_close = info.get("previous_close")
    currency = (info.get("currency") or "SEK").upper()

    if last_price is not None and prev_close is not None:
        return float(last_price), float(prev_close), currency

    hist = t.history(period="7d", interval="1d")
    if hist is None or hist.empty or len(hist) < 2:
        raise ValueError(f"Ingen kursdata för {symbol}")

    last_price = float(hist["Close"].iloc[-1])
    prev_close = float(hist["Close"].iloc[-2])

    try:
        currency = (t.info.get("currency") or currency).upper()
    except Exception:
        pass

    return last_price, prev_close, currency


def build_email_html(updated_at: str, total_value: float, total_day: float, rows: list[dict]) -> str:
    total_day_color = color_for(total_day)

    tr_html = []
    for r in rows:
        day_color = color_for(r["day_val"])
        tr_html.append(
            f"""
            <tr>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;">{r['name']}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;white-space:nowrap;">{r['symbol']}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap;">{r['shares']}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap;">{r['price_sek']}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap;">{r['value_sek']}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap;color:{day_color};font-weight:600;">{r['day_sek']}</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html>
  <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;line-height:1.35;">
    <h2 style="margin:0 0 8px 0;">Min portfölj – uppdatering</h2>
    <div style="color:#555;margin-bottom:12px;">Uppdaterad: {updated_at}</div>

    <div style="margin:10px 0 4px 0;">
      <div style="font-size:16px;margin-bottom:4px;">
        Portföljvärde: <span style="font-weight:700;">{fmt_sek(total_value)}</span>
      </div>
      <div style="font-size:16px;">
        Utveckling idag: <span style="color:{total_day_color};font-weight:700;">{fmt_sek(total_day, signed=True)}</span>
      </div>
    </div>

    <h3 style="margin:18px 0 8px 0;">Innehav</h3>
    <table style="border-collapse:collapse;width:100%;max-width:820px;">
      <thead>
        <tr>
          <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #999;">Namn</th>
          <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #999;">Symbol</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #999;">Antal</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #999;">Kurs (SEK)</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #999;">Värde (SEK)</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #999;">Idag (SEK)</th>
        </tr>
      </thead>
      <tbody>
        {''.join(tr_html)}
      </tbody>
    </table>
  </body>
</html>"""


def send_email(subject: str, body_text: str, body_html: str):
    gmail_from = os.environ["GMAIL_FROM"]
    gmail_to = os.environ["GMAIL_TO"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail_from
    msg["To"] = gmail_to
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(gmail_from, gmail_app_password)
        server.send_message(msg)


def main():
    missing = [k for k in ("GMAIL_FROM", "GMAIL_TO", "GMAIL_APP_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Saknar env-var: {', '.join(missing)}")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fx_cache: dict[str, tuple[float, float]] = {"SEK": (1.0, 1.0)}

    rows = []
    total_value = 0.0
    total_day = 0.0

    for h in HOLDINGS:
        name = h["name"]
        sym = h["symbol"]
        shares = float(h["shares"])

        last_local, prev_local, currency = fetch_quote(sym)
        currency = (currency or "SEK").upper()

        if currency not in fx_cache:
            fx_cache[currency] = get_fx_to_sek(currency)
        fx_now, fx_prev = fx_cache[currency]

        price_sek = last_local * fx_now
        prev_sek = prev_local * fx_prev

        value_sek = price_sek * shares
        day_sek_val = (price_sek - prev_sek) * shares

        total_value += value_sek
        total_day += day_sek_val

        rows.append(
            {
                "name": name,
                "symbol": sym,
                "shares": f"{shares:.0f}",
                "price_sek": f"{price_sek:,.2f}".replace(",", " "),
                "value_sek": f"{value_sek:,.2f}".replace(",", " "),
                "day_sek": f"{day_sek_val:+,.2f}".replace(",", " "),
                "day_val": day_sek_val,
                "sort_value": value_sek,
            }
        )

    rows.sort(key=lambda r: r["sort_value"], reverse=True)

    subject = "Min portfölj – uppdatering"
    body_text_lines = [
        f"Uppdaterad: {updated_at}",
        "",
        f"Portföljvärde: {fmt_sek(total_value)}",
        f"Utveckling idag: {fmt_sek(total_day, signed=True)}",
        "",
        "Innehav:",
    ]
    for r in rows:
        body_text_lines.append(f"- {r['name']}: {r['value_sek']} SEK | Idag: {r['day_sek']} SEK")

    body_text = "\n".join(body_text_lines)
    body_html = build_email_html(updated_at, total_value, total_day, rows)

    send_email(subject, body_text, body_html)
    print("OK – mail skickat:", updated_at, "Total day:", total_day)


if __name__ == "__main__":
    main()
