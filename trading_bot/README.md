# Trading Bot — Binance Futures Testnet (USDT-M)

A small, structured Python CLI application that places MARKET and LIMIT
orders on the Binance Futures Testnet, with input validation, structured
logging, and clean separation between the API client and the CLI layer.

## Project structure

```
trading_bot/
  bot/
    __init__.py
    client.py          # Signed REST calls to Binance Futures Testnet
    orders.py           # Order placement logic (client -> normalized result)
    validators.py        # CLI input validation
    logging_config.py    # File + console logging setup
  cli.py                 # Click-based CLI entry point
  sample_logs/            # Example log output (see below)
  requirements.txt
  .env.example
  README.md
```

## Setup

1. **Create a Binance Futures Testnet account** at
   https://testnet.binancefuture.com and generate an API key + secret
   (Account → API Key).

2. **Install dependencies** (Python 3.9+):

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure credentials**:

   ```bash
   cp .env.example .env
   # then edit .env and fill in:
   # BINANCE_API_KEY=...
   # BINANCE_API_SECRET=...
   ```

## How to run

**Market order (BUY):**
```bash
python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01
```

**Limit order (SELL):**
```bash
python cli.py --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.01 --price 61000
```

**Dry run** (validates input and logs the request without calling the API —
useful for testing the app without live testnet keys or network access):
```bash
python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01 --dry-run
```

**Stop-Market order** (bonus third order type — e.g. a manual stop-loss):
```bash
python cli.py --symbol BTCUSDT --side SELL --type STOP_MARKET --quantity 0.01 --stop-price 58000
```

**Market/Limit entry with automatic Stop-Loss + Take-Profit** (bonus — places
the entry order, then attaches reduce-only `STOP_MARKET` exit orders on the
opposite side so the position is automatically protected):
```bash
python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01 \
    --stop-loss 58000 --take-profit 63000
```

All arguments are validated before any network call is made:
- `symbol` must look like a valid trading pair (e.g. `BTCUSDT`)
- `side` must be `BUY` or `SELL`
- `type` must be `MARKET`, `LIMIT`, or `STOP_MARKET`
- `quantity` must be a positive number
- `price` is required for `LIMIT` orders, rejected for `MARKET`/`STOP_MARKET`
- `stop_price` is required for `STOP_MARKET` orders, rejected otherwise
- `--stop-loss` / `--take-profit` are only valid alongside a `MARKET`/`LIMIT`
  entry order (not alongside a standalone `STOP_MARKET` order)

On success the CLI prints the order request summary, then the response
(`orderId`, `status`, `executedQty`, `avgPrice`), then a success message.
On failure (bad input, Binance API error, or network error) it prints a
clear `✗` error message and exits with a non-zero status code.

## Logging

Every request and response is logged to `logs/trading_bot.log`
(rotating file, DEBUG level — full request params, minus the signature,
and raw API responses) as well as a concise INFO-level summary on the
console. Errors (validation failures, API errors, network failures) are
always logged with enough context to debug after the fact.

`sample_logs/` contains example log output from a dry run:
- `market_order_sample.log` — a MARKET order
- `limit_order_sample.log` — a LIMIT order
- `bracket_order_sl_tp_sample.log` — a MARKET entry with automatic
  stop-loss + take-profit orders attached (bonus feature)

These were generated with `--dry-run` because this environment does not
have outbound network access to `testnet.binancefuture.com`. The dry-run
path exercises the exact same validation, logging, and CLI/response code
as a live call — only `BinanceFuturesClient.place_order()`'s actual HTTP
request is swapped for a mock response. To generate real logs against
the live testnet, run the commands above (without `--dry-run`) with your
own API keys; `logs/trading_bot.log` will be created/updated automatically.

## Assumptions

- USDT-M Futures only (`/fapi/v1/order` on `https://testnet.binancefuture.com`).
- Only `MARKET` and `LIMIT` order types are required; `LIMIT` orders use
  `timeInForce=GTC` by default.
- Quantity/price precision (tick size, lot size) is assumed to be handled
  by the exchange's own validation — the client does not fetch the exact
  `exchangeInfo` filters for each symbol before submitting, since the
  task scope is order placement, not full trading-rule enforcement.
- Credentials are read from environment variables (via `.env`), not
  passed on the command line, to avoid leaking secrets in shell history.
- One-way position mode is assumed (no `positionSide` parameter is sent).
- Network errors are retried up to 3 times with a short backoff before
  the app reports failure.

## Error handling summary

| Failure type              | Where caught                | Result                                   |
|---------------------------|------------------------------|-------------------------------------------|
| Invalid CLI input          | `validators.py`              | Logged + printed, exit code 1             |
| Missing API credentials    | `cli.py`                     | Logged + printed, exit code 1             |
| Binance API error (4xx/5xx)| `client.py` → `BinanceAPIError` | Logged with code/msg, printed, exit code 1 |
| Network/timeout error      | `client.py` (retried x3)     | Logged, printed, exit code 1              |
| Unexpected exception       | `cli.py` top-level catch     | Full traceback logged, printed, exit code 1|

## Bonus: Stop-Loss / Take-Profit (third order type)

Implemented `STOP_MARKET` as a third order type, usable two ways:

1. **Standalone** — place a `STOP_MARKET` order directly (e.g. to protect
   an existing manually-opened position):
   ```bash
   python cli.py --symbol BTCUSDT --side SELL --type STOP_MARKET --quantity 0.01 --stop-price 58000
   ```

2. **Bracketed with an entry order** — pass `--stop-loss` and/or
   `--take-profit` alongside a `MARKET`/`LIMIT` order. The bot places the
   entry order first, then automatically places `reduceOnly=true`
   `STOP_MARKET` orders on the *opposite* side at each trigger price, so
   they can only close the position (never accidentally open a new one
   or add to it):
   ```bash
   python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01 \
       --stop-loss 58000 --take-profit 63000
   ```

**Why this and not a full auto-strategy:** the task scope is order
placement infrastructure, not a trading strategy — a strategy needs its
own backtesting before it's meaningful, which is out of scope here.
Stop-loss/take-profit is the risk-management layer that any strategy
(manual or automated) would sit on top of, and it reuses the existing
`client.py`/`orders.py` structure cleanly (one new order type, one new
`orders.py` helper) rather than requiring new architecture.

**Note:** if the entry order succeeds but a bracket leg (SL or TP) fails
to place, the bot logs and reports that failure clearly — in that case
the position exists on the exchange without full protection, and the
`STOP_MARKET` command above can be run manually to add the missing leg.
