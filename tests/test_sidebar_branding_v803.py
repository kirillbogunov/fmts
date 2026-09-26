from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_sidebar_uses_pwa_icon_and_wrapped_brand_copy():
    html=(ROOT/'app/templates/base.html').read_text(encoding='utf-8')
    assert 'brand-mark brand-mark-image' in html
    assert '/static/icon-192.png' in html
    assert 'Facility Management &amp;' in html
    assert '<span>Task System</span>' in html

def test_sidebar_css_keeps_long_labels_visible():
    css=(ROOT/'app/static/app.css').read_text(encoding='utf-8')
    assert 'grid-template-columns:272px minmax(0,1fr)!important' in css
    assert '.sidebar .nav-label' in css
    assert 'text-overflow:clip!important' in css
    assert 'white-space:normal!important' in css

def test_pwa_icons_exist():
    for size in (192,512):
        p=ROOT/f'app/static/icon-{size}.png'
        assert p.exists() and p.stat().st_size > 500
