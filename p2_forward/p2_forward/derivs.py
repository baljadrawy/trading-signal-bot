"""Derivatives capture: architectural scaffold only. DISABLED in P2-E1 (owner D3).

Contains no endpoint, host or URL. Instantiating it while enabled is refused, and config validation already
rejects `derivatives_enabled=true`. A future package must add endpoints under its own authorization.
"""


class DerivativesDisabled(RuntimeError):
    pass


class DerivativesCollector:
    ENABLED = False

    def __init__(self, cfg: dict):
        if cfg.get("derivatives_enabled") or self.ENABLED:
            raise DerivativesDisabled("derivatives capture is not authorized in P2-E1")

    async def run(self) -> None:          # never scheduled in E1
        raise DerivativesDisabled("derivatives capture is not authorized in P2-E1")
