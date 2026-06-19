"""Tests for differential privacy + composing per-counterparty epsilon budget."""

from __future__ import annotations

from parley.dp import (
    EpsilonBudget,
    RDPAccountant,
    RDPBudget,
    gaussian_noise,
    laplace_noise,
    privatize_count,
    privatize_count_gaussian,
    rdp_gaussian,
    rdp_to_dp,
)


def test_laplace_is_deterministic_for_a_seed():
    assert laplace_noise(2.0, "deal-1:west") == laplace_noise(2.0, "deal-1:west")
    assert laplace_noise(2.0, "a") != laplace_noise(2.0, "b")


def test_privatize_count_is_nonnegative_and_reproducible():
    a = privatize_count(100, epsilon=1.0, seed="s")
    b = privatize_count(100, epsilon=1.0, seed="s")
    assert a == b and a >= 0


def test_lower_epsilon_means_more_noise_on_average():
    # tighter privacy (small eps) should deviate from the true count more, on avg
    true = 200
    hi_eps = [abs(privatize_count(true, epsilon=5.0, seed=f"h{i}") - true) for i in range(40)]
    lo_eps = [abs(privatize_count(true, epsilon=0.2, seed=f"l{i}") - true) for i in range(40)]
    assert sum(lo_eps) / 40 > sum(hi_eps) / 40


def test_budget_composes_and_exhausts():
    b = EpsilonBudget(total_epsilon=1.0)
    assert b.charge("northwind", 0.4)["allowed"] is True
    assert b.charge("northwind", 0.4)["allowed"] is True   # 0.8 spent
    r = b.charge("northwind", 0.4)                          # would be 1.2 > 1.0
    assert r["allowed"] is False and "exhausted" in r["reason"]
    # a different counterparty has its own fresh budget
    assert b.charge("acme", 0.9)["allowed"] is True


def test_budget_persists_across_deals_via_store_load():
    store: dict = {}
    def load(cp): return store.get(cp)
    def save(cp, v): store[cp] = v
    b1 = EpsilonBudget(total_epsilon=1.0, load=load, store=save)
    b1.charge("northwind", 0.7)
    # a NEW budget object (next deal) sees the prior spend and refuses to overspend
    b2 = EpsilonBudget(total_epsilon=1.0, load=load, store=save)
    assert b2.state("northwind").spent_epsilon == 0.7
    assert b2.charge("northwind", 0.5)["allowed"] is False


# ── Gaussian mechanism + Rényi-DP (advanced composition) ────────────────────

def test_gaussian_noise_deterministic_and_count_clamped():
    assert gaussian_noise(2.0, "s") == gaussian_noise(2.0, "s")
    assert privatize_count_gaussian(50, sigma=1.0, seed="s") >= 0


def test_rdp_gaussian_known_value():
    # alpha/(2 sigma^2): at sigma=1, alpha=2 -> 1.0
    assert abs(rdp_gaussian(2.0, 1.0) - 1.0) < 1e-12
    # more noise (larger sigma) -> smaller RDP at the same order
    assert rdp_gaussian(2.0, 4.0) < rdp_gaussian(2.0, 1.0)


def test_rdp_to_dp_is_positive_and_shrinks_with_more_noise():
    curve_noisy = {a: rdp_gaussian(a, 8.0) for a in (2, 4, 8, 16, 32)}
    curve_sharp = {a: rdp_gaussian(a, 2.0) for a in (2, 4, 8, 16, 32)}
    eps_noisy = rdp_to_dp(curve_noisy, 1e-5)
    eps_sharp = rdp_to_dp(curve_sharp, 1e-5)
    assert eps_noisy > 0 and eps_sharp > eps_noisy  # less noise = more epsilon spent


def test_rdp_advanced_composition_beats_linear():
    # The whole point: composing k Gaussian queries in RDP grows the epsilon
    # SUB-linearly vs k * (single-query epsilon). Verify k=16 < 16 * (k=1).
    acc1 = RDPAccountant(); acc1.compose(noise_multiplier=4.0, count=1)
    accK = RDPAccountant(); accK.compose(noise_multiplier=4.0, count=16)
    eps1 = acc1.spent_epsilon(1e-5)
    epsK = accK.spent_epsilon(1e-5)
    assert epsK < 16 * eps1  # advanced composition is tighter than linear sum


def test_rdp_budget_forces_decline_on_exhaustion():
    b = RDPBudget(epsilon=2.0, delta=1e-5)
    allowed = 0
    for i in range(100):
        r = b.charge("northwind", noise_multiplier=4.0)
        if r["allowed"]:
            allowed += 1
        else:
            assert "exhausted" in r["reason"]
            break
    assert 0 < allowed < 100                       # some fit, then it mechanically refuses
    assert b.spent("northwind") <= 2.0 + 1e-9      # never exceeds the cap


def test_rdp_budget_persists_across_deals():
    store: dict = {}
    b1 = RDPBudget(epsilon=2.0, load=lambda cp: store.get(cp), store=lambda cp, v: store.__setitem__(cp, v))
    b1.charge("northwind", 4.0)
    spent1 = b1.spent("northwind")
    b2 = RDPBudget(epsilon=2.0, load=lambda cp: store.get(cp), store=lambda cp, v: store.__setitem__(cp, v))
    assert abs(b2.spent("northwind") - spent1) < 1e-9  # next deal sees prior spend
