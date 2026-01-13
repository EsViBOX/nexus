from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    # Usamos Field con default None para que Pydantic lo busque en el entorno
    # pero Pylance no se queje de que falta en el constructor.
    nexus_api_key: str = Field(default="")
    nexus_api_key_legacy: str = Field(default="")

    nexus_dashboard_allowed_ips: str = "127.0.0.1"
    # registrator_server: str = "one.esvibox.com"
    # registrator_port: int = 80

    # Forzamos la lectura del archivo .env que acabamos de validar
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings():
    s = Settings()
    # Esto nos dirá qué ha cargado Pydantic realmente al arrancar
    key_check = s.nexus_api_key[:3] if s.nexus_api_key else "VACÍA"
    print(f"DEBUG: Pydantic cargó API_KEY: {key_check}...")
    return s
