import json

from app.routes.experience import _survey_questions
from app.access import visible_navigation, ROLE_REQUESTER, ROLE_MANAGER
from app.models import User


def test_survey_builder_accepts_json_questions_with_required_flag():
    payload=json.dumps([
        {'type':'rating','label':'Оцените качество','required':True},
        {'type':'text','label':'Комментарий','required':False},
    ],ensure_ascii=False)
    rows=_survey_questions(payload)
    assert rows == [
        {'type':'rating','label':'Оцените качество','required':True},
        {'type':'text','label':'Комментарий','required':False},
    ]


def test_survey_builder_keeps_legacy_format_compatible():
    rows=_survey_questions('rating|Оцените качество\nyesno|Проблема решена?\ntext|Комментарий')
    assert rows[0]['type']=='rating' and rows[0]['required'] is True
    assert rows[1]['type']=='yesno' and rows[1]['required'] is True
    assert rows[2]['type']=='text' and rows[2]['required'] is False


def test_invalid_survey_question_type_falls_back_to_rating():
    rows=_survey_questions('[{"type":"magic","label":"Вопрос"}]')
    assert rows == [{'type':'rating','label':'Вопрос','required':True}]


def test_quality_settings_hidden_from_requester_navigation():
    requester=User(username='req',full_name='Req',password_hash='x',role=ROLE_REQUESTER,active=True)
    manager=User(username='mgr',full_name='Mgr',password_hash='x',role=ROLE_MANAGER,active=True)
    assert visible_navigation(requester)['surveys'] is False
    assert visible_navigation(manager)['surveys'] is True
