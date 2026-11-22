# Bug Solution Tracker

Log each bug when you start on it, write the fix when you solve it, and the app tells you how long it took. At the end of the day it publishes a report as both `.txt` and `.docx`.

## Run
Double-click **`run_tracker.bat`** (or run `python app.py`). Needs Python 3.8+ only — no pip installs.

## Daily workflow
1. **Log a new issue**: type the error/issue, pick a category and priority, and paste the stack trace if you like. Press **Start Timer** (or Enter).
2. **In progress**: the timer runs live. **Pause** when you switch to something else; paused time isn't counted.
3. **Record the solution**: select the issue, write the solution (and root cause if you want), then click **Mark Solved**. You'll see the time taken.
4. **Solved today** shows your count, total time and average per issue. Double-click any row for full details; **Reopen** if a bug comes back.

## Reports (`reports/` folder)
`Bug_Report_YYYY-MM-DD.txt` and `.docx` are published:
- automatically at your end-of-day time (default **18:30**; change it in **Settings**)
- every time you close the app (can be turned off in Settings)
- whenever you click **Publish Today's Report** or **Publish Report for Date...**
- on startup, for any earlier day that has no report yet

Each report has: a summary (solved count, total/avg time, fastest and longest fix), time per category, each solved issue with problem/root cause/solution and timings, and any issues still open.

**Time taken** is hands-on time with pauses left out. **Elapsed** is wall-clock time from start to fix.

## Files
| Path | Purpose |
|---|---|
| `app.py` | Desktop app (Tkinter) |
| `tracker_core.py` | Storage, timing, TXT/DOCX report engine |
| `data/issues.json` | All your issues (back this up) |
| `data/config.json` | Settings |
| `reports/` | Daily reports |
