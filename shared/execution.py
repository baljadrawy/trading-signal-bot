"""Execution-price helpers shared by paper/live measurement paths."""


def rebase_long_bracket(
    planned_entry: float, fill_entry: float, target_1: float, target_2: float,
    target_3: float, stop_loss: float,
) -> dict:
    """Move a long bracket to the observed fill while preserving percentage risk/R."""
    values = [planned_entry, fill_entry, target_1, target_2, target_3, stop_loss]
    if any(float(value) <= 0 for value in values):
        raise ValueError("execution bracket prices must be positive")
    if not stop_loss < planned_entry < target_1 < target_2 < target_3:
        raise ValueError("invalid planned long bracket")
    scale = float(fill_entry) / float(planned_entry)
    return {
        "entry_price": round(float(fill_entry), 8),
        "target_1": round(float(target_1) * scale, 8),
        "target_2": round(float(target_2) * scale, 8),
        "target_3": round(float(target_3) * scale, 8),
        "stop_loss": round(float(stop_loss) * scale, 8),
    }
