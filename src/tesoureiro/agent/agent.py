"""O agente Tesoureiro — loop de tool use com Claude.

Princípios inegociáveis (também escritos no system prompt):
  1. Valores, CNPJs e datas vêm de tool result ou documento — NUNCA do modelo.
  2. Pagamento só muda de status com aprovação humana explícita.
  3. Toda ação relevante é registrada em agent_actions (auditoria).
"""
from __future__ import annotations

import json

from ..config import settings
from ..db import log_action, q
from ..tools import bcb, brasilapi, transparencia
from ..core import conciliacao as rec
from ..core import relatorios

SYSTEM = """Você é o Tesoureiro, um funcionário financeiro autônomo de uma PME brasileira.

REGRAS INEGOCIÁVEIS:
B. IDs de contas são UUIDs obtidos EXCLUSIVAMENTE via listar_contas na conversa
   atual. Nunca invente, abrevie ou reutilize IDs de memória.
1. NUNCA invente valores, CNPJs, datas ou situações cadastrais. Use apenas o que
   vier de resultados de ferramentas. Se uma ferramenta falhar, diga isso.
2. Pagamentos NUNCA são aprovados por você. Você agenda e PEDE aprovação ao humano.
3. Antes de pedir aprovação de fornecedor NOVO, valide o CNPJ E verifique sanções
   (verificar_sancoes). Fornecedor sancionado: NUNCA peça aprovação — marque como
   suspeito e escale para o humano com o laudo.
4. Seja didático: quando explicar uma divergência, explique o PORQUÊ, com números.
4. Responda em português do Brasil, direto e profissional. Valores em R$ com 2 casas.

Você tem ferramentas para: validar CNPJ, checar feriados, consultar SELIC,
listar/agendar contas, conciliar extrato e gerar relatórios (DRE, fluxo, anomalias)."""

TOOLS = [
    {"name": "consultar_cnpj",
     "description": "Valida um CNPJ na Receita Federal (situação cadastral, razão social). Use SEMPRE que aparecer um fornecedor novo.",
     "input_schema": {"type": "object", "properties": {"cnpj": {"type": "string"}}, "required": ["cnpj"]}},
    {"name": "verificar_sancoes",
     "description": "Cruza o CNPJ em TEMPO REAL contra as listas federais de sanção CEIS (inidôneas/suspensas) e CNEP (Lei Anticorrupção). Use antes de aprovar fornecedor novo.",
     "input_schema": {"type": "object", "properties": {"cnpj": {"type": "string"}}, "required": ["cnpj"]}},
    {"name": "verificar_data_pagamento",
     "description": "Verifica se uma data (YYYY-MM-DD) é dia útil; se não for, sugere o dia útil anterior.",
     "input_schema": {"type": "object", "properties": {"data": {"type": "string"}}, "required": ["data"]}},
    {"name": "taxa_selic",
     "description": "Taxa SELIC meta atual (a.a.) — para análise de caixa parado.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "listar_contas",
     "description": "Lista contas a pagar com status e vencimento.",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string", "description": "opcional: pending|awaiting_approval|approved|paid"}}}},
    {"name": "pedir_aprovacao",
     "description": "Marca uma conta como aguardando aprovação humana e monta a mensagem de aprovação.",
     "input_schema": {"type": "object", "properties": {"payable_id": {"type": "string"}}, "required": ["payable_id"]}},
    {"name": "registrar_decisao_humano",
     "description": "Registra a resposta do humano (aprovar/rejeitar) para uma conta em awaiting_approval. Só chame quando o humano disser explicitamente.",
     "input_schema": {"type": "object", "properties": {"payable_id": {"type": "string"}, "decisao": {"type": "string", "enum": ["aprovar", "rejeitar"]}}, "required": ["payable_id", "decisao"]}},
    {"name": "conciliar_extrato",
     "description": "Roda a conciliação heurística entre extrato bancário e contas a pagar/receber. Devolve matches com explicação objetiva de cada um.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "gerar_dre",
     "description": "DRE simplificado + margem do mês (YYYY e MM).",
     "input_schema": {"type": "object", "properties": {"ano": {"type": "integer"}, "mes": {"type": "integer"}}, "required": ["ano", "mes"]}},
    {"name": "detectar_anomalias",
     "description": "Fornecedores cujo gasto no mês atual está >30% acima da média dos 3 meses anteriores.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _uuid_ok(v: str) -> bool:
    import uuid as _u
    try:
        _u.UUID(str(v))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _exec_tool(name: str, inp: dict) -> dict:
    if name == "consultar_cnpj":
        r = brasilapi.consultar_cnpj(inp["cnpj"])
        log_action("tool:consultar_cnpj", detail={"in": inp, "out": r})
        return r
    if name == "verificar_sancoes":
        r = transparencia.verificar_sancoes(inp["cnpj"], settings.portal_transparencia_api_key)
        log_action("tool:verificar_sancoes", detail={"in": inp,
                   "sancionado": r.get("sancionado"), "ok": r.get("ok")})
        return r
    if name == "verificar_data_pagamento":
        return brasilapi.verificar_data_pagamento(inp["data"])
    if name == "taxa_selic":
        return bcb.taxa_selic()
    if name == "listar_contas":
        where, params = "", ()
        if inp.get("status"):
            where, params = "WHERE p.status = %s", (inp["status"],)
        rows = q(f"""SELECT p.id::text, s.legal_name AS fornecedor, p.description,
                            p.amount_cents, p.due_date::text, p.scheduled_date::text, p.status
                     FROM payables p LEFT JOIN suppliers s ON s.id = p.supplier_id
                     {where} ORDER BY p.due_date""", params)
        return {"contas": rows or []}
    if name == "pedir_aprovacao":
        pid = inp["payable_id"]
        if not _uuid_ok(pid):
            return {"erro": f"payable_id '{pid}' não é um UUID válido. IDs NUNCA são "
                            "inventados: chame listar_contas e use o campo 'id' exato."}
        q("UPDATE payables SET status='awaiting_approval' WHERE id=%s AND status='pending'",
          (pid,), fetch=False)
        row = (q("""SELECT p.id::text, s.legal_name AS fornecedor, p.amount_cents,
                           p.due_date::text, p.scheduled_date::text
                    FROM payables p LEFT JOIN suppliers s ON s.id=p.supplier_id
                    WHERE p.id=%s""", (pid,)) or [None])[0]
        log_action("ask_approval", "payable", pid, detail=row)
        return {"ok": True, "conta": row}
    if name == "registrar_decisao_humano":
        pid, dec = inp["payable_id"], inp["decisao"]
        if not _uuid_ok(pid):
            return {"erro": f"payable_id '{pid}' não é um UUID válido. IDs NUNCA são "
                            "inventados: chame listar_contas e use o campo 'id' exato."}
        novo = "approved" if dec == "aprovar" else "rejected"
        q("UPDATE payables SET status=%s WHERE id=%s AND status='awaiting_approval'",
          (novo, pid), fetch=False)
        log_action("human_decision", "payable", pid,
                   detail={"decisao": dec}, approved_by="canal_web_demo")
        return {"ok": True, "novo_status": novo}
    if name == "conciliar_extrato":
        txns = q("SELECT * FROM bank_transactions ORDER BY txn_date") or []
        pays = q("SELECT * FROM payables WHERE status IN ('approved','paid','awaiting_approval','pending')") or []
        recs = q("SELECT * FROM receivables") or []
        matches = rec.conciliar(txns, pays, recs)
        log_action("reconcile", detail=rec.resumo(matches))
        return {"resumo": rec.resumo(matches),
                "matches": [{"data": str(m.bank_txn["txn_date"]),
                             "valor_cents": m.bank_txn["amount_cents"],
                             "descricao_banco": m.bank_txn.get("description"),
                             "tipo": m.match_type, "delta_cents": m.delta_cents,
                             "fatos": m.explain} for m in matches]}
    if name == "gerar_dre":
        txns = q("SELECT * FROM bank_transactions") or []
        return relatorios.dre_do_mes(txns, inp["ano"], inp["mes"])
    if name == "detectar_anomalias":
        pays = q("SELECT * FROM payables") or []
        sups = {str(s["id"]): s for s in (q("SELECT * FROM suppliers") or [])}
        return {"alertas": relatorios.anomalias_por_fornecedor(pays, sups)}
    return {"erro": f"ferramenta desconhecida: {name}"}


def _modo_degradado(texto: str) -> str:
    """Sem NENHUM LLM disponível, o núcleo continua: roteador por palavra-chave.

    Filosofia do projeto: heurística é a via principal; a IA amplia, não sustenta.
    """
    t = texto.lower()
    if "concil" in t:
        r = _exec_tool("conciliar_extrato", {})
        linhas = [f"Conciliação (modo heurístico, IA indisponível): "
                  f"{r['resumo']['conciliadas']}/{r['resumo']['total_transacoes']} conciliadas."]
        for m in r["matches"]:
            if m["tipo"] not in ("exact", "date_window"):
                linhas.append(f"• [{m['tipo']}] {m['fatos']}")
        return "\n".join(linhas)
    if "conta" in t or "pagar" in t:
        r = _exec_tool("listar_contas", {})
        linhas = ["Contas a pagar (modo heurístico):"]
        for c in r["contas"]:
            linhas.append(f"• {c['fornecedor'] or '—'} | R$ {c['amount_cents']/100:.2f} "
                          f"| vence {c['due_date']} | {c['status']}")
        return "\n".join(linhas)
    if "dre" in t or "fechou" in t or "resultado" in t:
        import datetime as _dt
        hoje = _dt.date.today()
        r = _exec_tool("gerar_dre", {"ano": hoje.year, "mes": hoje.month})
        return (f"DRE {r['periodo']} (modo heurístico): receita R$ {r['receita_bruta_cents']/100:.2f}, "
                f"despesas R$ {r['despesas_cents']/100:.2f}, "
                f"resultado R$ {r['resultado_cents']/100:.2f}.")
    if "anomal" in t or "padrão" in t or "padrao" in t:
        r = _exec_tool("detectar_anomalias", {})
        if not r["alertas"]:
            return "Nenhuma anomalia detectada (modo heurístico)."
        a = r["alertas"][0]
        return (f"Anomalia: {a['fornecedor']} em {a['mes']} — R$ {a['valor_cents']/100:.2f}, "
                f"{a['variacao_pct']}% acima da média dos meses anteriores.")
    return ("Os provedores de IA estão indisponíveis agora, mas o núcleo continua operando. "
            "Posso: listar contas, conciliar o extrato, gerar o DRE ou detectar anomalias — "
            "peça por uma dessas.")


def conversar(mensagens: list[dict]) -> str:
    """Loop de tool use com CADEIA DE FAILOVER entre provedores.

    Ordem definida em TESOUREIRO_PROVIDERS. Se um provedor falhar no meio da
    conversa, o próximo assume com o MESMO histórico (formato neutro).
    Se todos falharem: modo degradado heurístico — o Tesoureiro não morre.
    """
    from .providers import ProviderError, montar_cadeia

    historico: list[dict] = [
        {"role": m["role"], "content": m["content"]} for m in mensagens
    ]
    cadeia = montar_cadeia(settings)
    if not cadeia:
        return _modo_degradado(mensagens[-1]["content"])

    for provider in cadeia:
        try:
            for _ in range(8):  # teto de iterações
                reply = provider.chat(SYSTEM, historico, TOOLS)
                if not reply.wants_tools:
                    return reply.text
                historico.append({"role": "assistant", "content": reply.text or None,
                                  "tool_calls": reply.tool_calls})
                for tc in reply.tool_calls:
                    try:
                        out = _exec_tool(tc["name"], tc["input"])
                    except Exception as e:  # noqa: BLE001 — ferramenta nunca derruba a API
                        log_action("tool_error", detail={"tool": tc["name"],
                                   "input": tc["input"], "erro": str(e)[:300]})
                        out = {"erro": f"Falha ao executar {tc['name']}: {e}. "
                                       "Verifique os parâmetros e tente de outra forma."}
                    historico.append({"role": "tool", "tool_call_id": tc["id"],
                                      "name": tc["name"],
                                      "content": json.dumps(out, ensure_ascii=False, default=str)})
            return "Atingi o limite de passos desta conversa — pode reformular o pedido?"
        except ProviderError as e:
            log_action("llm_failover", detail={"falhou": provider.name, "erro": str(e)[:300]})
            continue
    return _modo_degradado(mensagens[-1]["content"])
