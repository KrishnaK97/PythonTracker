"""
tracker_core.py - Data storage, timing and daily report generation for the
Bug Solution Tracker. Pure standard library (no pip installs required).
"""
import json
import os
import zipfile
from datetime import datetime, date, timedelta
from xml.sax.saxutils import escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DATA_FILE = os.path.join(DATA_DIR, "issues.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

TS_FMT = "%Y-%m-%d %H:%M:%S"
CATEGORIES = ["Bug", "Build/Compile", "Config/Env", "Performance", "Integration/API",
              "Database", "UI", "Deployment", "Other"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
DEFAULT_CONFIG = {"auto_export_time": "18:30", "export_on_close": True}


# ---------------------------------------------------------------- helpers
def now_str():
    return datetime.now().strftime(TS_FMT)


def parse_ts(s):
    return datetime.strptime(s, TS_FMT) if s else None


def fmt_duration(seconds):
    seconds = int(max(0, seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)


def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------- config
def load_config():
    _ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg):
    _ensure_dirs()
    _atomic_write_json(CONFIG_FILE, cfg)


# ---------------------------------------------------------------- store
class IssueStore:
    """Keeps all issues in data/issues.json.

    Issue fields: id, title, description, category, priority, status
    ("active" | "paused" | "solved"), started_at, solved_at, solution,
    root_cause, sessions [[start, end|None], ...]  (active work periods).
    """

    def __init__(self, path=DATA_FILE):
        _ensure_dirs()
        self.path = path
        self.issues = []
        self.load()

    # persistence
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.issues = json.load(f).get("issues", [])
            except (json.JSONDecodeError, OSError):
                backup = self.path + ".corrupt-" + datetime.now().strftime("%Y%m%d%H%M%S")
                os.replace(self.path, backup)
                self.issues = []

    def save(self):
        _atomic_write_json(self.path, {"issues": self.issues})

    # lookups
    def get(self, issue_id):
        return next((i for i in self.issues if i["id"] == issue_id), None)

    def open_issues(self):
        return [i for i in self.issues if i["status"] != "solved"]

    def _next_id(self):
        return max((i["id"] for i in self.issues), default=0) + 1

    # actions
    def start_issue(self, title, description="", category="Bug", priority="Medium"):
        title = title.strip()
        if not title:
            raise ValueError("Issue title is required.")
        ts = now_str()
        issue = {
            "id": self._next_id(), "title": title, "description": description.strip(),
            "category": category, "priority": priority, "status": "active",
            "started_at": ts, "solved_at": None, "solution": "", "root_cause": "",
            "sessions": [[ts, None]],
        }
        self.issues.append(issue)
        self.save()
        return issue

    def pause(self, issue_id):
        issue = self.get(issue_id)
        if issue and issue["status"] == "active":
            issue["sessions"][-1][1] = now_str()
            issue["status"] = "paused"
            self.save()
        return issue

    def resume(self, issue_id):
        issue = self.get(issue_id)
        if issue and issue["status"] == "paused":
            issue["sessions"].append([now_str(), None])
            issue["status"] = "active"
            self.save()
        return issue

    def solve(self, issue_id, solution, root_cause=""):
        issue = self.get(issue_id)
        if not issue or issue["status"] == "solved":
            return issue
        if not solution.strip():
            raise ValueError("Please describe the solution.")
        ts = now_str()
        if issue["sessions"] and issue["sessions"][-1][1] is None:
            issue["sessions"][-1][1] = ts
        issue.update(status="solved", solved_at=ts, solution=solution.strip(),
                     root_cause=root_cause.strip())
        self.save()
        return issue

    def reopen(self, issue_id):
        issue = self.get(issue_id)
        if issue and issue["status"] == "solved":
            issue["sessions"].append([now_str(), None])
            issue.update(status="active", solved_at=None)
            self.save()
        return issue

    def delete(self, issue_id):
        self.issues = [i for i in self.issues if i["id"] != issue_id]
        self.save()


# ---------------------------------------------------------------- timing
def active_seconds(issue, until=None):
    """Hands-on time: sum of work sessions (pauses excluded)."""
    until = until or datetime.now()
    total = 0.0
    for start, end in issue.get("sessions", []):
        s = parse_ts(start)
        e = parse_ts(end) if end else until
        total += max(0.0, (e - s).total_seconds())
    return total


def elapsed_seconds(issue, until=None):
    """Wall-clock time from start to solution (or now)."""
    start = parse_ts(issue["started_at"])
    end = parse_ts(issue["solved_at"]) if issue.get("solved_at") else (until or datetime.now())
    return max(0.0, (end - start).total_seconds())


# ---------------------------------------------------------------- report data
def _d(ts):
    return parse_ts(ts).date() if ts else None


def issues_for_day(issues, day):
    solved = [i for i in issues if i["status"] == "solved" and _d(i["solved_at"]) == day]
    solved.sort(key=lambda i: i["solved_at"])
    pending = [i for i in issues
               if _d(i["started_at"]) <= day
               and (i["status"] != "solved" or _d(i["solved_at"]) > day)]
    pending.sort(key=lambda i: i["started_at"])
    return solved, pending


def day_summary(issues, day):
    solved, pending = issues_for_day(issues, day)
    times = [active_seconds(i) for i in solved]
    by_cat = {}
    for i, t in zip(solved, times):
        c = by_cat.setdefault(i["category"], [0, 0.0])
        c[0] += 1
        c[1] += t
    return {
        "day": day, "solved": solved, "pending": pending,
        "count": len(solved), "total": sum(times),
        "avg": (sum(times) / len(times)) if times else 0,
        "fastest": min(zip(times, solved), key=lambda x: x[0]) if times else None,
        "longest": max(zip(times, solved), key=lambda x: x[0]) if times else None,
        "by_category": by_cat,
    }


def days_with_activity(issues):
    days = set()
    for i in issues:
        days.add(_d(i["started_at"]))
        if i.get("solved_at"):
            days.add(_d(i["solved_at"]))
    return sorted(d for d in days if d)


# ---------------------------------------------------------------- TXT report
def build_txt(summary):
    day = summary["day"]
    L = []
    bar = "=" * 72
    L += [bar, f"  DAILY BUG RESOLUTION REPORT  -  {day.strftime('%A, %d %B %Y')}", bar, ""]
    L.append("SUMMARY")
    L.append("-" * 72)
    L.append(f"  Issues solved        : {summary['count']}")
    L.append(f"  Total solving time   : {fmt_duration(summary['total'])}")
    L.append(f"  Average per issue    : {fmt_duration(summary['avg'])}")
    if summary["fastest"]:
        t, i = summary["fastest"]
        L.append(f"  Fastest fix          : #{i['id']} {i['title']} ({fmt_duration(t)})")
        t, i = summary["longest"]
        L.append(f"  Longest fix          : #{i['id']} {i['title']} ({fmt_duration(t)})")
    L.append(f"  Still open           : {len(summary['pending'])}")
    L.append("")

    if summary["by_category"]:
        L.append("BY CATEGORY")
        L.append("-" * 72)
        for cat, (n, t) in sorted(summary["by_category"].items(), key=lambda x: -x[1][1]):
            L.append(f"  {cat:<20} {n:>3} issue(s)   {fmt_duration(t)}")
        L.append("")

    L.append("SOLVED ISSUES")
    L.append("-" * 72)
    if not summary["solved"]:
        L.append("  (none)")
    for i in summary["solved"]:
        L.append(f"#{i['id']}  {i['title']}")
        L.append(f"    Category / Priority : {i['category']} / {i['priority']}")
        L.append(f"    Started             : {i['started_at']}")
        L.append(f"    Solved              : {i['solved_at']}")
        L.append(f"    Time taken (active) : {fmt_duration(active_seconds(i))}")
        L.append(f"    Elapsed (wall-clock): {fmt_duration(elapsed_seconds(i))}")
        for label, key in (("Problem", "description"), ("Root cause", "root_cause"),
                           ("Solution", "solution")):
            if i.get(key):
                lines = i[key].splitlines() or [""]
                L.append(f"    {label + ':':<20}  {lines[0]}")
                for ln in lines[1:]:
                    L.append(f"    {'':<20}  {ln}")
        L.append("")

    L.append("OPEN / IN-PROGRESS ISSUES")
    L.append("-" * 72)
    if not summary["pending"]:
        L.append("  (none)")
    end_of_day = datetime.combine(summary["day"], datetime.max.time())
    cutoff = min(end_of_day, datetime.now())
    for i in summary["pending"]:
        L.append(f"#{i['id']}  {i['title']}  [{i['category']} / {i['priority']}]")
        L.append(f"    Started: {i['started_at']}   Time spent so far: "
                 f"{fmt_duration(active_seconds(i, cutoff))}")
    L += ["", f"Generated {now_str()} by Bug Solution Tracker", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- DOCX report
class _Docx:
    """Tiny .docx writer (paragraphs, runs, tables) - no python-docx needed."""
    NAVY, TEAL, GREY = "1F3864", "2E75B6", "595959"

    def __init__(self):
        self.body = []

    @staticmethod
    def _run(text, bold=False, size=21, color=None, italic=False):
        rpr = '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        rpr += "<w:b/>" if bold else ""
        rpr += "<w:i/>" if italic else ""
        rpr += f'<w:color w:val="{color}"/>' if color else ""
        rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        parts = []
        for n, line in enumerate(str(text).split("\n")):
            if n:
                parts.append("<w:br/>")
            parts.append(f'<w:t xml:space="preserve">{escape(line)}</w:t>')
        return f"<w:r><w:rPr>{rpr}</w:rPr>{''.join(parts)}</w:r>"

    def para(self, runs, space_after=80, border_bottom=False, keep_next=False):
        if isinstance(runs, str):
            runs = [self._run(runs)]
        # OOXML requires this element order: keepNext, pBdr, spacing
        ppr = "<w:keepNext/>" if keep_next else ""
        if border_bottom:
            ppr += ('<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="1" '
                    f'w:color="{self.TEAL}"/></w:pBdr>')
        ppr += f'<w:spacing w:before="0" w:after="{space_after}"/>'
        self.body.append(f"<w:p><w:pPr>{ppr}</w:pPr>{''.join(runs)}</w:p>")

    def heading(self, text, size=28, color=None):
        self.para([self._run(text, bold=True, size=size, color=color or self.NAVY)],
                  space_after=120, border_bottom=True, keep_next=True)

    def field(self, label, value):
        self.para([self._run(label + ": ", bold=True, color=self.GREY), self._run(value)],
                  space_after=40)

    def table(self, rows, widths):
        b = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                    for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        xml = [f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>{b}'
               '</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/>'
               '<w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>']
        xml += [f'<w:gridCol w:w="{w}"/>' for w in widths]
        xml.append("</w:tblGrid>")
        for r, row in enumerate(rows):
            xml.append("<w:tr>")
            for c, cell in enumerate(row):
                shade = (f'<w:shd w:val="clear" w:color="auto" w:fill="{self.NAVY}"/>' if r == 0
                         else ('<w:shd w:val="clear" w:color="auto" w:fill="F2F6FB"/>'
                               if r % 2 == 0 else ""))
                run = self._run(cell, bold=(r == 0), size=19,
                                color="FFFFFF" if r == 0 else None)
                xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/>{shade}'
                           f'</w:tcPr><w:p><w:pPr><w:spacing w:before="40" w:after="40"/>'
                           f'</w:pPr>{run}</w:p></w:tc>')
            xml.append("</w:tr>")
        xml.append("</w:tbl>")
        self.body.append("".join(xml))
        self.para("", space_after=120)

    def save(self, path):
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}>'
                    f'<w:body>{"".join(self.body)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                    '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
                    'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
        doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        tmp = path + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("word/document.xml", document)
        try:
            os.replace(tmp, path)
        except PermissionError:
            os.remove(tmp)
            raise


def build_docx(summary, path):
    d = _Docx()
    day = summary["day"]
    d.para([d._run("Daily Bug Resolution Report", bold=True, size=40, color=d.NAVY)],
           space_after=40)
    d.para([d._run(day.strftime("%A, %d %B %Y"), size=24, color=d.TEAL)], space_after=240)

    d.heading("Summary")
    rows = [["Metric", "Value"],
            ["Issues solved", str(summary["count"])],
            ["Total solving time", fmt_duration(summary["total"])],
            ["Average per issue", fmt_duration(summary["avg"])]]
    if summary["fastest"]:
        t, i = summary["fastest"]
        rows.append(["Fastest fix", f"#{i['id']} {i['title']} ({fmt_duration(t)})"])
        t, i = summary["longest"]
        rows.append(["Longest fix", f"#{i['id']} {i['title']} ({fmt_duration(t)})"])
    rows.append(["Still open", str(len(summary["pending"]))])
    d.table(rows, [3000, 6600])

    if summary["by_category"]:
        d.heading("Time by Category")
        rows = [["Category", "Issues", "Time"]]
        for cat, (n, t) in sorted(summary["by_category"].items(), key=lambda x: -x[1][1]):
            rows.append([cat, str(n), fmt_duration(t)])
        d.table(rows, [4600, 2000, 3000])

    d.heading("Solved Issues")
    if summary["solved"]:
        rows = [["#", "Issue", "Category", "Started", "Solved", "Time taken"]]
        for i in summary["solved"]:
            rows.append([str(i["id"]), i["title"], i["category"], i["started_at"][11:16],
                         i["solved_at"][11:16], fmt_duration(active_seconds(i))])
        d.table(rows, [500, 3700, 1500, 1100, 1100, 1700])
        for i in summary["solved"]:
            d.para([d._run(f"#{i['id']}  {i['title']}", bold=True, size=24, color=d.TEAL)],
                   space_after=60, keep_next=True)
            d.field("Category / Priority", f"{i['category']} / {i['priority']}")
            d.field("Started → Solved", f"{i['started_at']}  →  {i['solved_at']}")
            d.field("Time taken (active)", fmt_duration(active_seconds(i)))
            d.field("Elapsed (wall-clock)", fmt_duration(elapsed_seconds(i)))
            if i.get("description"):
                d.field("Problem", i["description"])
            if i.get("root_cause"):
                d.field("Root cause", i["root_cause"])
            d.field("Solution", i["solution"])
            d.para("", space_after=160)
    else:
        d.para([d._run("No issues solved on this day.", italic=True, color=d.GREY)])

    d.heading("Open / In-Progress Issues")
    if summary["pending"]:
        cutoff = min(datetime.combine(day, datetime.max.time()), datetime.now())
        rows = [["#", "Issue", "Category", "Priority", "Started", "Time so far"]]
        for i in summary["pending"]:
            rows.append([str(i["id"]), i["title"], i["category"], i["priority"],
                         i["started_at"][:16], fmt_duration(active_seconds(i, cutoff))])
        d.table(rows, [500, 3600, 1500, 1100, 1700, 1200])
    else:
        d.para([d._run("None - clean slate!", italic=True, color=d.GREY)])

    d.para([d._run(f"Generated {now_str()} by Bug Solution Tracker", italic=True, size=16,
                   color=d.GREY)], space_after=0)
    d.save(path)


# ---------------------------------------------------------------- export
def report_paths(day):
    base = os.path.join(REPORTS_DIR, f"Bug_Report_{day.isoformat()}")
    return base + ".txt", base + ".docx"


def export_day(issues, day=None):
    """Write TXT + DOCX for the given day. Returns (txt_path, docx_path)."""
    _ensure_dirs()
    day = day or date.today()
    summary = day_summary(issues, day)
    txt_path, docx_path = report_paths(day)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(build_txt(summary))
    try:
        build_docx(summary, docx_path)
    except PermissionError:
        # File is open in Word - write alongside instead of failing.
        docx_path = docx_path.replace(".docx", f"_{datetime.now():%H%M%S}.docx")
        build_docx(summary, docx_path)
    return txt_path, docx_path


def backfill_missing_reports(issues):
    """Create reports for any past day that has activity but no report yet."""
    created = []
    for day in days_with_activity(issues):
        if day >= date.today():
            continue
        txt, docx = report_paths(day)
        if not (os.path.exists(txt) and os.path.exists(docx)):
            created.append(export_day(issues, day))
    return created
