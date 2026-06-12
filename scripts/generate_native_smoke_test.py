from __future__ import annotations

import struct
import zlib
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def build_diagram_image(path: Path) -> None:
    width, height = 900, 420
    white = (250, 252, 251, 255)
    teal = (31, 122, 100, 255)
    light = (223, 242, 234, 255)
    dark = (14, 87, 71, 255)
    charcoal = (36, 68, 59, 255)

    pixels = [[white for _ in range(width)] for _ in range(height)]

    def fill_rect(x: int, y: int, w: int, h: int, color: tuple[int, int, int, int]) -> None:
        for py in range(y, min(y + h, height)):
            row = pixels[py]
            for px in range(x, min(x + w, width)):
                row[px] = color

    def stroke_rect(x: int, y: int, w: int, h: int, color: tuple[int, int, int, int], thickness: int = 4) -> None:
        fill_rect(x, y, w, thickness, color)
        fill_rect(x, y + h - thickness, w, thickness, color)
        fill_rect(x, y, thickness, h, color)
        fill_rect(x + w - thickness, y, thickness, h, color)

    def line(x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int, int], thickness: int = 5) -> None:
        steps = max(abs(x2 - x1), abs(y2 - y1)) + 1
        for step in range(steps):
            x = round(x1 + (x2 - x1) * step / max(steps - 1, 1))
            y = round(y1 + (y2 - y1) * step / max(steps - 1, 1))
            fill_rect(max(0, x - thickness // 2), max(0, y - thickness // 2), thickness, thickness, color)

    def add_block_label(x: int, y: int, w: int, h: int) -> None:
        fill_rect(x + 16, y + 20, w - 32, 10, charcoal)
        fill_rect(x + 16, y + 40, w - 90, 8, charcoal)
        fill_rect(x + 16, y + 58, w - 48, 8, charcoal)

    boxes = [
        (40, 60, 180, 90),
        (260, 60, 180, 90),
        (480, 60, 180, 90),
        (700, 60, 160, 90),
        (260, 220, 220, 90),
        (540, 220, 260, 90),
    ]
    for x, y, w, h in boxes:
        fill_rect(x, y, w, h, light)
        stroke_rect(x, y, w, h, teal)
        add_block_label(x, y, w, h)

    for coords in [
        (220, 105, 260, 105),
        (440, 105, 480, 105),
        (660, 105, 700, 105),
        (370, 150, 370, 220),
        (650, 150, 650, 220),
        (480, 265, 540, 265),
    ]:
        line(*coords, color=dark)

    fill_rect(70, 355, 760, 8, charcoal)
    fill_rect(70, 375, 640, 6, charcoal)

    raw_rows = []
    for row in pixels:
        raw_rows.append(b"\x00" + bytes(channel for pixel in row for channel in pixel))
    compressed = zlib.compress(b"".join(raw_rows), level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(png)


def main() -> None:
    out_dir = Path("data/uploads")
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "native-image-smoke-diagram.png"
    build_diagram_image(image_path)
    img = ImageReader(BytesIO(image_path.read_bytes()))
    out_path = out_dir / "native-image-smoke-test.pdf"
    packet = canvas.Canvas(str(out_path), pagesize=letter)
    for page in range(1, 4):
        packet.setFont("Helvetica-Bold", 18)
        packet.drawString(72, 740, f"Native Image Smoke Test - Page {page}")
        packet.setFont("Helvetica", 11)
        packet.drawString(
            72,
            710,
            "This PDF embeds a chart-style image for Azure AI Search native image serving validation.",
        )
        packet.drawString(
            72,
            694,
            "Question targets: blueprint, diagram, architecture, evidence, construction workflow.",
        )
        packet.drawImage(img, 72, 380, width=420, height=220, preserveAspectRatio=True, mask="auto")
        packet.setFont("Helvetica-Bold", 12)
        packet.drawString(72, 348, "Architecture Notes")
        packet.setFont("Helvetica", 11)
        packet.drawString(
            72,
            330,
            "Source docs -> Blob -> Search skillset -> enrichment index -> canonical chunks -> native multimodal KB.",
        )
        packet.drawString(
            72,
            314,
            "This page should allow testing both app-managed chunk grounding and image-backed native retrieval.",
        )
        packet.showPage()
    packet.save()
    print(out_path)


if __name__ == "__main__":
    main()
