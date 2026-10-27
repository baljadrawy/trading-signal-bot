"""Alpha budgets: a fixed amount of significance level that tests draw from and can never re-use. Stdlib only.

THE VALUES BELOW ARE OWNER-GOVERNED. They are the latest documented planning values (PROFITABILITY_ROADMAP_2026-10-24
§5.4; EVIDENCE_LADDER_PARAMETERS.md; A30-A33), not validated or binding choices: the calibration level is still
unvalidated (DR-2). Changing them is an owner decision recorded outside this module. The governed constants equal the
S5-PWR-1 power package's (which nothing outside that package may import); tests/test_r2_variant_ledger.py asserts
that the two stay identical.

* Governed admissions: fixed alpha = 1/240 per admission, from a program budget of 12 admissions (FWER 1/20).
* Exploratory family: family-wise alpha = 0.05 split equally across the family (S4 uses 0.05/3 for H1-H3).
  Exploratory alpha never admits a result as confirmation and never draws on the governed budget.
"""
from fractions import Fraction

GOVERNED_ALPHA_PER_ADMISSION = Fraction(1, 240)    # A32 §4 equal split, LATEST_DOCUMENTED (owner-governed)
GOVERNED_PROGRAM_ADMISSIONS = 12                   # A31 §3 / A33 §7, provisional (owner-governed)
GOVERNED_PROGRAM_FWER = Fraction(1, 20)            # A30 §4 union bound (owner-governed)
EXPLORATORY_FAMILY_FWER = Fraction(1, 20)                                                # 0.05 per family
EXPLORATORY_FAMILY_SIZE = 3                                                              # S4 H1-H3


class AlphaBudgetExhausted(Exception):
    """A spend would exceed the budget."""


class AlphaReuseRefused(Exception):
    """A look / label that already spent alpha may not spend it again."""


def _fraction(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, Fraction)):
        raise ValueError(f"{name} must be an int or Fraction (exact arithmetic)")
    v = Fraction(v)
    if not 0 < v < 1:
        raise ValueError(f"{name} must be in (0, 1)")
    return v


class AlphaBudget:
    """Fixed total alpha; each labelled test spends ``per_test`` once. Exact (Fraction) arithmetic throughout."""

    def __init__(self, name, total, per_test, spent_labels=()):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        self.name = name
        self.total = _fraction("total", total)
        self.per_test = _fraction("per_test", per_test)
        if self.per_test > self.total:
            raise ValueError("per_test exceeds total")
        self._labels = []
        for label in spent_labels:            # replay of previously recorded spends, same rules
            self.spend(label)

    @property
    def spent(self) -> Fraction:
        return self.per_test * len(self._labels)

    @property
    def remaining(self) -> Fraction:
        return self.total - self.spent

    @property
    def remaining_tests(self) -> int:
        return int(self.remaining // self.per_test)

    @property
    def labels(self) -> tuple:
        return tuple(self._labels)

    def spend(self, label) -> Fraction:
        """Spend ``per_test`` for ``label``; returns the alpha the test must use. Refuses re-use and exhaustion."""
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        if label in self._labels:
            raise AlphaReuseRefused(f"{self.name}: {label!r} already spent alpha (no re-use of a spent look)")
        if self.spent + self.per_test > self.total:
            raise AlphaBudgetExhausted(f"{self.name}: budget {self.total} exhausted ({len(self._labels)} spent)")
        self._labels.append(label)
        return self.per_test


def governed_admission_budget(spent_labels=()) -> AlphaBudget:
    """Program budget for governed admissions: 12 x 1/240 = 1/20 (owner-governed, see module docstring)."""
    return AlphaBudget("governed-admissions", GOVERNED_ALPHA_PER_ADMISSION * GOVERNED_PROGRAM_ADMISSIONS,
                       GOVERNED_ALPHA_PER_ADMISSION, spent_labels)


def exploratory_family_budget(family, family_size=EXPLORATORY_FAMILY_SIZE, family_fwer=EXPLORATORY_FAMILY_FWER,
                              spent_labels=()) -> AlphaBudget:
    """Exploratory family budget: ``family_fwer`` split equally across ``family_size`` tests (default 0.05/3)."""
    if isinstance(family_size, bool) or not isinstance(family_size, int) or family_size < 1:
        raise ValueError("family_size must be an int >= 1")
    fwer = _fraction("family_fwer", family_fwer)
    return AlphaBudget(f"exploratory:{family}", fwer, fwer / family_size, spent_labels)
