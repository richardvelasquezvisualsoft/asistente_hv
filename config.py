import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class ConfiguracionProyecto(BaseSettings):
    """
    Configuración global del proyecto utilizando pydantic-settings.
    Mapea y valida las variables de entorno definidas en el archivo .env.
    """
    # Credenciales de Base de Datos PostgreSQL (Generales / Fallback)
    DB_USER: str = Field(default="postgres", validation_alias="DB_USER")
    DB_PASSWORD: str = Field(default="adm_v1su@ls0ft", validation_alias="DB_PASSWORD")
    DB_HOST: str = Field(default="192.168.100.5", validation_alias="DB_HOST")
    DB_PORT: int = Field(default=5432, validation_alias="DB_PORT")
    DB_NAME_HV: str = Field(default="hv_db", validation_alias="DB_NAME_HV")
    DB_NAME_RAG: str = Field(default="rag_db", validation_alias="DB_NAME_RAG")
    DB_NAME_WEBHOOK: str = Field(default="webhook_db", validation_alias="DB_NAME_WEBHOOK")
    DB_NAME_N8N: str = Field(default="n8n_db", validation_alias="DB_NAME_N8N")

    # Credenciales específicas de HV
    DB_HV_HOST: Optional[str] = Field(default=None, validation_alias="DB_HV_HOST")
    DB_HV_PORT: Optional[int] = Field(default=None, validation_alias="DB_HV_PORT")
    DB_HV_USER: Optional[str] = Field(default="hv_user", validation_alias="DB_HV_USER")
    DB_HV_PASSWORD: Optional[str] = Field(default="hv_3lR1nc0n", validation_alias="DB_HV_PASSWORD")

    # Credenciales específicas de RAG
    DB_RAG_HOST: Optional[str] = Field(default=None, validation_alias="DB_RAG_HOST")
    DB_RAG_PORT: Optional[int] = Field(default=None, validation_alias="DB_RAG_PORT")
    DB_RAG_USER: Optional[str] = Field(default="rag_user", validation_alias="DB_RAG_USER")
    DB_RAG_PASSWORD: Optional[str] = Field(default="rag_v1su@ls0ft", validation_alias="DB_RAG_PASSWORD")

    # Credenciales específicas de Webhooks
    DB_WEBHOOK_HOST: Optional[str] = Field(default=None, validation_alias="DB_WEBHOOK_HOST")
    DB_WEBHOOK_PORT: Optional[int] = Field(default=None, validation_alias="DB_WEBHOOK_PORT")
    DB_WEBHOOK_USER: Optional[str] = Field(default="webhook_user", validation_alias="DB_WEBHOOK_USER")
    DB_WEBHOOK_PASSWORD: Optional[str] = Field(default="wh_v1su@ls0ft", validation_alias="DB_WEBHOOK_PASSWORD")

    # Credenciales específicas de n8n
    DB_N8N_HOST: Optional[str] = Field(default=None, validation_alias="DB_N8N_HOST")
    DB_N8N_PORT: Optional[int] = Field(default=None, validation_alias="DB_N8N_PORT")
    DB_N8N_USER: Optional[str] = Field(default="n8n_user", validation_alias="DB_N8N_USER")
    DB_N8N_PASSWORD: Optional[str] = Field(default="n8n_v1su@ls0ft", validation_alias="DB_N8N_PASSWORD")

    # Credenciales de Meta (WhatsApp Cloud API)
    META_VERIFY_TOKEN: str = Field(default="mi_token_de_verificacion_secreto", validation_alias="META_VERIFY_TOKEN")
    META_ACCESS_TOKEN: str = Field(default="EAAO...", validation_alias="META_ACCESS_TOKEN")
    META_PHONE_NUMBER_ID: str = Field(default="1234567890", validation_alias="META_PHONE_NUMBER_ID")

    # Clave de API de OpenAI
    OPENAI_API_KEY: str = Field(default="sk-...", validation_alias="OPENAI_API_KEY")

    # Configuración de Google Calendar
    GOOGLE_CALENDAR_ID: str = Field(
        default="dm4lco0k6ha652uk8jhoi2nm9hq14rut@import.calendar.google.com",
        validation_alias="GOOGLE_CALENDAR_ID"
    )
    # Contenido JSON de la cuenta de servicio de Google
    GOOGLE_CREDENTIALS_JSON: Optional[str] = Field(default=None, validation_alias="GOOGLE_CREDENTIALS_JSON")

    @property
    def url_bd_hv(self) -> str:
        """Retorna la URL asíncrona para la base de datos de gestión de estados y asesores."""
        import urllib.parse
        host = self.DB_HV_HOST or self.DB_HOST
        port = self.DB_HV_PORT or self.DB_PORT
        user = self.DB_HV_USER or self.DB_USER
        pwd = self.DB_HV_PASSWORD or self.DB_PASSWORD
        quoted_pwd = urllib.parse.quote_plus(pwd)
        return f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{self.DB_NAME_HV}"

    @property
    def url_bd_rag(self) -> str:
        """Retorna la URL asíncrona para la base de datos del RAG (PGVector)."""
        import urllib.parse
        host = self.DB_RAG_HOST or self.DB_HOST
        port = self.DB_RAG_PORT or self.DB_PORT
        user = self.DB_RAG_USER or self.DB_USER
        pwd = self.DB_RAG_PASSWORD or self.DB_PASSWORD
        quoted_pwd = urllib.parse.quote_plus(pwd)
        return f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{self.DB_NAME_RAG}"

    @property
    def url_bd_webhook(self) -> str:
        """Retorna la URL asíncrona para la base de datos de logs de webhook."""
        import urllib.parse
        host = self.DB_WEBHOOK_HOST or self.DB_HOST
        port = self.DB_WEBHOOK_PORT or self.DB_PORT
        user = self.DB_WEBHOOK_USER or self.DB_USER
        pwd = self.DB_WEBHOOK_PASSWORD or self.DB_PASSWORD
        quoted_pwd = urllib.parse.quote_plus(pwd)
        return f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{self.DB_NAME_WEBHOOK}"

    @property
    def url_bd_n8n(self) -> str:
        """Retorna la URL asíncrona para la base de datos de n8n."""
        import urllib.parse
        host = self.DB_N8N_HOST or self.DB_HOST
        port = self.DB_N8N_PORT or self.DB_PORT
        user = self.DB_N8N_USER or self.DB_USER
        pwd = self.DB_N8N_PASSWORD or self.DB_PASSWORD
        quoted_pwd = urllib.parse.quote_plus(pwd)
        return f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{self.DB_NAME_N8N}"

    def __init__(self, **values):
        try:
            from core.config_encryption import load_encrypted_config
            enc_config = load_encrypted_config()
            if enc_config:
                for k, v in enc_config.items():
                    if v is not None:
                        values[k] = v
        except Exception:
            pass
        super().__init__(**values)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

# Instancia global de configuración
configuracion = ConfiguracionProyecto()
