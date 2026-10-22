"""Second, independent reader: Claude looks at each photo tile and transcribes every location in it.

Used by scan.py when an Anthropic API key is available (ANTHROPIC_API_KEY or an `ant auth login`
profile). Its readings are run through the same target matcher as the OCR text, so a notice that
Tesseract garbled can still be caught. Hits found only here are boxed by tile, not by word.
"""
import base64
import io
import json
import os

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"
TILE_GRID = (2, 2)   # columns, rows
OVERLAP = 0.12       # fraction of tile size shared with neighbours, so no line is cut in every tile

PROMPT = """This is part of a photographed Indian newspaper page (Mumbai editions: public notices,
legal notices, auction notices, ads). Read it carefully, including small print, text near the
edges, and text that is partly cut off or curved.

For EVERY notice or article visible (even partially), list every location detail exactly as
printed: full addresses, flat/shop/office numbers with building names, society names, road and
street names, area/locality names, landmarks, village names, C.S./CTS/survey numbers with their
division (e.g. "C.S. No. 123 of Fort Division"), "Backbay Reclamation" block numbers, and every
6-digit pincode. Include the advocate's/signatory's address too, but mark it as such.

Copy text verbatim (keep the original spelling, even if it looks wrong). Do not guess words you
cannot see; if a word is unreadable, write [?] in its place. Set cut_off true when the notice runs
past the edge of the picture."""

SCHEMA = {
    "type": "object",
    "properties": {
        "notices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "subject_locations": {"type": "array", "items": {"type": "string"}},
                    "signatory_locations": {"type": "array", "items": {"type": "string"}},
                    "pincodes": {"type": "array", "items": {"type": "string"}},
                    "cut_off": {"type": "boolean"},
                },
                "required": ["heading", "subject_locations", "signatory_locations", "pincodes", "cut_off"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["notices"],
    "additionalProperties": False,
}


def available():
    try:
        anthropic.Anthropic()
        return True
    except Exception:
        return False


def tiles(img):
    cols, rows = TILE_GRID
    tw, th = img.width / cols, img.height / rows
    ox, oy = tw * OVERLAP, th * OVERLAP
    for r in range(rows):
        for c in range(cols):
            box = (max(0, int(c * tw - ox)), max(0, int(r * th - oy)),
                   min(img.width, int((c + 1) * tw + ox)), min(img.height, int((r + 1) * th + oy)))
            yield box, img.crop(box)


def read_tile(client, tile):
    buf = io.BytesIO()
    tile.convert("RGB").save(buf, "JPEG", quality=90)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stopped early ({response.stop_reason}) on a tile")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["notices"]


def read_page(img, client=None):
    """Yield (tile_box, notice) for every notice Claude reads on the page."""
    client = client or anthropic.Anthropic()
    for box, tile in tiles(img):
        for notice in read_tile(client, tile):
            yield box, notice
