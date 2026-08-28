# Tesoureiro 🏦

**Software financeiro te mostra o problema. O Tesoureiro resolve.**
*Financial software shows you the problem. Tesoureiro solves it.*

Funcionário financeiro autônomo para PMEs: um agente de IA que lança contas,
valida fornecedores na Receita Federal em tempo real, agenda pagamentos
respeitando feriados, **pede aprovação humana antes de qualquer pagamento**,
concilia o extrato explicando *por que* cada divergência aconteceu, e fecha
DRE com alertas de anomalia.

**➡️ Demo ao vivo: entre e use.** (link no topo do repositório)

## Princípios
1. **Zero invenção de dados** — valores, CNPJs e datas vêm de documentos ou de
   APIs públicas (BrasilAPI/Receita, Banco Central). Nunca do modelo.
2. **Heurística decide, LLM explica** — a conciliação é determinística e
   auditável; a IA escreve o laudo didático e conversa com você.
3. **Human-in-the-loop onde há dinheiro** — pagamento só muda de status com
   aprovação humana explícita, registrada na trilha de auditoria.
4. **Dinheiro em centavos (BIGINT)** — float não entra em conciliação.

## Rodar local
```bash
cp .env.example .env   # coloque sua ANTHROPIC_API_KEY
docker compose up -d --build
docker compose exec api python scripts/seed_demo.py
# abra http://127.0.0.1:8082
```

## Arquitetura
`FastAPI (chat web + API) → agente Claude (tool use) → Postgres (fonte de verdade)`
Ferramentas do agente: consulta CNPJ (BrasilAPI), feriados nacionais, SELIC (BCB),
contas a pagar, aprovação humana, conciliação, DRE, anomalias.
Detalhes e trade-offs: `docs/architecture.md`.

## Licença
MIT © Marcos Sea

## Dados públicos como massa de teste real
O importador `scripts/import_publico.py` aceita qualquer CSV financeiro com
mapeamento de colunas por argumento — testado com o formato dos downloads do
**Portal da Transparência** (portaldatransparencia.gov.br/download-de-dados,
Despesas → Execução) e de portais municipais em dados.gov.br:

```bash
docker compose exec api python scripts/import_publico.py despesas.csv --as payables \
  --col-data "Data Pagamento" --col-valor "Valor" \
  --col-favorecido "Nome Favorecido" --col-cnpj "CNPJ" --col-desc "Elemento Despesa" \
  --validar-cnpj 10        # valida os CNPJs reais na Receita via BrasilAPI
```
Trata `;` ou `,`, valores no formato brasileiro (`1.234,56`), datas
`dd/mm/aaaa`, linhas sujas (ignoradas com contagem) e dedupe por hash.

## Resiliência: cadeia de provedores + modo degradado
`TESOUREIRO_PROVIDERS=anthropic,deepseek,ollama` define a ordem de failover.
Se um provedor cair no meio da conversa, o próximo assume **com o mesmo
histórico** (formato neutro interno; adaptadores para a API da Anthropic e para
qualquer API OpenAI-compatível — DeepSeek, OpenAI, Groq, Ollama local).
Cada failover fica registrado na trilha de auditoria (`llm_failover`).
Se TODOS caírem, o Tesoureiro entra em **modo degradado heurístico**:
conciliação, contas, DRE e anomalias continuam funcionando sem nenhum LLM —
a IA amplia o núcleo, não o sustenta.

## Compliance em tempo real (diferencial)
Antes de aprovar um fornecedor, o agente cruza o CNPJ **em tempo real** contra
as listas federais de sanção via API do Portal da Transparência:
**CEIS** (empresas inidôneas e suspensas) e **CNEP** (punidas pela Lei
Anticorrupção). Fornecedor sancionado → pagamento bloqueado e escalado para
humano com laudo. Se a API estiver fora, o agente **não assume que o fornecedor
está limpo** — informa que a checagem falhou (fail-safe, nunca fail-open).
Chave gratuita: portaldatransparencia.gov.br/api-de-dados/cadastrar-email
