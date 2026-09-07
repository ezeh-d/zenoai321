"""Read-only demo identity validation; no SDK import or order transport."""
import re


def verify_demo(sdk, login: int, server: str) -> dict:
    """Check actual connected identity, exposing no raw account or SDK errors.

    Caller owns connection lifecycle and deadline. This verifier is not an
    execution authorization; identity must be rechecked before any future order.
    """
    def failure(code):
        return {"ok": False, "mode": "PAPER", "demo_verified": False, "error": code}

    if type(login) is not int or login <= 0 or not isinstance(server, str) or not server.strip():
        return failure("INVALID_CONFIGURATION")
    try:
        info = sdk.account_info()
        if info is None:
            return failure("ACCOUNT_UNAVAILABLE")
        mode = info.trade_mode
        if type(mode) is not int or mode != sdk.ACCOUNT_TRADE_MODE_DEMO:
            return failure("NOT_DEMO")
        if type(info.login) is not int or info.login != login or info.server != server:
            return failure("ACCOUNT_MISMATCH")
        currency = info.currency
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            return failure("INVALID_ACCOUNT_METADATA")
        return {"ok": True, "mode": "PAPER", "demo_verified": True, "currency": currency}
    except Exception:
        # SDK errors can contain credentials, terminal paths or personal data.
        return failure("ACCOUNT_UNAVAILABLE")
