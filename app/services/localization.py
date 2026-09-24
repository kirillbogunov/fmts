from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

TRANSLATIONS = {
    'ru': {
        'dashboard':'Дашборд','tickets':'Заявки','notifications':'Уведомления','team_schedule':'Графики сотрудников',
        'teams':'Группы исполнителей','sites':'Объекты','equipment':'Оборудование / CMDB','data_import':'Импорт данных',
        'maintenance':'ТО / ППР','inventory':'Склад / ЗИП','contractors':'Подрядчики','services':'Каталог сервисов',
        'knowledge':'База знаний','templates':'Шаблоны / Наряды','automation':'Автоматизация','categories':'Классификаторы',
        'surveys':'Оценка качества','resources':'Бронирование ресурсов','itsm':'ITSM / Изменения','sla_calendars':'SLA-календари','kpi':'KPI / Рейтинг','labor':'Трудозатраты',
        'reports':'Конструктор отчётов','subscriptions':'Подписки / рассылки','audit':'Журнал контроля','integrations':'Интеграции',
        'system_services':'Системные сервисы','settings':'Настройки','users':'Пользователи','about':'О программе',
        'work':'РАБОТА','assets':'ТОИР И АКТИВЫ','service_desk':'SERVICE DESK','analytics':'АНАЛИТИКА','management':'УПРАВЛЕНИЕ',
        'profile':'Профиль','logout':'Выйти','install':'Установить приложение'
    },
    'kk': {
        'dashboard':'Бақылау тақтасы','tickets':'Өтінімдер','notifications':'Хабарламалар','team_schedule':'Қызметкерлер кестесі',
        'teams':'Орындаушылар топтары','sites':'Нысандар','equipment':'Жабдық / CMDB','data_import':'Деректерді импорттау',
        'maintenance':'ТҚК / ЖЖЖ','inventory':'Қойма / ҚБ','contractors':'Мердігерлер','services':'Қызметтер каталогы',
        'knowledge':'Білім базасы','templates':'Үлгілер / Нарядтар','automation':'Автоматтандыру','categories':'Жіктеуіштер',
        'surveys':'Сапаны бағалау','resources':'Ресурстарды брондау','itsm':'ITSM / Өзгерістер','sla_calendars':'SLA күнтізбелері','kpi':'KPI / Рейтинг','labor':'Еңбек шығындары',
        'reports':'Есептер конструкторы','subscriptions':'Жазылымдар / тарату','audit':'Бақылау журналы','integrations':'Интеграциялар',
        'system_services':'Жүйелік сервистер','settings':'Баптаулар','users':'Пайдаланушылар','about':'Бағдарлама туралы',
        'work':'ЖҰМЫС','assets':'ТҚК ЖӘНЕ АКТИВТЕР','service_desk':'SERVICE DESK','analytics':'ТАЛДАУ','management':'БАСҚАРУ',
        'profile':'Профиль','logout':'Шығу','install':'Қосымшаны орнату'
    },
    'en': {
        'dashboard':'Dashboard','tickets':'Tickets','notifications':'Notifications','team_schedule':'Staff schedules',
        'teams':'Support groups','sites':'Sites','equipment':'Equipment / CMDB','data_import':'Data import',
        'maintenance':'Maintenance / PPM','inventory':'Inventory / Spares','contractors':'Contractors','services':'Service catalog',
        'knowledge':'Knowledge base','templates':'Templates / Work orders','automation':'Automation','categories':'Classifiers',
        'surveys':'Quality feedback','resources':'Resource booking','itsm':'ITSM / Changes','sla_calendars':'SLA calendars','kpi':'KPI / Rating','labor':'Labor analytics',
        'reports':'Report builder','subscriptions':'Subscriptions / digests','audit':'Audit log','integrations':'Integrations',
        'system_services':'System services','settings':'Settings','users':'Users','about':'About',
        'work':'WORK','assets':'MAINTENANCE & ASSETS','service_desk':'SERVICE DESK','analytics':'ANALYTICS','management':'MANAGEMENT',
        'profile':'Profile','logout':'Sign out','install':'Install app'
    },
}

SUPPORTED_LOCALES = [('ru','Русский'),('kk','Қазақша'),('en','English')]

# Full IANA timezone catalog. The preferred list is shown first in selectors,
# while the remaining zones are sorted by region/name. Keeping raw IANA values
# preserves compatibility with all previously saved calendars and user profiles.
PREFERRED_TIMEZONES = [
    'Asia/Almaty','Asia/Qostanay','Asia/Aqtobe','Asia/Aqtau','Asia/Atyrau','Asia/Oral','Asia/Qyzylorda',
    'Europe/Moscow','Asia/Yekaterinburg','Asia/Omsk','Asia/Novosibirsk','UTC'
]

try:
    _ALL_IANA_TIMEZONES = set(available_timezones())
except Exception:
    _ALL_IANA_TIMEZONES = set()
_ALL_IANA_TIMEZONES.update(PREFERRED_TIMEZONES)
SUPPORTED_TIMEZONES = PREFERRED_TIMEZONES + sorted(_ALL_IANA_TIMEZONES.difference(PREFERRED_TIMEZONES))

_TIMEZONE_RU_NAMES = {
    'Asia/Almaty':'Казахстан',
    'Asia/Qostanay':'Костанай / Северный Казахстан',
    'Asia/Aqtobe':'Актобе',
    'Asia/Aqtau':'Актау',
    'Asia/Atyrau':'Атырау',
    'Asia/Oral':'Уральск',
    'Asia/Qyzylorda':'Кызылорда',
    'Europe/Moscow':'Москва',
    'Asia/Yekaterinburg':'Екатеринбург',
    'Asia/Omsk':'Омск',
    'Asia/Novosibirsk':'Новосибирск',
    'UTC':'UTC',
}

def _offset_text(name: str) -> str:
    try:
        now = datetime.now(timezone.utc).astimezone(ZoneInfo(name))
        offset = now.utcoffset()
        if offset is None:
            return 'UTC'
        total = int(offset.total_seconds() // 60)
        sign = '+' if total >= 0 else '-'
        total = abs(total)
        hh, mm = divmod(total, 60)
        return f'UTC{sign}{hh}' if mm == 0 else f'UTC{sign}{hh:02d}:{mm:02d}'
    except Exception:
        return 'UTC'

def timezone_label(name: str | None) -> str:
    value = (name or 'Asia/Almaty').strip() or 'Asia/Almaty'
    title = _TIMEZONE_RU_NAMES.get(value)
    if title:
        return title if value == 'UTC' else f'{title} · {_offset_text(value)}'
    pretty = value.replace('_',' ')
    return f'{pretty} · {_offset_text(value)}'

def timezone_options() -> list[dict[str,str]]:
    rows=[]
    for value in SUPPORTED_TIMEZONES:
        group = 'Избранные' if value in PREFERRED_TIMEZONES else (value.split('/',1)[0] if '/' in value else 'Прочее')
        label = timezone_label(value)
        rows.append({'value':value,'label':label,'group':group,'search':f'{label} {value}'.lower()})
    return rows

TIMEZONE_OPTIONS = timezone_options()

def normalize_timezone_name(name: str | None, default: str = 'Asia/Almaty') -> str:
    value = (name or '').strip()
    return value if value in _ALL_IANA_TIMEZONES else default

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
