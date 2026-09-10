# Steam Bundle Image Tool - How to Run

A tool for automatically downloading Steam store assets and generating professional two-game bundle capsules and banners.

---

## Architecture Overview

```
BundleImageTool/
├── main.py                   # Main entry point (check -> download -> generate)
├── create_bundle_assets.py   # Image composition, diagonal split, logo & bg logic
├── download_steam_assets.py  # Steam CDN downloader (anonymous CDN / PICS)
├── downloads/                # Cached raw assets per app: downloads/<appid>/
│   └── <appid>/
│       ├── library_hero_2x.jpg
│       └── logo_2x.png
└── output/                   # Generated bundle assets: output/bundle_<id1>_<id2>/
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

When you run `main.py <appid1> <appid2>`:
1. **Check**: Checks `downloads/<appid>/` for `library_hero_2x.jpg` and `logo_2x.png`.
2. **Download**: If any required assets are missing, automatically downloads them from Steam. If already present, skips downloading.
3. **Generate**: Composites the background hero images, draws the divider line, fits and drops shadows on the logos on top, and outputs all 6 Steam bundle resolutions.

---

## Basic Usage

```powershell
python main.py <appid1> <appid2>
```

**Example:**
```powershell
python main.py 3681780 2666510
```

> **Image Order**:
> - `<appid1>` is placed on the **left / bottom** half.
> - `<appid2>` is placed on the **right / top** half.

---

## Options Reference

### 1. Rotation (`--rotation`)
Tilts the dividing line by extra degrees from the default ~8.5° diagonal lean.

- Default: `0` (~8.5° slant)
- Positive (`+15`, `+20`, `+80`): Steeper lean towards horizontal. At `80`, the line splits top/bottom.
- Negative (`-5`): Shallower lean, closer to a vertical split.

```powershell
python main.py 3681780 2666510 --rotation 20
python main.py 3681780 2666510 --rotation 80
```

---

### 2. Per-App Logo Scaling (`--scale`)
Scales individual game logos relative to their auto-fitted container. Repeatable.

- Format: `--scale <appid>x<multiplier>`
- Example: `3681780x1.3` means 30% larger.

```powershell
# Scale only App 1 logo by 1.3x:
python main.py 3681780 2666510 --scale 3681780x1.3

# Scale both logos individually:
python main.py 3681780 2666510 --scale 3681780x1.1 --scale 2666510x1.2
```

---

### 3. Background Image Movement (`--up`, `--down`, `--left`, `--right`, `--move`)
Shifts an app's background hero image in pixels (calibrated to the 920×430 reference resolution and scaled proportionally across all 6 asset sizes). The canvas automatically expands its internal crop boundary so **no black borders or empty space will appear**.

Accepted formats (both quoted and unquoted work):
- `--down <appid> <pixels>` or `--down "<appid> <pixels>"` or `--down <appid>+<pixels>`
- `--up <appid> <pixels>`
- `--left <appid> <pixels>`
- `--right <appid> <pixels>`
- `--move "<direction>: <appid> <pixels>"`

```powershell
# Move App 3681780 background down by 50px:
python main.py 3681780 2666510 --down 3681780 +50

# Move App 2666510 background up by 20px:
python main.py 3681780 2666510 --up 2666510 +20

# Move App 3681780 left by 30px:
python main.py 3681780 2666510 --left 3681780 +30
# OR with negative right:
python main.py 3681780 2666510 --right 3681780 -30

# Using --move syntax:
python main.py 3681780 2666510 --move "down: 3681780 +50"
```

---

### 4. Single Image Generation (`--only` / `"name image" only`)
By default, the script generates all 6 bundle images. To generate only one (or a subset of) specific images, specify `--only <name>` or trailing `<name> only`.

- Supported image names:
  - `package_header` (1414 × 464)
  - `header_capsule` (920 × 430)
  - `small_capsule` (462 × 174)
  - `main_capsule` (1232 × 706)
  - `vertical_capsule` (748 × 896)
  - `page_background` (1438 × 810)

```powershell
# Generate only the vertical capsule with --only flag:
python main.py 3681780 3419430 --rotation 45 --only vertical_capsule

# Or using natural trailing syntax:
python main.py 3681780 3419430 --rotation 45 vertical_capsule only
```

---

### 5. Other Flags

| Flag | Description |
|---|---|
| `--only <name>` / `-o` | Generate only specific image(s) (e.g. `--only vertical_capsule`). |
| `--force-download` | Re-downloads Steam assets even if already cached locally. |
| `--downloads-dir <dir>` | Custom directory for downloaded assets (default: `downloads`). |
| `--output-dir <dir>` | Custom directory for generated bundles (default: `output`). |

---

## Full Example Command

Run bundle for **3681780** (WinMon) and **2666510** (Rusty's Retirement) with 80° rotation, 1.3× logo scale for WinMon, and moving WinMon background down 50px:

```powershell
python main.py 3681780 2666510 --rotation 80 --scale 3681780x1.3 --down 3681780 +50
```

---

## Output Asset Specifications

Assets are saved into `output/bundle_<appid1>_<appid2>/`:

| Asset Name | Resolution | Description |
|---|---|---|
| `package_header_1414x464.jpg` | 1414 × 464 | Steam package / bundle store header |
| `header_capsule_920x430.jpg` | 920 × 430 | Store header capsule |
| `small_capsule_462x174.jpg` | 462 × 174 | Search / small store capsule |
| `main_capsule_1232x706.jpg` | 1232 × 706 | Main storefront carousel capsule |
| `vertical_capsule_748x896.jpg` | 748 × 896 | Library / vertical store capsule |
| `page_background_1438x810.jpg` | 1438 × 810 | Bundle detail page background |
