import tkinter as tk
from tkinter import ttk
from datetime import datetime
import yfinance as yf

import smtplib
from email.message import EmailMessage

# --- Dina innehav ---
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

# Yahoo FX tickers
FX_TICKERS = {"USD": "USDSEK=X", "CAD": "CADSEK=X", "SEK": None}

# --- Gmail-inställningar ---
# Tips: lägg gärna lösenordet i en miljövariabel i stället för i koden, men detta fungerar.
GMAIL_FROM = "peter.ekvardt@gmail.com"
GMAIL_TO = "peter.ekvardt@gmail.com"
GMAIL_APP_PASSWORD = "tshozrsrxvhoyadv"  # utan mellanslag


def send_portfolio_email_gmail(subject: str, body_text: str, body_html: str | None = None):
    """Skickar ett mail via Gmail SMTP. Kräver app-lösenord."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = GMAIL_TO

    # Alltid en textdel (bra fallback)
    msg.set_content(body_text)

    # Valfritt HTML-lager (så färger funkar i iPhone/Gmail/Outlook)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def get_fx_to_sek(currency: str) -> float:
    currency = (currency or "SEK").upper()
    if currency == "SEK":
        return 1.0
    fx_symbol = FX_TICKERS.get(currency)
    if not fx_symbol:
        raise ValueError(f"Saknar FX-ticker för {currency}→SEK")
    info = yf.Ticker(fx_symbol).fast_info
    if info and "last_price" in info:
        return float(info["last_price"])
    hist = yf.Ticker(fx_symbol).history(period="5d", interval="1d")
    if hist is None or hist.empty:
        raise ValueError(f"Kunde inte hämta FX {fx_symbol}")
    return float(hist["Close"].iloc[-1])


def fetch_quote(symbol: str):
    """Returnerar (price_local, open_local, currency)"""
    t = yf.Ticker(symbol)

    info = t.fast_info
    if info and "last_price" in info:
        price = float(info["last_price"])
        open_price = info.get("open")
        open_price = float(open_price) if open_price not in (None, 0) else price
        currency = (info.get("currency") or "SEK").upper()
        return price, open_price, currency

    # fallback
    hist = t.history(period="5d", interval="1d")
    if hist is None or hist.empty:
        raise ValueError(f"Ingen kursdata för {symbol}")
    price = float(hist["Close"].iloc[-1])
    open_price = float(hist["Open"].iloc[-1]) if "Open" in hist else price
    try:
        currency = (t.info.get("currency") or "SEK").upper()
    except Exception:
        currency = "SEK"
    return price, open_price, currency


def fmt_sek(amount: float, signed: bool = False) -> str:
    s = f"{amount:+,.2f}" if signed else f"{amount:,.2f}"
    return s.replace(",", " ") + " kr"


def color_for(amount: float) -> str:
    if amount > 0:
        return "blue"
    if amount < 0:
        return "red"
    return "black"


def build_email_html(updated_at: str, total_value: float, total_day: float, rows: list[dict]) -> str:
    # Inline-stilar (snällast mot mailklienter)
    total_day_color = color_for(total_day)
    total_value_color = color_for(total_value)  # total_value är nästan alltid positiv, men ok

    # Bygg tabellrader
    tr_html = []
    for r in rows:
        day_color = color_for(r["day_sek"])
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
        Portföljvärde: <span style="color:{total_value_color};font-weight:700;">{fmt_sek(total_value)}</span>
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Min portfölj (SEK)")
        self.geometry("860x540")

        self.refresh_seconds = 30

        self.value_var = tk.StringVar(value="—")
        self.day_var = tk.StringVar(value="—")
        self.updated_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Redo")

        # Styles för ttk-label (för att färg verkligen ska slå igenom)
        self.style = ttk.Style()
        self.style.configure("DayZero.TLabel", font=("Segoe UI", 14), foreground="black")
        self.style.configure("DayPos.TLabel", font=("Segoe UI", 14), foreground="blue")
        self.style.configure("DayNeg.TLabel", font=("Segoe UI", 14), foreground="red")

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Portföljvärde (SEK)").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.value_var, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=1, sticky="w", padx=10
        )

        ttk.Label(top, text="Utveckling idag (SEK)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.day_label = ttk.Label(top, textvariable=self.day_var, style="DayZero.TLabel")
        self.day_label.grid(row=1, column=1, sticky="w", padx=10, pady=(6, 0))

        ttk.Label(top, text="Uppdaterad").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(top, textvariable=self.updated_var).grid(row=2, column=1, sticky="w", padx=10, pady=(6, 0))

        ttk.Button(top, text="Uppdatera nu", command=self.update_values_safe).grid(row=0, column=2, rowspan=2, padx=10)
        ttk.Button(top, text="Skicka mail", command=self.email_snapshot_safe).grid(row=2, column=2, padx=10, sticky="we")

        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=12)

        cols = ("name", "symbol", "shares", "price_sek", "value_sek", "day_sek")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.tree.heading("name", text="Namn")
        self.tree.heading("symbol", text="Symbol")
        self.tree.heading("shares", text="Antal")
        self.tree.heading("price_sek", text="Kurs (SEK)")
        self.tree.heading("value_sek", text="Värde (SEK)")
        self.tree.heading("day_sek", text="Idag (SEK)")

        self.tree.column("name", width=260)
        self.tree.column("symbol", width=110)
        self.tree.column("shares", width=80, anchor="e")
        self.tree.column("price_sek", width=110, anchor="e")
        self.tree.column("value_sek", width=140, anchor="e")
        self.tree.column("day_sek", width=120, anchor="e")

        # Tags för färg i tabellen
        self.tree.tag_configure("pos", foreground="blue")
        self.tree.tag_configure("neg", foreground="red")

        for h in HOLDINGS:
            self.tree.insert("", "end", iid=h["symbol"], values=(h["name"], h["symbol"], h["shares"], "—", "—", "—"))

        self.last_totals = {"value": 0.0, "day": 0.0, "updated": "—"}

        self.update_values_safe()
        self.after(self.refresh_seconds * 1000, self.auto_refresh)

    def auto_refresh(self):
        self.update_values_safe()
        self.after(self.refresh_seconds * 1000, self.auto_refresh)

    def update_values_safe(self):
        try:
            self.update_values()
            self.status_var.set("Redo")
        except Exception as e:
            self.status_var.set(f"Fel vid uppdatering: {e}")

    def update_values(self):
        self.status_var.set("Uppdaterar…")
        self.update_idletasks()

        total_value = 0.0
        total_day = 0.0
        now_str = datetime.now().strftime("%H:%M:%S")
        self.updated_var.set(now_str)

        fx_cache = {"SEK": 1.0}

        for h in HOLDINGS:
            name = h["name"]
            sym = h["symbol"]
            shares = float(h["shares"])

            price_local, open_local, currency = fetch_quote(sym)
            currency = (currency or "SEK").upper()

            if currency not in fx_cache:
                fx_cache[currency] = get_fx_to_sek(currency)
            fx = fx_cache[currency]

            price_sek = price_local * fx
            open_sek = open_local * fx
            change_sek = price_sek - open_sek

            value_sek = price_sek * shares
            day_sek = change_sek * shares

            total_value += value_sek
            total_day += day_sek

            tag = "pos" if day_sek > 0 else "neg" if day_sek < 0 else ""
            self.tree.item(
                sym,
                values=(
                    name,
                    sym,
                    f"{shares:.0f}",
                    f"{price_sek:,.2f}".replace(",", " "),
                    f"{value_sek:,.2f}".replace(",", " "),
                    f"{day_sek:+,.2f}".replace(",", " "),
                ),
                tags=(tag,) if tag else (),
            )

        # Sortera efter värde (störst först) – använder kolumn 4 (value_sek)
        rows = []
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            v = vals[4]
            try:
                value = float(str(v).replace(" ", "").replace("kr", ""))
            except Exception:
                value = 0.0
            rows.append((value, item))
        rows.sort(reverse=True, key=lambda x: x[0])
        for idx, (_, item) in enumerate(rows):
            self.tree.move(item, "", idx)

        self.value_var.set(fmt_sek(total_value))
        self.day_var.set(fmt_sek(total_day, signed=True))

        # Färg på totalsiffran (via style)
        style = "DayPos.TLabel" if total_day > 0 else "DayNeg.TLabel" if total_day < 0 else "DayZero.TLabel"
        self.day_label.configure(style=style)

        # Spara totals till mailet
        self.last_totals = {"value": total_value, "day": total_day, "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}

    def email_snapshot_safe(self):
        try:
            self.email_snapshot()
            self.status_var.set("Mail skickat (om inloggning OK).")
        except Exception as e:
            self.status_var.set(f"Mail-fel: {e}")

    def email_snapshot(self):
        # Bygg rader från tabellen (som redan är sorterad)
        rows = []
        lines = []
        for item in self.tree.get_children():
            name, sym, shares, price_sek, value_sek, day_sek = self.tree.item(item, "values")
            lines.append(f"- {name}: {value_sek} SEK | Idag: {day_sek} SEK")
            # För HTML-tabellen
            try:
                day_val = float(str(day_sek).replace(" ", "").replace("kr", ""))
            except Exception:
                day_val = 0.0
            rows.append(
                {
                    "name": str(name),
                    "symbol": str(sym),
                    "shares": str(shares),
                    "price_sek": str(price_sek),
                    "value_sek": str(value_sek),
                    "day_sek": str(day_sek),
                    "day_val": day_val,
                }
            )

        subject = "Min portfölj – uppdatering"
        updated_at = self.last_totals.get("updated") or datetime.now().strftime("%Y-%m-%d %H:%M")
        total_value = float(self.last_totals.get("value") or 0.0)
        total_day = float(self.last_totals.get("day") or 0.0)

        body_text = (
            f"Uppdaterad: {updated_at}\n\n"
            f"Portföljvärde: {fmt_sek(total_value)}\n"
            f"Utveckling idag: {fmt_sek(total_day, signed=True)}\n\n"
            "Innehav:\n" + "\n".join(lines)
        )

        body_html = build_email_html(updated_at, total_value, total_day, rows)

        send_portfolio_email_gmail(subject, body_text, body_html)


if __name__ == "__main__":
    App().mainloop()
