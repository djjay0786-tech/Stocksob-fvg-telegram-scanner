# NSE/BSE Monthly + 3M Bullish OB/FVG Telegram Scanner

Free starter scanner for GitHub Actions.

## What it does
- Reads symbols from `universe.csv`
- Downloads daily OHLC data using `yfinance`
- Builds Monthly and 3-Month candles
- Finds a simple, deterministic bullish Order Block:
  the last bearish candle before a bullish displacement candle that closes above the prior candle high
- Finds a simple bullish 3-candle FVG:
  candle 3 low > candle 1 high
- Alerts when price **first enters** a zone
- While price remains inside the zone, sends a **status alert once per day** (configurable)
- Sends Telegram alerts
- Stores alert state in `state.json` so duplicate entry alerts are avoided

## Important
Order Block/FVG definitions vary between traders. This project uses the definitions above so the scanner is reproducible. Test it before using it for trading.

## GitHub setup
1. Create a GitHub repository.
2. Upload all files in this project.
3. Go to Settings -> Secrets and variables -> Actions -> New repository secret.
4. Add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Run Actions -> OB/FVG Scanner -> Run workflow.
6. After testing, enable the scheduled workflow.

GitHub Actions schedules are not guaranteed to run exactly on time. They can be delayed during high load.

## Universe
`universe.csv` contains a starter list. Add your NSE/BSE symbols in Yahoo Finance format:
- NSE: `RELIANCE.NS`
- BSE: `500325.BO`

For the full NSE/BSE universe, replace/update `universe.csv` with the symbols you want to monitor. Very large universes may hit free data-source/rate limits.

## Settings
Edit `config.py`:
- `ENTRY_ALERT_COOLDOWN_HOURS`
- `INSIDE_ALERT_HOURS`
- `MIN_FVG_POINTS`
- `MIN_DISPLACEMENT_BODY_ATR`

The default inside alert is once per 24 hours per zone.

## Telegram
Create a bot with BotFather, send `/start` to the bot, then put the bot token and chat ID into GitHub Secrets. Never commit the token to the repository.
