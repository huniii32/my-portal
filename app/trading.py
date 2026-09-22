"""Trading read-only helpers: risk summary, fill/hourly notifications, symbols."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import config as _config
from app.config import TRADING_SYMBOL_NAMES

_FILL_CACHE: tuple[tuple[tuple[str, int, int], tuple[str, int, int]], tuple[dict, ...]] | None = None
_SYMBOL_NAMES_CACHE: tuple[tuple[str, int, int], dict[str, str]] | None = None


def _file_signature(path: Path) -> tuple[str, int, int]:
    """Return a path-aware signature; missing/racing files simply invalidate caches."""
    path = Path(path)
    path_key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return path_key, -1, -1
    return path_key, stat.st_mtime_ns, stat.st_size


def _trading_risk() -> dict | None:
    """곰비용 트레이딩 위험 요약 — 실패 시 None (브리핑 전체는 살린다)."""
    try:
        raw = json.loads(_config.TRADING_RISK_STATUS.read_text())
    except Exception:
        return None
    try:
        alerts = raw.get("alerts") or []
        latest = alerts[-1] if alerts else None
        return {
            "updated": raw.get("updated"),
            "position_count": int(raw.get("position_count") or 0),
            "unrealized": raw.get("unrealized"),
            "alert": (
                {"title": str(latest.get("title", ""))[:60], "message": str(latest.get("message", ""))[:400]}
                if latest
                else None
            ),
        }
    except Exception:
        return None


def _opaque_notification_id(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:16]


def _notification_number(value: object, fallback: object = None) -> str:
    selected = value if value not in (None, "") else fallback
    if selected in (None, "") or isinstance(selected, bool):
        return "정보 없음"
    text = str(selected).strip()
    return text[:24] if text else "정보 없음"


def _notification_price(value: object, fallback: object = None) -> str:
    selected = value if value not in (None, "") else fallback
    if selected in (None, "") or isinstance(selected, bool):
        return "정보 없음"
    try:
        number = Decimal(str(selected).strip().replace(",", ""))
        if not number.is_finite():
            return "정보 없음"
    except (InvalidOperation, ValueError):
        return str(selected).strip()[:24] or "정보 없음"
    if number == number.to_integral_value():
        return f"{number:,.0f}원"
    return f"{number:,.2f}".rstrip("0").rstrip(".") + "원"


def _valid_fill_quantity(value: object) -> bool:
    if value in (None, "") or isinstance(value, bool):
        return False
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return False
    return number.is_finite() and number > 0


def _trading_symbol_names() -> dict[str, str]:
    global _SYMBOL_NAMES_CACHE
    signature = _file_signature(_config.SYMBOL_NAMES_PATH)
    if _SYMBOL_NAMES_CACHE is not None and _SYMBOL_NAMES_CACHE[0] == signature:
        return _SYMBOL_NAMES_CACHE[1].copy()
    try:
        raw = json.loads(_config.SYMBOL_NAMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        raw = {}
    names = {
        str(symbol).strip()[:30]: name.strip()[:60]
        for symbol, name in raw.items()
        if isinstance(symbol, str) and symbol.strip() and isinstance(name, str) and name.strip()
    } if isinstance(raw, dict) else {}
    _SYMBOL_NAMES_CACHE = (signature, names)
    return names.copy()


def _trading_symbol_name(symbol: str, names: dict[str, str] | None = None) -> str:
    names = _trading_symbol_names() if names is None else names
    return names.get(symbol, TRADING_SYMBOL_NAMES.get(symbol, symbol))


_RETURN_PCT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")


def _notification_decimal(value: object) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def _parse_return_pct(text: object) -> Decimal | None:
    """매도 사유의 TAKE/STOP 퍼센트(예: 'TAKE 2.1% >= +2%')에서 손익률을 꺼낸다."""
    if not isinstance(text, str) or not text.strip():
        return None
    match = _RETURN_PCT_RE.search(text)
    if not match:
        return None
    try:
        pct = Decimal(match.group(1))
    except (InvalidOperation, ValueError):
        return None
    if not pct.is_finite() or abs(pct) > 1000:
        return None
    return pct


def _format_return_pct(pct: Decimal | float) -> str:
    return f"{float(pct):+.1f}%"


def _fifo_sell_return_pct(lots: list[list[Decimal]], sell_qty: Decimal | None, sell_avg: Decimal | None) -> Decimal | None:
    """이전 매수 평균가(FIFO) 대비 매도 손익률. 이력이 부족하면 None."""
    if not lots or sell_qty is None or sell_avg is None:
        return None
    remaining = sell_qty
    cost_total = Decimal(0)
    matched_qty = Decimal(0)
    for lot_qty, lot_avg in lots:
        if remaining <= 0:
            break
        take = lot_qty if lot_qty < remaining else remaining
        cost_total += take * lot_avg
        matched_qty += take
        remaining -= take
    if matched_qty <= 0 or remaining > 0:
        return None
    cost_avg = cost_total / matched_qty
    if cost_avg == 0:
        return None
    return (sell_avg - cost_avg) / cost_avg * Decimal(100)


def _consume_fifo_lots(lots: list[list[Decimal]], sell_qty: Decimal | None) -> None:
    if sell_qty is None or sell_qty <= 0:
        return
    remaining = sell_qty
    while lots and remaining > 0:
        lot_qty, _lot_avg = lots[0]
        if lot_qty <= remaining:
            remaining -= lot_qty
            lots.pop(0)
        else:
            lots[0][0] = lot_qty - remaining
            remaining = Decimal(0)


def _trading_fill_notifications() -> list[dict]:
    global _FILL_CACHE
    signature = (_file_signature(_config.LIVE_ORDERS_PATH), _file_signature(_config.SYMBOL_NAMES_PATH))
    if _FILL_CACHE is not None and _FILL_CACHE[0] == signature:
        return [item.copy() for item in _FILL_CACHE[1]]
    fills: list[dict] = []
    seen_ids: set[str] = set()
    submit_metadata: dict[str, dict] = {}
    invalid_order_ids: set[str] = set()
    buy_lots: dict[str, list[list[Decimal]]] = {}
    symbol_names = _trading_symbol_names()
    try:
        handle = _config.LIVE_ORDERS_PATH.open(encoding="utf-8")
    except OSError:
        _FILL_CACHE = (signature, ())
        return fills
    with handle:
        for line in handle:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError, UnicodeError):
                continue
            if not isinstance(record, dict):
                continue

            action = record.get("action")
            order_id_value = record.get("order_id")
            if "order_id" in record and not isinstance(order_id_value, str):
                continue
            order_id = order_id_value.strip() if isinstance(order_id_value, str) else ""
            if len(order_id) > 256:
                continue
            if action == "submit":
                side_value = record.get("side")
                symbol_value = record.get("symbol")
                if not isinstance(side_value, str) or not isinstance(symbol_value, str):
                    continue
                side = side_value.strip().upper()
                symbol = symbol_value.strip()
                if side not in {"BUY", "SELL"} or not symbol or len(symbol) > 30:
                    continue
                if order_id:
                    if order_id not in invalid_order_ids:
                        existing = submit_metadata.get(order_id)
                        if existing is not None and (existing["side"] != side or existing["symbol"] != symbol):
                            submit_metadata.pop(order_id, None)
                            invalid_order_ids.add(order_id)
                        else:
                            metadata = {
                                "side": side,
                                "symbol": symbol,
                                "filled": record.get("filled"),
                                "qty": record.get("qty"),
                                "avg": record.get("avg"),
                                "price": record.get("price"),
                                "limit_price": record.get("limit_price"),
                                "reason": record.get("reason"),
                            }
                            submit_metadata.pop(order_id, None)
                            submit_metadata[order_id] = metadata
                            if len(submit_metadata) > 2048:
                                submit_metadata.pop(next(iter(submit_metadata)))
                if record.get("ok") is not True or record.get("status") != "FILLED":
                    continue
                if side not in {"BUY", "SELL"} or not symbol:
                    continue
                quantity = _notification_number(record.get("filled"), record.get("qty"))
                average = _notification_price(record.get("avg"), record.get("price"))
                seed = order_id or f"{record.get('ts', '')}:{symbol}:{side}"
                fill_qty = _notification_decimal(record.get("filled")) or _notification_decimal(record.get("qty"))
                fill_avg = _notification_decimal(record.get("avg")) or _notification_decimal(record.get("price"))
                fill_reason = record.get("reason")
            elif action == "reconcile" and record.get("status") == "FILLED" and record.get("verified_fill") is True:
                if not order_id or order_id in invalid_order_ids:
                    continue
                metadata = submit_metadata.get(order_id)
                if metadata is None:
                    continue
                side = metadata["side"]
                symbol = metadata["symbol"]
                if side not in {"BUY", "SELL"} or not symbol:
                    continue
                if "side" in record:
                    reconcile_side = record["side"]
                    if not isinstance(reconcile_side, str) or reconcile_side.strip().upper() != side:
                        continue
                if "symbol" in record:
                    reconcile_symbol = record["symbol"]
                    if not isinstance(reconcile_symbol, str) or reconcile_symbol.strip() != symbol:
                        continue
                reconcile_quantity = record.get("filled_qty")
                if record.get("filled_qty_explicit") is True and _valid_fill_quantity(reconcile_quantity):
                    quantity = _notification_number(reconcile_quantity)
                else:
                    quantity = _notification_number(metadata.get("filled"), metadata.get("qty"))
                price_value = next(
                    (value for value in (record.get("avg"), record.get("price"), metadata.get("avg"), metadata.get("price"), metadata.get("limit_price")) if value not in (None, "")),
                    None,
                )
                average = _notification_price(price_value)
                seed = order_id
                if record.get("filled_qty_explicit") is True and _valid_fill_quantity(reconcile_quantity):
                    fill_qty = _notification_decimal(reconcile_quantity)
                else:
                    fill_qty = _notification_decimal(metadata.get("filled")) or _notification_decimal(metadata.get("qty"))
                fill_avg = _notification_decimal(price_value)
                fill_reason = record.get("reason") or metadata.get("reason")
            else:
                continue

            name = _trading_symbol_name(symbol, symbol_names)
            notification_id = _opaque_notification_id("fill", seed)
            if notification_id in seen_ids:
                continue
            seen_ids.add(notification_id)
            if side == "BUY":
                if fill_qty is not None and fill_avg is not None:
                    buy_lots.setdefault(symbol, []).append([fill_qty, fill_avg])
                message = f"{name} {quantity}주 · 평균 {average}"
            else:
                return_pct = _parse_return_pct(fill_reason)
                if return_pct is None:
                    return_pct = _fifo_sell_return_pct(buy_lots.get(symbol, []), fill_qty, fill_avg)
                _consume_fifo_lots(buy_lots.setdefault(symbol, []), fill_qty)
                display = name if name == symbol else f"{name}[{symbol}]"
                base = f"{display} {quantity}주 · 평균 {average}"
                if return_pct is None:
                    message = base
                else:
                    message = f"{base} (손익률 {_format_return_pct(return_pct)})"
            fills.append(
                {
                    "id": notification_id,
                    "type": f"fill_{side.lower()}",
                    "title": "주식 매수 체결" if side == "BUY" else "주식 매도 체결",
                    "message": message,
                }
            )
            if len(fills) > 5:
                fills.pop(0)
    _FILL_CACHE = (signature, tuple(item.copy() for item in fills))
    return [item.copy() for item in _FILL_CACHE[1]]


def _trading_hourly_notifications() -> list[dict]:
    alerts: list[dict] = []
    try:
        raw = json.loads(_config.TRADING_RISK_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return alerts
    records = raw.get("alerts") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        return alerts
    for record in records:
        if not isinstance(record, dict) or record.get("key") != "hourly":
            continue
        timestamp = str(record.get("ts", "")).strip()
        source_title = str(record.get("title") or "정시 트레이딩 보고").strip()[:80]
        detail_value = next(
            (record.get(key) for key in ("detail", "report", "content", "message") if isinstance(record.get(key), str) and record.get(key).strip()),
            "",
        )
        detail = detail_value.strip()[:20_000]
        summary_value = record.get("summary") if isinstance(record.get("summary"), str) else detail
        message = summary_value.strip().splitlines()[0][:180] if summary_value.strip() else ""
        alerts.append(
            {
                "id": _opaque_notification_id("hourly", f"{timestamp}:{source_title}"),
                "type": "hourly",
                "title": "트레이딩 정시 보고",
                "message": message,
                "detail": detail,
            }
        )
        if len(alerts) > 5:
            alerts.pop(0)
    return alerts


def _trading_notifications() -> dict:
    return {"fills": _trading_fill_notifications(), "hourly": _trading_hourly_notifications()}
