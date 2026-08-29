"""Portal da Transparência (API REST) — cruzamento de compliance EM TEMPO REAL.

Bases consultadas por CNPJ:
  • CEIS — Cadastro de Empresas Inidôneas e Suspensas
  • CNEP — Cadastro Nacional de Empresas Punidas (Lei Anticorrupção)

Requer chave gratuita (cadastro por e-mail):
  https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email
A chave vai no header `chave-api-dados` e no .env como PORTAL_TRANSPARENCIA_API_KEY.

Regra do projeto: erro de API é devolvido EXPLÍCITO — o agente informa que a
checagem não pôde ser feita; nunca assume "sem sanção" em caso de falha.
"""
from __future__ import annotations

import httpx

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
_TIMEOUT = 15.0

import re


def _record_matches_cnpj(item, digits: str) -> bool:
    """Confere localmente se o registro pertence ao CNPJ consultado.

    DEFESA CRÍTICA: a API do Portal ignora silenciosamente parâmetros que não
    reconhece e devolve a lista GERAL de sanções. Sem esta verificação, todo
    fornecedor do país apareceria como sancionado (falso positivo em série).
    Nunca confie no filtro do servidor quando a resposta decide um pagamento.
    """
    def walk(v):
        if isinstance(v, dict):
            return any(walk(x) for x in v.values())
        if isinstance(v, list):
            return any(walk(x) for x in v)
        if isinstance(v, str):
            d = re.sub(r"\D", "", v)
            return d == digits
        return False
    return walk(item)


def _consultar_base(recurso: str, cnpj_digits: str, api_key: str) -> dict:
    """Consulta uma base de sanções. recurso: 'ceis' | 'cnep'."""
    try:
        r = httpx.get(
            f"{BASE}/{recurso}",
            params={"cnpjSancionado": cnpj_digits, "pagina": 1},
            headers={"chave-api-dados": api_key, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        return {"ok": False, "erro": f"Falha de rede na API da Transparência ({recurso}): {e}"}
    if r.status_code in (401, 403):
        return {"ok": False, "erro": f"Chave da API da Transparência inválida/ausente (HTTP {r.status_code})"}
    if r.status_code != 200:
        return {"ok": False, "erro": f"API da Transparência ({recurso}) HTTP {r.status_code}"}
    try:
        itens = r.json()
    except ValueError:
        return {"ok": False, "erro": f"Resposta não-JSON da base {recurso}"}
    brutos = itens if isinstance(itens, list) else []
    itens_do_cnpj = [i for i in brutos if _record_matches_cnpj(i, cnpj_digits)]
    filtro_servidor_falhou = bool(brutos) and not itens_do_cnpj
    registros = []
    for item in itens_do_cnpj:
        registros.append({
            "orgao_sancionador": (item.get("orgaoSancionador") or {}).get("nome")
                                  if isinstance(item.get("orgaoSancionador"), dict)
                                  else item.get("orgaoSancionador"),
            "tipo_sancao": (item.get("tipoSancao") or {}).get("descricaoResumida")
                            if isinstance(item.get("tipoSancao"), dict)
                            else item.get("tipoSancao"),
            "data_inicio": item.get("dataInicioSancao"),
            "data_fim": item.get("dataFimSancao"),
        })
    out = {"ok": True, "quantidade": len(registros), "registros": registros[:5]}
    if filtro_servidor_falhou:
        out["nota"] = ("Servidor devolveu registros de OUTROS CNPJs (filtro remoto "
                       "ignorado); filtro local aplicado — nenhum registro pertence "
                       "ao CNPJ consultado.")
    return out


def verificar_sancoes(cnpj: str, api_key: str) -> dict:
    """Cruza um CNPJ contra CEIS e CNEP em tempo real."""
    digits = "".join(c for c in cnpj if c.isdigit())
    if len(digits) != 14:
        return {"ok": False, "erro": f"CNPJ inválido: '{cnpj}'"}
    if not api_key:
        return {"ok": False,
                "erro": "PORTAL_TRANSPARENCIA_API_KEY não configurada — cadastre em "
                        "portaldatransparencia.gov.br/api-de-dados/cadastrar-email"}
    ceis = _consultar_base("ceis", digits, api_key)
    cnep = _consultar_base("cnep", digits, api_key)
    if not ceis["ok"] and not cnep["ok"]:
        return {"ok": False, "erro": f"CEIS: {ceis['erro']} | CNEP: {cnep['erro']}",
                "recomendacao": "Checagem de sanções INDISPONÍVEL — não assumir que o fornecedor está limpo."}
    sancionado = (ceis.get("quantidade", 0) or 0) + (cnep.get("quantidade", 0) or 0) > 0
    return {
        "ok": True,
        "cnpj": digits,
        "sancionado": sancionado,
        "ceis": ceis,
        "cnep": cnep,
        "recomendacao": ("Fornecedor consta em cadastro público de sanções (CEIS/CNEP) — "
                         "recomendo confirmar com jurídico/contábil antes de prosseguir "
                         "com pagamento ou contratação" if sancionado
                         else "Nenhuma sanção encontrada nas bases CEIS/CNEP nesta consulta."),
    }
