"""FastAPI — serve a API do agente E o frontend da demo (uma página estática).

Um deploy só: uvicorn nesta app atrás do Caddy/Traefik no VPS.
"""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.agent import conversar
from ..config import settings
from ..db import q

app = FastAPI(title="Tesoureiro", version="0.1.0")
STATIC = Path(__file__).parent / "static"

# ---- proteções da demo pública (rate limit simples em memória) ----
_hits: dict[str, list[float]] = defaultdict(list)
_daily = {"day": "", "count": 0}


def _guard(request: Request):
    ip = request.client.host if request.client else "?"
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < 60]
    if len(_hits[ip]) >= settings.rate_limit_per_minute:
        raise HTTPException(429, "Muitas mensagens — aguarde um minuto.")
    _hits[ip].append(now)
    today = time.strftime("%Y-%m-%d")
    if _daily["day"] != today:
        _daily.update(day=today, count=0)
    if _daily["count"] >= settings.max_agent_calls_per_day:
        raise HTTPException(429, "Limite diário da demo atingido — volte amanhã.")
    _daily["count"] += 1


class ChatIn(BaseModel):
    messages: list[dict]  # [{role, content}] — histórico completo (agente é stateless)


@app.get("/health")
def health():
    return {"status": "ok", "demo": settings.demo_mode}


@app.post("/v1/chat")
def chat(body: ChatIn, request: Request):
    _guard(request)
    if not body.messages or body.messages[-1].get("role") != "user":
        raise HTTPException(400, "Última mensagem deve ser do usuário.")
    reply = conversar(body.messages)
    return {"reply": reply}


@app.get("/v1/painel")
def painel(request: Request):
    """Dados do painel lateral da demo — leitura direta, sem passar pelo LLM."""
    contas = q("""SELECT p.id::text, s.legal_name AS fornecedor, p.description,
                         p.amount_cents, p.due_date::text, p.status
                  FROM payables p LEFT JOIN suppliers s ON s.id=p.supplier_id
                  ORDER BY p.due_date""") or []
    acoes = q("""SELECT action, entity_type, approved_by, created_at
                 FROM agent_actions ORDER BY created_at DESC LIMIT 15""") or []
    return {"contas": contas, "auditoria": acoes}


@app.post("/v1/demo/reset")
def reset_demo(request: Request):
    if not settings.demo_mode:
        raise HTTPException(403, "Reset só em modo demo.")
    from scripts.seed_demo import seed  # import tardio p/ evitar ciclo
    seed()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
