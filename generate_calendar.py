#!/usr/bin/env python3
"""
Scan all of the authenticated user's GitHub repositories for GitHub Actions
`cron` schedules and emit an iCalendar (.ics) feed: one weekly-recurring event
per scheduled workflow, each with a reminder alarm.

Standard library only. Auth via env GH_TOKEN (a user PAT to include private
repos) or GITHUB_TOKEN (falls back to public repos only).
"""
import os
import re
import sys
import json
import base64
import datetime
import urllib.request
import urllib.error

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
USER = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("OWNER") or "Allanli1011"
ALARM_MIN = int(os.environ.get("ALARM_MINUTES", "15"))

# A fixed Sunday, so DTSTART is deterministic across regenerations (stable diff).
ANCHOR_SUNDAY = datetime.date(2024, 1, 7)
ORDER = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
DOW = {0: "SU", 1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}


def api(path):
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gha-calendar-script")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def api_get(path):
    try:
        return api(path)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def list_repos():
    def paged(path_tmpl):
        out, page = [], 1
        while True:
            data = api(path_tmpl.format(page=page))
            out.extend(data)
            if len(data) < 100:
                break
            page += 1
        return out

    try:
        repos = paged("/user/repos?per_page=100&affiliation=owner&page={page}")
        sys.stderr.write("repo source: authenticated (incl. private)\n")
    except urllib.error.HTTPError:
        repos = paged(f"/users/{USER}/repos?per_page=100&type=owner&page={{page}}")
        sys.stderr.write("repo source: public-only (no user PAT)\n")
    return [r for r in repos if not r.get("fork") and not r.get("archived")]


def workflow_files(full):
    items = api_get(f"/repos/{full}/contents/.github/workflows")
    if not isinstance(items, list):
        return []
    return [it["name"] for it in items if it["name"].endswith((".yml", ".yaml"))]


def file_text(full, name):
    data = api_get(f"/repos/{full}/contents/.github/workflows/{name}")
    if not data or "content" not in data:
        return ""
    return base64.b64decode(data["content"]).decode("utf-8", "replace")


def parse_field(field, lo, hi):
    """Expand a cron field to a sorted list of ints. '*' -> None. Bad token -> 'BAD'."""
    field = field.strip()
    if field == "*":
        return None
    vals = set()
    for part in field.split(","):
        part = part.strip()
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            vals.update(range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        m = re.match(r"^\*/(\d+)$", part)
        if m:
            vals.update(range(lo, hi + 1, int(m.group(1))))
            continue
        if re.match(r"^\d+$", part):
            vals.add(int(part))
            continue
        return "BAD"
    return sorted(vals)


def extract_name(text, fallback):
    m = re.search(r'(?m)^name:\s*(.+?)\s*$', text)
    return m.group(1).strip().strip('"').strip("'") if m else fallback


def crons_from_text(text):
    return re.findall(r'(?mi)^\s*-?\s*cron:\s*["\']?([^"\'#\n]+)', text)


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_event(full, fname, wname, cron):
    parts = cron.split()
    if len(parts) != 5:
        return None
    mi, ho, dom, mon, dow = parts
    minutes, hours, dows = parse_field(mi, 0, 59), parse_field(ho, 0, 23), parse_field(dow, 0, 7)
    if "BAD" in (minutes, hours, dows):
        return None
    minute = minutes[0] if minutes else 0
    hour = hours[0] if hours else 0

    byday = None
    if dows is not None:
        byday = sorted({DOW[d] for d in dows}, key=ORDER.index)

    if byday:
        dt_date = ANCHOR_SUNDAY + datetime.timedelta(days=min(ORDER.index(b) for b in byday))
    else:
        dt_date = ANCHOR_SUNDAY
    dtstart = datetime.datetime(dt_date.year, dt_date.month, dt_date.day, hour, minute)
    dtend = dtstart + datetime.timedelta(minutes=30)
    fmt = "%Y%m%dT%H%M%SZ"

    rrule = ("FREQ=WEEKLY;BYDAY=" + ",".join(byday)) if byday else "FREQ=DAILY"
    if hours and len(hours) > 1:
        rrule += ";BYHOUR=" + ",".join(map(str, hours))
    if minutes and len(minutes) > 1:
        rrule += ";BYMINUTE=" + ",".join(map(str, minutes))

    uid = ("gha-" + full + "-" + fname).replace("/", "-").replace(" ", "_") + "@allanli1011"
    summary = f"⏰ {wname} - {full.split('/')[-1]}"
    desc = (f"仓库: {full}\\nWorkflow: {fname}\\ncron (UTC): {cron.strip()}\\n"
            f"说明: GitHub 整点常延迟 1-3 小时。")
    return "\r\n".join([
        "BEGIN:VEVENT",
        f"UID:{uid}",
        "DTSTAMP:20240101T000000Z",
        f"DTSTART:{dtstart.strftime(fmt)}",
        f"DTEND:{dtend.strftime(fmt)}",
        f"RRULE:{rrule}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{desc}",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{esc(summary)}",
        f"TRIGGER:-PT{ALARM_MIN}M",
        "END:VALARM",
        "END:VEVENT",
    ])


def main():
    out = "github-actions-schedule.ics"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]

    events = []
    repos = list_repos()
    sys.stderr.write(f"scanning {len(repos)} repos...\n")
    for r in repos:
        full = r["full_name"]
        for fname in workflow_files(full):
            text = file_text(full, fname)
            crons = crons_from_text(text)
            if not crons:
                continue
            wname = extract_name(text, fname)
            for c in crons:
                ev = build_event(full, fname, wname, c)
                if ev:
                    events.append((full + "|" + fname + "|" + c, ev))
    events.sort()

    cal = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Allanli1011//GitHub Actions Schedule//ZH",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:GitHub Actions 定时任务",
        "X-WR-TIMEZONE:Asia/Shanghai",
    ] + [ev for _, ev in events] + ["END:VCALENDAR"]

    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(cal) + "\r\n")
    sys.stderr.write(f"wrote {len(events)} events -> {out}\n")


if __name__ == "__main__":
    main()
