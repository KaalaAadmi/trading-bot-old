# Technical Analysis Agent

Once your data is:

- Filtered ✅ (Market Research Agent)

- Fetched & stored ✅ (Data Collector Agent)

The Technical Analysis Agent is next in line. Its job is to:

- Analyze the stored OHLCV data

- Detect inverse fair value gaps (IFVGs), structure breaks (MSBs), liquidity zones

- Validate strategy-specific conditions (volume spikes, session time, optional OBs)

- Generate signals for trade evaluation(includes the calculated risk-reward ratio)

## 📄 Technical Analysis Agent — Architecture & Responsibilities

🔧 Agent Name
`technical_analysis_agent.py`

## 🧠 Purpose

Analyze stored HTF and LTF price data to identify:

- Unmitigated Fair Value Gaps

- Market Structure Breaks (MSBs)

- Buy-side / Sell-side liquidity

Confirm confluence rules (volume spikes, session alignment, optional OBs)

➡️ Emit trade candidate signals (Buy/Sell/Hold) to analysis_signals stream or publish to Redis for further evaluation.

### 📥 Inputs

- OHLCV data from TimescaleDB

- Ticker/timeframe from the data_collector_channel stream

- Config thresholds (e.g. FVG % height, confluence settings)

### 📤 Outputs

- `trade_signal`: {ticker, timeframe, direction, signal_type, reason, metadata}

- `tracking_info`: For journaling/logging/debugging purposes

### 🧩 Responsibilities

| Task                       | Description                                          |
| -------------------------- | ---------------------------------------------------- |
| ✅ Detect IFVGs            | Use gap detection on historical candles              |
| ✅ Track unmitigated FVGs  | Avoid FVGs already revisited or invalidated          |
| ✅ Detect MSBs             | Using internal/external structure (configurable)     |
| ✅ Detect liquidity levels | Swing highs/lows, equal highs/lows                   |
| ✅ Validate entry criteria | Inversion + MSB + one confluence (volume/session/OB) |
| ✅ Emit signals            | Structured message to downstream agents              |

## 🧠 Key Implementation Details

### 🔍 Fair Value Gap Logic

```python
if candle_n1['high'] < candle_n3['low']:
    bullish_fvg = (candle_n1['high'], candle_n3['low'])
```

Track if price has re-entered that zone (i.e., "mitigated").

### 🔁 Structure Break (MSB)

- Confirm with HH/LL shift using high/low across N candles.

- Can use zig-zag logic or internal/external MSB rules.

### 🔥 Volume Spike Filter

Use relative volume:

```python
if current_volume > average_volume * spike_factor:
    confirm_volume_spike = True
```

### 🧱 Folder & File Structure

```markdown
agents/
technical_analysis/
**init**.py
technical_analysis_agent.py
logic/
fvg_detector.py
msb_detector.py
liquidity_tracker.py
utils/
data_loader.py
validation.py
```

> The configs are already stored in `core/config/settings.yaml` file. So we have to refer to that and use the values stored in the file.

### ⚠️ Things to Keep in Mind

#### ❗ Loop Prevention

If you refetch data and retrigger analysis, avoid duplicate signal emissions.

#### ❗ FVG Tracking

Don’t re-signal old FVGs. Track status (mitigated, pending, invalidated).

#### ❗ Confluence Logic

Ensure confluence rules don’t make signal generation too strict. Balance is key.

#### ❗ DB Queries

Avoid loading thousands of candles into memory. Use windowed SQL queries.

### 🚩 Potential Loopholes & Pitfalls

| Problem                      | Recommendation                                                   |
| ---------------------------- | ---------------------------------------------------------------- |
| Detecting FVGs               | across sessions Anchor analysis to recent completed sessions     |
| Large memory use             | Paginate data load from DB                                       |
| Re-detection of same FVG     | Store detected FVGs in Redis or DB with state (pending/filled)   |
| MSB false positives          | Require structure confirmation + volume spike                    |
| Multiple timeframes mismatch | Ensure LTF/HTF pairing and alignment (from Data Collector Agent) |

### 🧠 Redis Stream Proposal

After emitting signal:

```json
{
  "ticker": "AAPL",
  "timeframe": "5m",
  "direction": "SELL",
  "reason": "Inverse FVG + MSB + SessionTime",
  "fvg_level": [high, low],
  "liquidity_target": 145.60,
  "stop_loss": 149.25,
  "rr": 2.1
}
```

Published to:

- `analysis_signals` stream

- Used by: Portfolio Manager Agent, Journaling Agent, etc.

## Tracked FVGs & Liquidity Management

### 📊 Tracked FVGs & Liquidity Management

The Technical Analysis Agent is responsible for managing and persisting:

- Unmitigated Fair Value Gaps (FVGs) in a table named tracked_fvgs

- Buy-side and Sell-side liquidity levels in a table named tracked_liquidity

### 🧠 Why the Technical Analysis Agent?

The TA Agent is the only module that:

- Has full candle structure context

- Identifies and confirms FVGs, MSBs, and liquidity targets

- Tracks the lifecycle of FVGs (created → filled/invalidated)

- Monitors which liquidity levels have been tapped or remain valid

### 📁 tracked_fvgs Table Schema

| Column        | Type          | Description                             |
| ------------- | ------------- | --------------------------------------- |
| id            | SERIAL / UUID | Primary key                             |
| symbol        | TEXT          | Ticker (e.g., BTC-USD)                  |
| timeframe     | TEXT          | e.g., 5m, 1h                            |
| direction     | TEXT          | bullish or bearish                      |
| high          | NUMERIC       | High boundary of the FVG                |
| low           | NUMERIC       | Low boundary of the FVG                 |
| formed_at     | TIMESTAMPTZ   | Candle time when it formed              |
| tatus         | TEXT          | pending, filled, invalidated            |
| confirmed     | BOOLEAN       | Was it inversed and structure-confirmed |
| msb_confirmed | BOOLEAN       | Market Structure Break confirmation     |
| metadata      | JSONB         | Confluence info: volume spike, OB, etc. |
| last_checked  | TIMESTAMPTZ   | Timestamp of last evaluation            |

### 📁 tracked_liquidity Table Schema

| Column      | Type          | Description                    |
| ----------- | ------------- | ------------------------------ |
| id          | SERIAL / UUID | Primary key                    |
| symbol      | TEXT          | Ticker                         |
| timeframe   | TEXT          | e.g., 5m, 1h                   |
| type        | TEXT          | buy-side or sell-side          |
| level       | NUMERIC       | Liquidity price level          |
| formed_at   | TIMESTAMPTZ   | Time of swing high/low         |
| tapped      | BOOLEAN       | Whether it’s been swept        |
| tap_time    | TIMESTAMPTZ   | When it was swept (if tapped)  |
| equal_highs | BOOLEAN       | If this was an equal high/low  |
| metadata    | JSONB         | Optional structure/volume info |

### 🔁 Lifecycle Logic

| Phase                  | Action                                  |
| ---------------------- | --------------------------------------- |
| On FVG detection       | Add to tracked_fvgs with pending status |
| On mitigation          | Set status to filled or invalidated     |
| On liquidity detection | Add to tracked_liquidity                |
| On price tap           | Set tapped = true, add tap_time         |

### 🧠 Future Split-Off Option

If performance becomes an issue:

- Offload tracking to a lightweight “FVG Tracker Agent”

- It can update FVG and liquidity status in the background

### ✅ Why Persist in DB?

- Survives restarts

- Enables detailed journaling and post-trade review

- Helps Portfolio Manager Agent avoid duplicate trades

- Offers audit trail for backtests

## ✅ Summary

| Feature                      | Included |
| ---------------------------- | -------- |
| HTF/LTF alignment            | ✅       |
| Unmitigated FVG detection    | ✅       |
| MSB structure check          | ✅       |
| Volume/session/OB confluence | ✅       |
| Redis stream output          | ✅       |
| Extensible config            | ✅       |

## 🔥 Full Correct Understanding of when to take and entry (Detailed)

| Stage | Action                    | Timeframe                                      |
| ----- | ------------------------- | ---------------------------------------------- |
| 1️⃣    | Detect Unmitigated FVGs   | On HTF (e.g., 1h, 4h)                          |
| 2️⃣    | Monitor Price on LTF      | On LTF (e.g., 5m, 15m)                         |
| 3️⃣    | Wait for Inversion Signal | On LTF: close inside or opposite FVG direction |
| 4️⃣    | Check MSB + Confluences   | Still on LTF                                   |
| 5️⃣    | Take Entry                | On LTF, after confirmed structure shift (MSB)  |

### 📍 Key Points to Understand (very important)

| Point                              | Explanation                                                                                   |
| ---------------------------------- | --------------------------------------------------------------------------------------------- |
| FVG Formation                      | Happens on HTF candles. You find important, high-quality gaps at bigger timeframes.           |
| Monitoring & Entry Trigger         | Happens on LTF, inside the HTF FVG region.                                                    |
| Inversion Confirmation             | You need to see price close inside or opposite direction relative to the HTF FVG, on the LTF. |
| Structure Break Confirmation (MSB) | Must happen on LTF after inversion — this is critical to avoid fake moves.                    |

|Targets| Can be set based on LTF liquidity pools but must be aware of HTF structure as a guide.|

## 🧠 Why This Matters?

- HTF FVGs represent big liquidity imbalances that smart money will eventually attack.

- LTF gives you better timing and precision for when the market actually commits to a move.

- Without LTF confirmation, you risk trying to pre-guess smart money — and getting punished for it.

✅ You want the HTF idea + LTF execution.

This way, you combine:

- Power of higher timeframe context

- Speed of lower timeframe execution

- Accuracy of MSB + Inversion triggers

🎯 Visual Summary

```text

[HTF (1h)]

- Find FVGs
- Track them as 'pending'

↓

[LTF (5m)]

- Watch price inside FVG zone
- Confirm inversion candle close
- Confirm MSB structure break
- Apply volume/session/OB filters
- Take entry only if all rules are satisfied
```
