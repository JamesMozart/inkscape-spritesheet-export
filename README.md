# Sprite Sheet Merger for Inkscape

An Inkscape extension that exports layers as PNG frames and merges them into a single sprite sheet.

## Features

- Exports each Inkscape layer to a PNG frame using the Inkscape command line.
- Merges frames into a grid: `{tag}` = row, `{index}` = column.
- Multi-process export for faster performance.
- Exports at page size, so all frames share the same canvas dimensions.
- Optional DPI scaling and frame spacing.

## Layer Naming Rule

Each layer must be named `{tag}-{index}`, for example:

- idle-0
- idle-1
- idle-2
- run-0
- run-1
- run-2
- jump-0
- jump-1

`{tag}`   — animation name, becomes a **row** in the sprite sheet. `{index}` — frame number, becomes a **column**.

Layers that do not match this pattern are skipped.

## Output Layout

|       | col 0  | col 1  | col 2  |
|-------|--------|--------|--------|
| idle  | idle-0 | idle-1 | idle-2 |
| jump  | jump-0 | jump-1 |        |
| run   | run-0  | run-1  | run-2  |

## Installation

1. Copy the `inkscape_spritesheet_export/` folder into your Inkscape extensions directory:
   - **Linux / macOS**: `~/.config/inkscape/extensions/`
   - **Windows**: `%APPDATA%\inkscape\extensions\`
2. Restart Inkscape.
3. The extension appears under **Extensions → Export → Export Layers and Merge to Sprite Sheet**.

## Requirements

- Inkscape 1.0 or later (must be available in `PATH`, or set the full path in the dialog).
- Python 3 with Pillow: `pip install Pillow`

## Usage

1. Open your animation SVG in Inkscape.
2. Put each frame in its own layer and rename layers to `{tag}-{index}`.
3. Go to **Extensions → Export → Export Layers and Merge to Sprite Sheet**.
4. Choose the output PNG path, frame gap, DPI, and number of parallel jobs.
5. Click **Apply**.

## Options

| Option | Description |
|---|---|
| Output PNG file | Path to the merged sprite sheet. |
| Gap between frames | Empty pixels between columns and rows. |
| Export DPI | Output size = page size × DPI / 96. Default 96 keeps 1:1. |
| Parallel jobs | Number of worker processes. 0 = auto (`cpu_count() - 1`). |
| Path to inkscape executable | Leave empty to use the system `PATH`. |
| Keep temporary files | Keep temp SVG/PNG files for debugging. |

## License

MIT
