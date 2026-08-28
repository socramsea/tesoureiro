"""Ferramentas de dados públicos — BrasilAPI (CNPJ, feriados).

Regra de ouro: o agente NUNCA inventa situação cadastral ou data de feriado.
Se a API falhar, a ferramenta devolve erro explícito e o agente informa o humano.
"""
from __future__ import annotations

import datetime as dt

import httpx

BASE = "https://brasilapi.com.br/api"
_TIMEOUT = 10.0


def consultar_cnpj(cnpj: str) -> dict:
    """Valida um CNPJ na Receita (via BrasilAPI). Retorna situação e razão social."""
    digits = "".join(c for c in cnpj if c.isdigit())
    if len(digits) != 14:
        return {"ok": False, "erro": f"CNPJ inválido: '{cnpj}' (esperado 14 dígitos)"}
    try:
        r = httpx.get(f"{BASE}/cnpj/v1/{digits}", timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        return {"ok": False, "erro": f"Falha de rede na BrasilAPI: {e}"}
    if r.status_code == 404:
        return {"ok": True, "encontrado": False, "cnpj": digits,
                "alerta": "CNPJ NÃO ENCONTRADO na Receita — possível fraude"}
    if r.status_code != 200:
        return {"ok": False, "erro": f"BrasilAPI HTTP {r.status_code}"}
    d = r.json()
    situacao = d.get("descricao_situacao_cadastral", "?")
    return {
        "ok": True,
        "encontrado": True,
        "cnpj": digits,
        "razao_social": d.get("razao_social"),
        "nome_fantasia": d.get("nome_fantasia"),
        "situacao": situacao,
        "ativa": situacao.upper() == "ATIVA",
        "uf": d.get("uf"),
        "municipio": d.get("municipio"),
    }


def _feriados(ano: int) -> list[dt.date] | None:
    try:
        r = httpx.get(f"{BASE}/feriados/v1/{ano}", timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        return [dt.date.fromisoformat(f["date"]) for f in r.json()]
    except httpx.HTTPError:
        return None


def verificar_data_pagamento(data_iso: str) -> dict:
    """Se a data cai em feriado nacional ou fim de semana, sugere o dia útil ANTERIOR."""
    try:
        alvo = dt.date.fromisoformat(data_iso)
    except ValueError:
        return {"ok": False, "erro": f"Data inválida: '{data_iso}' (use YYYY-MM-DD)"}
    feriados = _feriados(alvo.year)
    if feriados is None:
        return {"ok": False, "erro": "BrasilAPI de feriados indisponível — confirmar manualmente"}
    if alvo.month == 1 and alvo.day < 10:  # virada de ano: carrega o ano anterior também
        extra = _feriados(alvo.year - 1)
        feriados += extra or []

    def util(d: dt.date) -> bool:
        return d.weekday() < 5 and d not in feriados

    if util(alvo):
        return {"ok": True, "data": data_iso, "dia_util": True, "sugestao": data_iso}
    sug = alvo
    while not util(sug):
        sug -= dt.timedelta(days=1)
    motivo = "fim de semana" if alvo.weekday() >= 5 else "feriado nacional"
    return {"ok": True, "data": data_iso, "dia_util": False, "motivo": motivo,
            "sugestao": sug.isoformat()}
