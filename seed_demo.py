import secrets, os
from datetime import date, timedelta, datetime
from app.db import Base, engine, SessionLocal
from app.models import User, Site, Equipment, Ticket, MaintenancePlan, InventoryItem, Contractor, TicketWorkSession, ServiceCatalog, CustomField, KnowledgeArticle, AutomationRule
from app.security import hash_password
from app.migrations import run_lightweight_migrations
from app.services.maintenance import next_ticket_number
from app.services.reference_data import ensure_default_reference_data

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)
db=SessionLocal()
try:
    ensure_default_reference_data(db)
    if not db.query(User).first():
        admin=User(username=os.getenv("INITIAL_ADMIN_USERNAME","admin"),full_name=os.getenv("INITIAL_ADMIN_NAME","Администратор"),password_hash=hash_password(os.getenv("INITIAL_ADMIN_PASSWORD","ChangeMe123!")),role="admin")
        disp=User(username="dispatcher",full_name="Диспетчер хоз. отдела",password_hash=hash_password("dispatcher123"),role="dispatcher")
        tech=User(username="tech",full_name="Техник",password_hash=hash_password("technician123"),role="technician")
        db.add_all([admin,disp,tech]); db.flush()
    else:
        admin=db.query(User).filter(User.username=="admin").first()
        tech=db.query(User).filter(User.role=="technician").first()

    if not db.query(Site).first():
        sites=[Site(name="Магазин №1",address="Петропавловск"),Site(name="Магазин №2",address="Петропавловск"),Site(name="Фабрика кухни",address="Петропавловск")]
        db.add_all(sites); db.flush()
        eqs=[
            Equipment(site_id=sites[0].id,name="Бонета морозильная №7",inventory_no="ХО-000173",category="Холодильное оборудование",model="Demo Frost 2500",status="working",qr_token=secrets.token_urlsafe(24),next_maintenance_at=date.today()+timedelta(days=5)),
            Equipment(site_id=sites[1].id,name="Кондиционер торгового зала",inventory_no="КЛ-000041",category="Климат",model="Demo AC 24",status="working",qr_token=secrets.token_urlsafe(24),next_maintenance_at=date.today()+timedelta(days=18)),
            Equipment(site_id=sites[2].id,name="Печь конвекционная №1",inventory_no="КХ-000012",category="Технологическое оборудование",model="Demo Oven",status="working",qr_token=secrets.token_urlsafe(24),next_maintenance_at=date.today()+timedelta(days=12)),
        ]
        db.add_all(eqs); db.flush()
        db.add(MaintenancePlan(equipment_id=eqs[0].id,name="Ежемесячное ТО",interval_days=30,next_run=date.today()+timedelta(days=5),assignee_id=tech.id if tech else None,checklist='["Очистить теплообменник","Проверить температуру","Проверить вентиляторы"]'))
        t=Ticket(number=next_ticket_number(db),title="Повышенная температура в бонете",description="Температура держится выше установленной. Проверить холодильный контур.",category="Ремонт",priority="high",status="assigned",site_id=sites[0].id,equipment_id=eqs[0].id,requester_id=admin.id if admin else None,assignee_id=tech.id if tech else None,sla_due_at=datetime.utcnow()+timedelta(hours=8))
        db.add(t); db.flush()
        if tech:
            end=datetime.utcnow()-timedelta(minutes=15)
            start=end-timedelta(minutes=35)
            db.add(TicketWorkSession(ticket_id=t.id,user_id=tech.id,started_at=start,ended_at=end,duration_seconds=35*60,note="Первичная диагностика",source="manual"))


    if not db.query(ServiceCatalog).first():
        svc=ServiceCatalog(code="cold-service",name="Холодильное оборудование",description="Ремонт и обслуживание холодильного оборудования",category="Холодильное оборудование",default_priority="high",default_sla_hours=4)
        db.add(svc); db.flush()
        db.add_all([
            CustomField(service_id=svc.id,code="current_temp",name="Текущая температура, °C",field_type="number",required=False,sort_order=10),
            CustomField(service_id=svc.id,code="error_code",name="Код ошибки",field_type="text",required=False,sort_order=20),
            KnowledgeArticle(title="Первичная диагностика холодильного оборудования",body="Проверьте питание, заданную и фактическую температуру, состояние вентиляторов и наличие кодов ошибок.",tags="холодильник, температура, диагностика",equipment_category="Холодильное оборудование",service_id=svc.id,created_by_id=admin.id if admin else None),
            AutomationRule(name="Холодильное оборудование — автоназначение",conditions_json='{"category":"Холодильное оборудование"}',actions_json='{"assign_least_loaded":true,"set_priority":"high","sla_hours":4}',sort_order=10),
        ])

    if not db.query(InventoryItem).first():
        db.add_all([InventoryItem(sku="ZIP-001",name="Вентилятор 230В",qty=3,min_qty=2,unit="шт",unit_cost=28000),InventoryItem(sku="ZIP-002",name="Фильтр кондиционера",qty=4,min_qty=5,unit="шт",unit_cost=6500),InventoryItem(sku="MAT-001",name="Хладагент",qty=12,min_qty=5,unit="кг",unit_cost=9000)])
    if not db.query(Contractor).first():
        db.add(Contractor(name="Сервис Холод",phone="+7 7XX XXX XX XX",email="service@example.kz",specialization="Холодильное оборудование",rating=4.8))
    db.commit()
    print(f"Демо-база инициализирована. Вход: {os.getenv('INITIAL_ADMIN_USERNAME','admin')} / пароль из INITIAL_ADMIN_PASSWORD")
finally:
    db.close()
