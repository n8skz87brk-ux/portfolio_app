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


# =========================
# Config (env)
# =========================
BASE_CCY = (os.getenv("BASE_CCY", "SEK") or "SEK").upper().strip()
SUBJECT_PREFIX = (os.getenv("SUBJECT_PREFIX", "Portfölj") or "Portfölj").strip()
HOLDINGS_PATH = Path(os.getenv("HOLDINGS_PATH", "holdings.json"))

# Sorting: value_desc | name_asc | change_desc
SORT_BY = (os.getenv("SORT_BY", "value_desc") or "value_desc").strip().lower()


# =========================
# Helpers
# =========================
def getenv_required(key: str) -> str:
    v = os.getenv(key, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return v


def is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def fmt_money(amount: float, ccy: str) -> str:
    if amount is None or is_nan(amount):
        return "-"
    s = f"{amount:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} {ccy}"


def fmt_number(x: float) -> str:
    if x is None or is_nan(x):
        return "-"
    s = f"{x:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return s


def guess_ccy(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.endswith(".ST"):
        return "SEK"
    if s.endswith(".TO") or s.endswith(".V"):
        return "CAD"
    return "USD"


def load_holdings() -> list[dict]:
    if not HOLDINGS_PATH.exists():
        raise RuntimeError(f"Hittar inte holdings-filen: {HOLDINGS_PATH}")

    raw = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("holdings.json måste vara en lista []")

    out: list[dict] = []
    for item in raw:
        name = str(item.get("name", "")).strip()
        symbol = str(item.get("symbol", "")).strip()
        shares = item.get("shares", 0)
        if not name or not symbol:
            continue
        out.append({"name": name, "symbol": symbol, "shares": float(shares)})
    return out


# =========================
# Market data (robust)
# =========================
def get_last_two_closes(symbols: list[str]) -> dict[str, tuple[float, float]]:
    """
    Return dict: symbol -> (last_close, prev_close)
    Uses yf.download which is usually more reliable on GitHub runners than fast_info.
    """
    if not symbols:
        return {}

    data = yf.download(
        tickers=" ".join(symbols),
        period="10d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )

    out: dict[str, tuple[float, float]] = {}

    # Single ticker case
    if not hasattr(data.columns, "levels"):
        closes = data["Close"].dropna()
        if len(closes) >= 2:
            out[symbols[0]] = (float(closes.iloc[-1]), float(closes.iloc[-2]))
        else:
            out[symbols[0]] = (math.nan, math.nan)
        return out

    # Multi-ticker: columns like (TICKER, 'Close')
    for sym in symbols:
        try:
            series = data[(sym, "Close")].dropna()
            if len(series) >= 2:
                out[sym] = (float(series.iloc[-1]), float(series.iloc[-2]))
            else:
                out[sym] = (math.nan, math.nan)
        except Exception:
            out[sym] = (math.nan, math.nan)

    return out


def get_fx_to_sek() -> dict[str, float]:
    """
    Returns mapping for USD->SEK and CAD->SEK using Yahoo FX tickers.
    """
    fx = {"SEK": 1.0}
    if BASE_CCY != "SEK":
        return fx

    pairs = ["USDSEK=X", "CADSEK=X"]
    fx_closes = get_last_two_closes(pairs)
    usd = fx_closes.get("USDSEK=X", (math.nan, math.nan))[0]
    cad = fx_closes.get("CADSEK=X", (math.nan, math.nan))[0]
    if not is_nan(usd):
        fx["USD"] = usd
    if not is_nan(cad):
        fx["CAD"] = cad
    return fx


# =========================
# Compute rows
# =========================
def compute_rows(holdings: list[dict]) -> tuple[list[dict], list[str], dict[str, float]]:
    symbols = [h["symbol"] for h in holdings]
    closes = get_last_two_closes(symbols)
    fxmap = get_fx_to_sek()

    rows: list[dict] = []
    missing: list[str] = []

    for h in holdings:
        name = h["name"]
        sym = h["symbol"]
        shares = float(h["shares"])

        last, prev = closes.get(sym, (math.nan, math.nan))
        ccy = guess_ccy(sym)

        fx = 1.0
        if BASE_CCY == "SEK":
            fx = fxmap.get(ccy, math.nan)

        ok = not (is_nan(last) or is_nan(prev) or is_nan(fx))

        if not ok:
            missing.append(sym)

        last_base = last * fx if ok else math.nan
        prev_base = prev * fx if ok else math.nan

        value = shares * last_base if ok else math.nan
        change = shares * (last_base - prev_base) if ok else math.nan

        rows.append(
            {
                "name": name,
                "symbol": sym,
                "shares": shares,
                "ccy": ccy,
                "last_base": last_base,
                "prev_base": prev_base,
                "value": value,
                "change": change,
                "ok": ok,
            }
        )

    # Sorting
    def key_value_desc(r):
        return (0 if r["ok"] else 1, -(r["value"] if r["ok"] else -1e30))

    def key_change_desc(r):
        return (0 if r["ok"] else 1, -(r["change"] if r["ok"] else -1e30))

    def key_name_asc(r):
        return (0 if r["ok"] else 1, r["name"].lower())

    if SORT_BY == "name_asc":
        rows.sort(key=key_name_asc)
    elif SORT_BY == "change_desc":
        rows.sort(key=key_change_desc)
    else:
        rows.sort(key=key_value_desc)

    return rows, missing, fxmap


# =========================
# Build email bodies
# =========================
def build_subject_and_bodies(rows: list[dict], missing: list[str], fxmap: dict[str, float]) -> tuple[str, str, str]:
    tz = ZoneInfo("Europe/Stockholm")
    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    total_value = sum(r["value"] for r in rows if r["ok"])
    total_change = sum(r["change"] for r in rows if r["ok"])

    arrow = "▲" if total_change >= 0 else "▼"
    subject = f"{SUBJECT_PREFIX} {arrow} {fmt_money(total_value, BASE_CCY)} ({fmt_money(total_change, BASE_CCY)})"

    # ---------- Plain text (NO ticker) ----------
    header = (
        f"{'Innehav':24} {'Antal':>8} "
        f"{'Senast':>14} {'Stängn-1':>14} {'Värde':>16} {'Δ idag':>16}"
    )
    lines = [
        subject,
        f"Portföljrapport {now_str} (basvaluta: {BASE_CCY})",
        "",
        header,
        "-" * len(header),
    ]

    for r in rows:
        lines.append(
            f"{r['name'][:24]:24} {r['shares']:8.2f} "
            f"{fmt_money(r['last_base'], BASE_CCY):>14} {fmt_money(r['prev_base'], BASE_CCY):>14} "
            f"{fmt_money(r['value'], BASE_CCY):>16} {fmt_money(r['change'], BASE_CCY):>16}"
        )

    lines.append("")
    lines.append(f"Totalt värde: {fmt_money(total_value, BASE_CCY)}")
    lines.append(f"Förändring vs föregående stängning: {fmt_money(total_change, BASE_CCY)}")

    if BASE_CCY == "SEK":
        fx_parts = []
        if "USD" in fxmap and not is_nan(fxmap["USD"]):
            fx_parts.append(f"USD/SEK: {fxmap['USD']:.4f}")
        if "CAD" in fxmap and not is_nan(fxmap["CAD"]):
            fx_parts.append(f"CAD/SEK: {fxmap['CAD']:.4f}")
        if fx_parts:
            lines.append(" · ".join(fx_parts))

    if missing:
        lines.append("")
        lines.append("⚠️ VARNING – saknar prisdata för:")
        for sym in missing:
            lines.append(f"  - {sym}")

    body_text = "\n".join(lines)

    # ---------- HTML (NO ticker + colors) ----------
    def colorize(value: float, text: str) -> str:
        # Blått vid plus, rött vid minus
        if value < 0:
            return f"<span style='color:#c00000'>{text}</span>"
        if value > 0:
            return f"<span style='color:#1f4fd8'>{text}</span>"
        return text

    def td(val: str, align: str = "left") -> str:
        return (
            "<td style='padding:6px 10px;border-bottom:1px solid #ddd;"
            f"text-align:{align};white-space:nowrap'>{val}</td>"
        )

    html_rows = []
    for r in rows:
        v = fmt_money(r["value"], BASE_CCY)
        ch = fmt_money(r["change"], BASE_CCY)
        html_rows.append(
            "<tr>"
            + td(r["name"], "left")
            + td(fmt_number(r["shares"]), "right")
            + td(fmt_money(r["last_base"], BASE_CCY), "right")
            + td(fmt_money(r["prev_base"], BASE_CCY), "right")
            + td(colorize(r["value"], v), "right")
            + td(colorize(r["change"], ch), "right")
            + "</tr>"
        )

    warn_html = ""
    if missing:
        items = "".join([f"<li><code>{m}</code></li>" for m in missing])
        warn_html = f"""
        <div style="margin-top:14px;padding:10px 12px;border:1px solid #f0c36d;background:#fff7e6">
          <strong>⚠️ VARNING</strong> – saknar prisdata för:
          <ul style="margin:8px 0 0 18px">{items}</ul>
        </div>
        """

    fx_line = ""
    if BASE_CCY == "SEK":
        parts = []
        if "USD" in fxmap and not is_nan(fxmap["USD"]):
            parts.append(f"USD/SEK: {fxmap['USD']:.4f}")
        if "CAD" in fxmap and not is_nan(fxmap["CAD"]):
            parts.append(f"CAD/SEK: {fxmap['CAD']:.4f}")
        if parts:
            fx_line = f"<div style='margin-top:6px;color:#444'>{' · '.join(parts)}</div>"

    total_change_html = colorize(total_change, fmt_money(total_change, BASE_CCY))

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color:#111;">
        <h2 style="margin:0 0 8px 0;">{subject}</h2>
        <div style="color:#444;margin-bottom:10px;">Portföljrapport {now_str} (basvaluta: {BASE_CCY})</div>

        <table style="border-collapse:collapse;font-size:14px;">
          <thead>
            <tr>
              <th style="text-align:left;padding:6px 10px;border-bottom:2px solid #333;">Innehav</th>
              <th style="text-align:right;padding:6px 10px;border-bottom:2px solid #333;">Antal</th>
              <th style="text-align:right;padding:6px 10px;border-bottom:2px solid #333;">Senast</th>
              <th style="text-align:right;padding:6px 10px;border-bottom:2px solid #333;">Stängn-1</th>
              <th style="text-align:right;padding:6px 10px;border-bottom:2px solid #333;">Värde</th>
              <th style="text-align:right;padding:6px 10px;border-bottom:2px solid #333;">Δ idag</th>
            </tr>
          </thead>
          <tbody>
            {''.join(html_rows)}
          </tbody>
        </table>

        <div style="margin-top:12px;">
          <div><strong>Totalt värde:</strong> {fmt_money(total_value, BASE_CCY)}</div>
          <div><strong>Förändring vs föregående stängning:</strong> {total_change_html}</div>
          {fx_line}
        </div>

        {warn_html}

        <div style="margin-top:14px;color:#666;font-size:12px;">
          (Mailet skickas även som ren text om din klient skulle visa tabeller konstigt.)
        </div>
      </body>
    </html>
    """

    return subject, body_text, body_html


# =========================
# Send email
# =========================
def send_email(subject: str, body_text: str, body_html: str) -> None:
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

    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


# =========================
# Main
# =========================
def main() -> int:
    holdings = load_holdings()
    rows, missing, fxmap = compute_rows(holdings)
    subject, body_text, body_html = build_subject_and_bodies(rows, missing, fxmap)

    # Logg i Actions
    print(subject)
    if missing:
        print("[WARN] Missing price data for:", ", ".join(missing))

    send_email(subject, body_text, body_html)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
