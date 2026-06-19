"""Differential privacy with a COMPOSING per-counterparty epsilon budget.

This turns the consent kernel into a quantitative privacy accountant: every
released statistic spends epsilon, the spend COMPOSES across deals with the same
counterparty (persisted via Band Memory), and once the budget is exhausted the
vault is mechanically forced to DECLINE — not an LLM opinion, a math constraint.

Two accountants ship: (1) Laplace with BASIC/SEQUENTIAL composition (epsilon sums
linearly) via ``EpsilonBudget`` — simple and conservative; (2) the Gaussian
mechanism with RÉNYI-DP (RDP) ADVANCED composition via ``RDPBudget`` — composes
additively in RDP space and converts to a much tighter (epsilon, delta) bound, so
the same budget answers more queries.

Deterministic by construction (seeded Laplace) so runs are reproducible and
CI-checkable. Pure: stdlib only, no band import.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional


def _seeded_uniform(seed: str) -> float:
    """Deterministic uniform in (0,1) from a string seed (sha256-based)."""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    # 52 hex chars -> integer in [0, 16^52); normalize to (0,1).
    return (int(h[:13], 16) + 1) / (16 ** 13 + 1)


def laplace_noise(scale: float, seed: str) -> float:
    """Deterministic Laplace(0, scale) sample via inverse-CDF on a seeded uniform."""
    u = _seeded_uniform(seed) - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))


def privatize_count(count: int, *, epsilon: float, sensitivity: float = 1.0, seed: str) -> int:
    """Add calibrated Laplace noise (b = sensitivity/epsilon) to a count; clamp >=0.

    Lower epsilon = more noise = more privacy. seed makes it reproducible.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    scale = sensitivity / epsilon
    noisy = count + laplace_noise(scale, seed)
    return max(0, int(round(noisy)))


# ── Gaussian mechanism + Rényi-DP (RDP) accounting ──────────────────────────
#
# The Laplace path above composes LINEARLY (epsilon sums), which is correct but
# loose. The Gaussian mechanism accounted in Rényi-DP composes ADDITIVELY in RDP
# space and converts to a much tighter (epsilon, delta) bound — the modern
# accountant used by Opacus / TF-Privacy (Mironov, "Rényi Differential Privacy",
# 2017). This lets the SAME privacy budget answer more queries than linear
# composition would, while keeping the forced-decline-on-exhaustion guarantee.

def _seeded_gaussian(seed: str) -> float:
    """Deterministic standard normal N(0,1) via Box-Muller on two seeded uniforms."""
    u1 = _seeded_uniform(seed + ":g1")
    u2 = _seeded_uniform(seed + ":g2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def gaussian_noise(sigma: float, seed: str) -> float:
    """Deterministic N(0, sigma^2) sample."""
    return sigma * _seeded_gaussian(seed)


def privatize_count_gaussian(count: int, *, sigma: float, sensitivity: float = 1.0, seed: str) -> int:
    """Add Gaussian noise with std = sigma*sensitivity to a count; clamp >=0."""
    if sigma <= 0:
        raise ValueError("sigma (noise multiplier) must be > 0")
    return max(0, int(round(count + gaussian_noise(sigma * sensitivity, seed))))


# Standard RDP order grid (as used by production DP accountants).
RDP_ORDERS: tuple[float, ...] = (1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0,
                                 6.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0)


def rdp_gaussian(alpha: float, noise_multiplier: float) -> float:
    """RDP epsilon at order alpha for one Gaussian-mechanism query.

    For the sensitivity-normalized Gaussian mechanism with noise multiplier
    sigma (= noise_std / sensitivity), the (alpha)-RDP is alpha / (2 * sigma^2).
    """
    if noise_multiplier <= 0:
        raise ValueError("noise_multiplier must be > 0")
    return alpha / (2.0 * noise_multiplier ** 2)


def rdp_to_dp(rdp_by_order: dict, delta: float) -> float:
    """Convert an RDP curve {alpha: rdp_eps} to (epsilon, delta)-DP.

    epsilon(delta) = min over alpha>1 of [ rdp_eps(alpha) + ln(1/delta)/(alpha-1) ].
    """
    if not 0 < delta < 1:
        raise ValueError("delta must be in (0,1)")
    best = float("inf")
    for alpha, rdp in rdp_by_order.items():
        if alpha <= 1:
            continue
        eps = rdp + math.log(1.0 / delta) / (alpha - 1.0)
        best = min(best, eps)
    return best


class RDPAccountant:
    """Composes Gaussian-mechanism queries in Rényi-DP and reports (epsilon, delta).

    Composition is ADDITIVE per order (the RDP advantage): k queries at noise
    multiplier sigma accumulate k * alpha/(2 sigma^2) at each order alpha, then the
    tightest (epsilon, delta) is taken across orders. Far below linear epsilon-sum.
    """

    def __init__(self, orders: tuple = RDP_ORDERS) -> None:
        self.orders = orders
        self._rdp: dict = {a: 0.0 for a in orders}

    def compose(self, noise_multiplier: float, count: int = 1) -> None:
        for a in self.orders:
            self._rdp[a] += count * rdp_gaussian(a, noise_multiplier)

    def spent_epsilon(self, delta: float) -> float:
        return rdp_to_dp(self._rdp, delta)


class RDPBudget:
    """A per-counterparty (epsilon, delta) budget under RDP composition.

    Like ``EpsilonBudget`` but with advanced (Rényi) composition: a query is
    charged as a Gaussian noise multiplier; if accepting it would push the spent
    (epsilon, delta) over the cap, the charge is REFUSED and the vault must
    DECLINE. ``load``/``store`` persist per-counterparty RDP curves across deals.
    """

    def __init__(self, epsilon: float, *, delta: float = 1e-5,
                 orders: tuple = RDP_ORDERS,
                 load: Optional[callable] = None, store: Optional[callable] = None) -> None:
        self.epsilon = epsilon
        self.delta = delta
        self.orders = orders
        self._load = load
        self._store = store
        self._mem: dict = {}

    def _curve(self, cp: str) -> dict:
        if self._load is not None:
            v = self._load(cp)
            if v is not None:
                return {float(a): float(e) for a, e in dict(v).items()}
        return dict(self._mem.get(cp, {a: 0.0 for a in self.orders}))

    def _save(self, cp: str, curve: dict) -> None:
        self._mem[cp] = curve
        if self._store is not None:
            self._store(cp, curve)

    def spent(self, counterparty: str) -> float:
        return rdp_to_dp(self._curve(counterparty), self.delta)

    def charge(self, counterparty: str, noise_multiplier: float) -> dict:
        """Try to spend one Gaussian query (given its noise multiplier).

        Returns {allowed, spent_epsilon, remaining, reason}. If the post-charge
        epsilon would exceed the cap, nothing is spent and allowed=False.
        """
        if noise_multiplier <= 0:
            return {"allowed": False, "spent_epsilon": self.spent(counterparty),
                    "remaining": 0.0, "reason": "noise_multiplier must be > 0"}
        curve = self._curve(counterparty)
        trial = {a: curve.get(a, 0.0) + rdp_gaussian(a, noise_multiplier) for a in self.orders}
        new_eps = rdp_to_dp(trial, self.delta)
        if new_eps > self.epsilon + 1e-12:
            return {"allowed": False, "spent_epsilon": round(self.spent(counterparty), 6),
                    "remaining": round(self.epsilon - self.spent(counterparty), 6),
                    "reason": f"RDP budget exhausted (would reach epsilon={round(new_eps,4)} > "
                              f"cap {self.epsilon} at delta={self.delta})"}
        self._save(counterparty, trial)
        return {"allowed": True, "spent_epsilon": round(new_eps, 6),
                "remaining": round(self.epsilon - new_eps, 6), "reason": "charged"}


@dataclass
class BudgetState:
    counterparty: str
    total_epsilon: float
    spent_epsilon: float = 0.0

    @property
    def remaining(self) -> float:
        return round(self.total_epsilon - self.spent_epsilon, 6)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 1e-9


class EpsilonBudget:
    """A composing DP budget per counterparty, optionally persisted across deals.

    ``store``/``load`` callables let it ride on Band Memory (or any KV) so the
    spend COMPOSES across separate negotiations with the same counterparty — the
    feature that makes exhaustion (and the forced decline) real over time.
    """

    def __init__(self, total_epsilon: float = 3.0, *,
                 load: Optional[callable] = None, store: Optional[callable] = None) -> None:
        self.total_epsilon = total_epsilon
        self._load = load
        self._store = store
        self._mem: dict[str, float] = {}

    def _get_spent(self, cp: str) -> float:
        if self._load is not None:
            v = self._load(cp)
            if v is not None:
                return float(v)
        return self._mem.get(cp, 0.0)

    def _set_spent(self, cp: str, spent: float) -> None:
        self._mem[cp] = spent
        if self._store is not None:
            self._store(cp, spent)

    def state(self, counterparty: str) -> BudgetState:
        return BudgetState(counterparty, self.total_epsilon, self._get_spent(counterparty))

    def can_afford(self, counterparty: str, epsilon: float) -> bool:
        return self.state(counterparty).remaining + 1e-9 >= epsilon

    def charge(self, counterparty: str, epsilon: float) -> dict:
        """Try to spend epsilon. Returns {allowed, remaining, reason}.

        If it would exceed the budget, the charge is REFUSED (allowed=False) and
        nothing is spent — the caller must DECLINE the query.
        """
        st = self.state(counterparty)
        if epsilon <= 0:
            return {"allowed": False, "remaining": st.remaining, "reason": "epsilon must be > 0"}
        if st.remaining + 1e-9 < epsilon:
            return {"allowed": False, "remaining": st.remaining,
                    "reason": f"privacy budget exhausted (need {epsilon}, have {st.remaining})"}
        self._set_spent(counterparty, st.spent_epsilon + epsilon)
        return {"allowed": True, "remaining": self.state(counterparty).remaining, "reason": "charged"}
