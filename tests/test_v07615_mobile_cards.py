from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_uses_native_mobile_recent_cards():
    tpl = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    assert "dashboard-recent-mobile" in tpl
    assert "dashboard-recent-card" in tpl
    assert "dashboard-recent-desktop" in tpl


def test_tickets_have_dedicated_mobile_cards_and_collapsible_bulk():
    tpl = (ROOT / "app/templates/tickets.html").read_text(encoding="utf-8")
    assert "mobile-ticket-workflow" in tpl
    assert "mobile-ticket-card" in tpl
    assert "mobile-bulk-details" in tpl
    assert "mobile-ticket-tags" in tpl
    assert "data-bulk-root" in tpl


def test_mobile_css_prevents_badge_letter_breaking_and_overlap():
    css = (ROOT / "app/static/app.css").read_text(encoding="utf-8")
    assert "v0.7.6.15 — mobile dashboard + ticket cards" in css
    assert "word-break:normal!important" in css
    assert "white-space:nowrap!important" in css
    assert "scroll-padding-bottom:108px" in css
    assert ".desktop-ticket-workflow{display:none!important}" in css
