from pathlib import Path


def test_v085_version_and_cache():
    assert 'app_version: str = "0.8.5"' in Path('app/config.py').read_text(encoding='utf-8')
    assert "fmts-v085-template-workspace" in Path('app/static/service-worker.js').read_text(encoding='utf-8')


def test_template_workspace_is_user_friendly():
    html = Path('app/templates/ticket_templates.html').read_text(encoding='utf-8')
    assert 'Шаблоны работ' in html
    assert 'Библиотека' in html
    assert 'Подзадачи / наряды' in html
    assert 'Добавить работу' in html
    assert 'Запустить шаблон' in html
    assert 'name="sort_order"' not in html
    assert 'templateSearch' in html


def test_template_routes_support_editing_and_reordering():
    src = Path('app/routes/operations.py').read_text(encoding='utf-8')
    for fragment in [
        "/ticket-templates/{template_id}/update",
        "/ticket-templates/{template_id}/duplicate",
        "/tasks/{task_id}/update",
        "/tasks/{task_id}/move",
        "/tasks/{task_id}/duplicate",
        "/tasks/{task_id}/delete",
    ]:
        assert fragment in src
    assert 'max_order + 10' in src
