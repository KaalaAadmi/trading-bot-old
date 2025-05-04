-- Create Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
-- Create a table for OHLCV data
CREATE TABLE IF NOT EXISTS ohlcv_data (
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    PRIMARY KEY (symbol, timestamp, timeframe)
);

-- Create a hypertable for efficient time-series queries
SELECT create_hypertable('ohlcv_data', 'timestamp', if_not_exists => TRUE);

-- Create a table for tracked FVGs
CREATE TABLE IF NOT EXISTS tracked_fvgs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    direction TEXT NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    formed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL, -- pending, filled, invalidated
    confirmed BOOLEAN DEFAULT FALSE,
    msb_confirmed BOOLEAN DEFAULT FALSE,
    fvg_height NUMERIC,
    pct_of_price NUMERIC,
    avg_height NUMERIC,
    inversion_time TIMESTAMPTZ,
    signal_emitted_at TIMESTAMPTZ,
    metadata JSONB,
    last_checked TIMESTAMPTZ
);

-- Create a table for tracked liquidity zones
CREATE TABLE IF NOT EXISTS tracked_liquidity (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    type TEXT NOT NULL, -- buy-side or sell-side
    level NUMERIC NOT NULL,
    formed_at TIMESTAMPTZ NOT NULL,
    tapped BOOLEAN DEFAULT FALSE,
    tap_time TIMESTAMPTZ,
    tapped_by_fvg_id INTEGER REFERENCES tracked_fvgs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equal_highs BOOLEAN DEFAULT FALSE,
    metadata JSONB
);

-- Create a table for tracking technical analysis signals
CREATE TABLE technical_analysis_signals (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    fvg_id INT REFERENCES tracked_fvgs(id),
    msb_id INT,
    liquidity_target NUMERIC,
    stop_loss NUMERIC,
    rr NUMERIC,
    reason TEXT,
    status TEXT DEFAULT 'pending', -- pending, triggered, invalidated
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
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