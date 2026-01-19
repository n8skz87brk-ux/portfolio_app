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

FX_TICKERS = {"USD": "USDSEK=X", "CAD": "CADSEK=X", "SEK": None}

GMAIL_FROM = "peter.ekvardt@gmail.com"
GMAIL_TO = "peter.ekvardt@gmail.com"
GMAIL_APP_PASSWORD = "tshozrsrxvhoyadv"


def send_portfolio_email_gmail(subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = GMAIL_TO
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def get_fx_to_sek(currency: str) -> float:
    currency = (currency or "SEK").upper()
    if currency == "SEK":
        return 1.0
    fx_symbol = FX_TICKERS.get(currency)
    info = yf.Ticker(fx_symbol).fast_info
    if info and "last_price" in info:
        return float(info["last_price"])
    hist = yf.Ticker(fx_symbol).history(period="5d", interval="1d")
    return float(hist["Close"].iloc[-1])


def fetch_quote(symbol: str):
    t = yf.Ticker(symbol)
    info = t.fast_info
    if info and "last_price" in info:
        price = float(info["last_price"])
        open_price = info.get("open") or price
        currency = (info.get("currency") or "SEK").upper()
        return price, float(open_price), currency

    hist = t.history(period="5d", interval="1d")
    price = float(hist["Close"].iloc[-1])
    open_price = float(hist["Open"].iloc[-1]) if "Open" in hist else price
    currency = (t.info.get("currency") or "SEK").upper()
    return price, open_price, currency


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

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Portföljvärde (SEK)").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.value_var, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=1, sticky="w", padx=10
        )

        ttk.Label(top, text="Utveckling idag (SEK)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.day_label = ttk.Label(top, textvariable=self.day_var, font=("Segoe UI", 14))
        self.day_label.grid(row=1, column=1, sticky="w", padx=10, pady=(6, 0))

        ttk.Label(top, text="Uppdaterad").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(top, textvariable=self.updated_var).grid(row=2, column=1, sticky="w", padx=10, pady=(6, 0))

        ttk.Button(top, text="Uppdatera nu", command=self.update_values_safe).grid(
            row=0, column=2, rowspan=2, padx=10
        )
        ttk.Button(top, text="Skicka mail", command=self.email_snapshot_safe).grid(
            row=2, column=2, padx=10, sticky="we"
        )

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

        # Tags för färg
        self.tree.tag_configure("pos", foreground="blue")
        self.tree.tag_configure("neg", foreground="red")

        for h in HOLDINGS:
            self.tree.insert("", "end", iid=h["symbol"], values=(h["name"], h["symbol"], h["shares"], "—", "—", "—"))

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
        self.updated_var.set(datetime.now().strftime("%H:%M:%S"))

        fx_cache = {"SEK": 1.0}

        for h in HOLDINGS:
            name = h["name"]
            sym = h["symbol"]
            shares = float(h["shares"])

            price_local, open_local, currency = fetch_quote(sym)
            if currency not in fx_cache:
                fx_cache[currency] = get_fx_to_sek(currency)
            fx = fx_cache[currency]

            price_sek = price_local * fx
            open_sek = open_local * fx
            day_sek = (price_sek - open_sek) * shares
            value_sek = price_sek * shares

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

        self.value_var.set(f"{total_value:,.2f}".replace(",", " ") + " kr")
        self.day_var.set(f"{total_day:+,.2f}".replace(",", " ") + " kr")

        # Färg på totalsiffran
        self.day_label.configure(foreground="blue" if total_day > 0 else "red" if total_day < 0 else "black")

    def email_snapshot_safe(self):
        try:
            self.email_snapshot()
            self.status_var.set("Mail skickat.")
        except Exception as e:
            self.status_var.set(f"Mail-fel: {e}")

    def email_snapshot(self):
        lines = []
        for item in self.tree.get_children():
            name, sym, shares, price_sek, value_sek, day_sek = self.tree.item(item, "values")
            lines.append(f"- {name}: {value_sek} SEK | Idag: {day_sek} SEK")

        subject = "Min portfölj – uppdatering"
        body = (
            f"Uppdaterad: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Portföljvärde: {self.value_var.get()}\n"
            f"Utveckling idag: {self.day_var.get()}\n\n"
            "Innehav:\n" + "\n".join(lines)
        )
        send_portfolio_email_gmail(subject, body)


if __name__ == "__main__":
    App().mainloop()
