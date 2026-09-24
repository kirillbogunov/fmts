from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FMTS"
    app_version: str = "0.7.6.15"
    developer_name: str = "Кирилл Вадимович Богунов"
    developer_telegram: str = "@kirill_bogunov"
    developer_url: str = "https://t.me/kirill_bogunov"
    secret_key: str = "change-me"
    database_url: str = "sqlite:///./toir.db"
    # Public URL used by QR codes and external links. Set PUBLIC_BASE_URL in production.
    public_base_url: str = ""
    # Backwards-compatible legacy setting. If empty, the current request host is used.
    base_url: str = ""
    upload_dir: str = "./uploads"
    cookie_https_only: bool = False
    comment_photo_max_count: int = 5
    comment_photo_max_mb: int = 12

    # Enterprise ServiceDesk channels and automation
    enterprise_loop_seconds: int = 60
    sla_warning_minutes: int = 30

    # E-mail -> ticket and outgoing notifications
    imap_enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_folder: str = "INBOX"
    imap_default_site_id: int = 0
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Telegram / WhatsApp webhook notifications
    telegram_bot_token: str = ""
    whatsapp_webhook_url: str = ""
    whatsapp_webhook_token: str = ""

    # Web Push (optional VAPID)
    push_vapid_public_key: str = ""
    push_vapid_private_key: str = ""
    push_vapid_subject: str = "mailto:admin@example.com"

    # LDAP / Active Directory authentication (optional)
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_port: int = 389
    ldap_use_ssl: bool = False
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base_dn: str = ""
    ldap_username_attr: str = "sAMAccountName"
    ldap_display_name_attr: str = "displayName"
    ldap_email_attr: str = "mail"
    ldap_phone_attr: str = "telephoneNumber"
    ldap_department_attr: str = "department"
    ldap_manager_attr: str = "manager"
    ldap_sync_filter: str = "(&(objectClass=user)(!(objectClass=computer)))"

    # Optional trusted-gateway SSO. Keep disabled unless a reverse proxy/IdP
    # validates the user before forwarding these headers.
    sso_enabled: bool = False
    sso_user_header: str = "X-FMTS-User"
    sso_shared_secret: str = ""
    sso_secret_header: str = "X-FMTS-SSO-Secret"

    # E-mail command processing
    email_status_commands_enabled: bool = True
    email_add_recipients_as_observers: bool = True

    # Localization / time zones
    default_timezone: str = "Asia/Almaty"
    default_locale: str = "ru"

    # Zabbix -> CMDB (optional)
    zabbix_enabled: bool = False
    zabbix_url: str = ""
    zabbix_username: str = ""
    zabbix_password: str = ""
    zabbix_token: str = ""
    zabbix_default_site_id: int = 0
    zabbix_verify_ssl: bool = True
    zabbix_sync_interval_minutes: int = 60

    # Monthly KPI / technician rating. The weights are normalized automatically.
    kpi_monthly_target_points: float = 30.0
    kpi_weight_sla: float = 0.40
    kpi_weight_closure: float = 0.25
    kpi_weight_productivity: float = 0.20
    kpi_weight_documentation: float = 0.15

    # 1C -> Web webhook token. Use a long random value in production.
    onec_webhook_token: str = "change-me-1c-webhook-token"

    # Web -> 1C integration
    # Optional connector. The standalone core works when this is False.
    onec_enabled: bool = False
    onec_auto_push: bool = False
    onec_mode: str = "http_service"
    onec_base_url: str = ""
    onec_username: str = ""
    onec_password: str = ""
    onec_verify_ssl: bool = True
    onec_timeout: int = 20
    onec_sites_path: str = "/hs/toir/v1/sites"
    onec_equipment_path: str = "/hs/toir/v1/equipment"
    onec_inventory_path: str = "/hs/toir/v1/inventory"
    onec_tickets_path: str = "/hs/toir/v1/tickets"
    onec_ui_path: str = "/hs/toir/v1/ui"

    # Exact old 1C metadata names used by the supplied configuration.
    onec_ticket_document: str = "ЗаявкаХозОтдела"
    onec_department_catalog: str = "Подразделения"
    onec_status_enum: str = "Статусы"
    onec_priority_enum: str = "Приоритет"
    onec_category_enum: str = "Категория"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
