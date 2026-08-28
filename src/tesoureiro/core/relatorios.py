"""DRE simplificado, fluxo de caixa e detecção de anomalias — tudo determinístico."""
from __future__ import annotations

from collections import defaultdict


def dre_do_mes(bank_txns: list[dict], ano: int, mes: int) -> dict:
    receitas = despesas = 0
    por_categoria: dict[str, int] = defaultdict(int)
    for t in bank_txns:
        d = t["txn_date"]
        if d.year != ano or d.month != mes:
            continue
        if t["amount_cents"] > 0:
            receitas += t["amount_cents"]
        else:
            despesas += -t["amount_cents"]
            por_categoria[(t.get("description") or "outros").split()[0].lower()] += -t["amount_cents"]
    resultado = receitas - despesas
    return {
        "periodo": f"{ano}-{mes:02d}",
        "receita_bruta_cents": receitas,
        "despesas_cents": despesas,
        "resultado_cents": resultado,
        "margem_pct": round(resultado / receitas * 100, 1) if receitas else None,
        "despesas_por_grupo": dict(sorted(por_categoria.items(), key=lambda x: -x[1])[:10]),
    }


def fluxo_caixa(bank_txns: list[dict], saldo_inicial_cents: int = 0) -> list[dict]:
    saldo = saldo_inicial_cents
    por_dia: dict = defaultdict(int)
    for t in bank_txns:
        por_dia[t["txn_date"]] += t["amount_cents"]
    linhas = []
    for dia in sorted(por_dia):
        saldo += por_dia[dia]
        linhas.append({"data": dia.isoformat(), "movimento_cents": por_dia[dia], "saldo_cents": saldo})
    return linhas


def anomalias_por_fornecedor(payables: list[dict], suppliers_by_id: dict) -> list[dict]:
    """Compara o mês mais recente de cada fornecedor com a média dos 3 anteriores."""
    hist: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in payables:
        sid = str(p.get("supplier_id") or "sem_fornecedor")
        chave = p["due_date"].strftime("%Y-%m")
        hist[sid][chave] += p["amount_cents"]
    alertas = []
    for sid, meses in hist.items():
        ordenados = sorted(meses)
        if len(ordenados) < 2:
            continue
        atual = meses[ordenados[-1]]
        anteriores = [meses[m] for m in ordenados[:-1]][-3:]
        media = sum(anteriores) / len(anteriores)
        if media > 0 and atual > media * 1.3:
            nome = (suppliers_by_id.get(sid, {}) or {}).get("legal_name", "Fornecedor")
            alertas.append({
                "fornecedor": nome,
                "mes": ordenados[-1],
                "valor_cents": atual,
                "media_anterior_cents": int(media),
                "variacao_pct": round((atual / media - 1) * 100),
            })
    return sorted(alertas, key=lambda a: -a["variacao_pct"])
