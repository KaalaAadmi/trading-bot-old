-- Create Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create a table for OHLCV data
CREATE TABLE
    IF NOT EXISTS ohlcv_data (
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
SELECT
    create_hypertable ('ohlcv_data', 'timestamp', if_not_exists = > TRUE);

-- Create a table for tracked FVGs
CREATE TABLE
    IF NOT EXISTS tracked_fvgs (
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
CREATE TABLE
    IF NOT EXISTS tracked_liquidity (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        timeframe VARCHAR(10) NOT NULL,
        type TEXT NOT NULL, -- buy-side or sell-side
        level NUMERIC NOT NULL,
        formed_at TIMESTAMPTZ NOT NULL,
        tapped BOOLEAN DEFAULT FALSE,
        tap_time TIMESTAMPTZ,
        tapped_by_fvg_id INTEGER REFERENCES tracked_fvgs (id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW (),
        equal_highs BOOLEAN DEFAULT FALSE,
        metadata JSONB
    );

-- Create a table for tracking technical analysis signals
CREATE TABLE
    technical_analysis_signals (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        direction TEXT NOT NULL,
        fvg_id INT REFERENCES tracked_fvgs (id),
        msb_broken_level NUMERIC,
        msb_timestamp TIMESTAMPTZ,
        liquidity_target NUMERIC,
        stop_loss NUMERIC,
        rr NUMERIC,
        reason TEXT,
        status TEXT DEFAULT 'pending', -- pending, triggered, invalidated
        created_at TIMESTAMPTZ DEFAULT NOW (),
        updated_at TIMESTAMPTZ DEFAULT NOW ()
    );

-- Create a table for trade journal entries
CREATE TABLE
    IF NOT EXISTS journal (
        id SERIAL PRIMARY KEY,
        signal_id INTEGER REFERENCES technical_analysis_signals (id),
        execution_id UUID REFERENCES execution_signals (execution_id),
        symbol VARCHAR(20) NOT NULL,
        timeframe VARCHAR(10) NOT NULL,
        direction VARCHAR(10) NOT NULL, -- BUY or SELL
        entry_price NUMERIC NOT NULL,
        exit_price NUMERIC,
        position_size NUMERIC NOT NULL,
        pnl NUMERIC,
        pnl_pct NUMERIC, -- (pnl / entry_price * 100)
        max_drawdown_pct NUMERIC, -- max adverse movement during trade
        holding_period INTERVAL, -- how long was the trade open
        stop_loss NUMERIC,
        take_profit NUMERIC,
        rr NUMERIC,
        signal_confidence NUMERIC(5, 4),
        account_balance_at_entry NUMERIC,
        account_balance_at_exit NUMERIC,
        market_volatility_at_entry NUMERIC, -- e.g., ATR or stddev
        spread_at_entry NUMERIC, -- bid-ask spread at entry
        outcome TEXT, -- hit TP, hit SL, manual close
        status VARCHAR(20) DEFAULT 'CLOSED',
        entry_timestamp TIMESTAMPTZ,
        exit_timestamp TIMESTAMPTZ,
        reason TEXT,
        metadata JSONB
    );

-- Create a table for performance metrics
CREATE TABLE
    IF NOT EXISTS performance_metrics (
        id SERIAL PRIMARY KEY,
        metric_name VARCHAR(50) NOT NULL,
        metric_value NUMERIC NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW ()
    );

-- Example SQL for portfolio_positions table
CREATE TABLE
    IF NOT EXISTS portfolio_positions (
        id SERIAL PRIMARY KEY,
        signal_id INTEGER REFERENCES technical_analysis_signals (id), -- Link back to the signal
        broker_order_id VARCHAR(255) UNIQUE, -- ID from the broker
        ticker VARCHAR(50) NOT NULL,
        direction VARCHAR(10) NOT NULL, -- BUY or SELL
        entry_price NUMERIC(18, 8) NOT NULL,
        quantity NUMERIC(18, 8) NOT NULL,
        stop_loss NUMERIC(18, 8),
        take_profit NUMERIC(18, 8),
        status VARCHAR(20) NOT NULL DEFAULT 'open', -- open, closed
        entry_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW (),
        exit_price NUMERIC(18, 8),
        exit_timestamp TIMESTAMPTZ,
        pnl NUMERIC(18, 8),
        metadata JSONB -- Optional extra info
    );

-- Optional: Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_ticker_status ON portfolio_positions (ticker, status);

CREATE INDEX IF NOT EXISTS idx_portfolio_positions_signal_id ON portfolio_positions (signal_id);

CREATE TABLE
    IF NOT EXISTS execution_signals (
        id SERIAL PRIMARY KEY,
        execution_id UUID UNIQUE NOT NULL,
        -- signal_id INTEGER REFERENCES technical_analysis_signals(id),
        ticker VARCHAR(50) NOT NULL,
        direction VARCHAR(10) NOT NULL,
        status VARCHAR(20) NOT NULL,
        fill_price NUMERIC(18, 8) NOT NULL,
        position_size NUMERIC(18, 8) NOT NULL,
        stop_loss NUMERIC(18, 8),
        take_profit NUMERIC(18, 8),
        fvg_id VARCHAR(100),
        fvg_height NUMERIC(18, 8),
        reason TEXT,
        timeframe VARCHAR(20),
        fvg_direction VARCHAR(10),
        rr NUMERIC(18, 8),
        account_balance_at_entry NUMERIC(18, 8),
        signal_confidence NUMERIC(5, 4),
        broker_order_id VARCHAR(255),
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW (),
        metadata JSONB -- optional for any extra fields
    );

CREATE INDEX IF NOT EXISTS idx_execution_signals_symbol ON execution_signals (symbol);

CREATE INDEX IF NOT EXISTS idx_execution_signals_execution_id ON execution_signals (execution_id);

CREATE INDEX IF NOT EXISTS idx_execution_signals_fvg_id ON execution_signals (fvg_id);