from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_and_svg_sprite():
    config = (ROOT / 'app/config.py').read_text(encoding='utf-8')
    assert '0.7.6.15' in config
    icons = (ROOT / 'app/static/icons.svg').read_text(encoding='utf-8')
    for icon_id in ['menu','dashboard','tickets','bell','maintenance','settings','user','search','plus','map','camera']:
        assert f'id="{icon_id}"' in icons


def test_templates_do_not_use_platform_emoji_icons():
    forbidden = set('⚡★☆☷⚙♙ⓘ⌕☰☑▧▤▦▣⌂◎◴◌◉◆◫⌘◷▥✉⇄⇩↻✎＋✓✔✕✖▶■⏸☎')
    hits = []
    for path in (ROOT / 'app/templates').glob('*.html'):
        text = path.read_text(encoding='utf-8')
        for ch in text:
            if ch in forbidden or 0x1F000 <= ord(ch) <= 0x1FAFF:
                hits.append((path.name, ch))
                break
    assert not hits, hits


def test_mobile_css_has_safe_layout_rules():
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    assert 'v0.7.6.14 — stable SVG icon system + mobile responsive pass' in css
    assert 'env(safe-area-inset-bottom' in css
    assert 'font-size:16px!important' in css
    assert '.mobile-bottom-nav' in css
    assert '.ticket-action-dock' in css


def test_service_worker_caches_svg_sprite():
    sw = (ROOT / 'app/static/service-worker.js').read_text(encoding='utf-8')
    assert 'fmts-v07615-mobile-cards' in sw
    assert '/static/icons.svg' in sw
