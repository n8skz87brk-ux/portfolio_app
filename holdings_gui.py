import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

HOLDINGS_FILE = "holdings.json"


def load_holdings() -> list[dict]:
    if not os.path.exists(HOLDINGS_FILE):
        return []
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        # Normalisera keys + typer
        out = []
        for h in data:
            if not isinstance(h, dict):
                continue
            name = str(h.get("name", "")).strip()
            symbol = str(h.get("symbol", "")).strip()
            shares = h.get("shares", 0)
            try:
                shares = int(shares)
            except Exception:
                shares = 0
            if name and symbol:
                out.append({"name": name, "symbol": symbol, "shares": shares})
        return out
    except Exception:
        return []


def save_holdings(holdings: list[dict]) -> None:
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(holdings, f, ensure_ascii=False, indent=2)


class HoldingsApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Innehav – Portfölj")
        self.geometry("820x520")
        self.minsize(760, 420)

        # lite snyggare radhöjd
        style = ttk.Style()
        style.configure("Treeview", rowheight=24)

        self.holdings = load_holdings()

        # sort-state
        self.sort_state = {"col": None, "descending": False}

        self._build_ui()
        self._refresh_table()

    # ---------------- UI ----------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(fill="x")

        self.lbl_file = ttk.Label(top, text=f"Fil: {HOLDINGS_FILE}", font=("", 10, "bold"))
        self.lbl_file.pack(side="left")

        btns = ttk.Frame(top)
        btns.pack(side="right")

        ttk.Button(btns, text="Lägg till", command=self.add_dialog).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Ändra", command=self.edit_dialog).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Ta bort", command=self.delete_row).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Spara", command=self.save).pack(side="left")

        mid = ttk.Frame(self, padding=10)
        mid.pack(fill="both", expand=True)

        cols = ("name", "symbol", "shares")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)

        # Rubriker (klickbara för sortering)
        self.tree.heading("name", text="Namn", command=lambda: self.sort_by("name"))
        self.tree.heading("symbol", text="Symbol", command=lambda: self.sort_by("symbol"))
        self.tree.heading("shares", text="Antal", command=lambda: self.sort_by("shares"))

        # Snyggare kolumner
        self.tree.column("name", width=360, anchor="w", stretch=True)
        self.tree.column("symbol", width=160, anchor="w", stretch=False)
        self.tree.column("shares", width=100, anchor="e", stretch=False)

        # Dubbelklick = ändra
        self.tree.bind("<Double-1>", lambda _e: self.edit_dialog())

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="Tips: Dubbelklicka på en rad för att ändra. Klicka på rubrikerna för att sortera. "
                 "Spara skriver till holdings.json.",
            foreground="#666",
        ).pack(side="left")

    # ---------------- Helpers ----------------
    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        try:
            return int(iid)
        except Exception:
            return None

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())

        for idx, h in enumerate(self.holdings):
            shares_txt = f"{h['shares']} st"
            self.tree.insert("", "end", iid=str(idx), values=(h["name"], h["symbol"], shares_txt))

        self._update_header_arrows()

    def _update_header_arrows(self):
        # Sätt pilar på sortkolumnen
        col = self.sort_state["col"]
        desc = self.sort_state["descending"]
        arrow = " ↓" if desc else " ↑"

        def txt(base, key):
            return base + (arrow if col == key else "")

        self.tree.heading("name", text=txt("Namn", "name"), command=lambda: self.sort_by("name"))
        self.tree.heading("symbol", text=txt("Symbol", "symbol"), command=lambda: self.sort_by("symbol"))
        self.tree.heading("shares", text=txt("Antal", "shares"), command=lambda: self.sort_by("shares"))

    def _select_all(self, entry: ttk.Entry):
        entry.focus_set()
        entry.selection_range(0, "end")
        entry.icursor("end")

    def _bind_flow(self, dialog, e_name, e_symbol, e_shares):
        # Enter: hoppa mellan fält
        e_name.bind("<Return>", lambda _e: self._select_all(e_symbol))
        e_symbol.bind("<Return>", lambda _e: self._select_all(e_shares))
        e_shares.bind("<Return>", lambda _e: dialog.focus_set())

        # FocusIn: markera allt (så du kan skriva direkt och ersätta)
        e_symbol.bind("<FocusIn>", lambda _e: e_symbol.selection_range(0, "end"))
        e_shares.bind("<FocusIn>", lambda _e: e_shares.selection_range(0, "end"))

    # ---------------- Actions ----------------
    def sort_by(self, col: str):
        prev_col = self.sort_state["col"]
        if prev_col == col:
            self.sort_state["descending"] = not self.sort_state["descending"]
        else:
            self.sort_state["col"] = col
            self.sort_state["descending"] = False

        desc = self.sort_state["descending"]

        if col in ("name", "symbol"):
            self.holdings.sort(key=lambda x: x[col].lower(), reverse=desc)
        else:
            self.holdings.sort(key=lambda x: int(x.get(col, 0)), reverse=desc)

        self._refresh_table()

    def add_dialog(self):
        self._open_edit_dialog(title="Lägg till innehav", initial={"name": "", "symbol": "", "shares": ""})

    def edit_dialog(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Ändra", "Markera en rad först.")
            return
        h = self.holdings[idx]
        self._open_edit_dialog(
            title="Ändra innehav",
            initial={"name": h["name"], "symbol": h["symbol"], "shares": str(h["shares"])},
            idx=idx,
        )

    def _open_edit_dialog(self, title: str, initial: dict, idx: int | None = None):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        frm = ttk.Frame(dialog, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Namn").grid(row=0, column=0, sticky="w")
        e_name = ttk.Entry(frm, width=45)
        e_name.grid(row=1, column=0, sticky="we", padx=(0, 10), pady=(0, 10))

        ttk.Label(frm, text="Symbol").grid(row=0, column=1, sticky="w")
        e_symbol = ttk.Entry(frm, width=20)
        e_symbol.grid(row=1, column=1, sticky="we", pady=(0, 10))

        ttk.Label(frm, text="Antal").grid(row=2, column=0, sticky="w")
        e_shares = ttk.Entry(frm, width=12, justify="right")
        e_shares.grid(row=3, column=0, sticky="w", pady=(0, 10))

        # Fyll initiala värden
        e_name.insert(0, initial.get("name", ""))
        e_symbol.insert(0, initial.get("symbol", ""))
        e_shares.insert(0, initial.get("shares", ""))  # tomt är bättre än "0"

        # Bind fokusflöde (det du ville fixa)
        self._bind_flow(dialog, e_name, e_symbol, e_shares)
        dialog.after(80, lambda: self._select_all(e_name))

        btnbar = ttk.Frame(frm)
        btnbar.grid(row=4, column=0, columnspan=2, sticky="e")

        def on_ok():
            name = e_name.get().strip()
            symbol = e_symbol.get().strip()
            shares_raw = e_shares.get().strip()

            if not name:
                messagebox.showerror("Fel", "Namn får inte vara tomt.")
                self._select_all(e_name)
                return
            if not symbol:
                messagebox.showerror("Fel", "Symbol får inte vara tomt.")
                self._select_all(e_symbol)
                return

            try:
                shares = int(shares_raw) if shares_raw != "" else 0
                if shares < 0:
                    raise ValueError()
            except Exception:
                messagebox.showerror("Fel", "Antal måste vara ett heltal (0 eller större).")
                self._select_all(e_shares)
                return

            new_item = {"name": name, "symbol": symbol, "shares": shares}

            if idx is None:
                self.holdings.append(new_item)
            else:
                self.holdings[idx] = new_item

            self._refresh_table()
            dialog.destroy()

        ttk.Button(btnbar, text="Avbryt", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btnbar, text="OK", command=on_ok).pack(side="right")

        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def delete_row(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Ta bort", "Markera en rad först.")
            return

        h = self.holdings[idx]
        if not messagebox.askyesno("Ta bort", f"Ta bort '{h['name']}'?"):
            return

        self.holdings.pop(idx)
        self._refresh_table()

    def save(self):
        # sortera stabilt vid spar (valfritt)
        holdings_sorted = sorted(self.holdings, key=lambda x: (x["name"].lower(), x["symbol"].lower()))
        try:
            save_holdings(holdings_sorted)
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara: {e}")
            return

        self.holdings = holdings_sorted
        self._refresh_table()
        messagebox.showinfo("Sparat", f"Sparade {len(self.holdings)} rader till {HOLDINGS_FILE}.")


if __name__ == "__main__":
    app = HoldingsApp()
    app.mainloop()
