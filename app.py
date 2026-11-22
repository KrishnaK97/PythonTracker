"""
Bug Solution Tracker - desktop app.
Log a problem when you start on it, write the fix when you solve it, and the
app measures how long it took. Daily reports (.txt + .docx) are published to
the reports/ folder automatically at your end-of-day time and when you close.

Run:  python app.py   (or double-click run_tracker.bat)
"""
import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk, messagebox, simpledialog

import tracker_core as core

REFRESH_MS = 1000
AUTO_CHECK_MS = 30_000


class TrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bug Solution Tracker")
        self.geometry("1100x780")
        self.minsize(900, 640)

        self.store = core.IssueStore()
        self.cfg = core.load_config()
        self.last_auto_export = None  # date of last automatic end-of-day export

        self._style()
        self._build_ui()
        self.refresh_all()

        created = core.backfill_missing_reports(self.store.issues)
        if created:
            self.status(f"Published {len(created)} missed report(s) from previous days.")

        self.after(REFRESH_MS, self._tick)
        self.after(2000, self._auto_export_check)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------ UI
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            s.theme_use("clam")
        s.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#1F3864")
        s.configure("Sub.TLabel", font=("Segoe UI", 9), foreground="#595959")
        s.configure("Stat.TLabel", font=("Segoe UI", 11, "bold"), foreground="#2E75B6")
        s.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        s.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # header
        head = ttk.Frame(root)
        head.pack(fill="x")
        ttk.Label(head, text="Bug Solution Tracker", style="Header.TLabel").pack(side="left")
        self.clock_lbl = ttk.Label(head, style="Sub.TLabel")
        self.clock_lbl.pack(side="right")

        # toolbar
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(6, 8))
        ttk.Button(bar, text="Publish Today's Report", style="Accent.TButton",
                   command=self.export_today).pack(side="left")
        ttk.Button(bar, text="Publish Report for Date...",
                   command=self.export_for_date).pack(side="left", padx=6)
        ttk.Button(bar, text="Open Reports Folder",
                   command=lambda: self._open_path(core.REPORTS_DIR)).pack(side="left")
        ttk.Button(bar, text="Settings", command=self.settings).pack(side="right")

        panes = ttk.PanedWindow(root, orient="vertical")
        panes.pack(fill="both", expand=True)

        # ---- top: new issue + open issues
        top = ttk.Frame(panes)
        panes.add(top, weight=3)

        new = ttk.LabelFrame(top, text=" 1. Log a new issue (timer starts immediately) ",
                             padding=8)
        new.pack(fill="x")
        new.columnconfigure(1, weight=1)
        ttk.Label(new, text="Issue / error:").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        title_entry = ttk.Entry(new, textvariable=self.title_var)
        title_entry.grid(row=0, column=1, sticky="ew", padx=6)
        title_entry.bind("<Return>", lambda e: self.start_issue())
        ttk.Label(new, text="Category:").grid(row=0, column=2, sticky="w")
        self.cat_var = tk.StringVar(value=core.CATEGORIES[0])
        ttk.Combobox(new, textvariable=self.cat_var, values=core.CATEGORIES, width=16
                     ).grid(row=0, column=3, padx=6)
        ttk.Label(new, text="Priority:").grid(row=0, column=4, sticky="w")
        self.pri_var = tk.StringVar(value="Medium")
        ttk.Combobox(new, textvariable=self.pri_var, values=core.PRIORITIES, width=9,
                     state="readonly").grid(row=0, column=5, padx=6)
        ttk.Label(new, text="Details / stack\ntrace (optional):").grid(row=1, column=0,
                                                                       sticky="nw", pady=4)
        self.desc_txt = tk.Text(new, height=3, wrap="word", font=("Consolas", 9))
        self.desc_txt.grid(row=1, column=1, columnspan=4, sticky="ew", padx=6, pady=4)
        ttk.Button(new, text="▶  Start Timer", style="Accent.TButton",
                   command=self.start_issue).grid(row=1, column=5, sticky="nsew", padx=6,
                                                  pady=4)

        openf = ttk.LabelFrame(top, text=" 2. Issues in progress ", padding=8)
        openf.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("id", "title", "category", "priority", "started", "active", "status")
        self.open_tree = self._tree(openf, cols,
                                    ("#", "Issue", "Category", "Priority", "Started",
                                     "Time spent", "Status"),
                                    (40, 380, 110, 70, 130, 100, 80), height=5)
        self.open_tree.bind("<<TreeviewSelect>>", self._on_open_select)
        self.open_tree.bind("<Double-1>", lambda e: self._details(self.open_tree))
        btns = ttk.Frame(openf)
        btns.pack(fill="x", pady=(6, 0))
        self.pause_btn = ttk.Button(btns, text="⏸  Pause", command=self.toggle_pause)
        self.pause_btn.pack(side="left")
        ttk.Button(btns, text="Delete", command=self.delete_selected).pack(side="left", padx=6)
        self.selected_lbl = ttk.Label(btns, text="Select an issue to pause or solve it.",
                                      style="Sub.TLabel")
        self.selected_lbl.pack(side="left", padx=10)

        # ---- middle: solution
        mid = ttk.LabelFrame(panes, text=" 3. Record the solution for the selected issue ",
                             padding=8)
        panes.add(mid, weight=2)
        mid.columnconfigure(1, weight=1)
        ttk.Label(mid, text="Root cause\n(optional):").grid(row=0, column=0, sticky="nw")
        self.cause_txt = tk.Text(mid, height=2, wrap="word", font=("Segoe UI", 9))
        self.cause_txt.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        ttk.Label(mid, text="Solution:").grid(row=1, column=0, sticky="nw")
        self.sol_txt = tk.Text(mid, height=4, wrap="word", font=("Segoe UI", 9))
        self.sol_txt.grid(row=1, column=1, sticky="nsew", padx=6, pady=2)
        mid.rowconfigure(1, weight=1)
        ttk.Button(mid, text="✔  Mark Solved", style="Accent.TButton",
                   command=self.solve_selected).grid(row=0, column=2, rowspan=2,
                                                     sticky="nsew", padx=6)

        # ---- bottom: today
        bot = ttk.LabelFrame(panes, text=" Solved today ", padding=8)
        panes.add(bot, weight=3)
        stats = ttk.Frame(bot)
        stats.pack(fill="x", pady=(0, 6))
        self.stat_lbls = {}
        for key, label in (("count", "Solved"), ("total", "Total time"),
                           ("avg", "Avg / issue"), ("open", "Still open")):
            f = ttk.Frame(stats)
            f.pack(side="left", padx=(0, 28))
            ttk.Label(f, text=label, style="Sub.TLabel").pack(anchor="w")
            self.stat_lbls[key] = ttk.Label(f, text="-", style="Stat.TLabel")
            self.stat_lbls[key].pack(anchor="w")
        cols = ("id", "title", "category", "started", "solved", "taken", "solution")
        self.done_tree = self._tree(bot, cols,
                                    ("#", "Issue", "Category", "Started", "Solved",
                                     "Time taken", "Solution"),
                                    (40, 280, 100, 70, 70, 90, 330), height=5)
        self.done_tree.bind("<Double-1>", lambda e: self._details(self.done_tree))
        rb = ttk.Frame(bot)
        rb.pack(fill="x", pady=(6, 0))
        ttk.Button(rb, text="Reopen", command=self.reopen_selected).pack(side="left")
        ttk.Label(rb, text="Double-click any row for full details.",
                  style="Sub.TLabel").pack(side="left", padx=10)

        # status bar
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w",
                  padding=(8, 3)).pack(fill="x", side="bottom")

    def _tree(self, parent, cols, heads, widths, height):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=height,
                            selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="w", stretch=(c in ("title", "solution")))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.tag_configure("paused", foreground="#9A6700")
        tree.tag_configure("active", foreground="#1F3864")
        tree.tag_configure("odd", background="#F2F6FB")
        return tree

    # ------------------------------------------------------------ helpers
    def status(self, msg):
        self.status_var.set(f"[{datetime.now():%H:%M:%S}]  {msg}")

    def _selected_id(self, tree):
        sel = tree.selection()
        return int(sel[0]) if sel else None

    def _open_path(self, path):
        if not os.path.splitext(path)[1]:
            os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ------------------------------------------------------------ refresh
    def refresh_all(self):
        keep = self._selected_id(self.open_tree)
        self.open_tree.delete(*self.open_tree.get_children())
        for i in sorted(self.store.open_issues(), key=lambda x: x["started_at"]):
            self.open_tree.insert("", "end", iid=str(i["id"]), tags=(i["status"],), values=(
                i["id"], i["title"], i["category"], i["priority"], i["started_at"][:16],
                core.fmt_duration(core.active_seconds(i)),
                "Running" if i["status"] == "active" else "Paused"))
        if keep and self.open_tree.exists(str(keep)):
            self.open_tree.selection_set(str(keep))

        s = core.day_summary(self.store.issues, date.today())
        self.done_tree.delete(*self.done_tree.get_children())
        for n, i in enumerate(reversed(s["solved"])):
            self.done_tree.insert("", "end", iid=str(i["id"]), tags=("odd",) if n % 2 else (),
                                  values=(i["id"], i["title"], i["category"],
                                          i["started_at"][11:16], i["solved_at"][11:16],
                                          core.fmt_duration(core.active_seconds(i)),
                                          i["solution"].replace("\n", " ")[:120]))
        self.stat_lbls["count"].config(text=str(s["count"]))
        self.stat_lbls["total"].config(text=core.fmt_duration(s["total"]))
        self.stat_lbls["avg"].config(text=core.fmt_duration(s["avg"]))
        self.stat_lbls["open"].config(text=str(len(self.store.open_issues())))
        self._on_open_select()

    def _tick(self):
        self.clock_lbl.config(text=datetime.now().strftime("%A, %d %b %Y   %H:%M:%S"))
        for iid in self.open_tree.get_children():
            issue = self.store.get(int(iid))
            if issue and issue["status"] == "active":
                self.open_tree.set(iid, "active", core.fmt_duration(core.active_seconds(issue)))
        self.after(REFRESH_MS, self._tick)

    def _on_open_select(self, _event=None):
        iid = self._selected_id(self.open_tree)
        issue = self.store.get(iid) if iid else None
        if issue:
            self.pause_btn.config(text="▶  Resume" if issue["status"] == "paused" else "⏸  Pause")
            self.selected_lbl.config(text=f"Selected: #{issue['id']} {issue['title'][:60]}")
        else:
            self.pause_btn.config(text="⏸  Pause")
            self.selected_lbl.config(text="Select an issue to pause or solve it.")

    # ------------------------------------------------------------ actions
    def start_issue(self):
        try:
            issue = self.store.start_issue(self.title_var.get(),
                                           self.desc_txt.get("1.0", "end"),
                                           self.cat_var.get() or "Other", self.pri_var.get())
        except ValueError as e:
            messagebox.showwarning("Missing info", str(e))
            return
        self.title_var.set("")
        self.desc_txt.delete("1.0", "end")
        self.refresh_all()
        self.open_tree.selection_set(str(issue["id"]))
        self.open_tree.see(str(issue["id"]))
        self.status(f"Timer started for #{issue['id']}: {issue['title']}")

    def toggle_pause(self):
        iid = self._selected_id(self.open_tree)
        if not iid:
            self.status("Select an issue first.")
            return
        issue = self.store.get(iid)
        if issue["status"] == "active":
            self.store.pause(iid)
            self.status(f"Paused #{iid} (pause time is not counted).")
        else:
            self.store.resume(iid)
            self.status(f"Resumed #{iid}.")
        self.refresh_all()

    def solve_selected(self):
        iid = self._selected_id(self.open_tree)
        if not iid:
            messagebox.showinfo("Select an issue", "Select the issue you solved in the "
                                "'Issues in progress' list first.")
            return
        try:
            issue = self.store.solve(iid, self.sol_txt.get("1.0", "end"),
                                     self.cause_txt.get("1.0", "end"))
        except ValueError as e:
            messagebox.showwarning("Missing info", str(e))
            return
        self.sol_txt.delete("1.0", "end")
        self.cause_txt.delete("1.0", "end")
        self.refresh_all()
        taken = core.fmt_duration(core.active_seconds(issue))
        self.status(f"Solved #{iid} in {taken}. Nice work!")
        messagebox.showinfo("Issue solved",
                            f"#{iid}  {issue['title']}\n\nTime taken: {taken}\n"
                            f"Elapsed (incl. pauses): "
                            f"{core.fmt_duration(core.elapsed_seconds(issue))}")

    def delete_selected(self):
        iid = self._selected_id(self.open_tree)
        if iid and messagebox.askyesno("Delete issue", f"Delete issue #{iid}? "
                                       "This cannot be undone."):
            self.store.delete(iid)
            self.refresh_all()
            self.status(f"Deleted #{iid}.")

    def reopen_selected(self):
        iid = self._selected_id(self.done_tree)
        if iid and messagebox.askyesno("Reopen", f"Reopen #{iid}? The timer resumes and "
                                       "previous time is kept."):
            self.store.reopen(iid)
            self.refresh_all()
            self.status(f"Reopened #{iid}.")

    def _details(self, tree):
        iid = self._selected_id(tree)
        issue = self.store.get(iid) if iid else None
        if not issue:
            return
        win = tk.Toplevel(self)
        win.title(f"Issue #{iid}")
        win.geometry("640x480")
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 10), padx=12, pady=10)
        txt.pack(fill="both", expand=True)
        lines = [f"#{issue['id']}  {issue['title']}", "",
                 f"Category / Priority : {issue['category']} / {issue['priority']}",
                 f"Status              : {issue['status']}",
                 f"Started             : {issue['started_at']}",
                 f"Solved              : {issue['solved_at'] or '-'}",
                 f"Time taken (active) : {core.fmt_duration(core.active_seconds(issue))}",
                 f"Elapsed (wall-clock): {core.fmt_duration(core.elapsed_seconds(issue))}",
                 f"Work sessions       : {len(issue['sessions'])}", ""]
        for label, key in (("PROBLEM", "description"), ("ROOT CAUSE", "root_cause"),
                           ("SOLUTION", "solution")):
            if issue.get(key):
                lines += [label, issue[key], ""]
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")

    # ------------------------------------------------------------ reports
    def export_today(self, silent=False):
        txt, docx = core.export_day(self.store.issues, date.today())
        self.status(f"Report published: {os.path.basename(txt)} and {os.path.basename(docx)}")
        if not silent and messagebox.askyesno(
                "Report published", f"Saved to the reports folder:\n\n"
                f"{os.path.basename(txt)}\n{os.path.basename(docx)}\n\nOpen the Word report now?"):
            self._open_path(docx)

    def export_for_date(self):
        default = (date.today() - timedelta(days=1)).isoformat()
        s = simpledialog.askstring("Publish report", "Date (YYYY-MM-DD):",
                                   initialvalue=default, parent=self)
        if not s:
            return
        try:
            day = datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except ValueError:
            messagebox.showerror("Invalid date", "Please use the format YYYY-MM-DD.")
            return
        txt, docx = core.export_day(self.store.issues, day)
        self.status(f"Report for {day} published.")
        if messagebox.askyesno("Report published", f"Report for {day} saved.\n\nOpen it now?"):
            self._open_path(docx)

    def _auto_export_check(self):
        try:
            hh, mm = map(int, self.cfg.get("auto_export_time", "18:30").split(":"))
            now = datetime.now()
            if (now.hour, now.minute) >= (hh, mm) and self.last_auto_export != now.date():
                self.last_auto_export = now.date()
                self.export_today(silent=True)
                self.status(f"End of day ({hh:02d}:{mm:02d}) - today's report was published "
                            "automatically.")
                self.bell()
        except Exception as e:  # never crash the app because of the scheduler
            self.status(f"Auto-publish failed: {e}")
        self.after(AUTO_CHECK_MS, self._auto_export_check)

    def settings(self):
        s = simpledialog.askstring(
            "Settings", "End-of-day auto-publish time (HH:MM, 24h):",
            initialvalue=self.cfg.get("auto_export_time", "18:30"), parent=self)
        if s is None:
            return
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s.strip()):
            messagebox.showerror("Invalid time", "Use HH:MM, e.g. 18:30.")
            return
        self.cfg["auto_export_time"] = s.strip()
        self.cfg["export_on_close"] = messagebox.askyesno(
            "Settings", "Also publish today's report every time you close the app?")
        core.save_config(self.cfg)
        self.last_auto_export = None
        self.status(f"Settings saved. Auto-publish at {s.strip()}.")

    def on_close(self):
        try:
            active_today = date.today() in core.days_with_activity(self.store.issues)
            if self.cfg.get("export_on_close", True) and (
                    active_today or self.store.open_issues()):
                core.export_day(self.store.issues, date.today())
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    TrackerApp().mainloop()
