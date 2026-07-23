"""
Input validation for order parameters.

Kept independent of Click/argparse so it can be unit-tested or reused
by a different CLI/UI layer later.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_MARKET"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")


class ValidationError(Exception):
    """Raised when user-supplied order parameters are invalid."""


def validate_symbol(symbol: str) -> str:
    if not symbol:
        raise ValidationError("Symbol is required (e.g. BTCUSDT).")
    symbol = symbol.strip().upper()
    if not SYMBOL_PATTERN.match(symbol):
        raise ValidationError(
            f"Invalid symbol format: '{symbol}'. Expected something like 'BTCUSDT'."
        )
    return symbol


def validate_side(side: str) -> str:
    side = (side or "").strip().upper()
    if side not in VALID_SIDES:
        raise ValidationError(f"Invalid side '{side}'. Must be one of {sorted(VALID_SIDES)}.")
    return side


def validate_order_type(order_type: str) -> str:
    order_type = (order_type or "").strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ValidationError(
            f"Invalid order type '{order_type}'. Must be one of {sorted(VALID_ORDER_TYPES)}."
        )
    return order_type


def validate_quantity(quantity) -> Decimal:
    try:
        qty = Decimal(str(quantity))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Quantity must be a number, got '{quantity}'.")
    if qty <= 0:
        raise ValidationError("Quantity must be greater than 0.")
    return qty


def validate_price(price, order_type: str) -> Optional[Decimal]:
    if order_type == "LIMIT":
        if price is None:
            raise ValidationError("Price is required for LIMIT orders.")
        try:
            p = Decimal(str(price))
        except (InvalidOperation, ValueError):
            raise ValidationError(f"Price must be a number, got '{price}'.")
        if p <= 0:
            raise ValidationError("Price must be greater than 0.")
        return p

    # MARKET and STOP_MARKET orders ignore the regular `price` field
    # (STOP_MARKET uses stopPrice instead, validated separately).
    if price is not None:
        raise ValidationError(f"Price must not be supplied for {order_type} orders.")
    return None


def validate_stop_price(stop_price, order_type: str) -> Optional[Decimal]:
    """Validate the trigger price for STOP_MARKET orders."""
    if order_type == "STOP_MARKET":
        if stop_price is None:
            raise ValidationError("--stop-price is required for STOP_MARKET orders.")
        try:
            sp = Decimal(str(stop_price))
        except (InvalidOperation, ValueError):
            raise ValidationError(f"Stop price must be a number, got '{stop_price}'.")
        if sp <= 0:
            raise ValidationError("Stop price must be greater than 0.")
        return sp

    if stop_price is not None:
        raise ValidationError(f"--stop-price must not be supplied for {order_type} orders.")
    return None


def validate_bracket_price(value, name: str) -> Optional[Decimal]:
    """Validate an optional --stop-loss / --take-profit trigger price."""
    if value is None:
        return None
    try:
        p = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{name} must be a number, got '{value}'.")
    if p <= 0:
        raise ValidationError(f"{name} must be greater than 0.")
    return p


def validate_order_params(symbol: str, side: str, order_type: str, quantity, price,
                           stop_price=None, stop_loss=None, take_profit=None):
    """Validate a full order request. Returns a dict of normalized values.

    stop_price   : trigger price, only for order_type == STOP_MARKET
    stop_loss    : optional bracket stop-loss trigger price, attached to
                   any MARKET/LIMIT entry order
    take_profit  : optional bracket take-profit trigger price, attached to
                   any MARKET/LIMIT entry order
    """
    clean_symbol = validate_symbol(symbol)
    clean_side = validate_side(side)
    clean_type = validate_order_type(order_type)
    clean_qty = validate_quantity(quantity)
    clean_price = validate_price(price, clean_type)
    clean_stop_price = validate_stop_price(stop_price, clean_type)

    clean_stop_loss = validate_bracket_price(stop_loss, "--stop-loss")
    clean_take_profit = validate_bracket_price(take_profit, "--take-profit")

    if clean_type == "STOP_MARKET" and (clean_stop_loss or clean_take_profit):
        raise ValidationError(
            "--stop-loss/--take-profit are for bracketing a MARKET/LIMIT entry order, "
            "not for a STOP_MARKET order itself."
        )

    return {
        "symbol": clean_symbol,
        "side": clean_side,
        "type": clean_type,
        "quantity": clean_qty,
        "price": clean_price,
        "stop_price": clean_stop_price,
        "stop_loss": clean_stop_loss,
        "take_profit": clean_take_profit,
    }
