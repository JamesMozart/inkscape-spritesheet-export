import os
import re
import copy
import shutil
import tempfile
import subprocess
import inkex
from multiprocessing import Pool, cpu_count
from PIL import Image


# Matches {tag}-{index}, e.g. run-0, idle-12
NAME_PATTERN = re.compile(r"^(?P<tag>.+?)-(?P<index>\d+)$")

# Inkscape namespace
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"


def _export_one_layer(args):
    """
    Subprocess entry point: export one layer as PNG.
    Arguments are packed into a tuple because multiprocessing's Pool.map
    can only pass a single argument.
    """
    (svg_path, layer_id, layer_label, out_path, dpi, inkscape_bin, temp_dir) = args

    # Re-read the SVG inside the subprocess to avoid passing lxml objects
    # (which cannot be pickled).
    import lxml.etree as ET

    parser = ET.XMLParser(huge_tree=True)
    tree = ET.parse(svg_path, parser)
    root = tree.getroot()

    # Find the target layer
    target = None
    for el in root.iter():
        if el.get("id") == layer_id:
            target = el
            break
    if target is None:
        raise RuntimeError(f"Layer not found: {layer_id} ({layer_label})")

    # Remove all other layers
    for el in list(root):
        if (el.tag.endswith("g")
                and el.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
                and el is not target):
            root.remove(el)

    # Make sure the target layer is visible:
    # if the style contains display:none, strip it out.
    style = target.get("style", "")
    if "display" in style:
        # Simply remove any display-related declarations
        parts = [p.strip() for p in style.split(";") if p.strip()]
        parts = [p for p in parts if not p.startswith("display")]
        new_style = ";".join(parts)
        if new_style:
            target.set("style", new_style)
        elif "style" in target.attrib:
            del target.attrib["style"]

    # Write a temporary SVG containing only the target layer
    temp_svg = os.path.join(temp_dir, f"{layer_id}.svg")
    tree.write(temp_svg, encoding="utf-8", xml_declaration=True)

    # Call the Inkscape CLI to export
    cmd = [
        inkscape_bin,
        temp_svg,
        f"--export-id={layer_id}",
        "--export-id-only",
        "--export-area-page",
        f"--export-dpi={dpi}",
        "--export-background=#00000000",
        "--export-background-opacity=0",
        f"--export-filename={out_path}",
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Inkscape failed to export {layer_label} (return code {result.returncode})\n"
            f"stderr: {result.stderr}"
        )

    if not os.path.exists(out_path):
        raise RuntimeError(f"Failed to export {layer_label}: {out_path} was not created")

    # Delete the temporary SVG
    try:
        os.remove(temp_svg)
    except OSError:
        pass

    return (layer_label, out_path)


class SpriteMergerExportMerge(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--output_file", type=str, default="spritesheet.png")
        pars.add_argument("--gap", type=int, default=0)
        pars.add_argument("--export_dpi", type=float, default=96.0)
        pars.add_argument("--inkscape_path", type=str, default="")
        pars.add_argument("--keep_temp", type=inkex.Boolean, default=False)
        pars.add_argument("--jobs", type=int, default=0)  # 0 means auto

    def effect(self):
        output_file = self.options.output_file
        gap = self.options.gap
        dpi = self.options.export_dpi
        inkscape_bin = self.options.inkscape_path.strip() or "inkscape"
        keep_temp = bool(self.options.keep_temp)
        jobs = self.options.jobs if self.options.jobs > 0 else max(1, cpu_count() - 1)

        # 1. Collect all layers
        layers = []
        for child in self.svg:
            if (child.tag.endswith("g")
                    and child.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"):
                label = child.get(f"{{{INKSCAPE_NS}}}label", "")
                layer_id = child.get("id")
                layers.append((label, layer_id))

        if not layers:
            inkex.errormsg("No layers found in the current document")
            return

        # Filter out layers that don't match the naming convention
        valid = [(label, lid) for label, lid in layers if NAME_PATTERN.match(label)]
        skipped = [(label, lid) for label, lid in layers if not NAME_PATTERN.match(label)]
        for label, _ in skipped:
            inkex.utils.debug(f"Skipping layer that does not match {{tag}}-{{index}} naming: {label}")

        if not valid:
            inkex.errormsg("No layers matching the naming convention to export")
            return

        temp_dir = tempfile.mkdtemp(prefix="sprite_merger_")
        inkex.utils.debug(f"Temporary directory: {temp_dir}")

        try:
            # Save the current document as a temporary SVG for subprocesses to read
            master_svg = os.path.join(temp_dir, "master.svg")
            self.document.write(master_svg)

            # 2. Parallel export using multiple processes
            tasks = []
            for label, layer_id in valid:
                out_path = os.path.join(temp_dir, f"{label}.png")
                tasks.append((master_svg, layer_id, label, out_path,
                              dpi, inkscape_bin, temp_dir))

            inkex.utils.debug(f"Starting parallel export of {len(tasks)} layers, processes: {jobs}")

            with Pool(processes=jobs) as pool:
                results = pool.map(_export_one_layer, tasks)

            inkex.utils.debug(f"Export complete, {len(results)} frames total")

            # 3. Parse {tag}-{index} and arrange into a grid
            grid = {}  # grid[tag][index] = path
            tags = []
            for label, path in results:
                m = NAME_PATTERN.match(label)
                tag = m.group("tag")
                index = int(m.group("index"))
                grid.setdefault(tag, {})[index] = path
                # maintain layer order, from top to bottom
                if tag not in tags:
                    tags.insert(0, tag)

            # tags = sorted(grid.keys())
            max_cols = max(max(indices.keys()) for indices in grid.values()) + 1

            opened = {}
            col_widths = [0] * max_cols
            row_heights = [0] * len(tags)

            for r, tag in enumerate(tags):
                for index, path in grid[tag].items():
                    try:
                        img = Image.open(path).convert("RGBA")
                    except Exception as e:
                        inkex.errormsg(f"Unable to open {path}: {e}")
                        return
                    opened[(r, index)] = img
                    if img.width > col_widths[index]:
                        col_widths[index] = img.width
                    if img.height > row_heights[r]:
                        row_heights[r] = img.height

            col_x = []
            x = 0
            for w in col_widths:
                col_x.append(x)
                x += w + gap

            row_y = []
            y = 0
            for h in row_heights:
                row_y.append(y)
                y += h + gap

            total_width = sum(col_widths) + gap * (max_cols - 1) if max_cols else 0
            total_height = sum(row_heights) + gap * (len(tags) - 1) if tags else 0

            if total_width <= 0 or total_height <= 0:
                inkex.errormsg("Computed canvas size is invalid")
                return

            canvas = Image.new("RGBA", (total_width, total_height), (0, 0, 0, 0))

            for r, tag in enumerate(tags):
                for index in sorted(grid[tag].keys()):
                    img = opened[(r, index)]
                    cell_x = col_x[index] + (col_widths[index] - img.width) // 2
                    cell_y = row_y[r] + (row_heights[r] - img.height) // 2
                    canvas.paste(img, (cell_x, cell_y), img)

            canvas.save(output_file, "PNG")

            inkex.utils.debug("[DONE]")
            inkex.utils.debug(f"Generated {output_file}")
            inkex.utils.debug(f"Size: {canvas.width}x{canvas.height}")
            inkex.utils.debug(f"Rows (tags): {tags}")
            inkex.utils.debug(f"Columns: {max_cols}")

        finally:
            if keep_temp:
                inkex.utils.debug(f"Keeping temporary files: {temp_dir}")
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    SpriteMergerExportMerge().run()
