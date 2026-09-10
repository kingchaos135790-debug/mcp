import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastmcp import FastMCP
from PIL import Image as PILImage

from extensions.desktop import WindowsDesktopExtension


class ViewImageExtensionTests(unittest.TestCase):
    def test_view_image_returns_mcp_image_content(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "sample.webp"
                PILImage.new("RGB", (320, 240), (10, 20, 30)).save(path, format="WEBP")
                mcp = FastMCP("view-image-test")
                WindowsDesktopExtension().register(mcp, SimpleNamespace(desktop=None, analytics=None))
                result = await mcp.call_tool("view_image", {"path": str(path)}, run_middleware=False)
                self.assertEqual([type(item).__name__ for item in result.content], ["TextContent", "ImageContent"])
                self.assertEqual(result.content[1].mimeType, "image/png")
                self.assertTrue(result.content[1].data)
        asyncio.run(run_test())

    def test_view_image_crop_reports_source_region(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "long.png"
                PILImage.new("RGB", (800, 4000), "white").save(path)
                mcp = FastMCP("view-image-crop-test")
                WindowsDesktopExtension().register(mcp, SimpleNamespace(desktop=None, analytics=None))
                result = await mcp.call_tool(
                    "view_image",
                    {"path": str(path), "crop_x": 0, "crop_y": 1000, "crop_width": 800, "crop_height": 1000},
                    run_middleware=False,
                )
                self.assertIn("crop=(0, 1000, 800, 2000)", result.content[0].text)
                self.assertIn("Rendered: 800x1000 PNG", result.content[0].text)
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
