"""
Order placement logic — sits between the CLI and the raw API client.

Responsible for: building the final request payload from validated
input, calling the client, and normalizing the response into a
predictable dict the CLI can print.
"""

import logging

from .client import BinanceAPIError, BinanceFuturesClient

logger = logging.getLogger("trading_bot.orders")


class OrderResult:
    """Normalized view of a Binance order response."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.order_id = raw.get("orderId")
        self.status = raw.get("status")
        self.executed_qty = raw.get("executedQty")
        self.avg_price = raw.get("avgPrice")
        self.symbol = raw.get("symbol")
        self.side = raw.get("side")
        self.order_type = raw.get("type")

    def __str__(self):
        return (
            f"orderId={self.order_id} status={self.status} "
            f"executedQty={self.executed_qty} avgPrice={self.avg_price}"
        )


def place_order(client: BinanceFuturesClient, symbol: str, side: str,
                 order_type: str, quantity, price=None, stop_price=None) -> OrderResult:
    """Build the request, submit it, and return a normalized OrderResult.

    Raises BinanceAPIError on failure (already logged by the client layer).
    """
    logger.info(
        "Submitting order: symbol=%s side=%s type=%s quantity=%s price=%s stop_price=%s",
        symbol, side, order_type, quantity, price, stop_price,
    )

    try:
        raw_response = client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=str(quantity),
            price=str(price) if price is not None else None,
            stop_price=str(stop_price) if stop_price is not None else None,
        )
    except BinanceAPIError:
        logger.error("Order submission failed for %s %s %s", symbol, side, order_type)
        raise

    result = OrderResult(raw_response)
    logger.info("Order accepted: %s", result)
    return result


def _opposite_side(side: str) -> str:
    return "SELL" if side == "BUY" else "BUY"


def place_bracket_order(client: BinanceFuturesClient, symbol: str, side: str,
                         order_type: str, quantity, price=None,
                         stop_loss=None, take_profit=None) -> dict:
    """Place an entry order plus optional stop-loss / take-profit exit orders.

    The entry order (MARKET or LIMIT) opens the position. stop_loss and
    take_profit, if given, are placed as reduce-only STOP_MARKET orders
    on the *opposite* side so they only ever close the position, never
    add to it. Returns {"entry": OrderResult, "stop_loss": OrderResult|None,
    "take_profit": OrderResult|None}.

    If the entry order succeeds but a bracket leg fails, the failure is
    logged and raised — the caller/CLI is responsible for warning the
    user that they now hold an unprotected position.
    """
    entry = place_order(client, symbol, side, order_type, quantity, price=price)
    results = {"entry": entry, "stop_loss": None, "take_profit": None}

    exit_side = _opposite_side(side)

    if stop_loss is not None:
        logger.info("Placing stop-loss: symbol=%s side=%s stopPrice=%s", symbol, exit_side, stop_loss)
        try:
            sl_raw = client.place_order(
                symbol=symbol, side=exit_side, order_type="STOP_MARKET",
                quantity=str(quantity), stop_price=str(stop_loss), reduce_only=True,
            )
            results["stop_loss"] = OrderResult(sl_raw)
            logger.info("Stop-loss accepted: %s", results["stop_loss"])
        except BinanceAPIError:
            logger.error("Stop-loss placement failed after entry order was already filled/placed.")
            raise

    if take_profit is not None:
        logger.info("Placing take-profit: symbol=%s side=%s stopPrice=%s", symbol, exit_side, take_profit)
        try:
            tp_raw = client.place_order(
                symbol=symbol, side=exit_side, order_type="STOP_MARKET",
                quantity=str(quantity), stop_price=str(take_profit), reduce_only=True,
            )
            results["take_profit"] = OrderResult(tp_raw)
            logger.info("Take-profit accepted: %s", results["take_profit"])
        except BinanceAPIError:
            logger.error("Take-profit placement failed after entry order was already filled/placed.")
            raise

    return results
