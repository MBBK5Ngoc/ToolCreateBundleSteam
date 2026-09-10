"""
check_desktop_companion.py

Reads EventRes.csv, checks each Steam AppID against the Steam store page to see
if the game has the "Desktop Companion" tag, then splits results into:
  - DesktopCompanion.csv
  - NonDesktopCompanion.csv
"""

import csv
import time
import sys
import requests
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_CSV = Path(__file__).parent / "EventRes.csv"
OUTPUT_DC = Path(__file__).parent / "DesktopCompanion.csv"
OUTPUT_NDC = Path(__file__).parent / "NonDesktopCompanion.csv"

APPID_COL = "Steam AppID"        # column name in EventRes.csv
TARGET_TAG = "Desktop Companion" # tag to look for (case-insensitive)

STORE_API = "https://store.steampowered.com/api/appdetails"
STORE_PAGE = "https://store.steampowered.com/app/{appid}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DELAY_SECONDS = 10   # be polite to Steam servers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_desktop_companion_tag_api(appid):
    """
    Try Steam store API first.
    Returns True/False, or None if the API call fails / game not found.
    """
    try:
        resp = requests.get(
            STORE_API,
            params={"appids": appid, "l": "english"},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        app_data = data.get(str(appid), {})
        if not app_data.get("success"):
            return None
        details = app_data.get("data", {})

        # Check official categories
        for cat in details.get("categories", []):
            if TARGET_TAG.lower() in cat.get("description", "").lower():
                return True

        # Check genres
        for genre in details.get("genres", []):
            if TARGET_TAG.lower() in genre.get("description", "").lower():
                return True

        return False
    except Exception as exc:
        print(f"    [API error] {exc}", file=sys.stderr)
        return None


def has_desktop_companion_tag_html(appid):
    """
    Fallback: fetch the Steam store page HTML and look for the tag text.
    Catches user-defined tags that the API does not expose.
    """
    url = STORE_PAGE.format(appid=appid)
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=20, allow_redirects=True)

        # Handle age-gate
        if "agecheck" in resp.url:
            resp = session.post(
                f"https://store.steampowered.com/agecheck/app/{appid}/",
                data={
                    "snr": "1_agecheck_agecheck__age-gate",
                    "ageDay": "1",
                    "ageMonth": "January",
                    "ageYear": "1990",
                },
                timeout=20,
                allow_redirects=True,
            )

        return TARGET_TAG.lower() in resp.text.lower()
    except Exception as exc:
        print(f"    [HTML error for {appid}] {exc}", file=sys.stderr)
        return False


def check_appid(appid):
    """
    Check whether the given AppID Steam page has the Desktop Companion tag.
    Uses the API first; falls back to HTML scraping.
    """
    appid = appid.strip()
    if not appid:
        return False

    api_result = has_desktop_companion_tag_api(appid)
    if api_result:
        return True

    time.sleep(0.5)
    return has_desktop_companion_tag_html(appid)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not INPUT_CSV.exists():
        sys.exit(f"ERROR: Input file not found: {INPUT_CSV}")

    with open(INPUT_CSV, newline="", encoding="cp1252", errors="replace") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if APPID_COL not in (fieldnames or []):
        sys.exit(
            f"ERROR: Column '{APPID_COL}' not found in CSV.\n"
            f"Available columns: {fieldnames}"
        )

    desktop_rows = []
    non_desktop_rows = []
    errors = []

    total = len(rows)
    print(f"Checking {total} entries...\n")

    for i, row in enumerate(rows, 1):
        appid = row.get(APPID_COL, "").strip()
        title = row.get("Game Title", "?")
        print(f"[{i}/{total}] AppID={appid!r:>10}  {title}")

        if not appid:
            print("    -> SKIP (no AppID)")
            non_desktop_rows.append(row)
            continue

        try:
            is_dc = check_appid(appid)
        except Exception as exc:
            print(f"    -> ERROR: {exc}", file=sys.stderr)
            errors.append((appid, title, str(exc)))
            non_desktop_rows.append(row)
            is_dc = False

        if is_dc:
            print(f"    -> [YES] HAS '{TARGET_TAG}' tag")
            desktop_rows.append(row)
        else:
            print(f"    -> [NO]  No '{TARGET_TAG}' tag")
            non_desktop_rows.append(row)

        if i < total:
            time.sleep(DELAY_SECONDS)

    def write_csv(path, rows_to_write):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_to_write)
        print(f"  Wrote {len(rows_to_write)} rows -> {path}")

    print("\n--- Results ---")
    write_csv(OUTPUT_DC, desktop_rows)
    write_csv(OUTPUT_NDC, non_desktop_rows)

    if errors:
        print(f"\n[!] {len(errors)} entries had errors (placed in NonDesktopCompanion.csv):")
        for appid, title, err in errors:
            print(f"   AppID {appid} ({title}): {err}")

    print("\nDone.")


if __name__ == "__main__":
    main()
