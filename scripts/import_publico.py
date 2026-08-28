"""Importador de dados públicos (e de qualquer CSV financeiro real).

Fontes testadas de dados abertos:
  • Portal da Transparência federal — portaldatransparencia.gov.br/download-de-dados
    (Despesas → Execução: CSV com favorecido, CNPJ, valor, data)
  • Portais de transparência municipais (dados.gov.br) — mesmo padrão
  • Exportações de ERP/extrato bancário em CSV — mesmo importador

O mapeamento de colunas é por argumento, então NENHUM formato fica hardcoded.
Valores brasileiros ("1.234,56") e datas dd/mm/aaaa são normalizados.

Exemplos:
  # Pagamentos públicos como contas a pagar já liquidadas (massa p/ DRE/anomalias)
  python scripts/import_publico.py despesas.csv --as payables \
      --col-data "Data Pagamento" --col-valor "Valor" \
      --col-favorecido "Nome Favorecido" --col-cnpj "CNPJ" --col-desc "Elemento Despesa"

  # Como extrato bancário (massa p/ conciliação)
  python scripts/import_publico.py extrato.csv --as bank \
      --col-data data --col-valor valor --col-desc historico --saida

  # Só conferir o parse, sem gravar nada:
  ... --dry-run
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import sys
import time

sys.path.insert(0, "src")


def parse_valor(raw: str) -> int | None:
    """'1.234,56' | '1234.56' | 'R$ 1.234,56' → centavos (int). None se ilegível."""
    s = re.sub(r"[^\d,.\-]", "", (raw or "").strip())
    if not s or s in ("-", ".", ","):
        return None
    neg = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:          # 1.234,56 → BR
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                      # 1234,56
        s = s.replace(",", ".")
    try:
        cents = round(float(s) * 100)
    except ValueError:
        return None
    return -cents if neg else cents


def parse_data(raw: str) -> dt.date | None:
    s = (raw or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def so_digitos(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def detectar_delimitador(caminho: str) -> str:
    with open(caminho, encoding="utf-8-sig", errors="replace") as f:
        primeira = f.readline()
    return ";" if primeira.count(";") > primeira.count(",") else ","


def carregar(caminho: str, args) -> list[dict]:
    delim = args.delimitador or detectar_delimitador(caminho)
    linhas, ignoradas = [], 0
    with open(caminho, encoding=args.encoding, errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delim)
        faltando = [c for c in (args.col_data, args.col_valor)
                    if c not in (reader.fieldnames or [])]
        if faltando:
            sys.exit(f"Colunas não encontradas no CSV: {faltando}\n"
                     f"Colunas disponíveis: {reader.fieldnames}")
        for row in reader:
            data = parse_data(row.get(args.col_data, ""))
            cents = parse_valor(row.get(args.col_valor, ""))
            if data is None or cents is None or cents == 0:
                ignoradas += 1
                continue
            if args.saida and cents > 0:
                cents = -cents  # planilha de despesa costuma vir com valor positivo
            linhas.append({
                "data": data,
                "cents": cents,
                "favorecido": (row.get(args.col_favorecido, "") or "").strip()[:200],
                "cnpj": so_digitos(row.get(args.col_cnpj, "")),
                "desc": (row.get(args.col_desc, "") or "").strip()[:300],
            })
    print(f"Lidas {len(linhas)} linhas válidas ({ignoradas} ignoradas por data/valor ilegível).")
    return linhas


def gravar(linhas: list[dict], args):
    from tesoureiro.db import get_conn
    ins_pay = ins_txn = ins_sup = 0
    with get_conn() as conn, conn.cursor() as cur:
        sup_cache: dict[str, str] = {}
        for ln in linhas[: args.limite]:
            if args.as_ == "payables":
                sid = None
                chave = ln["cnpj"] or ln["favorecido"]
                if chave:
                    sid = sup_cache.get(chave)
                    if sid is None:
                        cur.execute(
                            """INSERT INTO suppliers (cnpj, legal_name) VALUES (%s,%s)
                               ON CONFLICT (cnpj) DO UPDATE SET legal_name=EXCLUDED.legal_name
                               RETURNING id""",
                            (ln["cnpj"] or None, ln["favorecido"] or "Favorecido não informado"))
                        sid = cur.fetchone()["id"]
                        sup_cache[chave] = sid
                        ins_sup += 1
                cur.execute(
                    """INSERT INTO payables (supplier_id, description, amount_cents,
                                             due_date, scheduled_date, status)
                       VALUES (%s,%s,%s,%s,%s,'paid')""",
                    (sid, ln["desc"] or "Importado de dados públicos",
                     abs(ln["cents"]), ln["data"], ln["data"]))
                ins_pay += 1
            else:
                fitid = "pub-" + hashlib.sha1(
                    f"{ln['data']}|{ln['cents']}|{ln['desc']}|{ln['favorecido']}".encode()
                ).hexdigest()[:16]
                cur.execute(
                    """INSERT INTO bank_transactions (txn_date, amount_cents, description, fitid)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (fitid) DO NOTHING""",
                    (ln["data"], ln["cents"],
                     (ln["desc"] or ln["favorecido"])[:250], fitid))
                ins_txn += cur.rowcount
        conn.commit()
    print(f"Gravado: {ins_pay} payables, {ins_txn} transações, {ins_sup} fornecedores.")


def validar_cnpjs(linhas: list[dict], maximo: int):
    """Enriquecimento opcional via BrasilAPI — com pausa p/ respeitar a API pública."""
    from tesoureiro.tools.brasilapi import consultar_cnpj
    vistos = set()
    for ln in linhas:
        if len(vistos) >= maximo:
            break
        c = ln["cnpj"]
        if len(c) != 14 or c in vistos:
            continue
        vistos.add(c)
        r = consultar_cnpj(c)
        status = r.get("situacao") if r.get("ok") else f"ERRO: {r.get('erro')}"
        print(f"  CNPJ {c} → {r.get('razao_social', '?')} [{status}]")
        time.sleep(1.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--as", dest="as_", choices=["payables", "bank"], required=True)
    ap.add_argument("--col-data", required=True)
    ap.add_argument("--col-valor", required=True)
    ap.add_argument("--col-favorecido", default="")
    ap.add_argument("--col-cnpj", default="")
    ap.add_argument("--col-desc", default="")
    ap.add_argument("--delimitador", default=None, help="auto-detecta ; ou ,")
    ap.add_argument("--encoding", default="utf-8-sig", help="use latin-1 p/ CSVs antigos do governo")
    ap.add_argument("--saida", action="store_true",
                    help="trata valores como despesa (vira negativo no extrato)")
    ap.add_argument("--limite", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validar-cnpj", type=int, default=0, metavar="N",
                    help="valida os N primeiros CNPJs na BrasilAPI (1 req/1.2s)")
    args = ap.parse_args()

    linhas = carregar(args.csv, args)
    if args.validar_cnpj:
        validar_cnpjs(linhas, args.validar_cnpj)
    if args.dry_run:
        for ln in linhas[:8]:
            print(f"  {ln['data']} | {ln['cents']/100:>12.2f} | {ln['favorecido'][:35]:35s} | {ln['desc'][:40]}")
        print(f"(dry-run: nada gravado; {len(linhas)} linhas prontas)")
        return
    gravar(linhas, args)


if __name__ == "__main__":
    main()
