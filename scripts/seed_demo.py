"""Seed da demo: PME fictícia com divergências PLANTADAS de propósito.

CNPJs usados são de empresas públicas conhecidas (dados abertos da Receita) para
a tool de validação funcionar de verdade na demo. Os lançamentos são fictícios.
"""
from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, "src")
from tesoureiro.db import get_conn  # noqa: E402

HOJE = dt.date.today()
M = HOJE.replace(day=1)  # primeiro dia do mês corrente


def d(day: int, months_back: int = 0) -> dt.date:
    base = (M - dt.timedelta(days=1)).replace(day=1) if months_back else M
    for _ in range(max(0, months_back - 1)):
        base = (base - dt.timedelta(days=1)).replace(day=1)
    try:
        return base.replace(day=day)
    except ValueError:
        return base.replace(day=28)


SUPPLIERS = [
    # (cnpj real de empresa pública p/ a tool funcionar, razão social exibida)
    ("00000000000191", "BANCO DO BRASIL SA"),            # tarifas bancárias
    ("33000167000101", "PETROBRAS SA"),                   # combustível frota
    ("47960950000121", "MAGAZINE LUIZA SA"),              # material de escritório
    (None, "Imobiliária Recreio Ltda"),                   # aluguel (sem CNPJ → agente deve pedir)
]

def seed():
    with get_conn() as conn, conn.cursor() as cur:
        for t in ["reconciliations", "agent_actions", "bank_transactions",
                  "payables", "receivables", "documents", "suppliers"]:
            cur.execute(f"TRUNCATE {t} CASCADE")
        sup_ids = {}
        for cnpj, nome in SUPPLIERS:
            cur.execute(
                "INSERT INTO suppliers (cnpj, legal_name) VALUES (%s,%s) RETURNING id",
                (cnpj, nome))
            sup_ids[nome] = cur.fetchone()["id"]

        pay = []
        # histórico de 3 meses (base p/ anomalias) — combustível estável ~R$ 2.400
        for mb in (3, 2, 1):
            pay.append((sup_ids["PETROBRAS SA"], "Combustível frota", 240_000, d(10, mb), "paid"))
            pay.append((sup_ids["Imobiliária Recreio Ltda"], "Aluguel galpão", 850_000, d(5, mb), "paid"))
        # mês corrente
        pay += [
            (sup_ids["Imobiliária Recreio Ltda"], "Aluguel galpão", 850_000, d(5), "approved"),
            # ANOMALIA plantada: combustível 65% acima da média
            (sup_ids["PETROBRAS SA"], "Combustível frota", 396_000, d(10), "approved"),
            (sup_ids["MAGAZINE LUIZA SA"], "Material de escritório", 74_350, d(12), "approved"),
            (sup_ids["BANCO DO BRASIL SA"], "Tarifa pacote PJ", 8_900, d(15), "approved"),
            # pendente: é a conta que o visitante vai aprovar no chat
            (sup_ids["MAGAZINE LUIZA SA"], "Notebooks (2x) p/ equipe", 689_900, d(min(28, HOJE.day + 3)), "pending"),
        ]
        for sid, desc, cents, due, status in pay:
            cur.execute("""INSERT INTO payables (supplier_id, description, amount_cents,
                          due_date, scheduled_date, status) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (sid, desc, cents, due, due, status))

        cur.execute("""INSERT INTO receivables (customer_name, description, amount_cents, due_date, status)
                       VALUES ('Cliente Alfa Ltda','NF 1042 — serviços', 1250000, %s, 'open'),
                              ('Cliente Beta ME','NF 1043 — serviços', 480000, %s, 'open')""",
                    (d(8), d(20)))

        # extrato: divergências plantadas
        txns = [
            (d(5), -850_000, "PIX IMOBILIARIA RECREIO", "fit-001"),        # exact
            (d(11), -396_000, "COMPRA POSTO BR", "fit-002"),               # date_window (+1d)
            (d(12), -73_900, "MAGAZINE LUIZA", "fit-003"),                 # fee_adjusted (desconto R$ 4,50)
            (d(15), -8_900, "TARIFA PACOTE PJ", "fit-004"),                # exact
            (d(15), -8_900, "TARIFA PACOTE PJ", "fit-005"),                # DUPLICIDADE!
            (d(9), 625_000, "TED CLIENTE ALFA", "fit-006"),                # partial (50%)
            (d(14), -45_000, "DEB AUTOR SEGURO FROTA", "fit-007"),         # unmatched (não previsto)
        ]
        for date, cents, desc, fid in txns:
            cur.execute("""INSERT INTO bank_transactions (txn_date, amount_cents, description, fitid)
                           VALUES (%s,%s,%s,%s) ON CONFLICT (fitid) DO NOTHING""",
                        (date, cents, desc, fid))
        conn.commit()
    print("Seed OK — demo pronta.")


if __name__ == "__main__":
    seed()
