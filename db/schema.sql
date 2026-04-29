-- =========================================
-- DATABASE SCHEMA - PORTFOLIO DASHBOARD
-- =========================================

-- =====================
-- ACCOUNTS
-- =====================
CREATE TABLE public.accounts (
  id SERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,

  type VARCHAR NOT NULL CHECK (
    type IN ('PEA', 'CTO', 'AV', 'PER', 'PEI', 'livret', 'crypto', 'autre')
  ),

  platform VARCHAR,
  currency CHAR(3) NOT NULL DEFAULT 'EUR',
  opened_at DATE NOT NULL,

  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================
-- ASSETS
-- =====================
CREATE TABLE public.assets (
  id SERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,

  isin VARCHAR UNIQUE,
  yahoo_ticker VARCHAR,

  asset_class VARCHAR NOT NULL CHECK (
    asset_class IN ('action', 'etf', 'fonds', 'obligation', 'scpi', 'crypto', 'cash', 'autre')
  ),

  geography VARCHAR,
  sector VARCHAR,

  currency CHAR(3) NOT NULL DEFAULT 'EUR',

  auto_price BOOLEAN NOT NULL DEFAULT TRUE,
  is_benchmark BOOLEAN NOT NULL DEFAULT FALSE,

  last_known_price NUMERIC,
  last_price_updated_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================
-- SETTINGS (SINGLETON)
-- =====================
CREATE TABLE public.settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),

  livret_a_rate NUMERIC NOT NULL DEFAULT 0.030,
  monthly_income NUMERIC,
  monthly_dca NUMERIC,

  estimated_annual_return NUMERIC NOT NULL DEFAULT 0.070,
  inflation_rate NUMERIC NOT NULL DEFAULT 0.020,

  fire_target_amount NUMERIC,

  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================
-- SNAPSHOTS
-- =====================
CREATE TABLE public.snapshots (
  id SERIAL PRIMARY KEY,
  date DATE NOT NULL,

  account_id INTEGER NOT NULL REFERENCES public.accounts(id),

  total_value NUMERIC NOT NULL,
  invested_capital NUMERIC NOT NULL,
  cash NUMERIC NOT NULL DEFAULT 0,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================
-- TRANSACTIONS
-- =====================
CREATE TABLE public.transactions (
  id SERIAL PRIMARY KEY,
  date DATE NOT NULL,

  type VARCHAR NOT NULL CHECK (
    type IN ('deposit', 'withdrawal', 'buy', 'sell', 'dividend', 'fee')
  ),

  account_id INTEGER NOT NULL REFERENCES public.accounts(id),
  asset_id INTEGER REFERENCES public.assets(id),

  quantity NUMERIC,
  unit_price NUMERIC,

  fees NUMERIC NOT NULL DEFAULT 0,
  total_amount NUMERIC NOT NULL,

  comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
