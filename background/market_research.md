## ✅ Your Strategy Needs:

The strategy thrives when:

- There is enough movement to form FVGs and liquidity zones.

- The structure is clear enough to determine MSBs.

- The asset has enough liquidity to execute orders with minimal slippage.

- The market is not too choppy, i.e., healthy volatility, not randomness.

## 🎯 Finalized Filtering Criteria for Market Research Agent

### 1. Average Daily Volume (Liquidity Filter)

- Why? Ensures you're looking at active assets where price discovery is clean.

- How? 5–10 day average volume.

- Thresholds:

  - Stocks: > 1,000,000 shares/day

  - Crypto: > $10M/day (converted using OHLCV)

```python
df["avg_volume"] = df["volume"].rolling(window=5).mean()
```

### 2. Volatility Filter (Required for FVGs & MSBs)

- Why? Without volatility, no FVGs or meaningful liquidity zones form.

- How? Use rolling standard deviation of daily returns.

- Thresholds: Daily volatility > 2% (0.02)

```python
df["daily_returns"] = df["close"].pct_change()
df["volatility"] = df["daily_returns"].rolling(window=14).std()
```

### 3. Recent Price Movement (Momentum Filter)

- Why? Helps avoid consolidating or sideways assets. We want recent movement.

- How? % change in last 5 days.

- Threshold: Move > ±2% (0.02)

```python
recent_change = (df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5]
```

### 4. Minimum Price (Avoid Penny Stocks or Thin Crypto)

- Why? Structural noise is higher in low-priced assets.

- How? Last close.

- Threshold:

  - Stocks: > $1

  - Crypto: > $0.05

```python
df["valid_price"] = df["close"].iloc[-1] > min_price_threshold
```

### 5. Optional: Session Volume Spike

- Why? Sign of fresh interest; useful for intraday scalping.

- How? Compare current session volume to rolling average.

- Threshold: Spike > 2× average

## 🧠 Combined Filter Logic

```python

if (
    df["avg_volume"].mean() > volume_threshold and
    df["volatility"].mean() > volatility_threshold and
    abs(recent_change) > price_change_threshold and
    df["close"].iloc[-1] > min_price
):
    filtered_assets.append(ticker)
```

## ⚙️ Suggested Default Config

```yaml
filter_criteria:
  volume_threshold:
    stocks: 1000000
    crypto: 10000000 # in USD
  volatility_threshold: 0.02
  price_change_threshold: 0.02
  min_price:
    stocks: 1
    crypto: 0.05
```

## 💡 Bonus Ideas (Future Upgrades)

Score-based Ranking: Assign scores to each criteria and pick Top N instead of hard thresholds.

Adaptive Filters: Learn thresholds dynamically using recent bot performance.

ML-Based Screener: Train a classifier on winning vs losing trades to learn what pre-trade signals correlate with success.

## ✅ Summary of Filters to Consider

Filter Type Metric Threshold Purpose
Liquidity 5-day avg volume > 1M (stocks) Avoid illiquid chop
Volatility 14-day std dev of returns > 0.02 Ensure FVGs & breakouts possible
Momentum 5-day % change > 0.02 Avoid sideways action
Price Filter Last Close > $1 (stocks) Avoid penny-stock noise
Session Volume Spike ⚡ Current vol / avg vol > 2× Early sign of institutional activity
