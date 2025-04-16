# Refined Inverse FVG + Liquidity Trading Strategy (2025 Edition)

## Core Thesis

Exploit failed mitigation of **Fair Value Gaps (FVGs)** and their inversions, with confirmation from **Market Structure Breaks (MSBs)** and targeting **liquidity pools** (buy/sell-side).

---

## Strategy Framework

### 1. 🔍 FVG Identification (HTF)

- Use higher timeframes (e.g. 4H, 1H) to mark **unmitigated FVGs**.
- FVGs must be significant — suggested: **height > 1.5× average body** of last 20 candles (or based on ATR).
- **Ignore FVGs** that are too small (noise) or already filled.
- **Order Blocks (OBs)** should be marked alongside FVGs for potential confluence (optional).

### 2. 🔄 FVG Inversion Detection (LTF)

- Drop to a lower timeframe (e.g. 5min, 15min).
- Wait for **price to move cleanly through the FVG** in the opposite direction of its original intent.
- **Entry trigger**: A candle **closes beyond the far end of the FVG** in the inversion direction:
  - Bearish close above a bullish FVG = **sell signal**
  - Bullish close below a bearish FVG = **buy signal**
- This often coincides with a **Market Structure Break (MSB)** — but confirm MSB separately.

### 3. ✅ Entry Criteria

- **MSB is mandatory** — no trade without a confirmed **structure shift** in the trade direction.
- Entry only if the following two conditions are met:
  1. **IFVG (Inverse Fair Value Gap)** is confirmed by price closing through it.
  2. **MSB** is present in the same direction.
- Risk level is determined by the presence of **confluence factors**:
  - **OB**, **Volume Spike**, or **Session Time** alignment.

### 4. 🎯 Target Selection

- Target **unmitigated buy-side liquidity** (for longs) or **sell-side liquidity** (for shorts).
- Prefer swing highs/lows or equal highs/lows that remain untapped.

### 5. 🛡️ Stop Loss

- SL is placed just **below/above the original FVG**, depending on trade direction.
- Exit only if price **closes beyond the invalidated side** of the FVG.

### 6. 💰 Risk Management (Dynamic)

- **Default risk: 10% per trade**.
- If **two or more confluences** (from OB, volume, or session) are present, you may risk **up to 20%**.
- Use this dynamic sizing to allocate more capital to high-probability setups.

---

## Key Tactical Filters & Rules ✅

### 📦 Selecting Between Stacked FVGs

- Prioritise the **largest FVG** when multiple are stacked.
- Only act if **MSB** and **confluence factor** align with that specific FVG.
- Action: Add size labels to FVG boxes (pip/percentage).
- Action: Mark OBs near FVGs for added confidence (optional).

### 🎉 Avoiding Whipsaws (False Inversions)

- Use **volume filter** to ignore FVG inversions on low volume.
- Trade only during **London Open, NY Open, or overlap**.
- Action: Use session overlays and volume indicators to enforce this.

### 🎭 Preventing False Confirmations

- MSB is **non-negotiable** — always required.
- Action: Confirm MSB before every trade.
- Action: Use **internal/external structure rules** to define MSB:
  - **Internal break** = breach of recent swing high/low within a leg
  - **External break** = breach of major structure from previous swing

### ⏰ HTF-LTF Confluence for Accuracy

- HTF (1H, 4H, Daily) for FVG marking.
- LTF (5min, 15min) for entry execution.
- Leads to **better entries and tighter stop losses**.

---

## Setup Example (Bearish)

1. Identify unmitigated bearish FVG on 4H.
2. Wait for LTF (5min) candle to **close bearish beyond the top** of the FVG.
3. Confirm **MSB on LTF** in bearish direction.
4. If OB/volume/session confluence exists → risk 20%. If not → risk 10%.
5. Enter short.
6. SL = above FVG.
7. TP = next clean sell-side liquidity.

---

## Execution Checklist ✅

- [ ] HTF FVG marked and significant
- [ ] LTF entry candle confirms IFVG (price closes through)
- [ ] MSB confirmed in entry direction
- [ ] Confluence present (OB, Volume Spike, Session)
- [ ] Risk adjusted (10% or 20%)
- [ ] SL and TP clearly defined
- [ ] Screenshot + journal entry created

---

## Trade Journal Headings

- **Date**
- **Instrument**
- **HTF FVG timeframe & direction**
- **LTF entry timeframe**
- **Screenshot of FVG + MSB**
- **Entry Price**
- **Stop Loss Level**
- **Target Level**
- **Confluence Present (OB, Volume, Session)**
- **Execution notes**
- **Result (Win/Loss)**
- **RR Ratio**
- **Reflection (What went well / What to improve)**

---

## Implementation Tasks (Action Plan)

### 🔢 Select Between Stacked FVGs

- Action: Create FVG box labels with size % (or pip value)
- Action: Mark nearby OBs and check for MSB confirmation at that level

### 📊 Filter Whipsaws

- Action: Add volume indicator to chart (e.g. Volume Profile or standard vol bars)
- Action: Limit trades to specific sessions (e.g., script vertical session markers)

### 📐 Add MSB Confirmation

- Action: Learn to mark internal/external structure properly
- Action: Confirm MSB *before* trade entry – make it rule-based

### 🧪 Backtesting

- Action: Manually log 50 trades with screenshots and rationale
- Action: Create a TradingView log or Python tracker for journaling
- Track: Win%, avg RR, drawdown, SL hit causes

---

## Final Thoughts

Your strategy now rests on:

- **Clean structure** (MSB mandatory)
- **Smart filters** (volume/session)
- **Sniper entries** (LTF against HTF FVGs)
- **Simple targeting** (liquidity pools)
- **Risk scaling** based on confluence

You're avoiding the overfitting trap while still stacking probability. 🔥

Biggest risks now:
- Overconfidence during backtesting
- Poor journaling/tracking of performance
- Ignoring MSB confirmation in fast-paced moments

Master execution, and this strategy has serious potential. 🚀

