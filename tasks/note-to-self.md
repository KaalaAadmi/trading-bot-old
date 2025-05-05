NOTE TO SELF:

- [ ] The time at which the code is run, the ltf data is being fetched from that time, meaning, if I run the code for the first time at 10:32am, then the next run for the ltf data fetching is being done at 10:37am whereas it should be fetched at 10:35am. So, can we check the current time and then run it accordingly for ltf at the correct time for the first run and later it should run like it is? Or should we run the initial run when we are running the code, and the subsequent runs should be at clock time? For htf, I prefer it to be the 2nd option.
- [ ] Increase the data for storing(loopback_days) {change in `settings.yaml` for `data_collector_agent`}
- [ ] Filter more strictly. Way too lenient now. {change in `market_research_agent.py` for `market_research_agent`}
- [ ] Take input of the country where the user will trade and set it as a setting in `settings.yaml`
- [ ] Make a setting in `settings.yaml` for apikey and apiurl for the broker. Check if the broker supports fetching market data and then setting orders.
- [ ] Setup a setting in `settings.yaml` for apikey and apiurl for fetching market data
- [ ] Make a setting in `settings.yaml` wherein the environment is set to either `production` or `development`. If it is `production`, then the broker api calls are made. If it is `development`, then it only logs the signal and keeps a track of it in the journal.

Filter Code:

```python

df["avg_volume"] = df["volume"].rolling(window=5).mean() # Liquidity Filter

# Volatility Filter
df["daily_returns"] = df["close"].pct_change()
df["volatility"] = df["daily_returns"].rolling(window=14).std()

recent_change = (df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5] # Momentum filter

df["valid_price"] = df["close"].iloc[-1] > min_price_threshold # Avoid penny stocks

if (
    df["avg_volume"].mean() > volume_threshold and
    df["volatility"].mean() > volatility_threshold and
    abs(recent_change) > price_change_threshold and
    df["close"].iloc[-1] > min_price
):
    filtered_assets.append(ticker)
```
