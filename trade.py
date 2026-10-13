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

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from typing import Any

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


def parse_shares(raw: Any) -> int:
    try:
        v = float(str(raw).strip().replace(",", ".").replace(" ", ""))
    except Exception:
        raise ValueError(f"Antal måste vara ett tal, fick '{raw}'.")
    if v < 0 or abs(v - round(v)) > 1e-9:
        raise ValueError(f"Antal måste vara ett heltal (0 eller större), fick '{raw}'.")
    return int(round(v))


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


def apply_trade(
    holdings: list[dict[str, Any]],
    action: str,
    symbol: str,
    shares: Any,
    name: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returnerar (nya innehav, info om affären). Ändrar inte listan som skickas in.
    """
    action = normalize_action(action)
    symbol = (symbol or "").strip().upper()
    name = (name or "").strip()
    qty = parse_shares(shares)

    if not symbol:
        raise ValueError("Symbol får inte vara tom.")
    if action in ("kop", "salj") and qty == 0:
        raise ValueError("Antal måste vara större än 0 vid köp/sälj.")

    holdings = [dict(h) for h in holdings]
    existing = next((h for h in holdings if str(h["symbol"]).upper() == symbol), None)
    before = int(existing["shares"]) if existing else 0

    if action == "kop":
        after = before + qty
    elif action == "salj":
        if qty > before:
            raise ValueError(f"Kan inte sälja {qty} st {symbol} – innehavet är {before} st.")
        after = before - qty
    else:
        after = qty

    if existing:
        if name:
            existing["name"] = name
        existing["shares"] = after
        if after == 0:
            holdings.remove(existing)
        name = existing["name"]
    elif after > 0:
        name = name or symbol
        holdings.append({"name": name, "symbol": symbol, "shares": after})
    else:
        name = name or symbol

    info = {
        "action": action,
        "symbol": symbol,
        "name": name,
        "qty": qty,
        "before": before,
        "after": after,
    }
    return holdings, info


def default_log_path(holdings_path: str) -> str:
    base = os.path.splitext(holdings_path)[0]
    if base.endswith("_holdings"):
        base = base[: -len("_holdings")]
    return f"{base}_trades.csv"


def append_log(log_path: str, info: dict[str, Any]) -> None:
    new_file = not os.path.exists(log_path)
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["datum", "åtgärd", "symbol", "namn", "antal", "före", "efter"])
        w.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            ACTIONS[info["action"]],
            info["symbol"],
            info["name"],
            info["qty"],
            info["before"],
            info["after"],
        ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Registrera köp/sälj i en innehavsfil.")
    p.add_argument("--file", default="altie_holdings.json", help="Innehavsfil (JSON)")
    p.add_argument("--action", required=True, help="köp, sälj eller sätt")
    p.add_argument("--symbol", required=True, help="Yahoo-symbol, t.ex. VOLV-B.ST")
    p.add_argument("--shares", required=True, help="Antal aktier")
    p.add_argument("--name", default="", help="Bolagsnamn (krävs i praktiken för nya innehav)")
    p.add_argument("--log", default=None, help="Loggfil (CSV). Default: <fil>_trades.csv")
    args = p.parse_args(argv)

    try:
        holdings = load_holdings(args.file)
        holdings, info = apply_trade(holdings, args.action, args.symbol, args.shares, args.name)
    except ValueError as e:
        print(f"FEL: {e}", file=sys.stderr)
        return 1

    save_holdings(args.file, holdings)
    append_log(args.log or default_log_path(args.file), info)

    print(
        f"{ACTIONS[info['action']]} {info['name']} ({info['symbol']}): "
        f"{info['before']} st -> {info['after']} st"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
