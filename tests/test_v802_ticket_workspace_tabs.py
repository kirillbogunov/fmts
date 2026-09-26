from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = (ROOT / "app/templates/ticket_detail.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/app.css").read_text(encoding="utf-8")
SW = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")


def test_ticket_workspace_tabs_exist():
    assert 'id="ticket-workspace-tabs"' in TPL
    for tab in ("overview", "work", "history", "manage", "service"):
        assert f'data-ticket-tab="{tab}"' in TPL


def test_ticket_sections_are_grouped():
    assert 'id="ticket-overview" data-ticket-pane="overview"' in TPL
    assert 'id="maintenance-checklist" data-ticket-pane="work"' in TPL
    assert 'id="ticket-comments" data-ticket-pane="history"' in TPL
    assert 'id="ticket-control" data-ticket-pane="manage"' in TPL
    assert 'id="enterprise-ticket" data-ticket-pane="service"' in TPL


def test_workspace_tabs_mobile_and_sticky():
    assert '.ticket-workspace-tabs{' in CSS
    assert 'top:calc(var(--mobile-topbar-total-h) + 6px)!important' in CSS
    assert '.ticket-grid.ticket-tab-mode' in CSS


def test_service_desk_quick_jumps():
    for anchor in ("service-itsm", "service-links", "service-approvals"):
        assert anchor in TPL


def test_pwa_cache_bumped():
    assert 'fmts-v802-ticket-workspace-tabs' in SW
