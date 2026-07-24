"""
Desktop GUI: enter all field values once, pick how many virtual cards to
create, click "Create Cards" -- it fills the form that many times and
saves each card's details to MongoDB.

REQUIRES launch_browser.py to already be running and logged in.

Usage:
    python gui.py
"""

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from automate import CONFIG_PATH, run_batch

FIELDS = [
    ("description", "Description"),
    ("min_transaction_amount", "Minimum Transaction Amount"),
    ("max_transaction_amount", "Maximum Transaction Amount"),
    ("start_date", "Start Date (DD/MM/YYYY)"),
    ("end_date", "End Date (DD/MM/YYYY)"),
    ("cumulative_limit", "Cumulative Limit"),
    ("max_transactions", "Maximum Number of Transactions"),
    ("first_name", "First Name"),
    ("last_name", "Last Name"),
    ("user_email", "User Email"),
    ("user_country_code", "User Country Code (e.g. India +91)"),
    ("user_mobile_number", "User Mobile Number"),
]


def load_saved_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Virtual Card Creator")
        root.geometry("560x720")

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.entries: dict[str, tk.Entry] = {}
        self.worker_thread: threading.Thread | None = None

        saved = load_saved_config()
        today = datetime.now().strftime("%d/%m/%Y")
        defaults = {
            "start_date": today,
            "end_date": saved.get("end_date", "21/07/2028"),
        }

        form = ttk.Frame(root, padding=12)
        form.pack(fill="x")

        for row, (key, label) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(form, width=36)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            entry.insert(0, saved.get(key, defaults.get(key, "")))
            self.entries[key] = entry
        form.columnconfigure(1, weight=1)

        count_row = len(FIELDS)
        ttk.Label(form, text="How many cards to create").grid(
            row=count_row, column=0, sticky="w", pady=(10, 3)
        )
        self.count_entry = ttk.Entry(form, width=10)
        self.count_entry.grid(row=count_row, column=1, sticky="w", pady=(10, 3))
        self.count_entry.insert(0, "1")

        self.create_btn = ttk.Button(root, text="Create Cards", command=self.on_create)
        self.create_btn.pack(pady=8)

        log_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="Log").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=14, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

        self.root.after(100, self.poll_log_queue)

    def append_log(self, message: str) -> None:
        self.log_queue.put(message)

    def poll_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def collect_config(self) -> dict:
        return {key: entry.get().strip() for key, entry in self.entries.items()}

    def on_create(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Busy", "Already creating cards, please wait.")
            return

        cfg = self.collect_config()
        missing = [label for key, label in FIELDS if not cfg[key]]
        if missing:
            messagebox.showerror("Missing fields", "Please fill in:\n" + "\n".join(missing))
            return

        try:
            count = int(self.count_entry.get().strip())
            if count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid count", "Number of cards must be a positive integer.")
            return

        # Persist for next time (excludes start_date -- that should always
        # default to "today" on next launch, not whatever was last used).
        to_save = {k: v for k, v in cfg.items() if k != "start_date"}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2)

        self.create_btn.configure(state="disabled")
        self.worker_thread = threading.Thread(
            target=self.run_worker, args=(cfg, count), daemon=True
        )
        self.worker_thread.start()

    def run_worker(self, cfg: dict, count: int) -> None:
        try:
            run_batch(cfg, count, log=self.append_log)
            self.append_log(f"Done. Created {count} card(s). Saved to the database.")
        except Exception as e:
            self.append_log(f"Failed: {e}")
        finally:
            self.root.after(0, lambda: self.create_btn.configure(state="normal"))


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
