from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FMTS"
    app_version: str = "0.5.2"
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
