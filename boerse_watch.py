#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""
Watches the Freiburg Marathon Startplatzbörse and sends a push notification to
your phone (via the free ntfy app) as soon as a new Halbmarathon entry shows up.

SETUP (once)
  1. pip install playwright   (or: uv add playwright)
  2. python -m playwright install chromium
  3. Install the "ntfy" app (iOS / Android), tap "+" and subscribe to the
     topic name you put in NTFY_TOPIC below. Pick something random – anyone
     who knows the name can read the messages.

RUN
  python boerse_watch.py --dump    # shows what the script sees + parsed entries
  python boerse_watch.py --test    # sends a test push to your phone
  python boerse_watch.py           # starts watching (leave the window open)
"""
import argparse
import random
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime

from playwright.sync_api import sync_playwright

URL = "https://mein-freiburgmarathon.de/lauf/startplatzboerse/anmeldung/"
NTFY_TOPIC = "freiburg-hm-boerse-CHANGE-ME-8231"  # <- change this
SECTION_KEYWORDS = ("halbmarathon", "half marathon", "semi-marathon")
NOTIFY_OTHER_RACES = False  # True = also push for new Marathon / 10 km entries
INTERVAL = 60  # seconds between checks; please don't go much lower

# Lines to ignore: the page's countdown timer, empty lines, stray numbers
NOISE = re.compile(r"^[\d\s\-:DHMS.]*$")
# Table rows look like: "Julian > Kaufen 01.09.2026"
ENTRY = re.compile(r"^(?P<name>.+?)\s*>\s*Kaufen\s+(?P<date>\d{2}\.\d{2}\.\d{4})$", re.I)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(title, body, priority="high"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": "runner",
            "Click": URL,  # tapping the notification opens the Börse
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"Could not send notification: {e}")


def ensure_browser():
    # Downloads Chromium on first run (~150 MB); quick no-op afterwards
    log("Checking browser (first run downloads ~150 MB, please wait) ...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


def keep_awake():
    # Stops Windows from going to sleep while the watcher runs
    # (closing a laptop lid will still put it to sleep)
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def accept_cookies(page):
    try:
        page.get_by_role(
            "button", name=re.compile(r"alle akzeptieren|akzeptieren|accept all", re.I)
        ).first.click(timeout=4000)
        page.wait_for_timeout(2000)
    except Exception:
        pass


def page_lines(page):
    page.goto(URL, wait_until="networkidle", timeout=60000)
    accept_cookies(page)
    page.wait_for_timeout(3000)  # give the listing widget time to render
    lines = []
    for frame in page.frames:
        try:
            text = frame.inner_text("body", timeout=5000)
        except Exception:
            continue
        for line in text.splitlines():
            line = " ".join(line.split())
            if len(line) >= 4 and not NOISE.match(line):
                lines.append(line)
    return lines


def parse_entries(lines):
    """Return Counter of (race, first name, listing date) from the table."""
    entries = Counter()
    in_table = False
    race = "?"
    for line in lines:
        if line.lower().startswith("vorname"):  # table header
            in_table = True
            continue
        if not in_table:
            continue
        if line.upper().startswith("NEWSLETTER"):  # end of table
            break
        m = ENTRY.match(line)
        if m:
            entries[(race, m["name"], m["date"])] += 1
        else:
            race = line  # a section heading like "Marathon" / "Halbmarathon"
    if not in_table:
        raise RuntimeError("Listing table not found on page (layout changed?)")
    return entries


def is_target(race):
    return any(k in race.lower() for k in SECTION_KEYWORDS)


def fmt(entry):
    race, name, date = entry
    return f"{race}: {name} (listed {date})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="print page text + entries and exit")
    ap.add_argument("--test", action="store_true", help="send a test push and exit")
    args = ap.parse_args()

    if args.test:
        notify("Test from boerse_watch", "If you see this, notifications work.")
        log("Test notification sent.")
        return

    ensure_browser()
    keep_awake()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(locale="de-DE").new_page()

        if args.dump:
            lines = page_lines(page)
            print("\n".join(lines))
            print("\n--- parsed entries ---")
            for e in parse_entries(lines):
                print(("[TARGET] " if is_target(e[0]) else "         ") + fmt(e))
            return

        previous = None
        failures = 0
        while True:
            try:
                current = parse_entries(page_lines(page))
                failures = 0
                if previous is None:
                    hm = [e for e in current if is_target(e[0])]
                    log(f"Watching. {sum(current.values())} entries total, {len(hm)} Halbmarathon.")
                    body = f"Checking every {INTERVAL}s. Halbmarathon places right now: {len(hm)}"
                    if hm:
                        body += "\n" + "\n".join(fmt(e) for e in hm)
                    notify("Boerse watcher started", body,
                           priority="urgent" if hm else "default")
                else:
                    new = [e for e in current if current[e] > previous.get(e, 0)]
                    hm = [e for e in new if is_target(e[0])]
                    other = [e for e in new if not is_target(e[0])]
                    if hm:
                        log("NEW HALBMARATHON: " + "; ".join(fmt(e) for e in hm))
                        notify("NEW Halbmarathon start place!",
                               "\n".join(fmt(e) for e in hm), priority="urgent")
                    if other:
                        log("New other entries: " + "; ".join(fmt(e) for e in other))
                        if NOTIFY_OTHER_RACES:
                            notify("New Boerse entry (other race)",
                                   "\n".join(fmt(e) for e in other), priority="default")
                    if not new:
                        hm_now = sum(1 for e in current if is_target(e[0]))
                        log(f"No new entries ({hm_now} Halbmarathon listed).")
                previous = current
            except Exception as e:
                failures += 1
                log(f"Check failed ({failures}): {e}")
                if failures == 5:
                    notify("Boerse watcher has problems",
                           f"5 checks in a row failed: {e}", priority="default")
            time.sleep(INTERVAL + random.uniform(0, 10))


if __name__ == "__main__":
    main()
