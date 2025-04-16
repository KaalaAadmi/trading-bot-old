-- Create a table for OHLCV data
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL
);

-- Create a hypertable for efficient time-series queries
SELECT create_hypertable('ohlcv_data', 'timestamp', if_not_exists => TRUE);

-- Create a table for tracked FVGs
CREATE TABLE IF NOT EXISTS tracked_fvgs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    fvg_start NUMERIC NOT NULL,
    fvg_end NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mitigated BOOLEAN DEFAULT FALSE
);

-- Create a table for tracked liquidity zones
CREATE TABLE IF NOT EXISTS tracked_liquidity (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    liquidity_level NUMERIC NOT NULL,
    liquidity_type VARCHAR(10) NOT NULL, -- 'buy' or 'sell'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mitigated BOOLEAN DEFAULT FALSE
);

-- Create a table for trade journal entries
CREATE TABLE IF NOT EXISTS journal (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    entry_price NUMERIC NOT NULL,
    exit_price NUMERIC,
    position_size NUMERIC NOT NULL,
    pnl NUMERIC,
    trade_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED', 'CANCELLED'
    reason TEXT -- Reason for entry/exit
);

-- Create a table for performance metrics
CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(50) NOT NULL,
    metric_value NUMERIC NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);