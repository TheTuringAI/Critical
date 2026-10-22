"""Generates the extension icons (no image libraries required)."""
import struct
import zlib
from pathlib import Path


def png(size: int) -> bytes:
    rows = []
    r = size * 0.5
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = x + 0.5 - r, y + 0.5 - r
            inside = (abs(dx) ** 4 + abs(dy) ** 4) ** 0.25 <= r * 0.95
            if not inside:
                row += bytes([0, 0, 0, 0])
                continue
            # white "i" glyph on blue squircle
            u, v = (x + 0.5) / size, (y + 0.5) / size
            dot = (u - 0.5) ** 2 + (v - 0.28) ** 2 <= 0.085**2
            stem = abs(u - 0.5) <= 0.07 and 0.42 <= v <= 0.78
            row += bytes([255, 255, 255, 255]) if dot or stem else bytes([37, 99, 235, 255])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


out = Path(__file__).parent / "public" / "icons"
out.mkdir(parents=True, exist_ok=True)
for s in (16, 48, 128):
    (out / f"icon{s}.png").write_bytes(png(s))
