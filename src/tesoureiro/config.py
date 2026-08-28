"""Configuração central — tudo via variáveis de ambiente (.env)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://tesoureiro:tesoureiro@localhost:5432/tesoureiro"
    )
    # Cadeia de provedores (failover na ordem declarada)
    providers: str = os.getenv("TESOUREIRO_PROVIDERS", "anthropic")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    portal_transparencia_api_key: str = os.getenv("PORTAL_TRANSPARENCIA_API_KEY", "")
    api_key: str = os.getenv("TESOUREIRO_API_KEY", "")  # vazio = sem auth (só dev)
    demo_mode: bool = os.getenv("TESOUREIRO_DEMO", "1") == "1"
    max_agent_calls_per_day: int = int(os.getenv("TESOUREIRO_MAX_CALLS_DAY", "300"))
    rate_limit_per_minute: int = int(os.getenv("TESOUREIRO_RATE_PER_MIN", "10"))


settings = Settings()
