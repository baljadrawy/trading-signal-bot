"""Validation rules for learned gates. Invalid batches must never reach production gates."""
import math

ALLOWED_TRADE_TYPES = {'momentum', 'reversion'}
ALLOWED_TIMEFRAMES = {'15m', '1h', '4h', '1d'}
ALLOWED_MACRO_STATES = {'usdtd_flat', 'usdtd_rising', 'usdtd_rising_fast', 'usdtd_falling'}


def validate_cells(cells, *, trade_count: int, min_cell_n: int) -> list[str]:
    errors = []
    if trade_count <= 0:
        errors.append('trade_count must be positive')
    if not cells:
        errors.append('learning produced no cells')
    seen = set()
    for index, cell in enumerate(cells):
        key = (cell.get('trade_type'), cell.get('macro_state'), cell.get('timeframe'))
        prefix = f'cell[{index}] {key}'
        if key in seen:
            errors.append(f'{prefix}: duplicate key')
        seen.add(key)
        if key[0] not in ALLOWED_TRADE_TYPES:
            errors.append(f'{prefix}: invalid trade_type')
        if key[1] not in ALLOWED_MACRO_STATES:
            errors.append(f'{prefix}: invalid macro_state')
        if key[2] not in ALLOWED_TIMEFRAMES:
            errors.append(f'{prefix}: invalid timeframe')
        n, wr, expectancy, weight = cell.get('n'), cell.get('wr'), cell.get('expectancy'), cell.get('weight')
        if not isinstance(n, int) or n <= 0 or n > trade_count:
            errors.append(f'{prefix}: invalid n')
        if not _finite_between(wr, 0, 100):
            errors.append(f'{prefix}: invalid wr')
        if not _finite_between(expectancy, -100, 100):
            errors.append(f'{prefix}: invalid expectancy')
        if weight not in (0, 0.0, 1, 1.0):
            errors.append(f'{prefix}: weight must be 0 or 1')
        if isinstance(n, int) and n < min_cell_n and weight != 1.0:
            errors.append(f'{prefix}: undersized cell cannot be throttled')
    return errors


def _finite_between(value, lower, upper):
    try:
        number = float(value)
        return math.isfinite(number) and lower <= number <= upper
    except (TypeError, ValueError):
        return False
