# 🧠 Agentic Trading Bot — Product Requirements Document (PRD)

---

## 📌 Overview

This bot implements a fully automated **Inverse Fair Value Gap (FVG) and Liquidity strategy** using a modular, agent-based architecture. It is designed to:

- Automatically analyze markets (stocks/crypto)
- Detect high-probability trade setups
- Execute risk-managed trades
- Journal and evaluate performance
- Allow introspection and adaptation over time

---

## ⚙️ Tech Stack Summary

| Layer            | Technology              | Purpose                                                                                     |
| ---------------- | ----------------------- | ------------------------------------------------------------------------------------------- |
| Language         | Python                  | Core logic for all agents                                                                   |
| Containerization | Docker + Docker Compose | Modular deployment on homelab                                                               |
| Orchestration    | Docker Compose          | Lightweight, easy to manage in homelab                                                      |
| Scheduler        | APScheduler             | Schedule agent tasks                                                                        |
| Database         | TimescaleDB             | Store OHLCV, trades, metrics, journal                                                       |
| Message Bus      | Redis Pub/Sub           | Agent communication                                                                         |
| API Layer        | FastAPI                 | Inter-agent API access & control plane                                                      |
| Backtesting      | Custom Python Engine    | Strategy-aware replay system. Tailored to strategy; supports IFVG, liquidity, and MSB rules |
| Dashboard        | Streamlit               | Visual interface for logs & stats                                                           |
| Monitoring       | Prometheus + Grafana    | Agent and system monitoring                                                                 |

---

## 🤖 Agent Overview

### 1. 🧠 Market Research Agent

- Screens top assets by volume/volatility/structure
- Identifies candidates with unmitigated FVGs and imbalance
- **Immediately stores raw OHLCV data** in the database to reduce latency

### 2. 📊 Market Data Collector Agent

- Cleans, resamples and fills missing market data
- Can be bypassed if Market Research Agent stores raw data

### 3. 📉 Technical Analysis Agent

- Detects IFVGs, MSBs, Liquidity levels, Order Blocks
- Validates trade setup using structure rules

### 4. 🧮 FVG & Liquidity Tracker Agent

- Maintains state of unmitigated FVGs & liquidity zones
- Notifies TA Agent of changes

### 5. 🛡️ Risk Manager Agent

- Manages exposure and position sizing
- Adjusts risk based on confidence, confluences

### 6. 💼 Portfolio Manager Agent

- Executes trades using broker APIs
- Manages open positions and exits

### 7. 📝 Journaling Agent

- Stores trade metadata (entry reason, screenshot, RR, timestamps)
- Writes to TimescaleDB and optional CSVs

### 8. 📈 Performance Agent

- Tracks win rate, drawdown, profit factor
- Sends alerts when metrics degrade
- Feeds data into Streamlit dashboard

### 9. 🔔 Notification Agent (Optional)

- Sends trade, error, or system alerts to Discord/Telegram

---

## 🤯 Optional/Future Agents

- **Anomaly Detection Agent**: Detects outliers in behavior vs historical performance
- **Feedback Agent**: Suggests tuning to RR thresholds, OB confidence, etc.

---

## 🔧 AI Usage

- No AI agents at launch.
- May use AI in the future for:
  - Trade commentary/journaling automation
  - Pattern recognition or market anomaly flagging
  - Adaptive backtesting using RL

---

## 🗃 Folder Structure

```bash
agentic-trading-bot/
├── agents/
│ ├── market_research/
│ ├── market_data_collector/
│ ├── technical_analysis/
│ ├── fvg_tracker/
│ ├── risk_manager/
│ ├── portfolio_manager/
│ ├── journaling/
│ ├── performance/
│ ├── notification/
│ └── common/ # Shared logic
│
├── api/                  # FastAPI routes
│
├── core/
│   ├── scheduler/              # APScheduler jobs
│   ├── redis_bus/              # Redis pub/sub client
│   ├── logs/
│   |   ├── agent_logs/
│   └── config
│       ├── scheduler_config.yaml
│       └── settings.yaml
│
├── dashboard/                 # Streamlit UI
|
├── db/
│ ├── init.sql
│ └── migrations/
|
├── docker/
│ ├── docker-compose.yml
│ └── Dockerfiles/
│
├── backtesting/               # Custom replay engine
│
├── tests/
│   ├── integration/
│   └── unit/
│
├── requirements.txt
├── .env
└── README.md
```

---

## 🧾 Final TODO Summary

### 📦 Infrastructure

- [ ] Set up TimescaleDB (via Docker)

- [ ] Set up Redis (Pub/Sub)

- [ ] Set up Prometheus + Grafana

- [ ] Create shared .env and settings.yaml

- [ ] Define Docker Compose for multi-agent architecture

### 🧠 Core Modules

- [ ] Implement Redis Pub/Sub wrapper

- [ ] Build API layer (FastAPI)

- [ ] Logging system for agent health

### 🧠 Agent Development

- [ ] Market Research Agent

- [ ] Market Data Collector

- [ ] Technical Analysis Agent

- [ ] FVG & Liquidity Tracker Agent

- [ ] Risk Manager Agent

- [ ] Portfolio Manager Agent

- [ ] Journaling Agent

- [ ] Performance Agent

- [ ] Notification Agent (Optional)

### 📈 Dashboard & Monitoring

- [ ] Implement Streamlit dashboard

- [ ] Live portfolio stats + journal history

- [ ] Charts: RR, PnL, drawdown, etc.

- [ ] Prometheus exporters per agent

### 🧪 Backtesting System

- [ ] Replay engine

- [ ] Strategy validation

- [ ] Journaling integration

- [ ] Metrics tracking

### 🧪 Testing + Stability

- [ ] Unit tests (pytest)

- [ ] Integration test with dummy data

- [ ] Backtest vs live signal reconciliation

---

## 🧠 Final Touches

- Agent recovery on crash

- Add heartbeat logs/alerts

- Optional: Add auth to FastAPI routes

## ✅ Final Thoughts

- ✅ Fully agentic, modular, extensible system

- ✅ Backtesting and live trading with identical logic

- ✅ Redis handles real-time signal passing without overcomplicating with external queues

- ✅ TimescaleDB enables scalable, time-series aware data access

You're now fully equipped to build, run, monitor, and improve a modern, smart trading bot.
