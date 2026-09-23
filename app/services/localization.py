from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TRANSLATIONS = {
    'ru': {
        'dashboard':'Дашборд','tickets':'Заявки','notifications':'Уведомления','team_schedule':'График техников',
        'teams':'Группы исполнителей','sites':'Объекты','equipment':'Оборудование / CMDB','data_import':'Импорт данных',
        'maintenance':'ТО / ППР','inventory':'Склад / ЗИП','contractors':'Подрядчики','services':'Каталог сервисов',
        'knowledge':'База знаний','templates':'Шаблоны / Наряды','automation':'Автоматизация','categories':'Классификаторы',
        'surveys':'Анкеты качества','resources':'Бронирование ресурсов','itsm':'ITSM / Изменения','sla_calendars':'SLA-календари','kpi':'KPI / Рейтинг','labor':'Трудозатраты',
        'reports':'Конструктор отчётов','subscriptions':'Подписки / рассылки','audit':'Журнал контроля','integrations':'Интеграции',
        'system_services':'Системные сервисы','settings':'Настройки','users':'Пользователи','about':'О программе',
        'work':'РАБОТА','assets':'ТОИР И АКТИВЫ','service_desk':'SERVICE DESK','analytics':'АНАЛИТИКА','management':'УПРАВЛЕНИЕ',
        'profile':'Профиль','logout':'Выйти','install':'Установить приложение'
    },
    'kk': {
        'dashboard':'Бақылау тақтасы','tickets':'Өтінімдер','notifications':'Хабарламалар','team_schedule':'Техниктер кестесі',
        'teams':'Орындаушылар топтары','sites':'Нысандар','equipment':'Жабдық / CMDB','data_import':'Деректерді импорттау',
        'maintenance':'ТҚК / ЖЖЖ','inventory':'Қойма / ҚБ','contractors':'Мердігерлер','services':'Қызметтер каталогы',
        'knowledge':'Білім базасы','templates':'Үлгілер / Нарядтар','automation':'Автоматтандыру','categories':'Жіктеуіштер',
        'surveys':'Сапа сауалнамалары','resources':'Ресурстарды брондау','itsm':'ITSM / Өзгерістер','sla_calendars':'SLA күнтізбелері','kpi':'KPI / Рейтинг','labor':'Еңбек шығындары',
        'reports':'Есептер конструкторы','subscriptions':'Жазылымдар / тарату','audit':'Бақылау журналы','integrations':'Интеграциялар',
        'system_services':'Жүйелік сервистер','settings':'Баптаулар','users':'Пайдаланушылар','about':'Бағдарлама туралы',
        'work':'ЖҰМЫС','assets':'ТҚК ЖӘНЕ АКТИВТЕР','service_desk':'SERVICE DESK','analytics':'ТАЛДАУ','management':'БАСҚАРУ',
        'profile':'Профиль','logout':'Шығу','install':'Қосымшаны орнату'
    },
    'en': {
        'dashboard':'Dashboard','tickets':'Tickets','notifications':'Notifications','team_schedule':'Technician schedule',
        'teams':'Support groups','sites':'Sites','equipment':'Equipment / CMDB','data_import':'Data import',
        'maintenance':'Maintenance / PPM','inventory':'Inventory / Spares','contractors':'Contractors','services':'Service catalog',
        'knowledge':'Knowledge base','templates':'Templates / Work orders','automation':'Automation','categories':'Classifiers',
        'surveys':'Quality surveys','resources':'Resource booking','itsm':'ITSM / Changes','sla_calendars':'SLA calendars','kpi':'KPI / Rating','labor':'Labor analytics',
        'reports':'Report builder','subscriptions':'Subscriptions / digests','audit':'Audit log','integrations':'Integrations',
        'system_services':'System services','settings':'Settings','users':'Users','about':'About',
        'work':'WORK','assets':'MAINTENANCE & ASSETS','service_desk':'SERVICE DESK','analytics':'ANALYTICS','management':'MANAGEMENT',
        'profile':'Profile','logout':'Sign out','install':'Install app'
    },
}

SUPPORTED_LOCALES = [('ru','Русский'),('kk','Қазақша'),('en','English')]
SUPPORTED_TIMEZONES = [
    'Asia/Almaty','Asia/Aqtobe','Asia/Aqtau','Asia/Atyrau','Asia/Oral','Asia/Qostanay','Asia/Qyzylorda',
    'Europe/Moscow','Asia/Yekaterinburg','Asia/Omsk','Asia/Novosibirsk','UTC'
]

def tr(locale: str | None, key: str, fallback: str | None = None) -> str:
    loc = locale if locale in TRANSLATIONS else 'ru'
    return TRANSLATIONS.get(loc, {}).get(key, fallback or TRANSLATIONS['ru'].get(key, key))

def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or 'Asia/Almaty')
    except ZoneInfoNotFoundError:
        return ZoneInfo('Asia/Almaty')

def localize_dt(value: datetime | None, timezone_name: str | None) -> datetime | None:
    if value is None:
        return None
    # FMTS historically stores naive UTC datetimes.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_zone(timezone_name))

def format_dt(value: datetime | None, timezone_name: str | None, fmt: str = '%d.%m.%Y %H:%M') -> str:
    local = localize_dt(value, timezone_name)
    return local.strftime(fmt) if local else '—'
