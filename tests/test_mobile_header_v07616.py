from pathlib import Path


def test_mobile_header_keeps_ios_safe_area_height():
    css = Path('app/static/app.css').read_text(encoding='utf-8')
    assert '--mobile-topbar-content-h:58px' in css
    assert 'height:calc(var(--mobile-topbar-content-h) + env(safe-area-inset-top,0px))!important' in css
    assert 'padding-top:env(safe-area-inset-top,0px)!important' in css
    assert 'display:grid!important' in css


def test_mobile_body_offset_matches_header_height():
    css = Path('app/static/app.css').read_text(encoding='utf-8')
    assert 'padding-top:calc(var(--mobile-topbar-content-h) + env(safe-area-inset-top,0px))!important' in css
