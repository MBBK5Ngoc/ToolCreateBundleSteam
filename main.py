"""
main.py  -  Steam Bundle Asset Generator
==========================================
Usage:
    python main.py <appid1> <appid2> [<appid3> ...] [options]

Examples:
    # 2-game bundle:
    python main.py 3681780 2666510
    python main.py 3681780 2666510 --rotation 20
    python main.py 3681780 2666510 --scale 3681780x1.1 --scale 2666510x1.2

    # 3-game, 4-game, 5-game, 6-game bundles:
    python main.py 3681780 2666510 3419430
    python main.py 3681780 2666510 3419430 570
    python main.py 3681780 2666510 3419430 570 730 --layout strips
    python main.py 3681780 2666510 3419430 570 730 440 --layout grid

    # Layout & filtering options:
    python main.py 3681780 2666510 3419430 --only vertical_capsule
    python main.py 3681780 2666510 3419430 vertical_capsule only

Options:
    --layout STYLE          Layout mode: 'auto' (default), 'strips', 'grid', 'horizontal'
    --rotation DEGREES      Tilt the diagonal/slanted lines by extra degrees (default: 0)
    --scale APPIDxFACTOR    Scale a specific game's logo; repeatable
                            e.g. --scale 3681780x1.1 means 10% bigger logo
    --up APPID PIXELS       Shift app background image UP (repeatable)
    --down APPID PIXELS     Shift app background image DOWN (repeatable)
    --left APPID PIXELS     Shift app background image LEFT (repeatable)
    --right APPID PIXELS    Shift app background image RIGHT (repeatable)
    --move APPID DX DY      Shift background image by (dx, dy) (repeatable)
    --only IMAGE_NAME       Generate only specific image(s); repeatable
                            e.g. --only vertical_capsule or trailing: vertical_capsule only

Steps:
    1. For each AppID, check if required assets exist in the downloads folder.
    2. If any are missing, download them from Steam via download_steam_assets.py.
    3. Run create_bundle_assets.py to generate all 6 bundle images.

Required files per app (inside downloads/<appid>/):
    - library_hero_2x.jpg
    - logo_2x.png
"""

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Required files to check before deciding to download
# ---------------------------------------------------------------------------
REQUIRED_FILES = ["library_hero_2x.jpg", "logo_2x.png"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_assets(appid: str, downloads_dir: Path) -> list[str]:
    """Return list of missing required file names for an appid."""
    app_dir = downloads_dir / str(appid)
    missing = []
    for fname in REQUIRED_FILES:
        p = app_dir / fname
        if not p.exists() or p.stat().st_size == 0:
            missing.append(fname)
    return missing


def download_assets_for(appids: list[str], downloads_dir: Path) -> None:
    """Connect to Steam and download assets for the given appids."""
    try:
        from download_steam_assets import SteamAssetManager, download_app_assets
    except ImportError as e:
        print(f"[!] Could not import download_steam_assets.py: {e}")
        sys.exit(1)

    int_appids = [int(a) for a in appids]
    print(f"\n[Steam] Connecting to Steam to download assets for: {int_appids}")

    manager = SteamAssetManager()
    try:
        manager.connect()
        apps_data = manager.get_apps_info(int_appids)

        for appid in int_appids:
            common = apps_data.get(appid)
            if not common:
                print(f"[!] WARNING: Could not find AppInfo for AppID {appid}. Skipping download.")
                continue

            download_app_assets(
                appid=appid,
                common_data=common,
                output_dir=str(downloads_dir),
                target_lang="english",
                include_store_assets=True,
                skip_existing=True,
            )

    except KeyboardInterrupt:
        print("\n[!] Download interrupted by user.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[!] Download error: {exc}", file=sys.stderr)
        raise
    finally:
        manager.disconnect()


def generate_bundle(appids: list[str],
                    downloads_dir: Path, output_dir: Path,
                    rotation_deg: float = 0.0,
                    layout: str = "auto",
                    logo_scales: dict | None = None,
                    bg_offsets: dict | None = None,
                    only_images: list[str] | None = None) -> None:
    """Call create_bundle_assets.process() to generate bundle images."""
    try:
        from create_bundle_assets import process
    except ImportError as e:
        print(f"[!] Could not import create_bundle_assets.py: {e}")
        sys.exit(1)

    process(appids, downloads_dir, output_dir,
            rotation_deg=rotation_deg,
            layout=layout,
            logo_scales=logo_scales or {},
            bg_offsets=bg_offsets or {},
            only_images=only_images)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Steam bundle assets from multiple App IDs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py 3681780 2666510
  python main.py 3681780 2666510 3419430 570
  python main.py 3681780 2666510 3419430 570 730 --layout strips
  python main.py 3681780 2666510 3419430 570 730 440 --layout grid
        """,
    )
    parser.add_argument("appids", nargs="+", help="Steam App IDs (at least 2, e.g. 5 or 6 games)")
    parser.add_argument(
        "--layout", choices=["auto", "strips", "grid", "horizontal"], default="auto",
        help="Layout style: auto (default), strips, grid, horizontal",
    )
    parser.add_argument(
        "--downloads-dir", default="downloads",
        help="Folder that holds per-app asset subfolders (default: downloads)",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Folder to write finished bundle images (default: output)",
    )
    parser.add_argument(
        "--force-download", action="store_true",
        help="Force re-downloading assets even if they already exist",
    )
    parser.add_argument(
        "--rotation", type=float, default=0.0, metavar="DEGREES",
        help="Extra degrees to rotate the diagonal line from default (default: 0)",
    )
    parser.add_argument(
        "--scale", action="append", default=[], dest="scales",
        metavar="APPIDxFACTOR",
        help="Per-app logo scale multiplier, e.g. --scale 3681780x1.1 (repeatable)",
    )
    parser.add_argument(
        "--up", action="append", nargs="+", default=[],
        metavar="APPID PIXELS", help="Shift app background image UP by pixels (repeatable)",
    )
    parser.add_argument(
        "--down", action="append", nargs="+", default=[],
        metavar="APPID PIXELS", help="Shift app background image DOWN by pixels (repeatable)",
    )
    parser.add_argument(
        "--left", action="append", nargs="+", default=[],
        metavar="APPID PIXELS", help="Shift app background image LEFT by pixels (repeatable)",
    )
    parser.add_argument(
        "--right", action="append", nargs="+", default=[],
        metavar="APPID PIXELS", help="Shift app background image RIGHT by pixels (repeatable)",
    )
    parser.add_argument(
        "--move", action="append", nargs="+", default=[],
        metavar="DIRECTION: APPID PIXELS", help="Shift background, e.g. --move 'down: 3681780 +50'",
    )
    parser.add_argument(
        "--only", "-o", action="append", default=[], dest="only_images",
        metavar="IMAGE_NAME",
        help="Generate only specific image(s) (repeatable), e.g. --only vertical_capsule or 'vertical_capsule only'",
    )
    parser.add_argument(
        "extra_args", nargs="*",
        help=argparse.SUPPRESS,
    )
    args, unknown = parser.parse_known_args()

    # Separate numeric appids from trailing image target names (e.g. 'vertical_capsule only')
    actual_appids = []
    trailing_extra = []
    for item in args.appids:
        if item.isdigit():
            actual_appids.append(item)
        else:
            trailing_extra.append(item)

    if len(actual_appids) < 2:
        print(f"[!] Error: At least 2 Steam App IDs are required. Received: {actual_appids}", file=sys.stderr)
        sys.exit(1)

    extra_combined = (args.extra_args or []) + trailing_extra

    # Parse --only image target
    try:
        from create_bundle_assets import extract_only_args, resolve_target_specs
        only_images = extract_only_args(args.only_images, extra_combined, unknown)
        target_names = [s[0] for s in resolve_target_specs(only_images)] if only_images else None
    except Exception as e:
        print(f"[!] Error with --only option: {e}")
        sys.exit(1)

    # Parse --scale values: 'appidxFACTOR' -> {appid: float}
    logo_scales = {}
    for s in args.scales:
        try:
            parts = s.split("x", 1)
            if len(parts) != 2:
                raise ValueError()
            logo_scales[parts[0].strip()] = float(parts[1].strip())
        except ValueError:
            print(f"[!] Invalid --scale value '{s}'. Expected format: <appid>x<factor>  e.g. 3681780x1.1")
            sys.exit(1)

    # Parse background offset values
    try:
        from create_bundle_assets import build_bg_offsets
        bg_offsets = build_bg_offsets(
            up_list=args.up,
            down_list=args.down,
            left_list=args.left,
            right_list=args.right,
            move_list=args.move,
        )
    except Exception as e:
        print(f"[!] Error parsing background move options: {e}")
        sys.exit(1)

    base_dir      = Path(__file__).parent
    downloads_dir = base_dir / args.downloads_dir
    output_dir    = base_dir / args.output_dir

    downloads_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  Steam Bundle Asset Generator ({len(actual_appids)} Games)")
    for idx, aid in enumerate(actual_appids, start=1):
        print(f"  App {idx:<2}: {aid}")
    print(f"  Layout: {args.layout.upper()}")
    print(f"  Assets: {downloads_dir}")
    print(f"  Output: {output_dir}")
    if args.rotation != 0.0:
        print(f"  Rotation  : {args.rotation:+.1f} deg")
    if logo_scales:
        for aid, fac in logo_scales.items():
            print(f"  Logo scale: app {aid} x{fac:.2f}")
    if bg_offsets:
        for aid, off in bg_offsets.items():
            print(f"  BG shift  : app {aid} (x={off[0]:+.0f}px, y={off[1]:+.0f}px)")
    if target_names:
        print(f"  Target images : ONLY {target_names}")
    else:
        print(f"  Target images : ALL (6 assets)")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Check which appids need downloading
    # ------------------------------------------------------------------
    needs_download = []
    for appid in actual_appids:
        if args.force_download:
            needs_download.append(appid)
            print(f"\n[Check] App {appid}: --force-download set, will re-download.")
        else:
            missing = check_assets(appid, downloads_dir)
            if missing:
                print(f"\n[Check] App {appid}: MISSING {missing}")
                needs_download.append(appid)
            else:
                print(f"\n[Check] App {appid}: all required assets found. Skipping download.")

    # ------------------------------------------------------------------
    # Step 2: Download missing assets
    # ------------------------------------------------------------------
    if needs_download:
        print(f"\n[Download] Fetching assets for: {needs_download}")
        download_assets_for(needs_download, downloads_dir)

        # Verify after download
        all_ok = True
        for appid in actual_appids:
            missing = check_assets(appid, downloads_dir)
            if missing:
                print(f"[!] After download, App {appid} is still missing: {missing}")
                all_ok = False
        if not all_ok:
            print("\n[!] Cannot generate bundle — required files are still missing.")
            sys.exit(1)
    else:
        print("\n[Check] All required assets already present.")

    # ------------------------------------------------------------------
    # Step 3: Generate bundle assets
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  Generating bundle images...")
    print("=" * 60)
    generate_bundle(actual_appids, downloads_dir, output_dir,
                    rotation_deg=args.rotation,
                    layout=args.layout,
                    logo_scales=logo_scales,
                    bg_offsets=bg_offsets,
                    only_images=only_images)

    bundle_subfolder = f"bundle_{'_'.join(actual_appids)}"
    print("\n[Done] Bundle generation complete!")
    print(f"        -> {output_dir / bundle_subfolder}")


if __name__ == "__main__":
    main()
