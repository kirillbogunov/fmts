from pathlib import Path
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

def test_v804_centered_f_assets_exist():
    for name, size in [("icon-192.png",192),("icon-512.png",512),("icon-maskable-192.png",192),("icon-maskable-512.png",512),("apple-touch-icon.png",180),("favicon-64.png",64)]:
        p = ROOT / "app" / "static" / name
        assert p.exists()
        with Image.open(p) as im:
            assert im.size == (size, size)

def test_v804_manifest_has_any_and_maskable_icons():
    data=json.loads((ROOT/"app/static/manifest.webmanifest").read_text(encoding="utf-8"))
    purposes={i["purpose"] for i in data["icons"]}
    assert "any" in purposes
    assert "maskable" in purposes

def test_v804_base_uses_dedicated_apple_icon():
    html=(ROOT/"app/templates/base.html").read_text(encoding="utf-8")
    assert "/static/apple-touch-icon.png" in html
    assert "/static/favicon-64.png" in html
