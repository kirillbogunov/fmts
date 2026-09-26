from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v801_version_and_cache():
    config = (ROOT / 'app/config.py').read_text(encoding='utf-8')
    sw = (ROOT / 'app/static/service-worker.js').read_text(encoding='utf-8')
    assert ('app_version: str = "8.0.3"' in config) or ('app_version: str = "0.8.5"' in config)
    assert ("fmts-v803-sidebar-branding" in sw) or ("fmts-v085-template-workspace" in sw)


def test_mobile_nav_is_docked_to_bottom():
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    marker = 'FMTS v8.0.1 — unified mobile layout system'
    tail = css[css.index(marker):]
    assert 'left:0!important;right:0!important;bottom:0!important;' in tail
    assert 'border-radius:18px 18px 0 0!important;' in tail


def test_ticket_action_dock_precedes_main_ticket_grid():
    html = (ROOT / 'app/templates/ticket_detail.html').read_text(encoding='utf-8')
    dock = html.index('<div class="ticket-action-dock"')
    grid = html.index('<div class="grid2 wide-left ticket-grid">')
    assert dock < grid
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    tail = css[css.index('FMTS v8.0.1 — unified mobile layout system'):]
    assert 'position:sticky!important;' in tail
    assert '.ticket-mobile-spacer{display:none!important;height:0!important}' in tail


def test_mobile_long_values_are_wrappable():
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    tail = css[css.index('FMTS v8.0.1 — unified mobile layout system'):]
    assert 'overflow-wrap:anywhere!important' in tail
    assert '.pre{white-space:pre-wrap!important' in tail
