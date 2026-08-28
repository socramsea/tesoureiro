-- Tesoureiro — schema inicial
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cnpj TEXT UNIQUE,
  legal_name TEXT,
  trade_name TEXT,
  cnpj_status TEXT,
  cnpj_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_type TEXT,                -- boleto | nf | extrato | outro
  source TEXT,                  -- gmail | upload | seed
  raw_ref TEXT,
  extracted_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID REFERENCES suppliers(id),
  description TEXT,
  amount_cents BIGINT NOT NULL,
  due_date DATE NOT NULL,
  scheduled_date DATE,
  status TEXT NOT NULL DEFAULT 'pending',
    -- pending | awaiting_approval | approved | paid | rejected | flagged_fraud
  source_document_id UUID REFERENCES documents(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS receivables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_name TEXT,
  description TEXT,
  amount_cents BIGINT NOT NULL,
  due_date DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- open | received | overdue
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bank_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  txn_date DATE NOT NULL,
  amount_cents BIGINT NOT NULL,          -- negativo = saída
  description TEXT,
  fitid TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reconciliations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bank_txn_id UUID REFERENCES bank_transactions(id),
  payable_id UUID REFERENCES payables(id),
  receivable_id UUID REFERENCES receivables(id),
  match_type TEXT,   -- exact | date_window | fee_adjusted | partial | duplicate | unmatched
  delta_cents BIGINT DEFAULT 0,
  report_md TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id UUID,
  detail_json JSONB,
  approved_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payables_status ON payables(status);
CREATE INDEX IF NOT EXISTS idx_banktxn_date ON bank_transactions(txn_date);
