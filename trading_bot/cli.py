#!/usr/bin/env python3
"""
CLI entry point for the Binance Futures Testnet trading bot.

Examples
--------
Market order:
    python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01

Limit order:
    python cli.py --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.01 --price 60000

Standalone stop-market order (e.g. manual stop-loss):
    python cli.py --symbol BTCUSDT --side SELL --type STOP_MARKET --quantity 0.01 --stop-price 58000

Market entry with automatic stop-loss + take-profit bracket orders:
    python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01 \
        --stop-loss 58000 --take-profit 63000

Dry run (no network call, exercises validation + logging only):
    python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.01 --dry-run
"""

import os
import sys
import time

import click
from dotenv import load_dotenv

from bot.client import BinanceAPIError, BinanceFuturesClient, DEFAULT_BASE_URL
from bot.logging_config import setup_logging
from bot.orders import OrderResult, place_bracket_order, place_order
from bot.validators import ValidationError, validate_order_params

load_dotenv()


_mock_order_counter = 0


def _mock_order_response(symbol, side, order_type, quantity, price=None, stop_price=None):
    """Build a realistic fake response, used only in --dry-run mode."""
    global _mock_order_counter
    _mock_order_counter += 1
    fill_price = str(price) if price is not None else "60123.40"
    return {
        "orderId": (int(time.time() * 1000) % 1_000_000) + _mock_order_counter,
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "status": "FILLED" if order_type == "MARKET" else "NEW",
        "executedQty": str(quantity) if order_type == "MARKET" else "0",
        "avgPrice": fill_price if order_type == "MARKET" else "0",
        "price": str(price) if price is not None else "0",
        "stopPrice": str(stop_price) if stop_price is not None else "0",
    }


def _print_order_result(label: str, result: OrderResult):
    click.echo(f"\n{label}:")
    click.echo(f"  orderId     : {result.order_id}")
    click.echo(f"  status      : {result.status}")
    click.echo(f"  executedQty : {result.executed_qty}")
    click.echo(f"  avgPrice    : {result.avg_price}")


@click.command()
@click.option("--symbol", required=True, help="Trading pair, e.g. BTCUSDT")
@click.option("--side", required=True, help="BUY or SELL")
@click.option("--type", "order_type", required=True, help="MARKET, LIMIT, or STOP_MARKET")
@click.option("--quantity", required=True, help="Order quantity")
@click.option("--price", default=None, help="Limit price (required for LIMIT orders)")
@click.option("--stop-price", default=None, help="Trigger price (required for STOP_MARKET orders)")
@click.option("--stop-loss", default=None,
              help="Optional: attach an automatic reduce-only stop-loss at this trigger "
                   "price to a MARKET/LIMIT entry order.")
@click.option("--take-profit", default=None,
              help="Optional: attach an automatic reduce-only take-profit at this trigger "
                   "price to a MARKET/LIMIT entry order.")
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Validate and log the request without calling the Binance API.",
)
@click.option(
    "--base-url", default=DEFAULT_BASE_URL, show_default=True,
    help="Binance Futures REST base URL.",
)
def main(symbol, side, order_type, quantity, price, stop_price,
          stop_loss, take_profit, dry_run, base_url):
    """Place a MARKET, LIMIT, or STOP_MARKET order on Binance Futures Testnet (USDT-M).

    Optionally attach --stop-loss / --take-profit bracket orders to a
    MARKET/LIMIT entry so the position is automatically protected.
    """
    logger = setup_logging()

    # 1. Validate input -------------------------------------------------
    try:
        clean = validate_order_params(
            symbol, side, order_type, quantity, price,
            stop_price=stop_price, stop_loss=stop_loss, take_profit=take_profit,
        )
    except ValidationError as exc:
        logger.error("Input validation failed: %s", exc)
        click.secho(f"✗ Invalid input: {exc}", fg="red")
        sys.exit(1)

    is_bracket = clean["type"] in ("MARKET", "LIMIT") and (
        clean["stop_loss"] is not None or clean["take_profit"] is not None
    )

    click.echo("Order request summary:")
    click.echo(f"  symbol      : {clean['symbol']}")
    click.echo(f"  side        : {clean['side']}")
    click.echo(f"  type        : {clean['type']}")
    click.echo(f"  quantity    : {clean['quantity']}")
    click.echo(f"  price       : {clean['price'] if clean['price'] is not None else 'N/A'}")
    if clean["type"] == "STOP_MARKET":
        click.echo(f"  stop_price  : {clean['stop_price']}")
    if clean["stop_loss"] is not None:
        click.echo(f"  stop_loss   : {clean['stop_loss']} (reduce-only, opposite side)")
    if clean["take_profit"] is not None:
        click.echo(f"  take_profit : {clean['take_profit']} (reduce-only, opposite side)")
    if dry_run:
        click.echo("  mode        : DRY RUN (no order will be sent)")

    # 2. Submit order(s) -------------------------------------------------
    try:
        if dry_run:
            logger.info(
                "[DRY RUN] Would submit: symbol=%s side=%s type=%s quantity=%s "
                "price=%s stop_price=%s stop_loss=%s take_profit=%s",
                clean["symbol"], clean["side"], clean["type"], clean["quantity"],
                clean["price"], clean["stop_price"], clean["stop_loss"], clean["take_profit"],
            )
            entry_raw = _mock_order_response(
                clean["symbol"], clean["side"], clean["type"],
                clean["quantity"], clean["price"], clean["stop_price"],
            )
            logger.debug("[DRY RUN] Mock entry response: %s", entry_raw)
            entry_result = OrderResult(entry_raw)

            sl_result = tp_result = None
            exit_side = "SELL" if clean["side"] == "BUY" else "BUY"
            if clean["stop_loss"] is not None:
                sl_raw = _mock_order_response(
                    clean["symbol"], exit_side, "STOP_MARKET",
                    clean["quantity"], stop_price=clean["stop_loss"],
                )
                logger.debug("[DRY RUN] Mock stop-loss response: %s", sl_raw)
                sl_result = OrderResult(sl_raw)
            if clean["take_profit"] is not None:
                tp_raw = _mock_order_response(
                    clean["symbol"], exit_side, "STOP_MARKET",
                    clean["quantity"], stop_price=clean["take_profit"],
                )
                logger.debug("[DRY RUN] Mock take-profit response: %s", tp_raw)
                tp_result = OrderResult(tp_raw)

            results = {"entry": entry_result, "stop_loss": sl_result, "take_profit": tp_result}

        else:
            api_key = os.environ.get("BINANCE_API_KEY")
            api_secret = os.environ.get("BINANCE_API_SECRET")
            if not api_key or not api_secret:
                raise ValidationError(
                    "BINANCE_API_KEY / BINANCE_API_SECRET not set. "
                    "Copy .env.example to .env and fill in your testnet keys, "
                    "or use --dry-run to test without credentials."
                )
            client = BinanceFuturesClient(api_key, api_secret, base_url=base_url)

            if is_bracket:
                results = place_bracket_order(
                    client,
                    symbol=clean["symbol"], side=clean["side"], order_type=clean["type"],
                    quantity=clean["quantity"], price=clean["price"],
                    stop_loss=clean["stop_loss"], take_profit=clean["take_profit"],
                )
            else:
                entry_result = place_order(
                    client,
                    symbol=clean["symbol"], side=clean["side"], order_type=clean["type"],
                    quantity=clean["quantity"], price=clean["price"],
                    stop_price=clean["stop_price"],
                )
                results = {"entry": entry_result, "stop_loss": None, "take_profit": None}

    except ValidationError as exc:
        logger.error("Configuration error: %s", exc)
        click.secho(f"✗ Configuration error: {exc}", fg="red")
        sys.exit(1)
    except BinanceAPIError as exc:
        click.secho(f"✗ Order failed: {exc}", fg="red")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - top-level safety net for the CLI
        logger.exception("Unexpected error while placing order")
        click.secho(f"✗ Unexpected error: {exc}", fg="red")
        sys.exit(1)

    # 3. Print response(s) -----------------------------------------------
    _print_order_result("Entry order response", results["entry"])
    if results["stop_loss"] is not None:
        _print_order_result("Stop-loss order response", results["stop_loss"])
    if results["take_profit"] is not None:
        _print_order_result("Take-profit order response", results["take_profit"])

    click.secho("\n✓ Order(s) placed successfully.", fg="green")


if __name__ == "__main__":
    main()
