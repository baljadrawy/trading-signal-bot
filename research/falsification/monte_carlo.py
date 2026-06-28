"""Monte-Carlo resampling of the per-trade return stream (path distribution)."""
import numpy as np
from .metrics import max_drawdown


def monte_carlo(returns, n: int = 10000, seed: int = 0) -> dict:
    r = np.asarray(returns, float)
    if r.size < 5:
        return {"p_profit": float("nan"), "final_p5": float("nan"),
                "final_med": float("nan"), "final_p95": float("nan"),
                "worst_dd": float("nan")}
    rng = np.random.default_rng(seed)
    finals = np.empty(n); dds = np.empty(n)
    for i in range(n):
        s = rng.choice(r, size=r.size, replace=True)
        eq = np.cumprod(1.0 + s)
        finals[i] = eq[-1] - 1.0
        dds[i] = max_drawdown(eq)
    return {
        "p_profit": float(np.mean(finals > 0)),
        "final_p5": float(np.percentile(finals, 5)),
        "final_med": float(np.median(finals)),
        "final_p95": float(np.percentile(finals, 95)),
        "worst_dd": float(np.min(dds)),
    }
