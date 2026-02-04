# portfolio_cloud.py
# Sends a daily portfolio email (HTML + text) with clean layout:
# - No ticker in table
# - Only value, change SEK, change %
# - Whole kronor (no ören)
# - SEK shown only in summary
# - Blue for up, red for down (HTML)

from __future__ import annotations

import os
import sys
from datetime import datetime
import smtplib
from email.message import EmailMessage
from typing import Any

import yfinance as yf


# -----------------------------
# 1) EDIT YOUR HOLDINGS HERE
# -----------------------------
# Use Yahoo Finance symbols. Examples:
#   Swedish stocks: "ERIC-B.ST", "CAMX.ST"
#   US stocks: "AAPL"
HOLDINGS = [
    {"name": "Camurus", "symbol": "CAMX.ST", "shares": 16},
    {"name": "Nelly Group", "symbol": "NELLY.ST", "shares": 98},
    # {"name": "Ericsson B", "symbol": "ERIC-B.ST", "shares": 120},
]


# -----------------------------
# 2) EMAIL / SMTP SETTINGS
# -----------------------------
# Set these as GitHub Secrets (recommended):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587").strip() or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
MAIL_TO = os.getenv("MAIL_TO", "").strip()

# Optional:
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER).strip() or SMTP_USER
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "Portföljrapport").strip()


# -----------------------------
# Formatting helpers
# -----------------------------
def _fmt_int(x: Any) -> str:
    """Whole kronor, Swedish-style spacing; no SEK."""
    try:
        s = f"{float(x):,.0f}"  # 12,345
    except (TypeError, ValueError):
        return "-"
    return s.replace(",", " ")  # 12 345


def _fmt_pct(x: Any, decimals: int = 1) -> str:
    """Signed percent with decimals."""
    try:
        return f"{float(x):+.{decimals}f}%"
    except (TypeError, ValueError):
        return "-"


def _color_for_change(change_kr: Any) -> str:
    """Blue for up, red for down, neutral for 0/None."""
    try:
        c = float(change_kr)
    except (TypeError, ValueError):
        return "#333333"
    if c > 0:
        return "#0b63c7"  # blue
    if c < 0:
        return "#c4001a"  # red
    return "#333333"


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


# -----------------------------
# Market data
# -----------------------------
def fetch_quote(symbol: str) -> dict[str, float | None]:
    """
    Returns:
      price: current/last price (regularMarketPrice or last close)
      prev_close: previous close (previousClose)
    """
    t = yf.Ticker(symbol)
    info = {}
    try:
        info = t.fast_info or {}
    except Exception:
        info = {}

    price = _safe_float(info.get("last_price") or info.get("lastPrice") or info.get("regularMarketPrice"))
    prev_close = _safe_float(info.get("previous_close") or info.get("previousClose"))

    # Fallbacks via .info (slower but sometimes necessary)
    if price is None or prev_close is None:
        try:
            i = t.info or {}
        except Exception:
            i = {}
        if price is None:
            price = _safe_float(i.get("regularMarketPrice") or i.get("currentPrice"))
        if prev_close is None:
            prev_close = _safe_float(i.get("previousClose"))

    # Last resort: use last close from history (and prev close as the one before)
    if price is None or prev_close is None:
        try:
            hist = t.history(period="5d")
            if not hist.empty:
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    price = price if price is not None else float(closes.iloc[-1])
                    prev_close = prev_close if prev_close is not None else float(closes.iloc[-2])
        except Exception:
            pass

    return {"price": price, "prev_close": prev_close}


# -----------------------------
# HTML Builder (your required layout)
# -----------------------------
def build_portfolio_email_html(
    *,
    rows: list[dict[str, Any]],
    total_value_sek: float,
    total_change_sek: float,
    total_change_pct: float,
    title: str,
    asof_text: str,
) -> str:
    total_value_txt = f"{_fmt_int(total_value_sek)} SEK"
    total_change_txt = f"{_fmt_int(total_change_sek)} SEK ({_fmt_pct(total_change_pct, decimals=1)})"
    total_color = _color_for_change(total_change_sek)

    rows_sorted = sorted(rows, key=lambda r: (r.get("value_sek") or 0), reverse=True)

    tr_html: list[str] = []
    for r in rows_sorted:
        name = r.get("name", "-")
        value = r.get("value_sek", None)
        chg = r.get("change_sek", None)
        pct = r.get("change_pct", None)

        chg_color = _color_for_change(chg)

        tr_html.append(
            f"""
            <tr>
              <td style="padding:10px 12px; border-bottom:1px solid #e7e7e7; font-family:Arial,sans-serif; font-size:14px;">
                {name}
              </td>
              <td style="padding:10px 12px; border-bottom:1px solid #e7e7e7; text-align:right; font-family:Arial,sans-serif; font-size:14px;">
                {_fmt_int(value)}
              </td>
              <td style="padding:10px 12px; border-bottom:1px solid #e7e7e7; text-align:right; font-family:Arial,sans-serif; font-size:14px; color:{chg_color}; font-weight:600;">
                {_fmt_int(chg)}
              </td>
              <td style="padding:10px 12px; border-bottom:1px solid #e7e7e7; text-align:right; font-family:Arial,sans-serif; font-size:14px; color:{chg_color}; font-weight:600;">
                {_fmt_pct(pct, decimals=1)}
              </td>
            </tr>
            """
        )

    table_html = f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"
           style="border-collapse:collapse; border:1px solid #e7e7e7; border-radius:10px; overflow:hidden;">
      <thead>
        <tr style="background:#f6f7f9;">
          <th align="left"  style="padding:10px 12px; font-family:Arial,sans-serif; font-size:13px; color:#333; border-bottom:1px solid #e7e7e7;">Bolag</th>
          <th align="right" style="padding:10px 12px; font-family:Arial,sans-serif; font-size:13px; color:#333; border-bottom:1px solid #e7e7e7;">Värde</th>
          <th align="right" style="padding:10px 12px; font-family:Arial,sans-serif; font-size:13px; color:#333; border-bottom:1px solid #e7e7e7;">Förändring</th>
          <th align="right" style="padding:10px 12px; font-family:Arial,sans-serif; font-size:13px; color:#333; border-bottom:1px solid #e7e7e7;">%</th>
        </tr>
      </thead>
      <tbody>
        {''.join(tr_html) if tr_html else '<tr><td colspan="4" style="padding:12px;font-family:Arial,sans-serif;">Inga innehav.</td></tr>'}
      </tbody>
    </table>
    """

    html = f"""
    <div style="max-width:760px; margin:0 auto; padding:6px 10px;">
      <div style="font-family:Arial,sans-serif;">
        <h2 style="margin:10px 0 4px 0; font-size:18px; color:#111;">{title}</h2>
        <div style="margin:0 0 12px 0; font-size:12px; color:#666;">{asof_text}</div>

        <div style="margin:0 0 14px 0; padding:12px 14px; border:1px solid #e7e7e7; border-radius:10px; background:#ffffff;">
          <div style="font-size:13px; color:#666; margin-bottom:6px;">Sammanfattning</div>
          <div style="font-size:14px; color:#111; line-height:1.6;">
            <div><b>Totalt värde:</b> {total_value_txt}</div>
            <div><b>Förändring:</b> <span style="color:{total_color}; font-weight:700;">{total_change_txt}</span></div>
          </div>
        </div>

        {table_html}

        <div style="margin-top:10px; font-size:12px; color:#777; font-family:Arial,sans-serif;">
          (Hela kronor. Färg: blå = upp, röd = ner.)
        </div>
      </div>
    </div>
    """
    return html


def build_portfolio_email_text(
    *,
    rows: list[dict[str, Any]],
    total_value_sek: float,
    total_change_sek: float,
    total_change_pct: float,
    title: str,
    asof_text: str,
) -> str:
    lines = [title, asof_text, ""]
    lines.append(f"Totalt värde: { _fmt_int(total_value_sek) } SEK")
    lines.append(f"Förändring:  { _fmt_int(total_change_sek) } SEK ({ _fmt_pct(total_change_pct, 1) })")
    lines.append("")
    lines.append("Bolag | Värde | Förändring | %")
    lines.append("-" * 55)
    for r in sorted(rows, key=lambda r: (r.get("value_sek") or 0), reverse=True):
        lines.append(
            f"{r.get('name','-')} | {_fmt_int(r.get('value_sek'))} | {_fmt_int(r.get('change_sek'))} | {_fmt_pct(r.get('change_pct'),1)}"
        )
    return "\n".join(lines)


# -----------------------------
# Email send
# -----------------------------
def send_email(subject: str, html_body: str, text_body: str) -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and MAIL_TO):
        raise RuntimeError(
            "Missing SMTP settings. Ensure SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO are set as env/secrets."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        if SMTP_PORT in (587, 25):
            server.starttls()
            server.ehlo()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


# -----------------------------
# Main logic
# -----------------------------
def compute_portfolio(holdings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float, float]:
    rows: list[dict[str, Any]] = []

    total_value = 0.0
    total_prev_value = 0.0

    for h in holdings:
        name = str(h.get("name", "")).strip()
        symbol = str(h.get("symbol", "")).strip()
        shares = _safe_float(h.get("shares")) or 0.0

        if not name or not symbol or shares == 0:
            continue

        q = fetch_quote(symbol)
        price = q["price"]
        prev_close = q["prev_close"]

        # If we can't get prices, skip row but keep going
        if price is None or prev_close is None:
            rows.append(
                {
                    "name": name,
                    "value_sek": None,
                    "change_sek": None,
                    "change_pct": None,
                    "note": f"Kunde inte hämta kurs för {symbol}",
                }
            )
            continue

        value = shares * float(price)
        prev_value = shares * float(prev_close)
        change = value - prev_value
        change_pct = (change / prev_value * 100.0) if prev_value != 0 else 0.0

        total_value += value
        total_prev_value += prev_value

        rows.append(
            {
                "name": name,
                "value_sek": value,
                "change_sek": change,
                "change_pct": change_pct,
            }
        )

    total_change = total_value - total_prev_value
    total_change_pct = (total_change / total_prev_value * 100.0) if total_prev_value != 0 else 0.0

    return rows, total_value, total_change, total_change_pct


def main() -> None:
    now = datetime.now()  # GitHub Actions runner time is UTC by default unless you set TZ; subject includes date anyway
    date_str = now.strftime("%Y-%m-%d")
    title = f"{SUBJECT_PREFIX} – {date_str}"
    asof_text = f"Skapat: {now.strftime('%Y-%m-%d %H:%M')}"

    rows, total_value, total_change, total_change_pct = compute_portfolio(HOLDINGS)

    html_body = build_portfolio_email_html(
        rows=rows,
        total_value_sek=total_value,
        total_change_sek=total_change,
        total_change_pct=total_change_pct,
        title=title,
        asof_text=asof_text,
    )
    text_body = build_portfolio_email_text(
        rows=rows,
        total_value_sek=total_value,
        total_change_sek=total_change,
        total_change_pct=total_change_pct,
        title=title,
        asof_text=asof_text,
    )

    send_email(subject=title, html_body=html_body, text_body=text_body)
    print("OK: Email sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
