"""Motor de conciliação — HEURÍSTICA DECIDE, LLM só explica depois.

Ordem de tentativa (por transação bancária ainda não conciliada):
  1. exact        — valor exato + mesma data (±0 dias)
  2. date_window  — valor exato + data numa janela de ±3 dias
  3. fee_adjusted — valor com diferença pequena (tarifa/juros) na janela
  4. partial      — pagamento parcial (50–99% do esperado) na janela
  5. duplicate    — segunda transação idêntica a uma já conciliada
  6. unmatched    — nada encontrado

Dinheiro é BIGINT em centavos. Float não entra aqui.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

DATE_WINDOW_DAYS = 3
FEE_TOLERANCE_CENTS = 1500          # até R$ 15,00 de tarifa/juros
FEE_TOLERANCE_PCT = 0.02            # ou até 2% do valor


@dataclass
class Match:
    bank_txn: dict
    target: dict | None      # payable ou receivable
    target_kind: str | None  # 'payable' | 'receivable'
    match_type: str
    delta_cents: int
    explain: str             # fatos objetivos; o LLM transforma em laudo


def _janela(d1: dt.date, d2: dt.date) -> bool:
    return abs((d1 - d2).days) <= DATE_WINDOW_DAYS


def _tolerancia(esperado: int) -> int:
    return max(FEE_TOLERANCE_CENTS, int(abs(esperado) * FEE_TOLERANCE_PCT))


def conciliar(bank_txns: list[dict], payables: list[dict], receivables: list[dict]) -> list[Match]:
    """Recebe listas de dicts (linhas do banco de dados) e devolve matches."""
    usados_pay: set = set()
    usados_rec: set = set()
    conciliadas: list[tuple[int, dt.date, str]] = []  # p/ detectar duplicidade
    out: list[Match] = []

    for txn in sorted(bank_txns, key=lambda t: t["txn_date"]):
        amount = txn["amount_cents"]
        date = txn["txn_date"]
        saida = amount < 0
        alvo_lista = payables if saida else receivables
        usados = usados_pay if saida else usados_rec
        kind = "payable" if saida else "receivable"
        esperado_de = "valor agendado" if saida else "valor a receber"

        assinatura = (amount, date, (txn.get("description") or "").strip().lower())
        if assinatura in conciliadas:
            out.append(Match(txn, None, None, "duplicate", 0,
                             f"Transação idêntica (mesmo valor, data e descrição) já conciliada — possível lançamento em duplicidade de {abs(amount)/100:.2f}."))
            continue

        candidatos = [a for a in alvo_lista if a["id"] not in usados]
        alvo_val = abs(amount)

        def fechar(alvo, mtype, delta, explain):
            usados.add(alvo["id"])
            conciliadas.append(assinatura)
            out.append(Match(txn, alvo, kind, mtype, delta, explain))

        # 1) exato
        hit = next((a for a in candidatos
                    if a["amount_cents"] == alvo_val and a["due_date"] == date), None)
        if hit:
            fechar(hit, "exact", 0, "Valor e data exatos.")
            continue
        # 2) janela de data
        hit = next((a for a in candidatos
                    if a["amount_cents"] == alvo_val and _janela(a["due_date"], date)), None)
        if hit:
            dias = (date - hit["due_date"]).days
            fechar(hit, "date_window", 0,
                   f"Valor exato; liquidado {abs(dias)} dia(s) {'após' if dias > 0 else 'antes de'} o vencimento.")
            continue
        # 3) tarifa/juros
        hit = next((a for a in candidatos
                    if _janela(a["due_date"], date)
                    and 0 < abs(a["amount_cents"] - alvo_val) <= _tolerancia(a["amount_cents"])), None)
        if hit:
            delta = alvo_val - hit["amount_cents"]
            causa = "juros/multa por atraso" if delta > 0 else "tarifa ou desconto"
            fechar(hit, "fee_adjusted", delta,
                   f"Diferença de R$ {abs(delta)/100:.2f} sobre o {esperado_de} — compatível com {causa}.")
            continue
        # 4) parcial
        hit = next((a for a in candidatos
                    if _janela(a["due_date"], date)
                    and 0.5 * a["amount_cents"] <= alvo_val < a["amount_cents"]), None)
        if hit:
            delta = alvo_val - hit["amount_cents"]
            pct = alvo_val / hit["amount_cents"] * 100
            fechar(hit, "partial", delta,
                   f"Pagamento PARCIAL: {pct:.0f}% do esperado. Faltam R$ {abs(delta)/100:.2f}.")
            continue
        # 6) sem correspondência
        conciliadas.append(assinatura)
        out.append(Match(txn, None, None, "unmatched", 0,
                         f"Nenhum lançamento previsto corresponde a esta transação de R$ {alvo_val/100:.2f} em {date}."))
    return out


def resumo(matches: list[Match]) -> dict:
    por_tipo: dict[str, int] = {}
    for m in matches:
        por_tipo[m.match_type] = por_tipo.get(m.match_type, 0) + 1
    total = len(matches)
    ok = por_tipo.get("exact", 0) + por_tipo.get("date_window", 0) + por_tipo.get("fee_adjusted", 0)
    return {"total_transacoes": total, "conciliadas": ok,
            "atencao": total - ok, "por_tipo": por_tipo}
