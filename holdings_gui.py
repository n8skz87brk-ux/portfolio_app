import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ------------------------------------------------------------
# Settings / file paths
# ------------------------------------------------------------
DEFAULT_HOLDINGS_FILE = "holdings.json"


def load_holdings(path: str) -> list[dict]:
    """Load holdings from JSON file. If missing, return an empty list."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
        return []


def save_holdings(path: str, holdings: list[dict]) -> None:
    """Save holdings to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(holdings, f, ensure_ascii=False, indent=2)


def normalize_symbol(s: str) -> str:
    return (s or "").strip().upper()


def safe_int(v, default=0) -> int:
    try:
        # tillåt "1 234" och "1,234" och "1.234"
        s = str(v).strip().replace(" ", "").replace(",", "").replace(".", "")
        return int(s)
    except Exception:
        return default


def format_int_sv(n: int) -> str:
    """Format 1234567 -> '1 234 567' (svensk tusentalsavgräns)."""
    try:
        s = f"{int(n):,}".replace(",", " ")
        return s
    except Exception:
        return str(n)


class HoldingsApp(tk.Tk):
    def __init__(self, holdings_path: str = DEFAULT_HOLDINGS_FILE):
        super().__init__()

        self.title("Innehav – Portfölj")
        self.geometry("900x460")

        self.holdings_path = holdings_path
        self.holdings: list[dict] = load_holdings(self.holdings_path)

        # sort state: {"col": "name", "descending": False}
        self.sort_state = {"col": None, "descending": False}

        self._build_ui()
        self._refresh_table()

        # Hjälper om fönstret öppnas bakom andra
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text=f"Fil: {self.holdings_path}").pack(side="left")

        btns = ttk.Frame(top)
        btns.pack(side="right")

        ttk.Button(btns, text="Lägg till", command=self.add_row).pack(side="left", padx=4)
        ttk.Button(btns, text="Ändra", command=self.edit_row).pack(side="left", padx=4)
        ttk.Button(btns, text="Ta bort", command=self.delete_row).pack(side="left", padx=4)
        ttk.Button(btns, text="Spara", command=self.save).pack(side="left", padx=4)

        # Table
        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.pack(fill="both", expand=True)

        cols = ("name", "symbol", "shares")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")

        # Headings with click-to-sort
        self.tree.heading("name", text="Namn", command=lambda: self.sort_by("name"))
        self.tree.heading("symbol", text="Symbol", command=lambda: self.sort_by("symbol"))
        self.tree.heading("shares", text="Antal", command=lambda: self.sort_by("shares"))

        # Column formatting
        self.tree.column("name", width=420, anchor="w")
        self.tree.column("symbol", width=180, anchor="w")
        self.tree.column("shares", width=140, anchor="e")  # högerjusterat för siffror

        self.tree.pack(fill="both", expand=True, side="left")

        # Scrollbar
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.pack(fill="y", side="right")

        # Double click = edit
        self.tree.bind("<Double-1>", lambda _e: self.edit_row())

        # Bottom help
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="Tips: Dubbelklicka på en rad för att ändra. Klicka på rubrikerna för att sortera. Spara skriver till holdings.json.",
        ).pack(side="left")

    def _refresh_table(self):
        # clear
        for item in self.tree.get_children():
            self.tree.delete(item)

        # insert
        for idx, h in enumerate(self.holdings):
            name = h.get("name", "")
            symbol = h.get("symbol", "")
            shares_val = safe_int(h.get("shares", 0), 0)
            shares_str = f"{format_int_sv(shares_val)} st"
            self.tree.insert("", "end", iid=str(idx), values=(name, symbol, shares_str))

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _prompt_holding(self, title: str, initial: dict | None = None) -> dict | None:
        initial = initial or {}

        name = simpledialog.askstring(title, "Namn:", initialvalue=initial.get("name", ""), parent=self)
        if name is None:
            return None

        symbol = simpledialog.askstring(
            title,
            "Symbol (t.ex. CAMX.ST):",
            initialvalue=initial.get("symbol", ""),
            parent=self,
        )
        if symbol is None:
            return None

        shares_str = simpledialog.askstring(
            title,
            "Antal (heltal):",
            initialvalue=str(initial.get("shares", 0)),
            parent=self,
        )
        if shares_str is None:
            return None

        shares = safe_int(shares_str, 0)

        h = {
            "name": (name or "").strip(),
            "symbol": normalize_symbol(symbol),
            "shares": shares,
        }
        return h

    def add_row(self):
        h = self._prompt_holding("Lägg till innehav")
        if not h:
            return
        self.holdings.append(h)
        self._refresh_table()

    def edit_row(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Välj rad", "Markera en rad först.")
            return

        current = self.holdings[idx]
        h = self._prompt_holding("Ändra innehav", initial=current)
        if not h:
            return
        self.holdings[idx] = h
        self._refresh_table()

        # reselect best effort (same index after refresh)
        try:
            self.tree.selection_set(str(idx))
        except Exception:
            pass

    def delete_row(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Välj rad", "Markera en rad först.")
            return

        h = self.holdings[idx]
        if not messagebox.askyesno("Ta bort", f"Ta bort '{h.get('name','')}'?"):
            return

        self.holdings.pop(idx)
        self._refresh_table()

    def save(self):
        # Keep file stable: sort by name then symbol when saving
        holdings_sorted = sorted(self.holdings, key=lambda x: (str(x.get("name", "")).lower(), str(x.get("symbol", "")).lower()))

        try:
            save_holdings(self.holdings_path, holdings_sorted)
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara: {e}")
            return

        self.holdings = holdings_sorted
        self.sort_state = {"col": None, "descending": False}  # reset sort indicator
        self._refresh_table()
        messagebox.showinfo("Sparat", f"Sparade {len(self.holdings)} innehav till {self.holdings_path}.")

    def sort_by(self, col: str):
        # Toggle descending if clicking same column
        if self.sort_state["col"] == col:
            descending = not self.sort_state["descending"]
        else:
            descending = False

        def key_name(x): return str(x.get("name", "")).lower()
        def key_symbol(x): return str(x.get("symbol", "")).lower()
        def key_shares(x): return safe_int(x.get("shares", 0), 0)

        if col == "name":
            key_fn = key_name
        elif col == "symbol":
            key_fn = key_symbol
        else:
            key_fn = key_shares

        self.holdings = sorted(self.holdings, key=key_fn, reverse=descending)
        self.sort_state = {"col": col, "descending": descending}

        # Update header text with arrow
        self._update_header_arrows()
        self._refresh_table()

    def _update_header_arrows(self):
        # Reset
        self.tree.heading("name", text="Namn", command=lambda: self.sort_by("name"))
        self.tree.heading("symbol", text="Symbol", command=lambda: self.sort_by("symbol"))
        self.tree.heading("shares", text="Antal", command=lambda: self.sort_by("shares"))

        col = self.sort_state["col"]
        if not col:
            return
        arrow = " ↓" if self.sort_state["descending"] else " ↑"

        if col == "name":
            self.tree.heading("name", text="Namn" + arrow, command=lambda: self.sort_by("name"))
        elif col == "symbol":
            self.tree.heading("symbol", text="Symbol" + arrow, command=lambda: self.sort_by("symbol"))
        elif col == "shares":
            self.tree.heading("shares", text="Antal" + arrow, command=lambda: self.sort_by("shares"))


if __name__ == "__main__":
    app = HoldingsApp()
    app.mainloop()
