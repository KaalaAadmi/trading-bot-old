Please go through the `background/trading-strategy.md`, `background/agentic-approach.md` and `background/og_prd.md` documents to get background on what we are building. The `background/trading-strategy.md` contains the complete trading strategy that the bot will follow. The `background/agentic-approach.md` file contains the approach we will follow to build our bot. The `background/og_prd.md` file contains the product requirements for the bot that we are building. I have already created all the folders as per the folder structure mentioned in the prd document. Please let me know if I have missed out on anything or if you find some loopholes or concerns about the background of what we are trying to build. Please be brutally honest with me throughout this conversation as I really want to make the bot a success, and to be able to do that, I need you to be able to say to me that I am wrong(if I am wrong) or if there is an issue with my thinking.

I believe we need to have a list of tickers that refreshes automatically on a daily basis. I was thinking to start with the S&P500 ticker list for stocks and the Coin50 ticker list for crypto. How can I fetch this and automatically refresh my list at the end of the day? I believe we can use APScheduler, but please do elaborate on the process and tell me what files and folders I need to create and the contents of each of the files.

It works great! Thanks! Now let's proceed with the data collector agent. Please go through the files in `background/` folder for your reference on what the data collector is supposed to do and how it is supposed to do it. Please feel free to ask me any questions if you have any. Please do not hesitate to ask as it will help us build the bot better.

Fixed Unit tests + Added Redis Stream Acknowledgement

Now I get the following errors in logs when I run `python main.py` for some of the filtered assets. Please help me fix them:
ERROR IN LOGS:
2025-04-18 04:08:26,516 - agents.data_collector - ERROR - Error updating last fetched timestamp for asset 'BNB-EUR' with timeframe '5m': (sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'asyncpg.exceptions.DataError'>: invalid input for query argument $3: '2025-04-18 03:05:00+00:00' (expected a datetime.date or datetime.datetime instance, got 'str')
[SQL:
INSERT INTO ohlcv_data (symbol, timeframe, timestamp)
VALUES ($1, $2, $3)
ON CONFLICT (symbol, timeframe) DO UPDATE
SET timestamp = EXCLUDED.timestamp
]
[parameters: ('BNB-EUR', '5m', '2025-04-18 03:05:00+00:00')]
(Background on this error at: https://sqlalche.me/e/20/dbapi)
2025-04-18 04:08:26,517 - agents.data_collector - ERROR - Error retrieving last fetched timestamp for asset 'LTC-EUR' with timeframe '5m': tuple indices must be integers or slices, not str
2025-04-18 04:08:26,517 - agents.data_collector - INFO - Fetching ltf data for asset 'LTC-EUR' after None...
2025-04-18 04:08:26,518 - agents.data_collector - INFO - Fetching 7 days of '5m' data for asset 'LTC-EUR'...
2025-04-18 04:08:26,606 - agents.data_collector - INFO - Fetched 1765 rows of '5m' data for asset 'LTC-EUR'.

Traceback (most recent call last):
File "/Users/arnavbhattacharya/Documents/CODES/test/main.py", line 37, in <module>
asyncio.run(start_agents())
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/runners.py", line 194, in run
return runner.run(main)
^^^^^^^^^^^^^^^^
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/runners.py", line 118, in run
return self.\_loop.run_until_complete(task)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/base_events.py", line 687, in run_until_complete
return future.result()
^^^^^^^^^^^^^^^
File "/Users/arnavbhattacharya/Documents/CODES/test/main.py", line 26, in start_agents
await data_collector_agent.start()
File "/Users/arnavbhattacharya/Documents/CODES/test/agents/market_data_collector/data_collector_agent.py", line 245, in start
await self.fetch_live_data()
File "/Users/arnavbhattacharya/Documents/CODES/test/agents/market_data_collector/data_collector_agent.py", line 256, in fetch_live_data
await asyncio.gather(\*tasks)
File "/Users/arnavbhattacharya/Documents/CODES/test/agents/market_data_collector/data_collector_agent.py", line 97, in process_ohlcv
async with self.semaphore: # Use the lazy-initialized semaphore
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/locks.py", line 14, in **aenter**
await self.acquire()
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/locks.py", line 378, in acquire
fut = self.\_get_loop().create_future()
^^^^^^^^^^^^^^^^
File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/asyncio/mixins.py", line 20, in \_get_loop
raise RuntimeError(f'{self!r} is bound to a different event loop')
RuntimeError: <asyncio.locks.Semaphore object at 0x10ac6ea80 [locked]> is bound to a different event loop
(venv) arnavbhattacharya@Arnavs-Laptop test %

Few things to note, when I perform the following in a separate terminal, I get the following:
psql -h localhost -U bot_user -d trading_bot -p 5432
trading_bot=# \dt
List of relations
Schema | Name | Type | Owner  
--------+---------------------+-------+----------
public | journal | table | bot_user
public | ohlcv_data | table | bot_user
public | performance_metrics | table | bot_user
public | tracked_fvgs | table | bot_user
public | tracked_liquidity | table | bot_user
(5 rows)

trading_bot=# \c ohlcv_data
connection to server at "localhost" (::1), port 5432 failed: FATAL: database "ohlcv_data" does not exist
Previous connection kept

I was trying to view the stored data, but I failed with this error.

I am attaching the current version of my code for my data_collector_agent and these are the issues that I noticed:

- when I run `python main.py`, after market_research_agent is done with the research, the data collector agent receives the filtered assets in message from market_research_agent, but, I get the following error in logs:
  ERROR IN LOGS:
  2025-04-19 13:45:23,305 - core.redis_stream - INFO - Acknowledged message ID '1745066531707-0' on stream 'ticker_updates_channel'.
  2025-04-19 13:45:23,307 - agents.data_collector - ERROR - Error processing filtered assets: Semaphore is bound to a different event loop.
  2025-04-19 13:45:23,308 - core.redis_stream - INFO - Acknowledged message ID '1745066723297-0' on stream 'market_research_signals'.

After a while, I also see the following in the logs:
2025-04-19 13:47:51,051 - apscheduler.executors.default - INFO - Running job "DataCollectorAgent.fetch_ltf_data (trigger: interval[0:05:00], next run at: 2025-04-19 13:52:51 IST)" (scheduled at 2025-04-19 13:47:51.028472+01:00)
2025-04-19 13:47:51,060 - agents.data_collector - INFO - Fetching LTF data for tracked assets...

and the agent starts collecting the ltf data for the filtered assets.
I believe the issue is that the historic data is not being fetched and neither is the htf data being fetched. Please tell me honestly if you feel that my understanding or thinking is wrong or if there is a better way to tackle the problem and solve it. Please do let me know honestly if my understanding of the problem is wrong or flawed or mistaken somewhere.

- Can we add a feature where we fetch the day of the week and based on that fetch the ltf and htf data for the assets that are being traded on that day - meaning, if it is a public holiday or weekend, then we should only fetch data for crypto currencies and not stocks since the exchange is closed on those days. Similarly, we can fetch the data for stocks between from 15 mins before market opens and till 15 mins after market closes. This should only happen for fetch_htf_data() and fetch_ltf_data(). When market research agent sends the updated filtered assets at 12:00(this runs because of the apscheduler), the data collector agent should fetch and store the. historic data as well. In doing so, we need to ensure that the (symbol, timeframe, timestamp) of the data that is the primary key in the ohlcv_data table, should be unique and if there is a conflict(meaning we are try to store the data again, then it should do nothing and keep the previous data itself). Please implement the part where we are fetching the list of public holidays how you see fit and has proper result.

- I noticed that the 1h data is not being fetched at all and there is no historic data for htf price for any of the filtered asset

- The cryptocurrencies are being fetched in USD, we need to multiply it with the current conversion rate of usd to eur and then store it in the database. We are missing out on this step. If this is already being done, please let me know honestly.

---

NEW ISSUES:
I made the changes that you suggested for the above issues(including semaphore issue). After that when I run the bot with `python main.py`, I noticed the following which I feel are issues. Please do let me know if my understanding is incorrect or flawed honestly. If not please tell me what changes to the code do I need to make to solve these issues. If you require any further information, then please do let me know. For context, please refer to our entire conversation.
Issues(according to me):

- The time at which the code is being run, from that time the scheduler starts scheduling the tasks, so if the code is run at 10:33 am, all the data is being fetched from that time, meaning 1h data is fetched again at 11:33 am, instead of 11 am when we actually get the data, similarly, the 5m data will be again fetched 10:38am, iinstead of 10:35 am, when the data is available. How can we sync it with the market times?

- How many rows should the ohlcv_data table have if it run it now? I am asking this because i have around `375300` rows in my `ohlcv_data` database, and I don't feel that is the correct number of rows that should be there.
