"""
algotrader.backtest/cscv.py

Combinatorially Symmetric Cross-Validation (CSCV) per Bailey & Lopez de Prado
(2014).  Estimates the Probability of Backtest Overfitting (PBO) from the
distribution of OOS Sharpe ratios across walk-forward windows.

PBO < 0.40 is required before live activation per spec §9.1.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from algotrader.shared.logger import get_logger

log = get_logger(__name__)


def compute_cscv_pbo(sharpe_variants: list[float]) -> float:
    """
    Compute the Probability of Backtest Overfitting (PBO) via CSCV.

    Algorithm (per Bailey & Lopez de Prado 2014)
    ---------------------------------------------
    For each C(n, n//2) IS/OOS partition of the variant list:
      1. Find the IS-best variant: the index with the highest IS Sharpe.
      2. Rank that variant\'s IS Sharpe value within the OOS distribution
         (fraction of OOS values strictly less than is_best_sharpe).
      3. Compute logit of the rank. logit < 0 means the IS winner performs
         below the OOS median — i.e., the selection was overfit.
    PBO = fraction of partitions where logit < 0.

    Parameters
    ----------
    sharpe_variants : OOS Sharpe ratios from walk-forward windows or
                      parameter configurations.

    Returns
    -------
    float in [0.0, 1.0]. Values above 0.40 block live activation (spec §9.1).
    """
    n = len(sharpe_variants)
    if n < 4:
        log.warning("cscv_insufficient_variants", n=n)
        return 1.0

    arr = np.array(sharpe_variants, dtype=float)
    half = n // 2
    all_idx = list(range(n))
    all_combos = list(combinations(all_idx, half))

    rng = np.random.default_rng(seed=7)
    if len(all_combos) > 1000:
        chosen = rng.choice(len(all_combos), size=1000, replace=False)
        all_combos = [all_combos[i] for i in chosen]

    overfit_count = 0
    total = 0

    for is_idx in all_combos:
        oos_idx = [i for i in all_idx if i not in set(is_idx)]
        if not oos_idx:
            continue

        is_sharpes  = arr[list(is_idx)]
        oos_sharpes = arr[oos_idx]

        # IS-best: position in is_idx with the highest IS Sharpe, mapped back
        # to its global index so we read the same value from arr.
        best_global_idx = is_idx[int(np.argmax(is_sharpes))]
        is_best_sharpe  = arr[best_global_idx]

        # Fraction of OOS values strictly below the IS-best Sharpe.
        oos_rank = float(np.sum(oos_sharpes < is_best_sharpe)) / len(oos_sharpes)

        # Logit transform with boundary clamping so 0.0 and 1.0 do not blow up.
        if oos_rank <= 0.0:
            logit = -10.0
        elif oos_rank >= 1.0:
            logit =  10.0
        else:
            logit = math.log(oos_rank / (1.0 - oos_rank))

        if logit < 0.0:
            overfit_count += 1
        total += 1

    if total == 0:
        return 1.0

    pbo = overfit_count / total
    log.info("cscv_pbo_computed", pbo=round(pbo, 4), n_combos=total)
    return pbo
