from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    User, Site, Equipment, Ticket, AutomationRule, ServiceCatalog,
    SupportGroup, SupportGroupMember,
)
from app.services.automation import apply_ticket_rules, rule_matches


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_rule_matches_equipment_criticality_and_category():
    db = make_db()
    site = Site(name='Фабрика кухни')
    eq = Equipment(site=site, name='Холодильник', inventory_no='EQ-1', category='Холодильное оборудование', criticality='critical', qr_token='q1')
    ticket = Ticket(number='SR-1', title='Не охлаждает холодильник', site=site, equipment=eq, category='Ремонт')
    rule = AutomationRule(name='Критический холод', conditions_json='{"equipment_category":"Холодильное оборудование","equipment_criticality":"critical"}', actions_json='{"set_priority":"critical"}')
    db.add_all([site, eq, ticket, rule]); db.flush()
    assert rule_matches(rule, ticket) is True
    applied = apply_ticket_rules(db, ticket)
    assert applied == ['Критический холод']
    assert ticket.priority == 'critical'


def test_rule_applies_service_sla_and_group_assignment():
    db = make_db()
    site = Site(name='Магазин №1')
    tech1 = User(username='tech1', full_name='Техник 1', password_hash='x', role='technician', active=True)
    tech2 = User(username='tech2', full_name='Техник 2', password_hash='x', role='technician', active=True)
    group = SupportGroup(name='Холодильщики')
    service = ServiceCatalog(code='cold-emergency', name='Авария холодильного оборудования', default_priority='high', resolution_sla_minutes=120, active=True)
    db.add_all([site, tech1, tech2, group, service]); db.flush()
    db.add_all([
        SupportGroupMember(group_id=group.id, user_id=tech1.id, member_role='executor'),
        SupportGroupMember(group_id=group.id, user_id=tech2.id, member_role='executor'),
    ])
    start = datetime.utcnow()
    ticket = Ticket(number='SR-2', title='Не охлаждает холодильник', site_id=site.id, category='Холодильное оборудование', created_at=start)
    db.add(ticket); db.flush()
    rule = AutomationRule(
        name='Холодильники — SLA и группа',
        conditions_json='{"category":"Холодильное оборудование"}',
        actions_json=f'{{"apply_service_id":{service.id},"assign_group_id":{group.id}}}',
    )
    db.add(rule); db.flush()
    applied = apply_ticket_rules(db, ticket)
    assert applied == ['Холодильники — SLA и группа']
    assert ticket.service_id == service.id
    assert ticket.group_id == group.id
    assert ticket.assignee_id in {tech1.id, tech2.id}
    assert ticket.status == 'assigned'
    assert ticket.sla_due_at is not None
    assert timedelta(minutes=119) <= (ticket.sla_due_at - start) <= timedelta(minutes=121)
