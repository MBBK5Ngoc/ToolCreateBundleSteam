# ToolCreateBundleSteam - Steam Bundle Image Tool

A tool for automatically downloading Steam store assets and generating professional Steam bundle capsules and banners for **2, 3, 4, 5, 6 or more games**.

---

## Architecture Overview

```
BundleImageTool/
├── main.py                   # Main entry point (check -> download -> generate)
├── create_bundle_assets.py   # Multi-game image composition (strips, grid, horizontal, auto)
├── download_steam_assets.py  # Steam CDN downloader (anonymous CDN / PICS)
├── downloads/                # Cached raw assets per app: downloads/<appid>/
│   └── <appid>/
│       ├── library_hero_2x.jpg
│       └── logo_2x.png
└── output/                   # Generated bundle assets: output/bundle_<id1>_<id2>_.../
```

---

## Requirements & Setup

- Python 3.10+
- Dependencies:
  ```powershell
  pip install pillow numpy steam
  ```

---

## How It Works (Pipeline)

When you run `main.py <appid1> <appid2> [<appid3> ...]`:
1. **Check**: Checks `downloads/<appid>/` for `library_hero_2x.jpg` and `logo_2x.png` for all provided App IDs.
2. **Download**: If any required assets are missing, automatically downloads them from Steam PICS/CDN. If already present, skips downloading.
3. **Generate**: Composites background hero images, draws dividers, fits and drops shadows on the logos on top, and outputs all 6 Steam bundle resolutions.

---

## Basic Usage

### 2 Games (Classic Diagonal Split)
```powershell
python main.py 3681780 2666510
```

### Multi-Game Bundles (3, 4, 5, 6+ Games)
Pass 3, 4, 5, 6 or more Steam App IDs:
```powershell
# 3 Games:
python main.py 3681780 2666510 3419430

# 4 Games:
python main.py 3681780 2666510 3419430 570

# 5 Games:
python main.py 3681780 2666510 3419430 3719580 3595460

# 6 Games:
python main.py 3681780 2666510 3419430 570 3719580 3595460
```

---

## Layout Options (`--layout`)

Choose how multi-game bundles are visually arranged:

| Layout | Description |
|---|---|
| `--layout auto` *(default)* | Intelligently adapts to each asset's aspect ratio: slanted strips for wide capsules; balanced 2D grid cells or horizontal slices for `vertical_capsule`. |
| `--layout strips` | Parallel vertical/slanted slices across all assets. (Rotatable with `--rotation`). |
| `--layout grid` | Structured 2D collage grid (2×2 for 4 games, 3×2 on wide / 2×3 on tall for 6 games, 3+2 on wide / 2+2+1 on tall for 5 games). |
| `--layout horizontal` | Stacked horizontal slices (especially clean on tall assets like `vertical_capsule`). |

**Examples:**
```powershell
# 5 games in strips:
python main.py 3681780 2666510 3419430 3719580 3595460 --layout strips

# 6 games in a 2D collage grid:
python main.py 3681780 2666510 3419430 570 3719580 3595460 --layout grid

# 4 games with stacked horizontal rows:
python main.py 3681780 2666510 3419430 570 --layout horizontal
```

---

## Options Reference

### 1. Rotation (`--rotation`)
Tilts the dividing lines by extra degrees from the default slant.

- Default: `0` (~8.5° slant)
- Positive (`+15`, `+20`, `+80`): Steeper lean towards horizontal.
- Negative (`-5`): Shallower lean, closer to a vertical split.

```powershell
python main.py 3681780 2666510 3419430 --rotation 20
```

---

### 2. Per-App Logo Scaling (`--scale`)
Scales individual game logos relative to their auto-fitted container. Repeatable.

- Format: `--scale <appid>x<multiplier>`
- Example: `3681780x1.3` means 30% larger.

```powershell
python main.py 3681780 2666510 3419430 --scale 3681780x1.2 --scale 2666510x1.1
```

---

### 3. Background Image Movement (`--up`, `--down`, `--left`, `--right`, `--move`)
Shifts an app's background hero image in pixels (calibrated to the 920×430 reference resolution and scaled proportionally across all 6 asset sizes). The canvas automatically expands its internal crop boundary so **no black borders or empty space will appear**.

Accepted formats:
- `--down <appid|all> <pixels>` or `--down "<appid|all> <pixels>"` or `--down <appid|all>+<pixels>`
- `--up <appid|all> <pixels>`
- `--left <appid|all> <pixels>`
- `--right <appid|all> <pixels>`
- `--move "<direction>: <appid|all> <pixels>"`

```powershell
python main.py 3681780 2666510 3419430 --down 3681780 +50 --up 2666510 +20
# Shift all background images left by 300px:
python main.py 3681780 2666510 3419430 --left all 300
```

---

### 4. Single Image Generation (`--only` / `"name image" only`)
To generate only one (or a subset of) specific images, specify `--only <name>` or trailing `<name> only`.

- Supported image names:
  - `package_header` (1414 × 464)
  - `header_capsule` (920 × 430)
  - `small_capsule` (462 × 174)
  - `main_capsule` (1232 × 706)
  - `vertical_capsule` (748 × 896)
  - `page_background` (1438 × 810)

```powershell
python main.py 3681780 2666510 3419430 --only vertical_capsule
python main.py 3681780 2666510 3419430 vertical_capsule only
```

---

### 5. Other Flags

| Flag | Description |
|---|---|
| `--layout <mode>` | Layout style: `auto`, `strips`, `grid`, `horizontal`. |
| `--only <name>` / `-o` | Generate only specific image(s). |
| `--force-download` | Re-downloads Steam assets even if already cached locally. |
| `--downloads-dir <dir>` | Custom directory for downloaded assets (default: `downloads`). |
| `--output-dir <dir>` | Custom directory for generated bundles (default: `output`). |

---

## Output Asset Specifications

Assets are saved into `output/bundle_<appid1>_<appid2>_.../`:

| Asset Name | Resolution | Description |
|---|---|---|
| `package_header_1414x464.jpg` | 1414 × 464 | Steam package / bundle store header |
| `header_capsule_920x430.jpg` | 920 × 430 | Store header capsule |
| `small_capsule_462x174.jpg` | 462 × 174 | Search / small store capsule |
| `main_capsule_1232x706.jpg` | 1232 × 706 | Main storefront carousel capsule |
| `vertical_capsule_748x896.jpg` | 748 × 896 | Library / vertical store capsule |
| `page_background_1438x810.jpg` | 1438 × 810 | Bundle detail page background |
