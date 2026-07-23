"""
Thin wrapper around the Binance USDT-M Futures Testnet REST API.

Handles request signing, HTTP calls, retries on transient network errors,
and translation of API/HTTP errors into a single BinanceAPIError so the
CLI layer only has to deal with one exception type.
"""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests

logger = logging.getLogger("trading_bot.client")

DEFAULT_BASE_URL = "https://testnet.binancefuture.com"
RECV_WINDOW_MS = 5000
REQUEST_TIMEOUT_S = 10
MAX_RETRIES = 3
RETRY_BACKOFF_S = 1.5


class BinanceAPIError(Exception):
    """Raised for any failure talking to the Binance Futures API.

    Wraps both API-level errors (HTTP 4xx/5xx with a Binance error code)
    and network-level failures (timeouts, connection errors).
    """

    def __init__(self, message: str, status_code: int = None, binance_code: int = None):
        super().__init__(message)
        self.status_code = status_code
        self.binance_code = binance_code


class BinanceFuturesClient:
    """Minimal signed REST client for Binance Futures Testnet (USDT-M)."""

    def __init__(self, api_key: str, api_secret: str, base_url: str = DEFAULT_BASE_URL):
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret are required.")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    # -- internals ---------------------------------------------------------

    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = RECV_WINDOW_MS
        query_string = urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret, query_string.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    def _request(self, method: str, path: str, params: dict, signed: bool = True) -> dict:
        url = f"{self.base_url}{path}"
        request_params = self._sign(params) if signed else params

        # Never log the API secret or the computed signature
        safe_params = {k: v for k, v in request_params.items() if k != "signature"}
        logger.debug("API request -> %s %s params=%s", method, url, safe_params)

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.request(
                    method, url, params=request_params, timeout=REQUEST_TIMEOUT_S
                )
                logger.debug(
                    "API response <- status=%s body=%s", response.status_code, response.text
                )

                if response.status_code == 200:
                    return response.json()

                # Binance error payloads look like {"code": -1121, "msg": "..."}
                try:
                    err_body = response.json()
                except ValueError:
                    err_body = {"msg": response.text}

                msg = err_body.get("msg", "Unknown error")
                code = err_body.get("code")
                logger.error(
                    "Binance API error: HTTP %s code=%s msg=%s",
                    response.status_code, code, msg,
                )
                raise BinanceAPIError(
                    f"Binance API error {code}: {msg}",
                    status_code=response.status_code,
                    binance_code=code,
                )

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                logger.warning(
                    "Network error on attempt %s/%s: %s", attempt, MAX_RETRIES, exc
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_S * attempt)
                    continue
                logger.error("Network error after %s attempts: %s", MAX_RETRIES, exc)
                raise BinanceAPIError(f"Network error after {MAX_RETRIES} attempts: {exc}") from exc

        # Should not be reachable, but keep a safety net
        raise BinanceAPIError(f"Request failed: {last_error}")

    # -- public endpoints ----------------------------------------------------

    def ping(self) -> dict:
        """Connectivity check (unsigned)."""
        return self._request("GET", "/fapi/v1/ping", {}, signed=False)

    def get_server_time(self) -> dict:
        return self._request("GET", "/fapi/v1/time", {}, signed=False)

    def place_order(self, symbol: str, side: str, order_type: str,
                     quantity: str, price: str = None,
                     stop_price: str = None, reduce_only: bool = False,
                     time_in_force: str = "GTC") -> dict:
        """Place a MARKET, LIMIT, or STOP_MARKET order on USDT-M Futures.

        POST /fapi/v1/order

        stop_price : required for STOP_MARKET (trigger price)
        reduce_only: True for SL/TP orders that should only close an
                     existing position, never open a new one
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        if order_type == "LIMIT":
            params["price"] = price
            params["timeInForce"] = time_in_force
        elif order_type == "STOP_MARKET":
            params["stopPrice"] = stop_price
        if reduce_only:
            params["reduceOnly"] = "true"

        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def get_order(self, symbol: str, order_id: int) -> dict:
        """Query a specific order's status. GET /fapi/v1/order"""
        params = {"symbol": symbol, "orderId": order_id}
        return self._request("GET", "/fapi/v1/order", params, signed=True)
