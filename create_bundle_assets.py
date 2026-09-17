"""
create_bundle_assets.py

Creates Steam bundle assets by combining multiple games' library_hero_2x.jpg and logo_2x.png images.
Supports 2, 3, 4, 5, 6 or more games with flexible layouts:
  - 'auto'       : Smart default layout based on asset aspect ratio (slanted strips for wide assets, grid/rows for vertical capsule).
  - 'strips'     : Parallel vertical/slanted slices across all assets.
  - 'grid'       : Balanced 2D grid cells (e.g. 2x2 for 4 games, 3x2 for 6 games, 3+2 for 5 games on wide assets; 2x3 on vertical assets).
  - 'horizontal' : Stacked horizontal slices (especially clean on vertical capsule).

Generates all 6 standard Steam bundle resolutions:
  1. package_header   (1414 x 464)
  2. header_capsule    (920 x 430)
  3. small_capsule     (462 x 174)
  4. main_capsule     (1232 x 706)
  5. vertical_capsule  (748 x 896)
  6. page_background  (1438 x 810)

Usage:
    python create_bundle_assets.py <appid1> <appid2> [<appid3> ...] [options]

Examples:
    python create_bundle_assets.py 2666510 570
    python create_bundle_assets.py 3681780 2666510 3419430 570
    python create_bundle_assets.py 3681780 2666510 3419430 570 730 --layout strips
    python create_bundle_assets.py 3681780 2666510 3419430 570 730 440 --layout grid
"""

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, PngImagePlugin

# Allow loading large PNG files with large text chunks or high resolutions
PngImagePlugin.MAX_TEXT_CHUNK = 100 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = None

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
    # Keep the resulting fraction positive (always lean same direction)
    return max(0.0, math.tan(new_rad) * _REF_H / _REF_W)


def fit_cover(img: Image.Image, target_w: int, target_h: int, offset_x: float = 0.0, offset_y: float = 0.0) -> Image.Image:
    """
    Resize and crop `img` to cover (target_w x target_h).
    offset_x: horizontal shift in pixels (+ moves image right, - moves left).
    offset_y: vertical shift in pixels (+ moves image down, - moves up).
    Automatically expands the scale so non-zero shifts never reveal black borders.
    """
    target_w = max(1, int(target_w))
    target_h = max(1, int(target_h))
    req_w = target_w + 2 * abs(offset_x)
    req_h = target_h + 2 * abs(offset_y)
    scale = max(req_w / max(1, img.width), req_h / max(1, img.height))
    new_w = max(int(img.width * scale), int(req_w))
    new_h = max(int(img.height * scale), int(req_h))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = (new_w - target_w) // 2 - int(offset_x)
    top  = (new_h - target_h) // 2 - int(offset_y)

    left = max(0, min(left, new_w - target_w))
    top  = max(0, min(top,  new_h - target_h))

    return resized.crop((left, top, left + target_w, top + target_h))


def fit_contain_logo(logo: Image.Image, max_w: int, max_h: int, pad_frac: float = 0.08, extra_scale: float = 1.0) -> Image.Image:
    """
    Scale logo to fit within (max_w x max_h) with padding.
    extra_scale: additional multiplier on top of the fit-contain scale
                 (e.g. 1.2 makes the logo 20% larger than the default fit).
    """
    max_w = max(1, int(max_w))
    max_h = max(1, int(max_h))
    pad_w = int(max_w * pad_frac)
    pad_h = int(max_h * pad_frac)
    avail_w = max(1, max_w - 2 * pad_w)
    avail_h = max(1, max_h - 2 * pad_h)
    scale = min(avail_w / max(1, logo.width), avail_h / max(1, logo.height)) * extra_scale
    new_w = max(1, int(logo.width  * scale))
    new_h = max(1, int(logo.height * scale))
    return logo.resize((new_w, new_h), Image.Resampling.LANCZOS)


def drop_shadow(logo: Image.Image, offset=(4, 4), blur=8, shadow_color=(0, 0, 0, 160)) -> Image.Image:
    """Add smooth Gaussian blurred drop shadow to an RGBA logo."""
    if logo.mode == "RGBA":
        alpha = logo.split()[3]
    else:
        alpha = Image.new("L", logo.size, 255)
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


def paste_logo_centered(canvas: Image.Image, logo: Image.Image, cx: int, cy: int) -> None:
    """Paste RGBA logo centered around (cx, cy) on canvas."""
    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")
    lx = int(cx - logo.width  // 2)
    ly = int(cy - logo.height // 2)
    canvas.paste(logo, (lx, ly), logo)


# ---------------------------------------------------------------------------
# Layout Renderers
# ---------------------------------------------------------------------------

def render_strips_layout(heroes: list[Image.Image],
                         logos: list[Image.Image],
                         total_w: int,
                         total_h: int,
                         diagonal_angle: float,
                         logo_scales: list[float],
                         offsets: list[tuple[float, float]],
                         feather: int = 2,
                         divider_thickness: int = 3,
                         divider_color: tuple = (255, 255, 255),
                         divider_alpha: int = 180) -> Image.Image:
    """
    Render N games as parallel slanted/vertical strips across the canvas.
    When N=2, this produces the exact same diagonal split as the original 2-game tool.
    """
    n = len(heroes)
    bin_width = total_w / float(n)

    # 1. Build background composite with feathered seams
    ys = np.arange(total_h, dtype=np.float32)
    t = ys / max(total_h - 1, 1)
    slant = ((t - 0.5) * diagonal_angle * total_w).reshape(total_h, 1)
    xs = np.arange(total_w, dtype=np.float32).reshape(1, total_w)
    x_adj = xs - slant

    canvas = fit_cover(heroes[0], total_w, total_h, offset_x=offsets[0][0], offset_y=offsets[0][1]).convert("RGBA")

    for k in range(1, n):
        seam_x = k * bin_width
        dist = x_adj - seam_x
        mask_arr = np.where(dist >= 0, 255.0, 0.0)
        mask = Image.fromarray(mask_arr.astype(np.uint8), mode="L")
        if feather > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

        bg_k = fit_cover(heroes[k], total_w, total_h, offset_x=offsets[k][0], offset_y=offsets[k][1]).convert("RGBA")
        canvas.paste(bg_k, (0, 0), mask)

    # 2. Draw divider lines
    overlay = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(1, n):
        center_x = i * bin_width
        x_top = center_x - (diagonal_angle * total_w) / 2.0
        x_bot = center_x + (diagonal_angle * total_w) / 2.0
        draw.line([(x_top, 0), (x_bot, total_h)], fill=divider_color + (divider_alpha,), width=divider_thickness)

    canvas = Image.alpha_composite(canvas, overlay)

    # 3. Fit and paste logos in each strip
    max_logo_w = int(bin_width * 0.85)
    max_logo_h = int(total_h * 0.75)

    for k in range(n):
        cx = int((k + 0.5) * bin_width)
        cy = total_h // 2
        l = fit_contain_logo(logos[k], max_logo_w, max_logo_h, extra_scale=logo_scales[k])
        l = drop_shadow(l)
        paste_logo_centered(canvas, l, cx, cy)

    return canvas.convert("RGB")


def render_grid_layout(heroes: list[Image.Image],
                       logos: list[Image.Image],
                       total_w: int,
                       total_h: int,
                       logo_scales: list[float],
                       offsets: list[tuple[float, float]],
                       divider_thickness: int = 3,
                       divider_color: tuple = (255, 255, 255),
                       divider_alpha: int = 180) -> Image.Image:
    """
    Render games in a structured 2D grid collage.
    - 4 games: 2x2 grid
    - 6 games: 3x2 on wide, 2x3 on tall
    - 5 games: 3 top + 2 bottom on wide, 2 top + 2 middle + 1 bottom on tall
    - 3 games: 1 left + 2 stacked right on wide, 3 stacked on tall
    """
    n = len(heroes)
    is_wide = total_w >= total_h

    # Calculate cell bounding boxes: [(x0, y0, x1, y1), ...]
    cells = []
    dividers = []  # List of lines: [((x0, y0), (x1, y1)), ...]

    if n == 4:
        hw, hh = total_w // 2, total_h // 2
        cells = [
            (0, 0, hw, hh),
            (hw, 0, total_w, hh),
            (0, hh, hw, total_h),
            (hw, hh, total_w, total_h),
        ]
        dividers = [
            ((0, hh), (total_w, hh)),
            ((hw, 0), (hw, total_h)),
        ]
    elif n == 6:
        if is_wide:
            col_w, hh = total_w // 3, total_h // 2
            for r in range(2):
                y0 = r * hh
                y1 = total_h if r == 1 else (r + 1) * hh
                for c in range(3):
                    x0 = c * col_w
                    x1 = total_w if c == 2 else (c + 1) * col_w
                    cells.append((x0, y0, x1, y1))
            dividers = [
                ((0, hh), (total_w, hh)),
                ((col_w, 0), (col_w, total_h)),
                ((col_w * 2, 0), (col_w * 2, total_h)),
            ]
        else:
            hw, row_h = total_w // 2, total_h // 3
            for r in range(3):
                y0 = r * row_h
                y1 = total_h if r == 2 else (r + 1) * row_h
                for c in range(2):
                    x0 = c * hw
                    x1 = total_w if c == 1 else (c + 1) * hw
                    cells.append((x0, y0, x1, y1))
            dividers = [
                ((hw, 0), (hw, total_h)),
                ((0, row_h), (total_w, row_h)),
                ((0, row_h * 2), (total_w, row_h * 2)),
            ]
    elif n == 5:
        if is_wide:
            hh = total_h // 2
            # Row 0: 3 games
            col_w0 = total_w // 3
            cells.append((0, 0, col_w0, hh))
            cells.append((col_w0, 0, col_w0 * 2, hh))
            cells.append((col_w0 * 2, 0, total_w, hh))
            # Row 1: 2 games
            hw = total_w // 2
            cells.append((0, hh, hw, total_h))
            cells.append((hw, hh, total_w, total_h))
            dividers = [
                ((0, hh), (total_w, hh)),
                ((col_w0, 0), (col_w0, hh)),
                ((col_w0 * 2, 0), (col_w0 * 2, hh)),
                ((hw, hh), (hw, total_h)),
            ]
        else:
            row_h = total_h // 3
            hw = total_w // 2
            # Row 0: 2 games
            cells.append((0, 0, hw, row_h))
            cells.append((hw, 0, total_w, row_h))
            # Row 1: 2 games
            cells.append((0, row_h, hw, row_h * 2))
            cells.append((hw, row_h, total_w, row_h * 2))
            # Row 2: 1 featured game
            cells.append((0, row_h * 2, total_w, total_h))
            dividers = [
                ((0, row_h), (total_w, row_h)),
                ((0, row_h * 2), (total_w, row_h * 2)),
                ((hw, 0), (hw, row_h * 2)),
            ]
    elif n == 3:
        if is_wide:
            hw, hh = total_w // 2, total_h // 2
            cells = [
                (0, 0, hw, total_h),
                (hw, 0, total_w, hh),
                (hw, hh, total_w, total_h),
            ]
            dividers = [
                ((hw, 0), (hw, total_h)),
                ((hw, hh), (total_w, hh)),
            ]
        else:
            row_h = total_h // 3
            cells = [
                (0, 0, total_w, row_h),
                (0, row_h, total_w, row_h * 2),
                (0, row_h * 2, total_w, total_h),
            ]
            dividers = [
                ((0, row_h), (total_w, row_h)),
                ((0, row_h * 2), (total_w, row_h * 2)),
            ]
    else:
        # Fallback dynamic grid for arbitrary N
        cols = math.ceil(math.sqrt(n)) if is_wide else math.floor(math.sqrt(n))
        cols = max(1, cols)
        rows = math.ceil(n / cols)
        col_w = total_w // cols
        row_h = total_h // rows
        for idx in range(n):
            r = idx // cols
            c = idx % cols
            x0 = c * col_w
            y0 = r * row_h
            x1 = total_w if c == cols - 1 else (c + 1) * col_w
            y1 = total_h if r == rows - 1 else (r + 1) * row_h
            cells.append((x0, y0, x1, y1))
        # Dividers
        for c in range(1, cols):
            dividers.append(((c * col_w, 0), (c * col_w, total_h)))
        for r in range(1, rows):
            dividers.append(((0, r * row_h), (total_w, r * row_h)))

    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 255))

    # Paste background covers for each cell
    for idx, (x0, y0, x1, y1) in enumerate(cells[:n]):
        cw = x1 - x0
        ch = y1 - y0
        bg = fit_cover(heroes[idx], cw, ch, offset_x=offsets[idx][0], offset_y=offsets[idx][1])
        canvas.paste(bg, (x0, y0))

    # Draw divider lines
    overlay = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for p0, p1 in dividers:
        draw.line([p0, p1], fill=divider_color + (divider_alpha,), width=divider_thickness)
    canvas = Image.alpha_composite(canvas, overlay)

    # Paste logos centered in each cell
    for idx, (x0, y0, x1, y1) in enumerate(cells[:n]):
        cw = x1 - x0
        ch = y1 - y0
        cx = x0 + cw // 2
        cy = y0 + ch // 2
        max_lw = int(cw * 0.82)
        max_lh = int(ch * 0.75)
        l = fit_contain_logo(logos[idx], max_lw, max_lh, extra_scale=logo_scales[idx])
        l = drop_shadow(l)
        paste_logo_centered(canvas, l, cx, cy)

    return canvas.convert("RGB")


def render_horizontal_layout(heroes: list[Image.Image],
                             logos: list[Image.Image],
                             total_w: int,
                             total_h: int,
                             logo_scales: list[float],
                             offsets: list[tuple[float, float]],
                             divider_thickness: int = 3,
                             divider_color: tuple = (255, 255, 255),
                             divider_alpha: int = 180) -> Image.Image:
    """
    Render N games as stacked horizontal slices.
    Particularly useful for tall assets like vertical_capsule.
    """
    n = len(heroes)
    row_h = total_h / float(n)

    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 255))
    overlay = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for k in range(n):
        y0 = int(k * row_h)
        y1 = total_h if k == n - 1 else int((k + 1) * row_h)
        ch = y1 - y0

        bg = fit_cover(heroes[k], total_w, ch, offset_x=offsets[k][0], offset_y=offsets[k][1])
        canvas.paste(bg, (0, y0))

        if k < n - 1:
            draw.line([(0, y1), (total_w, y1)], fill=divider_color + (divider_alpha,), width=divider_thickness)

        max_lw = int(total_w * 0.70)
        max_lh = int(ch * 0.78)
        l = fit_contain_logo(logos[k], max_lw, max_lh, extra_scale=logo_scales[k])
        l = drop_shadow(l)
        paste_logo_centered(canvas, l, total_w // 2, y0 + ch // 2)

    canvas = Image.alpha_composite(canvas, overlay)
    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# High-Level Bundle Image Generation
# ---------------------------------------------------------------------------

def make_multi_bundle_image(heroes: list[Image.Image],
                            logos: list[Image.Image],
                            total_w: int,
                            total_h: int,
                            layout: str = "auto",
                            rotation_deg: float = 0.0,
                            logo_scales: list[float] | None = None,
                            offsets: list[tuple[float, float]] | None = None,
                            feather: int = 2) -> Image.Image:
    """
    Main generator dispatching to strips, grid, or horizontal layouts.
    """
    n = len(heroes)
    if n < 2:
        raise ValueError(f"make_multi_bundle_image requires at least 2 games, got {n}")

    if logo_scales is None:
        logo_scales = [1.0] * n
    else:
        logo_scales = list(logo_scales) + [1.0] * max(0, n - len(logo_scales))

    if offsets is None:
        offsets = [(0.0, 0.0)] * n
    else:
        offsets = list(offsets) + [(0.0, 0.0)] * max(0, n - len(offsets))

    eff_angle = compute_effective_angle(rotation_deg)

    # Determine effective layout if 'auto'
    chosen_layout = layout.lower().strip()
    if chosen_layout == "auto":
        is_tall = total_w < total_h  # e.g. vertical_capsule (748x896)
        if n == 2:
            chosen_layout = "strips"
        elif n == 3:
            chosen_layout = "horizontal" if is_tall else "strips"
        elif n in (4, 5, 6):
            chosen_layout = "grid" if is_tall else "strips"
        else:
            chosen_layout = "grid" if is_tall else "strips"

    if chosen_layout == "grid":
        return render_grid_layout(heroes, logos, total_w, total_h,
                                  logo_scales=logo_scales, offsets=offsets)
    elif chosen_layout == "horizontal":
        return render_horizontal_layout(heroes, logos, total_w, total_h,
                                        logo_scales=logo_scales, offsets=offsets)
    else:
        # Default: strips
        return render_strips_layout(heroes, logos, total_w, total_h,
                                    diagonal_angle=eff_angle,
                                    logo_scales=logo_scales,
                                    offsets=offsets,
                                    feather=feather)


def make_bundle_image(hero1: Image.Image, hero2: Image.Image,
                      logo1: Image.Image, logo2: Image.Image,
                      total_w: int, total_h: int,
                      feather: int = 0, diagonal_angle: float | None = None,
                      logo_scale1: float = 1.0, logo_scale2: float = 1.0,
                      offset1: tuple[float, float] = (0.0, 0.0),
                      offset2: tuple[float, float] = (0.0, 0.0)) -> Image.Image:
    """Backward-compatible 2-game wrapper."""
    angle = diagonal_angle if diagonal_angle is not None else BASE_DIAGONAL_ANGLE
    return render_strips_layout(
        heroes=[hero1, hero2],
        logos=[logo1, logo2],
        total_w=total_w,
        total_h=total_h,
        diagonal_angle=angle,
        logo_scales=[logo_scale1, logo_scale2],
        offsets=[offset1, offset2],
        feather=feather,
    )


# ---------------------------------------------------------------------------
# Main Process Function
# ---------------------------------------------------------------------------

def process(*args, **kwargs):
    """
    Generate bundle assets for multiple Steam apps.
    Supports flexible signatures:
      process(appids_list, downloads_dir, output_dir, ...)
      process(app1, app2, downloads_dir, output_dir, ...)
      process(appids=[...], downloads_dir=..., output_dir=..., ...)
    """
    # Parse positional vs keyword arguments flexibly
    appids = []
    rotation_deg = kwargs.get("rotation_deg", 0.0)
    layout = kwargs.get("layout", "auto")
    logo_scales = kwargs.get("logo_scales") or {}
    bg_offsets = kwargs.get("bg_offsets") or {}
    only_images = kwargs.get("only_images")

    if "appids" in kwargs:
        appids = [str(a) for a in kwargs["appids"]]
        downloads_dir = Path(kwargs["downloads_dir"])
        output_dir = Path(kwargs["output_dir"])
    elif len(args) >= 1 and isinstance(args[0], (list, tuple)):
        appids = [str(a) for a in args[0]]
        downloads_dir = Path(args[1])
        output_dir = Path(args[2])
    elif len(args) >= 4 and isinstance(args[0], (str, int)) and isinstance(args[1], (str, int)):
        # Old style: process(app1, app2, downloads_dir, output_dir, ...)
        # Collect any leading strings/ints as appids until a Path or non-digit directory
        app_list = []
        dir_idx = 0
        for i, a in enumerate(args):
            if isinstance(a, (str, int)) and str(a).strip().isdigit() and i < len(args) - 2:
                app_list.append(str(a))
            else:
                dir_idx = i
                break
        if len(app_list) >= 2:
            appids = app_list
            downloads_dir = Path(args[dir_idx])
            output_dir = Path(args[dir_idx + 1])
        else:
            appids = [str(args[0]), str(args[1])]
            downloads_dir = Path(args[2])
            output_dir = Path(args[3])
    else:
        raise ValueError("Invalid arguments passed to create_bundle_assets.process()")

    target_specs = resolve_target_specs(only_images)

    # Validate asset files
    for aid in appids:
        app_dir = downloads_dir / str(aid)
        for fname in ["library_hero_2x.jpg", "logo_2x.png"]:
            p = app_dir / fname
            if not p.exists():
                print(f"ERROR: Missing {p}", file=sys.stderr)
                sys.exit(1)

    print(f"Loading assets for {len(appids)} apps: {appids} ...")
    heroes = []
    logos = []
    for aid in appids:
        app_dir = downloads_dir / str(aid)
        h = Image.open(str(app_dir / "library_hero_2x.jpg")).convert("RGB")
        l = Image.open(str(app_dir / "logo_2x.png")).convert("RGBA")
        heroes.append(h)
        logos.append(l)

    eff_angle = compute_effective_angle(rotation_deg)
    print(f"\n  Apps count     : {len(appids)}")
    print(f"  Layout style   : {layout.upper()}")
    if layout in ("auto", "strips"):
        print(f"  Diagonal angle : {eff_angle:.4f}  (rotation offset: {rotation_deg:+.1f} deg)")
    all_off = bg_offsets.get("all", (0.0, 0.0))
    for aid in appids:
        s = float(logo_scales.get(str(aid), logo_scales.get("all", 1.0)))
        app_off = bg_offsets.get(str(aid), (0.0, 0.0))
        off = (app_off[0] + all_off[0], app_off[1] + all_off[1])
        info_strs = []
        if s != 1.0:
            info_strs.append(f"scale=x{s:.2f}")
        if off != (0.0, 0.0):
            info_strs.append(f"shift=(x={off[0]:+.0f}px, y={off[1]:+.0f}px)")
        if info_strs:
            print(f"  Custom app {aid:<10}: {', '.join(info_strs)}")

    if len(target_specs) < len(BUNDLE_SPECS):
        spec_names = ", ".join(s[0] for s in target_specs)
        print(f"  Target images  : ONLY [{spec_names}]")
    else:
        print(f"  Target images  : ALL ({len(BUNDLE_SPECS)} assets)")

    bundle_folder_name = f"bundle_{'_'.join(appids)}"
    out_folder = output_dir / bundle_folder_name
    out_folder.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating bundle assets -> {out_folder}\n")

    for spec_name, w, h in target_specs:
        feather = max(2, int(min(w, h) * 0.01))

        # Scale offsets proportionally to asset size relative to reference resolution
        scaled_offsets = []
        for aid in appids:
            app_off = bg_offsets.get(str(aid), (0.0, 0.0))
            eff_x = app_off[0] + all_off[0]
            eff_y = app_off[1] + all_off[1]
            scaled_offsets.append((eff_x * (w / _REF_W), eff_y * (h / _REF_H)))
        scales_list = [float(logo_scales.get(str(aid), logo_scales.get("all", 1.0))) for aid in appids]

        img = make_multi_bundle_image(
            heroes=heroes,
            logos=logos,
            total_w=w,
            total_h=h,
            layout=layout,
            rotation_deg=rotation_deg,
            logo_scales=scales_list,
            offsets=scaled_offsets,
            feather=feather,
        )
        out_path = out_folder / f"{spec_name}_{w}x{h}.jpg"
        img.save(str(out_path), "JPEG", quality=93, subsampling=0)
        print(f"  OK  {spec_name:<22}  {w}x{h}  ->  {out_path.name}")

    if len(target_specs) < len(BUNDLE_SPECS):
        print(f"\nDone! Generated {len(target_specs)} asset(s) in: {out_folder}")
    else:
        print(f"\nDone! All assets saved to: {out_folder}")


# ---------------------------------------------------------------------------
# CLI Argument Parsing Helpers
# ---------------------------------------------------------------------------

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
    m = re.match(r"^(\d+|all)[\s:x,]*([+-]?\d+(?:\.\d+)?)$", raw.strip(), flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse --{direction} value '{raw}'. Expected e.g. '{direction}: 3681780 +50' or '3681780 +50' or 'all 50'")
    return m.group(1).lower(), float(m.group(2))


def parse_move_token(tokens) -> tuple[str, float, float]:
    raw = " ".join(tokens) if isinstance(tokens, list) else str(tokens)
    raw = raw.strip()
    m_dir = re.match(r"^(up|down|left|right)[:\s]+(\d+|all)[\s:x,]*([+-]?\d+(?:\.\d+)?)$", raw, re.IGNORECASE)
    if m_dir:
        direction = m_dir.group(1).lower()
        appid = m_dir.group(2).lower()
        amount = float(m_dir.group(3))
        dx, dy = 0.0, 0.0
        if direction == "down": dy = amount
        elif direction == "up": dy = -amount
        elif direction == "right": dx = amount
        elif direction == "left": dx = -amount
        return appid, dx, dy
    m_xy = re.match(r"^(\d+|all)[\s,x]+([+-]?\d+(?:\.\d+)?)[\s,x]+([+-]?\d+(?:\.\d+)?)$", raw, re.IGNORECASE)
    if m_xy:
        return m_xy.group(1).lower(), float(m_xy.group(2)), float(m_xy.group(3))
    raise ValueError(f"Cannot parse --move value '{raw}'. Expected e.g. 'down: 3681780 +50' or '3681780 0 50' or 'all 0 50'")


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
        description="Create Steam bundle assets from multiple game App IDs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_bundle_assets.py 2666510 570
  python create_bundle_assets.py 3681780 2666510 3419430 570 --layout strips
  python create_bundle_assets.py 3681780 2666510 3419430 570 730 --layout grid
  python create_bundle_assets.py 3681780 2666510 3419430 --rotation 20 --scale 3681780x1.2
        """,
    )
    parser.add_argument("appids", nargs="+", help="Steam App IDs (at least 2, e.g. 5 or 6 games)")
    parser.add_argument("--downloads-dir", default="downloads",
                        help="Base folder for per-app assets (default: downloads)")
    parser.add_argument("--output-dir", default="output",
                        help="Output folder for bundle images (default: output)")
    parser.add_argument(
        "--layout", choices=["auto", "strips", "grid", "horizontal"], default="auto",
        help="Layout style: auto (default), strips, grid, horizontal",
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

    # Separate numeric appids from trailing image names like 'vertical_capsule only'
    actual_appids = []
    trailing_extra = []
    for item in args.appids:
        if item.isdigit():
            actual_appids.append(item)
        else:
            trailing_extra.append(item)

    extra_combined = (args.extra_args or []) + trailing_extra
    only_images = extract_only_args(args.only_images, extra_combined, unknown)

    if len(actual_appids) < 2:
        print(f"[!] Error: At least 2 Steam App IDs are required. Received: {actual_appids}", file=sys.stderr)
        sys.exit(1)

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

    process(actual_appids, downloads_dir, output_dir,
            rotation_deg=args.rotation,
            layout=args.layout,
            logo_scales=logo_scales,
            bg_offsets=bg_offsets,
            only_images=only_images)


if __name__ == "__main__":
    main()
