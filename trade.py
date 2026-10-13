# trade.py
# Registrera en affär (köp/sälj) eller sätt antal direkt i en innehavsfil.
#
# Exempel:
#   python trade.py --file altie_holdings.json --action kop  --symbol VOLV-B.ST --shares 10 --name "Volvo B"
#   python trade.py --file altie_holdings.json --action salj --symbol VOLV-B.ST --shares 4
#   python trade.py --file altie_holdings.json --action satt --symbol VOLV-B.ST --shares 25
#
# Säljer man allt (antal blir 0) tas raden bort. Varje affär loggas i en CSV
# (default: <fil>_trades.csv, t.ex. altie_trades.csv).
#
# Kontanter ligger som symbolen CASH ("Likvida medel", kurs 1 kr):
#   python trade.py --action satt --symbol CASH --shares 10654     # sätt saldo
#   python trade.py --action kop  --symbol CASH --shares 5000      # insättning
#   python trade.py --action salj --symbol CASH --shares 2000      # uttag
# Anges --amount vid köp/sälj av en aktie dras/läggs beloppet (inkl. courtage)
# automatiskt från/till kontanterna.

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from typing import Any

CASH_SYMBOL = "CASH"
CASH_NAME = "Likvida medel"

ACTIONS = {
    "kop": "Köp",
    "salj": "Sälj",
    "satt": "Sätt antal",
}

# Tillåt även svenska tecken och engelska ord som indata
_ACTION_ALIASES = {
    "köp": "kop", "kop": "kop", "buy": "kop",
    "sälj": "salj", "salj": "salj", "sell": "salj",
    "sätt": "satt", "satt": "satt", "set": "satt",
}


def normalize_action(action: str) -> str:
    a = (action or "").strip().lower()
    if a not in _ACTION_ALIASES:
        raise ValueError(f"Okänd åtgärd '{action}'. Använd köp, sälj eller sätt.")
    return _ACTION_ALIASES[a]


def parse_shares(raw: Any) -> int | float:
    """Heltal för aktier, upp till 6 decimaler för fondandelar."""
    try:
        v = float(str(raw).strip().replace(",", ".").replace(" ", ""))
    except Exception:
        raise ValueError(f"Antal måste vara ett tal, fick '{raw}'.")
    if v != v or v < 0:
        raise ValueError(f"Antal måste vara 0 eller större, fick '{raw}'.")
    return _clean_number(v)


def _clean_number(v: float) -> int | float:
    v = round(float(v), 6)
    return int(v) if v == int(v) else v


def fmt_shares(v: Any) -> str:
    return str(v).replace(".", ",")


def load_holdings(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("holdings", [])
    return [h for h in data if isinstance(h, dict) and h.get("symbol")]


def save_holdings(path: str, holdings: list[dict[str, Any]]) -> None:
    holdings = sorted(holdings, key=lambda x: (str(x["name"]).lower(), str(x["symbol"]).lower()))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(holdings, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _set_position(holdings: list[dict[str, Any]], symbol: str, name: str, after: int | float) -> str:
    """Sätter antal för symbol (tar bort raden vid 0). Returnerar namnet som gäller."""
    existing = next((h for h in holdings if str(h["symbol"]).upper() == symbol), None)
    if existing:
        if name:
            existing["name"] = name
        existing["shares"] = after
        if after == 0:
            holdings.remove(existing)
        return existing["name"]
    name = name or symbol
    if after != 0:
        holdings.append({"name": name, "symbol": symbol, "shares": after})
    return name


def _position(holdings: list[dict[str, Any]], symbol: str) -> int | float:
    h = next((h for h in holdings if str(h["symbol"]).upper() == symbol), None)
    return _clean_number(h["shares"]) if h else 0


def apply_trade(
    holdings: list[dict[str, Any]],
    action: str,
    symbol: str,
    shares: Any,
    name: str = "",
    amount: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returnerar (nya innehav, info om affären). Ändrar inte listan som skickas in.
    amount = affärens belopp i SEK inkl. courtage; justerar kontanterna (CASH)
    vid köp/sälj av andra värdepapper.
    """
    action = normalize_action(action)
    symbol = (symbol or "").strip().upper()
    name = (name or "").strip()
    qty = parse_shares(shares)
    if symbol == CASH_SYMBOL:
        name = name or CASH_NAME
    amt = None
    if amount is not None and str(amount).strip() != "":
        amt = parse_shares(amount)
        if symbol == CASH_SYMBOL or action == "satt":
            raise ValueError("Belopp kan bara anges vid köp/sälj av värdepapper.")

    if not symbol:
        raise ValueError("Symbol får inte vara tom.")
    if action in ("kop", "salj") and qty == 0:
        raise ValueError("Antal måste vara större än 0 vid köp/sälj.")

    holdings = [dict(h) for h in holdings]
    before = _position(holdings, symbol)

    if action == "kop":
        after = _clean_number(before + qty)
    elif action == "salj":
        if qty > before:
            raise ValueError(
                f"Kan inte sälja {fmt_shares(qty)} st {symbol} – innehavet är {fmt_shares(before)} st."
            )
        after = _clean_number(before - qty)
    else:
        after = qty

    name = _set_position(holdings, symbol, name, after)

    cash_before = cash_after = None
    if amt is not None:
        cash_before = _position(holdings, CASH_SYMBOL)
        delta = -amt if action == "kop" else amt
        cash_after = _clean_number(cash_before + delta)
        _set_position(holdings, CASH_SYMBOL, CASH_NAME, cash_after)

    info = {
        "action": action,
        "symbol": symbol,
        "name": name,
        "qty": qty,
        "before": before,
        "after": after,
        "amount": amt,
        "cash_before": cash_before,
        "cash_after": cash_after,
    }
    return holdings, info


def describe(info: dict[str, Any]) -> str:
    text = (
        f"{ACTIONS[info['action']]} {info['name']} ({info['symbol']}): "
        f"{fmt_shares(info['before'])} st -> {fmt_shares(info['after'])} st"
    )
    if info.get("amount") is not None:
        text += (
            f"\nBelopp {fmt_shares(info['amount'])} kr. Likvida medel: "
            f"{fmt_shares(info['cash_before'])} kr -> {fmt_shares(info['cash_after'])} kr"
        )
        if info["cash_after"] < 0:
            text += "\nVARNING: likvida medel är negativa – kontrollera saldot."
    return text


def default_log_path(holdings_path: str) -> str:
    base = os.path.splitext(holdings_path)[0]
    if base.endswith("_holdings"):
        base = base[: -len("_holdings")]
    return f"{base}_trades.csv"


LOG_HEADER = ["datum", "åtgärd", "symbol", "namn", "antal", "före", "efter", "belopp"]


def append_log(log_path: str, info: dict[str, Any]) -> None:
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if rows and rows[0] != LOG_HEADER:
            # Äldre logg utan beloppskolumn: skriv om med ny rubrik
            rows = [LOG_HEADER] + [r + [""] * (len(LOG_HEADER) - len(r)) for r in rows[1:]]
            with open(log_path, "w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(rows)
    new_file = not os.path.exists(log_path)
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(LOG_HEADER)
        w.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            ACTIONS[info["action"]],
            info["symbol"],
            info["name"],
            info["qty"],
            info["before"],
            info["after"],
            "" if info.get("amount") is None else info["amount"],
        ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Registrera köp/sälj i en innehavsfil.")
    p.add_argument("--file", default="altie_holdings.json", help="Innehavsfil (JSON)")
    p.add_argument("--action", required=True, help="köp, sälj eller sätt")
    p.add_argument("--symbol", required=True, help="Yahoo-symbol, t.ex. VOLV-B.ST")
    p.add_argument("--shares", required=True, help="Antal aktier/fondandelar (decimaler tillåtna)")
    p.add_argument("--name", default="", help="Bolagsnamn (krävs i praktiken för nya innehav)")
    p.add_argument("--amount", default="", help="Belopp i SEK inkl. courtage – justerar likvida medel")
    p.add_argument("--log", default=None, help="Loggfil (CSV). Default: <fil>_trades.csv")
    args = p.parse_args(argv)

    try:
        holdings = load_holdings(args.file)
        holdings, info = apply_trade(holdings, args.action, args.symbol, args.shares, args.name, args.amount)
    except ValueError as e:
        print(f"FEL: {e}", file=sys.stderr)
        return 1

    save_holdings(args.file, holdings)
    append_log(args.log or default_log_path(args.file), info)

    print(describe(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
