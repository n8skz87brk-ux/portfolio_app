import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ------------------------------------------------------------
# DEBUG PRINTS (Test 2)
# ------------------------------------------------------------
print("STARTAR GUI (holdings_gui.py laddas)")

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
        return int(v)
    except Exception:
        return default


class HoldingsApp(tk.Tk):
    def __init__(self, holdings_path: str = DEFAULT_HOLDINGS_FILE):
        print("INNE I HoldingsApp.__init__ (skapar Tk-root)")
        super().__init__()

        self.title("Holdings – Lägg till / Ändra / Ta bort")
        self.geometry("850x420")

        self.holdings_path = holdings_path
        self.holdings: list[dict] = load_holdings(self.holdings_path)

        # UI
        self._build_ui()
        self._refresh_table()

        # If window opens behind other apps, this helps a bit
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
        self.tree.heading("name", text="Namn")
        self.tree.heading("symbol", text="Symbol")
        self.tree.heading("shares", text="Antal")

        self.tree.column("name", width=380, anchor="w")
        self.tree.column("symbol", width=160, anchor="w")
        self.tree.column("shares", width=120, anchor="e")

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
            text="Tips: Dubbelklicka på en rad för att ändra. Spara skriver till holdings.json.",
        ).pack(side="left")

    def _refresh_table(self):
        # clear
        for item in self.tree.get_children():
            self.tree.delete(item)

        # insert
        for idx, h in enumerate(self.holdings):
            self.tree.insert("", "end", iid=str(idx), values=(h.get("name", ""), h.get("symbol", ""), h.get("shares", 0)))

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

        symbol = simpledialog.askstring(title, "Symbol (t.ex. CAMX.ST):", initialvalue=initial.get("symbol", ""), parent=self)
        if symbol is None:
            return None

        shares_str = simpledialog.askstring(title, "Antal (heltal):", initialvalue=str(initial.get("shares", 0)), parent=self)
        if shares_str is None:
            return None

        h = {
            "name": (name or "").strip(),
            "symbol": normalize_symbol(symbol),
            "shares": safe_int(shares_str, 0),
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

        # reselect
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
        # sort to make file stable (optional): by name then symbol
        holdings_sorted = sorted(self.holdings, key=lambda x: (x.get("name", ""), x.get("symbol", "")))

        try:
            save_holdings(self.holdings_path, holdings_sorted)
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara: {e}")
            return

        self.holdings = holdings_sorted
        self._refresh_table()
        messagebox.showinfo("Sparat", f"Sparade {len(self.holdings)} innehav till {self.holdings_path}.")


if __name__ == "__main__":
    print("INNE I MAIN (ska starta mainloop)")
    app = HoldingsApp()
    app.mainloop()
