from pathlib import Path


def test_v086_version_and_cache():
    assert 'app_version: str = "0.8.6"' in Path('app/config.py').read_text(encoding='utf-8')
    assert "fmts-v086-service-catalog" in Path('app/static/service-worker.js').read_text(encoding='utf-8')


def test_service_catalog_is_workspace_not_legacy_form():
    html=Path('app/templates/services.html').read_text(encoding='utf-8')
    assert 'service-workspace' in html
    assert 'service-library' in html
    assert 'SLA и рабочее время' in html
    assert 'Исполнители и автоматизация' in html
    assert 'Поля заявки' in html
    assert 'name="default_sla_hours"' not in html
    assert 'data-sla-presets' in html


def test_service_catalog_routes_support_editing():
    code=Path('app/routes/enterprise.py').read_text(encoding='utf-8')
    assert "@router.post('/services/{service_id}/update')" in code
    assert "@router.post('/services/{service_id}/toggle')" in code
    assert "@router.post('/services/{service_id}/fields/{field_id}/delete')" in code


def test_service_catalog_hidden_from_basic_roles():
    access=Path('app/access.py').read_text(encoding='utf-8')
    assert 'user.role in {ROLE_DISPATCHER, ROLE_MANAGER, ROLE_ADMIN}' in access
