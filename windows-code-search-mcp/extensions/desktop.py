from __future__ import annotations

import io
from importlib import import_module
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from PIL import Image as PILImage, ImageOps

from server_runtime import ServerContext


class WindowsDesktopExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        for module_name in ("windows_mcp.tools.shell", "windows_mcp.tools.filesystem"):
            module = import_module(module_name)
            module.register(mcp, get_desktop=lambda: context.desktop, get_analytics=lambda: context.analytics)

        @mcp.tool(
            name="view_image",
            description=(
                "Read a local image file from Windows and return it as real MCP image content for visual inspection. "
                "Supports PNG, JPEG, WebP, BMP, GIF and TIFF through Pillow. Optional crop coordinates are in "
                "source-image pixels; use crops for long product-detail images so text remains legible."
            ),
            annotations=ToolAnnotations(
                title="view_image",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        def view_image(
            path: str,
            crop_x: int = 0,
            crop_y: int = 0,
            crop_width: int = 0,
            crop_height: int = 0,
            max_width: int = 1920,
            max_height: int = 1920,
        ):
            target = Path(path).expanduser().resolve()
            if not target.exists() or not target.is_file():
                raise ValueError(f"Image file not found: {target}")
            if target.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("Image file is larger than the 100 MiB safety limit")
            if not (64 <= max_width <= 4096 and 64 <= max_height <= 4096):
                raise ValueError("max_width and max_height must be between 64 and 4096")
            if min(crop_x, crop_y, crop_width, crop_height) < 0:
                raise ValueError("crop coordinates and sizes cannot be negative")
            if (crop_width == 0) != (crop_height == 0):
                raise ValueError("crop_width and crop_height must both be zero or both be positive")

            try:
                with PILImage.open(target) as opened:
                    image = ImageOps.exif_transpose(opened)
                    image.load()
                    original_size = image.size
                    crop_box = None
                    if crop_width and crop_height:
                        right = min(crop_x + crop_width, image.width)
                        bottom = min(crop_y + crop_height, image.height)
                        if crop_x >= image.width or crop_y >= image.height or right <= crop_x or bottom <= crop_y:
                            raise ValueError(f"Crop is outside image bounds {image.width}x{image.height}")
                        crop_box = (crop_x, crop_y, right, bottom)
                        image = image.crop(crop_box)

                    image.thumbnail((max_width, max_height), PILImage.Resampling.LANCZOS)
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA" if "transparency" in image.info else "RGB")

                    output = io.BytesIO()
                    image.save(output, format="PNG", optimize=True)
                    rendered_size = image.size
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Unable to decode image {target}: {exc}") from exc

            crop_text = f"; crop={crop_box}" if crop_box else ""
            metadata = (
                f"Image: {target}\n"
                f"Original: {original_size[0]}x{original_size[1]}{crop_text}\n"
                f"Rendered: {rendered_size[0]}x{rendered_size[1]} PNG"
            )
            from fastmcp.utilities.types import Image as FastMCPImage

            return [metadata, FastMCPImage(data=output.getvalue(), format="png")]

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None
