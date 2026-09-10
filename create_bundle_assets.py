"""
create_bundle_assets.py

Creates Steam bundle assets by combining two games library_hero_2x.jpg images:
  - Diagonal split (left = Game 1, right = Game 2)
  - Each games logo_2x.png centered in its half
  - Generates all required bundle resolutions

Usage:
    python create_bundle_assets.py <appid1> <appid2> [--downloads-dir downloads] [--output-dir output]

Example:
    python create_bundle_assets.py 2666510 570
"""

import argparse
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------------------
# Bundle asset specs  (name, width, height)
# ---------------------------------------------------------------------------
BUNDLE_SPECS = [
    ("package_header",   1414, 464),
    ("header_capsule",    920, 430),
    ("small_capsule",     462, 174),
    ("main_capsule",     1232, 706),
    ("vertical_capsule",  748, 896),
    ("page_background",  1438, 810),
]

VALID_IMAGE_NAMES = [spec[0] for spec in BUNDLE_SPECS]


def resolve_target_specs(only_inputs: list[str] | None) -> list[tuple[str, int, int]]:
    """
    Filter BUNDLE_SPECS based on user request.
    If only_inputs is empty or None, returns all BUNDLE_SPECS.
    Matches leniently against spec names (e.g. 'vertical_capsule only', 'vertical_capsule', 'vertical').
    """
    if not only_inputs:
        return BUNDLE_SPECS

    matched_specs = []
    for item in only_inputs:
        tokens = [t.strip() for t in item.split(",") if t.strip()] if "," in item else [item.strip()]
        for raw in tokens:
            cleaned = raw.lower().strip()
            # Remove words like 'only'
            cleaned = re.sub(r"\bonly\b", "", cleaned).strip()
            # Remove file extensions like .jpg or .png
            cleaned = re.sub(r"\.(jpe?g|png)$", "", cleaned).strip()
            # Remove dimension suffixes like _748x896 or 748x896
            cleaned = re.sub(r"_?\d+x\d+$", "", cleaned).strip()
            cleaned = cleaned.replace("-", "_").replace(" ", "_").strip("_")

            if not cleaned:
                continue

            # 1. Exact match first
            found = [s for s in BUNDLE_SPECS if s[0] == cleaned]
            # 2. Prefix match
            if not found:
                found = [s for s in BUNDLE_SPECS if s[0].startswith(cleaned)]
            # 3. Substring match
            if not found:
                found = [s for s in BUNDLE_SPECS if cleaned in s[0]]

            if not found:
                valid_str = ", ".join(f"'{name}'" for name in VALID_IMAGE_NAMES)
                raise ValueError(
                    f"Unknown image name '{raw}'. Valid names are: {valid_str}"
                )

            for s in found:
                if s not in matched_specs:
                    matched_specs.append(s)

    return matched_specs if matched_specs else BUNDLE_SPECS


def extract_only_args(only_list: list[str] | None, extra_args: list[str] | None, unknown_args: list[str] | None = None) -> list[str]:
    """Combine --only flags with any trailing positional arguments like 'vertical_capsule only'."""
    combined = list(only_list or [])
    if extra_args:
        raw_extra = " ".join(extra_args).strip()
        if raw_extra:
            combined.append(raw_extra)
    if unknown_args:
        tokens = [u.lstrip("-") for u in unknown_args if u.strip()]
        raw_unknown = " ".join(tokens).strip()
        if raw_unknown:
            combined.append(raw_unknown)
    return combined

# Base diagonal angle (fraction of width shifted over full height).
# Corresponds to ~8.5 degrees from vertical at the 920x430 reference resolution.
BASE_DIAGONAL_ANGLE = 0.07

# Reference resolution used for consistent degree-based rotation across all sizes.
_REF_W, _REF_H = 920, 430


def compute_effective_angle(rotation_deg: float = 0.0) -> float:
    """
    Convert a rotation offset in degrees into the angle-fraction used by the
    diagonal mask, calibrated to the reference resolution (_REF_W x _REF_H).

    rotation_deg=0   -> BASE_DIAGONAL_ANGLE (unchanged)
    rotation_deg=+N  -> steeper lean (line tilts more right at bottom)
    rotation_deg=-N  -> shallower lean (approaching vertical at 0)

    Maximum allowed absolute rotation is 80 degrees to avoid degenerate lines.
    """
    rotation_deg = max(-80.0, min(80.0, rotation_deg))
    base_rad = math.atan(BASE_DIAGONAL_ANGLE * _REF_W / _REF_H)
    new_rad  = base_rad + math.radians(rotation_deg)
    # Clamp: keep the resulting fraction positive (always lean same direction)
    return max(0.0, math.tan(new_rad) * _REF_H / _REF_W)


def fit_cover(img, target_w, target_h, offset_x=0.0, offset_y=0.0):
    """
    Resize and crop `img` to cover (target_w x target_h).
    offset_x: horizontal shift in pixels (+ moves image right, - moves left).
    offset_y: vertical shift in pixels (+ moves image down, - moves up).
    Automatically expands the scale so non-zero shifts never reveal black borders.
    """
    req_w = target_w + 2 * abs(offset_x)
    req_h = target_h + 2 * abs(offset_y)
    scale = max(req_w / img.width, req_h / img.height)
    new_w = max(int(img.width * scale), int(req_w))
    new_h = max(int(img.height * scale), int(req_h))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = (new_w - target_w) // 2 - int(offset_x)
    top  = (new_h - target_h) // 2 - int(offset_y)

    left = max(0, min(left, new_w - target_w))
    top  = max(0, min(top,  new_h - target_h))

    return resized.crop((left, top, left + target_w, top + target_h))


def fit_contain_logo(logo, max_w, max_h, pad_frac=0.10, extra_scale=1.0):
    """
    Scale logo to fit within (max_w x max_h) with padding.
    extra_scale: additional multiplier on top of the fit-contain scale
                 (e.g. 1.2 makes the logo 20% larger than the default fit).
    """
    pad_w = int(max_w * pad_frac)
    pad_h = int(max_h * pad_frac)
    avail_w = max_w - 2 * pad_w
    avail_h = max_h - 2 * pad_h
    scale = min(avail_w / logo.width, avail_h / logo.height) * extra_scale
    new_w = max(1, int(logo.width  * scale))
    new_h = max(1, int(logo.height * scale))
    return logo.resize((new_w, new_h), Image.Resampling.LANCZOS)


def build_diagonal_mask(width, height, angle=None, feather=0):
    if angle is None:
        angle = BASE_DIAGONAL_ANGLE
    arr = np.zeros((height, width), dtype=np.float32)
    cx  = width / 2.0
    xs  = np.arange(width, dtype=np.float32)
    for y in range(height):
        t = y / max(height - 1, 1)
        diag_x = cx + (t - 0.5) * angle * width
        arr[y, :] = np.where(xs < diag_x, 255.0, 0.0)
    mask = Image.fromarray(arr.astype(np.uint8), mode="L")
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    return mask


def draw_divider(canvas, angle=None, color=(255, 255, 255), thickness=3, alpha=180):
    if angle is None:
        angle = BASE_DIAGONAL_ANGLE
    w, h  = canvas.size
    cx    = w / 2.0
    x_top = cx - (angle * w) / 2
    x_bot = cx + (angle * w) / 2
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)
    draw.line([(x_top, 0), (x_bot, h)], fill=color + (alpha,), width=thickness)
    if canvas.mode != "RGBA":
        canvas = canvas.convert("RGBA")
    canvas = Image.alpha_composite(canvas, overlay)
    return canvas.convert("RGB")


def drop_shadow(logo, offset=(4, 4), blur=8, shadow_color=(0, 0, 0, 160)):
    if logo.mode == "RGBA":
        alpha = logo.split()[3]
    else:
        alpha = Image.new("L", logo.size, 255)
    shadow_base = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    shadow_arr  = np.array(alpha, dtype=np.float32) * (shadow_color[3] / 255.0)
    shadow_mask = Image.fromarray(shadow_arr.astype(np.uint8), mode="L")
    shadow_colored = Image.new("RGBA", logo.size, shadow_color[:3] + (0,))
    shadow_colored.putalpha(shadow_mask)
    shadow_colored = shadow_colored.filter(ImageFilter.GaussianBlur(radius=blur))
    w = logo.width  + abs(offset[0]) + blur * 2
    h = logo.height + abs(offset[1]) + blur * 2
    composed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ox = blur + max(0,  offset[0])
    oy = blur + max(0,  offset[1])
    sx = blur + max(0, -offset[0])
    sy = blur + max(0, -offset[1])
    composed.paste(shadow_colored, (ox, oy), shadow_colored)
    if logo.mode == "RGBA":
        composed.paste(logo, (sx, sy), logo)
    else:
        composed.paste(logo, (sx, sy))
    return composed


def paste_logo_centered(canvas, logo, cx, cy):
    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")
    lx = max(0, min(cx - logo.width  // 2, canvas.width  - logo.width))
    ly = max(0, min(cy - logo.height // 2, canvas.height - logo.height))
    canvas.paste(logo, (lx, ly), logo)


def make_bundle_image(hero1, hero2, logo1, logo2, total_w, total_h,
                      feather=0, diagonal_angle=None,
                      logo_scale1=1.0, logo_scale2=1.0,
                      offset1=(0.0, 0.0), offset2=(0.0, 0.0)):
    """
    Composite two game hero images with a diagonal split and centered logos.

    diagonal_angle : pre-computed angle fraction (output of compute_effective_angle).
                     None falls back to BASE_DIAGONAL_ANGLE.
    logo_scale1/2  : extra scale multiplier for each game's logo (default 1.0).
    offset1/2      : (dx, dy) pixel shift for background hero1 and hero2.
    """
    if diagonal_angle is None:
        diagonal_angle = BASE_DIAGONAL_ANGLE

    bg1  = fit_cover(hero1, total_w, total_h, offset_x=offset1[0], offset_y=offset1[1])
    bg2  = fit_cover(hero2, total_w, total_h, offset_x=offset2[0], offset_y=offset2[1])
    mask = build_diagonal_mask(total_w, total_h, angle=diagonal_angle, feather=feather)
    canvas = Image.composite(bg1, bg2, mask).convert("RGBA")

    canvas = draw_divider(canvas, angle=diagonal_angle)

    half_w     = total_w // 2
    max_logo_w = int(half_w  * 0.85)
    max_logo_h = int(total_h * 0.75)

    l1 = fit_contain_logo(logo1, max_logo_w, max_logo_h, extra_scale=logo_scale1)
    l1 = drop_shadow(l1)
    paste_logo_centered(canvas, l1, cx=half_w // 2,          cy=total_h // 2)

    l2 = fit_contain_logo(logo2, max_logo_w, max_logo_h, extra_scale=logo_scale2)
    l2 = drop_shadow(l2)
    paste_logo_centered(canvas, l2, cx=half_w + half_w // 2, cy=total_h // 2)

    return canvas.convert("RGB")


def process(app1, app2, downloads_dir, output_dir,
            rotation_deg=0.0, logo_scales=None, bg_offsets=None,
            only_images=None):
    """
    Generate bundle assets for two Steam apps.

    rotation_deg : degrees to rotate the diagonal line on top of the default lean.
                   0 = default, positive = steeper, negative = shallower/vertical.
    logo_scales  : dict mapping str(appid) -> float multiplier for logo size.
                   e.g. {'3681780': 1.1, '2666510': 1.2}
    bg_offsets   : dict mapping str(appid) -> (dx, dy) pixel shift on reference resolution (920x430).
                   e.g. {'3681780': (0.0, 50.0)} to move background down 50px.
    only_images  : list of image names (or expressions like 'vertical_capsule only')
                   to generate only those specific assets instead of all 6.
    """
    if logo_scales is None:
        logo_scales = {}
    if bg_offsets is None:
        bg_offsets = {}

    target_specs = resolve_target_specs(only_images)

    dir1 = downloads_dir / str(app1)
    dir2 = downloads_dir / str(app2)

    for d, appid in [(dir1, app1), (dir2, app2)]:
        for fname in ["library_hero_2x.jpg", "logo_2x.png"]:
            p = d / fname
            if not p.exists():
                print(f"ERROR: Missing {p}", file=sys.stderr)
                sys.exit(1)

    print(f"Loading assets for app {app1} ...")
    hero1 = Image.open(str(dir1 / "library_hero_2x.jpg")).convert("RGB")
    logo1 = Image.open(str(dir1 / "logo_2x.png")).convert("RGBA")

    print(f"Loading assets for app {app2} ...")
    hero2 = Image.open(str(dir2 / "library_hero_2x.jpg")).convert("RGB")
    logo2 = Image.open(str(dir2 / "logo_2x.png")).convert("RGBA")

    # Resolve effective diagonal angle from rotation offset
    eff_angle   = compute_effective_angle(rotation_deg)
    logo_scale1 = float(logo_scales.get(str(app1), 1.0))
    logo_scale2 = float(logo_scales.get(str(app2), 1.0))
    raw_off1    = bg_offsets.get(str(app1), (0.0, 0.0))
    raw_off2    = bg_offsets.get(str(app2), (0.0, 0.0))

    print(f"\n  Diagonal angle : {eff_angle:.4f}  (rotation offset: {rotation_deg:+.1f} deg)")
    print(f"  Logo scale     : app {app1} x{logo_scale1:.2f},  app {app2} x{logo_scale2:.2f}")
    if raw_off1 != (0.0, 0.0) or raw_off2 != (0.0, 0.0):
        print(f"  BG shift (ref) : app {app1} (x={raw_off1[0]:+.0f}px, y={raw_off1[1]:+.0f}px),  "
              f"app {app2} (x={raw_off2[0]:+.0f}px, y={raw_off2[1]:+.0f}px)")
    if len(target_specs) < len(BUNDLE_SPECS):
        spec_names = ", ".join(s[0] for s in target_specs)
        print(f"  Target images  : ONLY [{spec_names}]")
    else:
        print(f"  Target images  : ALL ({len(BUNDLE_SPECS)} assets)")

    out_folder = output_dir / f"bundle_{app1}_{app2}"
    out_folder.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating bundle assets -> {out_folder}\n")

    for spec_name, w, h in target_specs:
        feather  = max(2, int(min(w, h) * 0.01))
        # Scale offsets proportionally to asset size relative to reference resolution
        off1 = (raw_off1[0] * (w / _REF_W), raw_off1[1] * (h / _REF_H))
        off2 = (raw_off2[0] * (w / _REF_W), raw_off2[1] * (h / _REF_H))
        img      = make_bundle_image(
            hero1, hero2, logo1, logo2, w, h,
            feather=feather,
            diagonal_angle=eff_angle,
            logo_scale1=logo_scale1,
            logo_scale2=logo_scale2,
            offset1=off1,
            offset2=off2,
        )
        out_path = out_folder / f"{spec_name}_{w}x{h}.jpg"
        img.save(str(out_path), "JPEG", quality=93, subsampling=0)
        print(f"  OK  {spec_name:<22}  {w}x{h}  ->  {out_path.name}")

    if len(target_specs) < len(BUNDLE_SPECS):
        print(f"\nDone! Generated {len(target_specs)} asset(s) in: {out_folder}")
    else:
        print(f"\nDone! All assets saved to: {out_folder}")


def _parse_scale(value: str) -> tuple[str, float]:
    """Parse 'appidxFACTOR' into (appid_str, factor_float). e.g. '3681780x1.2' -> ('3681780', 1.2)"""
    try:
        parts = value.split("x", 1)
        if len(parts) != 2:
            raise ValueError()
        return parts[0].strip(), float(parts[1].strip())
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(
            f"Invalid scale format '{value}'. Expected '<appid>x<factor>' e.g. 3681780x1.2"
        )


def parse_direction_token(direction: str, tokens) -> tuple[str, float]:
    raw = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    raw = raw.strip()
    raw = re.sub(r"^(up|down|left|right)[:\s]+", "", raw, flags=re.IGNORECASE)
    m = re.match(r"^(\d+)[\s:x,]*([+-]?\d+(?:\.\d+)?)$", raw.strip())
    if not m:
        raise ValueError(f"Cannot parse --{direction} value '{raw}'. Expected e.g. '{direction}: 3681780 +50' or '3681780 +50'")
    return m.group(1), float(m.group(2))


def parse_move_token(tokens) -> tuple[str, float, float]:
    raw = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    raw = raw.strip()
    m_dir = re.match(r"^(up|down|left|right)[:\s]+(\d+)[\s:x,]*([+-]?\d+(?:\.\d+)?)$", raw, re.IGNORECASE)
    if m_dir:
        direction = m_dir.group(1).lower()
        appid = m_dir.group(2)
        amount = float(m_dir.group(3))
        dx, dy = 0.0, 0.0
        if direction == "down": dy = amount
        elif direction == "up": dy = -amount
        elif direction == "right": dx = amount
        elif direction == "left": dx = -amount
        return appid, dx, dy
    m_xy = re.match(r"^(\d+)[\s,x]+([+-]?\d+(?:\.\d+)?)[\s,x]+([+-]?\d+(?:\.\d+)?)$", raw)
    if m_xy:
        return m_xy.group(1), float(m_xy.group(2)), float(m_xy.group(3))
    raise ValueError(f"Cannot parse --move value '{raw}'. Expected e.g. 'down: 3681780 +50' or '3681780 0 50'")


def build_bg_offsets(up_list=None, down_list=None, left_list=None, right_list=None, move_list=None) -> dict[str, tuple[float, float]]:
    offsets: dict[str, list[float]] = {}

    def _get(aid: str) -> list[float]:
        if aid not in offsets:
            offsets[aid] = [0.0, 0.0]
        return offsets[aid]

    for item in (up_list or []):
        aid, val = parse_direction_token("up", item)
        _get(aid)[1] -= val

    for item in (down_list or []):
        aid, val = parse_direction_token("down", item)
        _get(aid)[1] += val

    for item in (left_list or []):
        aid, val = parse_direction_token("left", item)
        _get(aid)[0] -= val

    for item in (right_list or []):
        aid, val = parse_direction_token("right", item)
        _get(aid)[0] += val

    for item in (move_list or []):
        aid, dx, dy = parse_move_token(item)
        _get(aid)[0] += dx
        _get(aid)[1] += dy

    return {aid: (vals[0], vals[1]) for aid, vals in offsets.items()}


def main():
    parser = argparse.ArgumentParser(
        description="Create Steam bundle assets from two game app IDs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_bundle_assets.py 2666510 570
  python create_bundle_assets.py 2666510 570 --rotation 20
  python create_bundle_assets.py 2666510 570 --scale 2666510x1.2 --scale 570x0.9
  python create_bundle_assets.py 3681780 2666510 --down "3681780 +50" --up "2666510 +20"
        """,
    )
    parser.add_argument("appid1", help="First game Steam App ID")
    parser.add_argument("appid2", help="Second game Steam App ID")
    parser.add_argument("--downloads-dir", default="downloads",
                        help="Base folder for per-app assets (default: downloads)")
    parser.add_argument("--output-dir", default="output",
                        help="Output folder for bundle images (default: output)")
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

    only_images = extract_only_args(args.only_images, args.extra_args, unknown)

    logo_scales = {}
    for s in args.scales:
        appid_str, factor = _parse_scale(s)
        logo_scales[appid_str] = factor

    bg_offsets = build_bg_offsets(
        up_list=args.up,
        down_list=args.down,
        left_list=args.left,
        right_list=args.right,
        move_list=args.move,
    )

    base_dir      = Path(__file__).parent
    downloads_dir = base_dir / args.downloads_dir
    output_dir    = base_dir / args.output_dir

    process(args.appid1, args.appid2, downloads_dir, output_dir,
            rotation_deg=args.rotation, logo_scales=logo_scales,
            bg_offsets=bg_offsets, only_images=only_images)


if __name__ == "__main__":
    main()

