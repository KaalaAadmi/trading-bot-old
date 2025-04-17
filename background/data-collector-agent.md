# 🧠 Data Collector Agent — Agent Documentation

## 📌 Purpose

The Data Collector Agent is responsible for:

- Periodically fetching historical and live price data for the filtered assets (from Market Research Agent)

- Pulling multiple timeframes (typically HTF & LTF) in sync to support HTF/LTF-based strategies

- Storing all collected data in TimescaleDB

- Publishing events to Redis Streams for downstream agents (e.g., Technical Analysis Agent)

- It is one of the most critical components in the pipeline, ensuring high-quality and well-synchronized market data.

---

## 🏗️ Architectural Role in the Agentic Bot

Triggered by: APScheduler or a similar internal job scheduler

### Consumes From:

- market:filtered_assets (Redis Stream) — list of tickers to track

### Publishes To:

- data:raw (Redis Stream) — new data payloads for analysis

### Dependencies:

- Redis (Streams)

- TimescaleDB (PostgreSQL)

- yfinance (or a better live/intraday API in future)

- APScheduler (for interval-based fetching)

---

## 🔁 Workflow

### 1. Get List of Tickers

Fetches tickers from:

- tickers.json updated by the Ticker Updater Agent

- Or directly from the market:filtered_assets Redis Stream

### 2. Fetch Historic Data

For each asset:

- Use yfinance.Ticker().history() to fetch:

- HTF data (e.g., 1-hour candles for 30 days)

- LTF data (e.g., 5-minute candles for 7 days)

Example:

```python
yf.Ticker(asset).history(interval="1h", period="30d") # HTF
yf.Ticker(asset).history(interval="5m", period="7d") # LTF
```

### 3. Transform and Store

For each row of data:

- Format the OHLCV structure

- Add ticker, timeframe, timestamp

- Save into TimescaleDB

Schema:

```sql
CREATE TABLE price_data (
timestamp TIMESTAMPTZ NOT NULL,
ticker TEXT NOT NULL,
timeframe TEXT NOT NULL, -- e.g., '1h', '5m'
open DOUBLE PRECISION,
high DOUBLE PRECISION,
low DOUBLE PRECISION,
close DOUBLE PRECISION,
volume DOUBLE PRECISION,
PRIMARY KEY (timestamp, ticker, timeframe)
);
SELECT create_hypertable('price_data', 'timestamp');
```

### 4. Publish to Redis Streams

After inserting into DB, publish a message to data:raw Redis Stream:

```json
{
  "ticker": "AAPL",
  "timeframe": "5m",
  "new_data": true,
  "range": ["2024-04-10T00:00:00Z", "2024-04-10T00:05:00Z"]
}
```

---

## ⚙️ Configurable Settings

From settings.yaml:

```yaml
timeframes:
htf: "1h"
ltf: "5m"

history:
ltf_lookback_days: 7
htf_lookback_days: 30

schedule:
ltf_interval_minutes: 5
htf_interval_minutes: 60
```

---

## 🧠 Intelligent Behavior

- Respects tickers passed by Market Research Agent

- Avoids redundant DB writes using Redis key or DB checks (e.g., last_fetched timestamp)

- Can retry failed fetches (optional feature via exponential backoff)

- Tightly integrated with Redis Stream consumers for real-time pipeline triggering

---

## ✅ Todo List

- [ ] Set up price_data TimescaleDB table

- [ ] Implement data fetching for both HTF & LTF

- [ ] Write DB insertion logic with idempotency checks

- [ ] Configure Redis Streams (data:raw)

- [ ] Publish stream messages with metadata for Technical Analysis Agent

- [ ] Schedule jobs via APScheduler

- [ ] Store last_fetched timestamps per (ticker, timeframe) in Redis or Postgres

- [ ] Add error handling, logging, and retry mechanism

- [ ] Add tests (mock yfinance / DB writes)

---

## 🚨 Warnings & Tips

- yfinance limits: Intraday is only 7 days. Migrate to paid APIs (e.g., TwelveData, Polygon.io) for production.

- Timestamps: Always store and convert to UTC!

- Redis Stream Overflow: Set MAXLEN for streams to avoid memory issues.

---

## 🧬 Future Improvements

- Pluggable data sources (modular input)

- Support for multi-timeframe strategies (4H/15m, 1D/1H)

- Real-time WebSocket integration for crypto

- Auto-resilience to API failures (proxy rotation / retry queues)

---
