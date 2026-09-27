"""Optional protection preventing accidental HOLDOUT consumption."""


def allow_partition(partition: str, *, purpose: str, unlock_holdout: bool = False) -> None:
    p = partition.upper()
    if p == "HOLDOUT" and not unlock_holdout:
        raise PermissionError(f"HOLDOUT_LOCKED_FOR_{purpose.upper()}")
    if p not in {"DISCOVERY", "VALIDATION", "HOLDOUT", "UNASSIGNED"}:
        raise ValueError("invalid research partition")
