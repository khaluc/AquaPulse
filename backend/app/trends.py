"""Report trends (flow step AB, plan section 15): is an area getting more reports?

The plan's rule - "increasing" when this week is at least 50% above last week - fires
on noise at the counts a pilot will see: 1 -> 2 reports is +100%, and a fair coin
splitting 3 reports between two weeks produces that half the time. Even the plan's
own example, 4 -> 9 (+125%), happens by chance 13% of the time.

So the percentage stays (it is what people understand), and a one-sided binomial test
says whether the change is bigger than chance: if the underlying rate did not change,
each of the n reports is equally likely to fall in either week. Three outcomes are
kept apart instead of one "increasing":

    increasing           +50% or more, and p <= 0.05
    possibly_increasing  +50% or more, but still plausible as chance
    insufficient_data    too few reports to say anything

Isolation Forest (also in section 15) needs months of daily history plus rainfall
data; neither exists yet, so it is not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb

INCREASE_THRESHOLD = 0.5  # the plan's +50%
SIGNIFICANCE = 0.05
MIN_REPORTS = 6  # both windows together; below this any percentage is noise

LABELS = {
    "increasing": "Tăng rõ",
    "possibly_increasing": "Có thể đang tăng, chưa chắc",
    "decreasing": "Giảm rõ",
    "stable": "Ổn định",
    "insufficient_data": "Chưa đủ dữ liệu",
}


def binomial_tail(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 1/2)."""
    if k <= 0:
        return 1.0
    return sum(comb(n, i) for i in range(k, n + 1)) / 2**n


@dataclass(frozen=True)
class Trend:
    current: int
    previous: int
    increase: float
    p_value: float
    trend: str

    def as_dict(self) -> dict[str, object]:
        return {
            "current": self.current,
            "previous": self.previous,
            "increase": round(self.increase, 3),
            "p_value": round(self.p_value, 4),
            "trend": self.trend,
            "label": LABELS[self.trend],
        }


def classify(current: int, previous: int) -> Trend:
    increase = (current - previous) / max(previous, 1)  # the plan's formula
    n = current + previous
    if n < MIN_REPORTS:
        return Trend(current, previous, increase, 1.0, "insufficient_data")
    if current >= previous:
        p = binomial_tail(current, n)
        if increase >= INCREASE_THRESHOLD:
            return Trend(current, previous, increase, p, "increasing" if p <= SIGNIFICANCE else "possibly_increasing")
        return Trend(current, previous, increase, p, "stable")
    p = binomial_tail(previous, n)
    trend = "decreasing" if p <= SIGNIFICANCE and increase <= -INCREASE_THRESHOLD else "stable"
    return Trend(current, previous, increase, p, trend)
