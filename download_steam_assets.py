"""
download_steam_assets.py

Downloads Steam graphical assets by AppID based on the SteamDB / Steam AppInfo specification.
Features:
- Connects anonymously to Steam PICS (Product Information Service) via SteamClient to fetch official AppInfo metadata.
- Downloads assets from:
    * small_capsule
    * header_image
    * library_assets_full (library_capsule, library_hero, library_hero_blur, library_logo, library_header)
    * Assets (main_capsule, header_2x, hero_capsule, page backgrounds, community icons)
- Prioritizes 'english' over other languages (e.g. sc_schinese).
- Prioritizes 'image2x' over 'image' when both exist.
- Saves files into structured directories per AppID with an assets_summary.json manifest.
"""

import os
import sys
import argparse
import csv
import json
import time
from pathlib import Path
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from steam.client import SteamClient
except ImportError:
    SteamClient = None


# ---------------------------------------------------------------------------
# Constants & CDN URLs
# ---------------------------------------------------------------------------
STORE_CDN_BASE = "https://shared.steamstatic.com/store_item_assets/steam/apps"
COMMUNITY_CDN_BASE = "https://shared.steamstatic.com/community_assets/images/apps"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}

# Standard Steam store assets to probe in the "Assets" general table
STANDARD_STORE_ASSETS = [
    ("main_capsule", "capsule_616x353.jpg"),
    ("small_capsule", "capsule_231x87.jpg"),
    ("header", "header.jpg"),
    ("header_2x", "header_2x.jpg"),
    ("hero_capsule", "hero_capsule.jpg"),
    ("page_background", "page_bg_generated_v6b.jpg"),
    ("raw_page_background", "page_bg_raw.jpg"),
    ("package_header", "package_header.jpg"),
]


# ---------------------------------------------------------------------------
# Asset Selection Logic
# ---------------------------------------------------------------------------

def pick_language_value(val_dict, target_lang="english"):
    """
    Given a dict mapping language -> value, picks the target_lang (e.g., 'english').
    If target_lang is not present, falls back gracefully to any available language value.
    """
    if not isinstance(val_dict, dict):
        return str(val_dict) if val_dict else None

    # Exact match for target language
    if target_lang in val_dict:
        return val_dict[target_lang]

    # Case-insensitive match
    for k, v in val_dict.items():
        if k.lower() == target_lang.lower():
            return v

    # Fallback to first available value
    for k, v in val_dict.items():
        if isinstance(v, str) and v:
            return v

    return None


def resolve_library_asset(asset_entry, target_lang="english"):
    """
    Resolves a library_assets_full item (e.g. library_capsule, library_hero, library_logo).
    Rule:
    - If it has both image/english and image2x/english, choose image2x!
    - If only image2x exists, use image2x.
    - If only image exists, use image.
    Returns: (resolution_type, relative_path) e.g. ('image2x', 'hash/library_capsule_2x.jpg')
    """
    if not isinstance(asset_entry, dict):
        return None, None

    # Check image2x first (priority)
    image2x_section = asset_entry.get("image2x")
    if isinstance(image2x_section, dict):
        val2x = pick_language_value(image2x_section, target_lang)
        if val2x:
            return "image2x", val2x

    # Check standard image
    image_section = asset_entry.get("image")
    if isinstance(image_section, dict):
        val = pick_language_value(image_section, target_lang)
        if val:
            return "image", val

    # If image2x or image is a direct string
    if isinstance(asset_entry.get("image2x"), str):
        return "image2x", asset_entry["image2x"]
    if isinstance(asset_entry.get("image"), str):
        return "image", asset_entry["image"]

    return None, None


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

def download_file(url, dest_path, session=None, timeout=20):
    """
    Downloads a file from url to dest_path.
    Returns (success: bool, status_code: int, size: int)
    """
    s = session or requests.Session()
    try:
        resp = s.get(url, headers=DEFAULT_HEADERS, stream=True, timeout=timeout)
        if resp.status_code == 200:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
            size = dest_path.stat().st_size
            return True, 200, size
        return False, resp.status_code, 0
    except Exception as exc:
        return False, -1, 0


# ---------------------------------------------------------------------------
# App Assets Processing
# ---------------------------------------------------------------------------

def get_app_assets_manifest(appid, common_data, target_lang="english", include_store_assets=True):
    """
    Extracts all requested assets from common_data according to the user's rules:
    - small_capsule
    - header_image
    - library_assets_full
    - Assets (general store assets & community assets)
    """
    assets_to_download = []
    seen_urls = set()

    def add_asset(category, name, url, filename):
        if url in seen_urls:
            return
        seen_urls.add(url)
        assets_to_download.append({
            "category": category,
            "name": name,
            "url": url,
            "filename": filename,
        })

    # 1. small_capsule
    if "small_capsule" in common_data:
        sc_val = pick_language_value(common_data["small_capsule"], target_lang)
        if sc_val:
            url = f"{STORE_CDN_BASE}/{appid}/{sc_val}"
            fname = Path(sc_val).name
            add_asset("small_capsule", "small_capsule", url, fname)

    # 2. header_image
    if "header_image" in common_data:
        hi_val = pick_language_value(common_data["header_image"], target_lang)
        if hi_val:
            url = f"{STORE_CDN_BASE}/{appid}/{hi_val}"
            fname = Path(hi_val).name
            add_asset("header_image", "header_image", url, fname)

    # 3. library_assets_full
    lib_full = common_data.get("library_assets_full", {})
    if isinstance(lib_full, dict):
        for subkey, entry in lib_full.items():
            if not isinstance(entry, dict):
                continue
            res_type, rel_path = resolve_library_asset(entry, target_lang)
            if rel_path:
                url = f"{STORE_CDN_BASE}/{appid}/{rel_path}"
                fname = Path(rel_path).name
                asset_label = f"{subkey}_{res_type}" if res_type else subkey
                add_asset("library_assets_full", asset_label, url, fname)

    # 4. Assets (General Store Assets & Community Assets)
    if include_store_assets:
        # Check standard store assets on Steam CDN
        s = requests.Session()
        for label, asset_fname in STANDARD_STORE_ASSETS:
            url = f"{STORE_CDN_BASE}/{appid}/{asset_fname}"
            # Check if exists on CDN via HEAD
            try:
                head_resp = s.head(url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=5)
                if head_resp.status_code == 200:
                    add_asset("store_assets", label, url, asset_fname)
            except Exception:
                pass

        # Community Assets: icon, logo, clienticon
        if "icon" in common_data:
            icon_hash = common_data["icon"]
            url = f"{COMMUNITY_CDN_BASE}/{appid}/{icon_hash}.jpg"
            add_asset("community_assets", "icon", url, f"community_icon_{icon_hash}.jpg")

        if "logo" in common_data:
            logo_hash = common_data["logo"]
            url = f"{COMMUNITY_CDN_BASE}/{appid}/{logo_hash}.jpg"
            add_asset("community_assets", "logo", url, f"community_logo_{logo_hash}.jpg")

        if "clienticon" in common_data:
            cicon_hash = common_data["clienticon"]
            url = f"{COMMUNITY_CDN_BASE}/{appid}/{cicon_hash}.ico"
            add_asset("community_assets", "clienticon", url, f"clienticon_{cicon_hash}.ico")

    return assets_to_download


def download_app_assets(appid, common_data, output_dir, target_lang="english", include_store_assets=True, skip_existing=False):
    """
    Resolves and downloads all assets for an AppID to output_dir / str(appid).
    """
    app_dir = Path(output_dir) / str(appid)
    app_dir.mkdir(parents=True, exist_ok=True)

    game_name = common_data.get("name", f"AppID {appid}")
    print(f"\n=======================================================")
    print(f"[*] Processing AppID {appid}: {game_name}")
    print(f"[*] Output directory: {app_dir.resolve()}")
    print(f"=======================================================")

    manifest = get_app_assets_manifest(
        appid=appid,
        common_data=common_data,
        target_lang=target_lang,
        include_store_assets=include_store_assets,
    )

    print(f"[+] Found {len(manifest)} assets matching criteria.")
    downloaded_summary = []
    session = requests.Session()

    for idx, item in enumerate(manifest, 1):
        cat = item["category"]
        name = item["name"]
        url = item["url"]
        fname = item["filename"]
        target_path = app_dir / fname

        print(f"  [{idx}/{len(manifest)}] [{cat}] {name} -> {fname}")
        print(f"      URL: {url}")

        if skip_existing and target_path.exists() and target_path.stat().st_size > 0:
            print(f"      -> SKIPPED (already exists, {target_path.stat().st_size:,} bytes)")
            downloaded_summary.append({**item, "local_path": str(target_path), "size_bytes": target_path.stat().st_size, "status": "skipped"})
            continue

        ok, status, size = download_file(url, target_path, session=session)
        if ok:
            print(f"      -> SUCCESS ({size:,} bytes)")
            downloaded_summary.append({**item, "local_path": str(target_path), "size_bytes": size, "status": "downloaded"})
        else:
            print(f"      -> FAILED (HTTP status {status})")
            downloaded_summary.append({**item, "local_path": str(target_path), "size_bytes": 0, "status": f"failed_http_{status}"})

    # Save manifest summary JSON
    summary_file = app_dir / "assets_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "appid": appid,
                "game_name": game_name,
                "target_lang": target_lang,
                "total_assets": len(manifest),
                "downloaded_count": sum(1 for x in downloaded_summary if x["status"] in ("downloaded", "skipped")),
                "assets": downloaded_summary,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"[+] Saved asset manifest: {summary_file.name}")
    return downloaded_summary


# ---------------------------------------------------------------------------
# Steam Client Manager
# ---------------------------------------------------------------------------

class SteamAssetManager:
    def __init__(self):
        self.client = None

    def connect(self):
        if SteamClient is None:
            raise RuntimeError("steam package is not installed. Please run: pip install 'steam[client]'")
        print("[*] Connecting to Steam network (anonymous login)...")
        self.client = SteamClient()
        res = self.client.anonymous_login()
        if res != 1:  # EResult.OK == 1
            raise RuntimeError(f"Failed to connect to Steam (result code: {res})")
        print("[+] Successfully connected to Steam PICS.")

    def disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            print("[*] Disconnected from Steam network.")

    def get_apps_info(self, appids):
        """
        Retrieves product info (PICS) for list of appids.
        Returns dict mapping int(appid) -> dict(common).
        """
        if not self.client:
            self.connect()

        int_appids = [int(a) for a in appids if str(a).strip().isdigit()]
        if not int_appids:
            return {}

        print(f"[*] Requesting product info for {len(int_appids)} app(s)...")
        pics_data = self.client.get_product_info(apps=int_appids)
        result = {}
        if pics_data and "apps" in pics_data:
            for aid, app_obj in pics_data["apps"].items():
                if isinstance(app_obj, dict):
                    result[aid] = app_obj.get("common", {})
        return result


# ---------------------------------------------------------------------------
# CLI & Entry Point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Download Steam assets by AppID based on SteamDB/Steam AppInfo specification."
    )
    parser.add_argument(
        "appids",
        nargs="*",
        type=int,
        help="One or more Steam AppIDs (e.g. 570 730 440)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        help="Path to a CSV file containing Steam AppIDs (e.g. EventRes.csv or DesktopCompanion.csv)",
    )
    parser.add_argument(
        "--appid-col",
        type=str,
        default="Steam AppID",
        help="Column name for AppID in CSV (default: 'Steam AppID')",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="./downloads",
        help="Output directory to store downloaded assets (default: ./downloads)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="english",
        help="Preferred language for localized assets (default: 'english')",
    )
    parser.add_argument(
        "--no-store-assets",
        action="store_true",
        help="Disable downloading standard store assets table (only download library_assets_full, small_capsule, header_image)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip downloading files that already exist on disk",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    appids = list(args.appids)

    # If CSV provided, read AppIDs from CSV
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            sys.exit(f"ERROR: CSV file not found: {csv_path}")
        print(f"[*] Reading AppIDs from CSV: {csv_path}")
        with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            col = args.appid_col
            if col not in (reader.fieldnames or []):
                # Fallback to check case-insensitive or 'appid'
                matches = [c for c in (reader.fieldnames or []) if "appid" in c.lower()]
                if matches:
                    col = matches[0]
                else:
                    sys.exit(f"ERROR: Column '{args.appid_col}' not found in CSV.")
            for row in reader:
                val = row.get(col, "").strip()
                if val.isdigit():
                    appids.append(int(val))

    if not appids:
        print("Usage: python download_steam_assets.py <appid> [appid2 ...]")
        print("Example: python download_steam_assets.py 570")
        sys.exit(1)

    # Deduplicate while preserving order
    unique_appids = list(dict.fromkeys(appids))
    print(f"[*] Total unique AppIDs to process: {len(unique_appids)}: {unique_appids}")

    manager = SteamAssetManager()
    try:
        manager.connect()
        apps_data = manager.get_apps_info(unique_appids)

        for appid in unique_appids:
            common = apps_data.get(appid)
            if not common:
                print(f"\n[!] WARNING: Could not find AppInfo for AppID {appid}. Skipping.")
                continue

            download_app_assets(
                appid=appid,
                common_data=common,
                output_dir=args.output_dir,
                target_lang=args.lang,
                include_store_assets=not args.no_store_assets,
                skip_existing=args.skip_existing,
            )

    except KeyboardInterrupt:
        print("\n[!] Process interrupted by user.")
    except Exception as exc:
        print(f"\n[!] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        manager.disconnect()

    print("\n[OK] All requested downloads completed.")


if __name__ == "__main__":
    main()
