# Manual do Tesoureiro

Este manual tem duas partes: **Parte 1** é para quem vai usar ou demonstrar o
Tesoureiro (recrutador, você mostrando o produto). **Parte 2** é para quem vai
operar, manter ou evoluir o código.

---

# PARTE 1 — Guia de Uso (para demonstrar ou testar)

## O que é

O Tesoureiro é um funcionário financeiro autônomo: um agente de IA que executa
rotinas financeiras de uma PME — lança contas, valida fornecedores na Receita
Federal e nas listas de sanção do governo, concilia extrato bancário, fecha DRE
e detecta gastos fora do padrão. Ele **nunca aprova pagamento sozinho** — sempre
pede confirmação humana antes de qualquer decisão que envolva dinheiro saindo.

**Link da demo pública:** https://tesoureiro.onrender.com
*(primeiro acesso pode levar ~30s — o servidor gratuito "dorme" após 15 min sem uso)*

**Código-fonte:** https://github.com/socramsea/tesoureiro

## O que é real e o que é fictício nesta demo

| | |
|---|---|
| Situação cadastral de CNPJ | **Real** — consulta ao vivo na Receita Federal (BrasilAPI) |
| Sanções CEIS/CNEP | **Real** — consulta ao vivo ao Portal da Transparência |
| Taxa SELIC | **Real** — Banco Central |
| Contas a pagar/receber, extrato bancário | **Fictício** — dados de uma PME de demonstração, com divergências plantadas de propósito para mostrar a conciliação funcionando |

## Como testar (roteiro sugerido)

1. **Veja o painel** à direita: contas a pagar com cores com significado —
   verde = pago, âmbar = vence hoje/aguarda aprovação, vermelho = atrasado.
2. **Peça uma anomalia:** digite `algum gasto fora do padrão?` — o agente
   compara o mês atual com a média dos anteriores e aponta o desvio.
3. **Peça a conciliação:** clique no botão ou digite
   `concilie o extrato e explique as divergências` — o agente cruza extrato
   bancário com as contas e explica cada diferença (tarifa, duplicidade,
   pagamento parcial, lançamento sem correspondência).
4. **Valide um fornecedor:** `valide o CNPJ da Petrobras` — consulta real à
   Receita.
5. **Teste o compliance:** `verifique sanções do CNPJ 00.000.000/0001-91`
   (Banco do Brasil) — este CNPJ real aparece nas listas públicas de sanção
   por processos administrativos de diversos órgãos; é um bom caso para
   mostrar o agente sinalizando risco a partir de dado público.
6. **Teste a aprovação humana:** `aprove a compra dos notebooks` — o agente
   valida o fornecedor, prepara a solicitação e **pede sua confirmação**
   (`aprovo`) antes de mudar qualquer status.
7. **Peça o DRE:** `como fechou o DRE deste mês?`

## Perguntas que mostram o diferencial (para uma conversa com recrutador)

- *"Se a API da Anthropic cair, o sistema para?"* → Não: há failover para
  outros provedores (DeepSeek/OpenAI) e um modo degradado heurístico que
  responde sem nenhuma IA.
- *"Como você sabe que o agente não está inventando números?"* → Toda ação
  fica registrada na trilha de auditoria (`agent_actions`), visível no
  painel; todo número deve vir de uma consulta real feita na conversa.
- *"Por que não usar banco vetorial na conciliação?"* → Conciliação é
  aritmética exata (valor, data, tolerância), não similaridade de texto —
  usar embedding ali trocaria determinismo auditável por resultado
  probabilístico sem necessidade.

---

# PARTE 2 — Guia de Operação (para manter e evoluir)

## Arquitetura em uma frase

`Frontend (HTML estático) → FastAPI → Agente (Claude + tool use) → Postgres`,
com ferramentas externas para CNPJ (BrasilAPI), sanções (Portal da
Transparência) e SELIC (Banco Central).

## Rodando localmente

```bash
git clone https://github.com/socramsea/tesoureiro.git
cd tesoureiro
cp .env.example .env
nano .env   # preencha ANTHROPIC_API_KEY e PORTAL_TRANSPARENCIA_API_KEY
docker compose up -d --build
docker compose exec api python scripts/seed_demo.py
# abra http://127.0.0.1:8082
```

## Fluxo de mudança de código (Git é a fonte da verdade)

**Nunca edite direto o container ou só a pasta local sem commitar.** O Render
reflete o que está no GitHub — uma mudança que não vira commit se perde na
próxima vez que alguém (você) descompactar um zip por cima ou o serviço
redeployar.

```bash
# 1. edite o código local
# 2. teste local:
docker compose up -d --build api
# 3. confirme a mudança está no arquivo:
grep -c "trecho que você mudou" caminho/do/arquivo.py
# 4. versione:
git add -A
git commit -m "descrição objetiva da mudança"
git push
# 5. o Render redeploya sozinho em ~3 min (Auto-Deploy: On Commit)
```

## Onde cada coisa vive

| Arquivo | Responsabilidade |
|---|---|
| `src/tesoureiro/agent/agent.py` | System prompt, definição das tools, loop de conversa e failover |
| `src/tesoureiro/agent/providers.py` | Adaptadores Anthropic e OpenAI-compatível (DeepSeek/OpenAI/Ollama) |
| `src/tesoureiro/core/conciliacao.py` | Motor heurístico determinístico de conciliação — NUNCA usa LLM para decidir match |
| `src/tesoureiro/core/relatorios.py` | DRE, fluxo de caixa, detecção de anomalias |
| `src/tesoureiro/tools/*.py` | Chamadas às APIs públicas (BrasilAPI, Portal da Transparência, BCB) |
| `src/tesoureiro/api/app.py` | Rotas FastAPI, rate limit, serve o frontend |
| `src/tesoureiro/api/static/index.html` | Frontend (chat + painel) — HTML/CSS/JS puro, sem framework |
| `scripts/seed_demo.py` | Popula a PME fictícia de demonstração |
| `scripts/import_publico.py` | Importa CSV de dados públicos (ex.: Portal da Transparência) como massa de teste |
| `infra/sql/001_initial.sql` | Schema do banco |

## Regra de ouro ao alterar o `agent.py`

O `SYSTEM` prompt é a única fonte de comportamento do agente — não existe
lógica de negócio escondida em outro lugar que sobrescreva uma regra dele.
Ao adicionar uma regra nova:
1. Adicione como item numerado nas `REGRAS INEGOCIÁVEIS` ou na seção
   `PÚBLICO E REGISTRO`.
2. `python3 -m compileall -q src` para garantir que não quebrou a sintaxe.
3. Teste a regra na conversa **em janela anônima** — o histórico de chat
   sobrevive a rebuild e pode mascarar se a correção realmente funcionou
   (isso já nos enganou uma vez: veja "Lições" abaixo).

## Diagnosticando um agente que parece errado

Ordem de investigação, do mais confiável ao menos confiável:

1. **Chame a ferramenta direto, sem o agente:**
   ```bash
   docker compose exec api python -c "
   from tesoureiro.tools.transparencia import verificar_sancoes
   from tesoureiro.config import settings
   print(verificar_sancoes('CNPJ_AQUI', settings.portal_transparencia_api_key))"
   ```
   Isso isola se o problema é na ferramenta/API ou na decisão do modelo.
2. **Consulte a trilha de auditoria** — mostra exatamente quais ferramentas
   foram chamadas e quando; se a ferramenta esperada não aparece, o agente
   não a chamou (pode estar narrando uma ação sem executá-la):
   ```bash
   docker compose exec postgres psql -U tesoureiro -d tesoureiro \
     -c "SELECT action, approved_by, created_at FROM agent_actions ORDER BY created_at DESC LIMIT 10;" | cat
   ```
3. **Consulte o dado bruto no banco** — para confirmar se um número citado
   pelo agente realmente existe:
   ```bash
   docker compose exec postgres psql -U tesoureiro -d tesoureiro \
     -c "SELECT * FROM bank_transactions ORDER BY txn_date;" | cat
   ```
4. **Recarregue em janela anônima** antes de concluir que uma correção não
   funcionou — o histórico da conversa no navegador pode estar repetindo uma
   conclusão de antes do fix.

## Lições aprendidas (bugs reais encontrados e corrigidos)

Documentado aqui porque cada um é uma decisão de arquitetura, não só um bug:

1. **Número inventado em relatório.** O agente escreveu "débito de R$ 12.000
   em julho" sem ter consultado nenhuma ferramenta. Corrigido com a regra 0
   (todo número deve vir de tool result nesta conversa).
2. **Ação narrada sem execução.** O agente descreveu "processarei sua
   aprovação" sem chamar `pedir_aprovacao`/`registrar_decisao_humano` — nada
   mudava no banco. Corrigido com a regra "AÇÕES EXIGEM FERRAMENTA".
3. **Filtro de API ignorado pelo servidor.** A API do Portal da Transparência
   ignorava o parâmetro `cnpjSancionado` e devolvia a lista geral de sanções
   do país — todo fornecedor consultado aparecia como sancionado (falso
   positivo em série). Corrigido filtrando **localmente** cada registro
   contra o CNPJ consultado, nunca confiando no filtro remoto quando a
   resposta decide um pagamento.
4. **Contexto de conversa sobrevive a correção de código.** Depois de
   corrigir o bug 3, o agente continuou dizendo "sancionado" — porque a
   *conversa aberta* ainda tinha a conclusão antiga no histórico. Corrigir
   o código não apaga memória de sessão; é preciso reiniciar a conversa.
5. **ID de banco de dados inventado.** O agente chamou uma ferramenta com
   `payable_id: "pay_003"` (formato inventado) em vez do UUID real, e a
   exceção não tratada derrubou a requisição inteira. Corrigido validando o
   formato do ID antes de tocar no banco e blindando o loop de ferramentas
   para que nenhuma exceção derrube a API — vira erro explícito devolvido ao
   agente, que se recupera consultando `listar_contas` de novo.

## Segurança

- `.env` nunca é commitado (está no `.gitignore`) — contém chaves de API reais.
- Se uma chave vazar (ex.: colada em chat, print, log), **rotacione-a**
  imediatamente no provedor (Anthropic Console, Portal da Transparência,
  Render → variável de ambiente do banco).
- O banco Postgres do Render free expira em 30 dias — se a demo precisar
  viver mais tempo, migre para plano pago ou para um VPS.
