from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_schedule_template_uses_clear_time_labels():
    html = (ROOT / 'app/templates/team_schedule.html').read_text(encoding='utf-8')
    assert '<span>Начало</span>' in html
    assert '<span>Окончание</span>' in html
    assert 'schedule-day-dot' in html


def test_schedule_css_avoids_seven_narrow_columns():
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    assert 'v0.7.6.18 — staff schedule layout hotfix' in css
    assert '.schedule-week-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))' in css
    assert '@media(max-width:860px)' in css
