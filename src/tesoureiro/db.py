"""Acesso ao Postgres — psycopg 3, conexões simples e explícitas."""
import psycopg
from psycopg.rows import dict_row

from .config import settings


def get_conn():
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def q(sql: str, params: tuple = (), fetch: bool = True):
    """Executa uma query. fetch=False para INSERT/UPDATE sem retorno."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if fetch and cur.description:
            return cur.fetchall()
        return None


def log_action(action: str, entity_type: str | None = None, entity_id=None,
               detail: dict | None = None, approved_by: str | None = None):
    """Trilha de auditoria: TODA ação relevante do agente passa por aqui."""
    import json
    q(
        """INSERT INTO agent_actions (action, entity_type, entity_id, detail_json, approved_by)
           VALUES (%s, %s, %s, %s, %s)""",
        (action, entity_type, entity_id, json.dumps(detail or {}, ensure_ascii=False), approved_by),
        fetch=False,
    )
