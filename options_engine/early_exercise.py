"""Early-exercise diagnostic (exploratory; Research Plan Amendment 8).

Every pricing path in the study is the European closed form: the RV baseline,
M(RV), B1, B2, M(B1), M(B2), the learning targets, and the locked predict path
(the trace is recorded in docs/results/v2/early-exercise-diagnostic.json).
SPY and AAPL options are American. This module measures what that costs:

- the early-exercise premium of every evaluated observation on the CRR tree of
  options_engine.american at the same S, K, T, r, q as the study, at the
  quote's own European implied volatility and at each method's sigma;
- the cancellation test for B1, whose sigma is inverted from a t-1 mid under
  the European formula and repriced under the same formula, against the
  consistent American treatment (invert on the tree, reprice on the tree),
  compared with M(RV), whose sigma does not come from an option price;
- the Design B primary and incremental comparisons restricted to observations
  whose premium is below the quote's tick, on the same folds and bootstrap.

Nothing here touches the locked modules; the study's numbers are not replaced.
The observation exports are streamed in chunks and aggregated incrementally.
"""
from __future__ import annotations

import json
import resource
import shutil
import sys
import time
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from . import __version__
from .carry_inputs import CarryInputs, file_digest
from .compare import BLOCK_LENGTH, REPLICATES, SEED, SENSITIVITY_BLOCKS, block_indices, pair_statistics, percentile_interval
from .live_config import LiveConfig
from .live_utils import atomic_json, clean_json
from .store import ObservationStore

EXPLORATORY = ("Exploratory (Research Plan Amendment 8): specified after an outside review, after every pre-registered result was known; "
               "no reported number is replaced and no claim here is confirmatory.")
STEPS = 200
CHUNKSIZE = 20_000
MATURITY_SPLIT_DAYS = 30.0
REGIMES = ("2020-21 near-zero", "2022 onward")
TERCILE_LABELS = ("low", "middle", "high")
# The study's pricing paths, file and line at the locked commit (docs/LOCK.md); every one is the European closed form.
PRICING_PATHS = {
    "RV baseline": "learning.py:123-128 evaluate(None, frame) -> price_with_volatility (learning.py:110-112, BlackScholesEngine.price, core.py:62); European",
    "M(RV)": "learning.py:123-128 evaluate(model, frame): predict_volatility (learning.py:88-107) then price_with_volatility (learning.py:110-112); European",
    "B1": "baselines.py:52-92 b1_baseline: sigma is the t-1 row's iv_brent_volatility (carry_inputs.py:323, a European inversion) or its strike interpolation "
          "(baselines.py:88); priced by walkforward.py:108 evaluate(None, ...) with baseline_sigma replaced (cli.py --baseline-file); European",
    "B2": "baselines.py:187-217 slice_points/fit_slice fit SVI to European implied volatilities; baselines.py:244 converts back to sigma; priced as B1; European",
    "M(B1)": "walkforward.py:107-109 fit_fold/evaluate on rows whose baseline_sigma is b1_sigma; price_with_volatility; European",
    "M(B2)": "as M(B1) with b2_sigma; European",
    "learning targets": "carry_inputs.py:304-338 apply_carry re-solves iv_brent_volatility with iv.py:21-90 implied_volatility, whose objective is "
                        "BlackScholesEngine.price (iv.py:53-54); learning.py:71 target = log(iv / baseline_sigma); European inversion",
    "locked predict path": "locked.py:205-231 prediction_set: predict_volatility then price_with_volatility (locked.py:229); B1 sigma is the t-1 "
                           "iv_brent_volatility (locked.py:207-208); scoring identification locked.py:395 implied_volatility; European",
    "binomial tree": "american.py:83-91 binomial_analysis is called only by analysis.py:66 at import time (diagnostic columns) and by the "
                     "cli price command (cli.py:234); it enters no study loss",
}


# ----------------------------------------------------------------------------- vector pricing
def bsm_prices(S, K, T, r, q, sigma, is_call):
    """European closed form, vectorized; the same formula as core.BlackScholesEngine.price."""
    S, K, T, r, q, sigma = (np.asarray(x, float) for x in (S, K, T, r, q, sigma))
    is_call = np.asarray(is_call, bool)
    sqrt_t = np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S/K)+(r-q+0.5*sigma*sigma)*T)/(sigma*sqrt_t)
        d2 = d1-sigma*sqrt_t
    call = S*np.exp(-q*T)*ndtr(d1)-K*np.exp(-r*T)*ndtr(d2)
    put = K*np.exp(-r*T)*ndtr(-d2)-S*np.exp(-q*T)*ndtr(-d1)
    return np.where(is_call, call, put)


def tree_prices(S, K, T, r, q, sigma, is_call, steps=STEPS):
    """American and European CRR prices on one tree per row, vectorized over rows; the same tree as american._Tree."""
    S, K, T, r, q, sigma = (np.asarray(x, float) for x in (S, K, T, r, q, sigma))
    is_call = np.asarray(is_call, bool)
    n = int(steps)
    if n < 1 or (T <= 0).any() or (sigma <= 0).any():
        raise ValueError("tree_prices needs steps >= 1, T > 0 and sigma > 0")
    dt = T/n
    up = np.exp(sigma*np.sqrt(dt))
    prob = (np.exp((r-q)*dt)-1/up)/(up-1/up)
    if not ((prob > 0) & (prob < 1)).all():
        raise ValueError("Risk-neutral step probability outside (0, 1); increase steps")
    discount = np.exp(-r*dt)[:, None]
    p = prob[:, None]
    sign = np.where(is_call, 1.0, -1.0)[:, None]
    strike = K[:, None]
    nodes = S[:, None]*np.exp((sigma*np.sqrt(dt))[:, None]*(2*np.arange(n+1)[None, :]-n))
    american = np.maximum(sign*(nodes-strike), 0.0)
    european = american.copy()
    up = up[:, None]
    for step in range(n-1, -1, -1):
        american = discount*(p*american[:, 1:]+(1-p)*american[:, :-1])
        european = discount*(p*european[:, 1:]+(1-p)*european[:, :-1])
        nodes = nodes[:, :step+1]*up
        american = np.maximum(american, sign*(nodes-strike))
    return american[:, 0], european[:, 0]


def invert(price, pricer, low=1e-4, high=10.0, iterations=50, tolerance=1e-9):
    """Bisection for the volatility at which `pricer(sigma)` equals `price`; NaN where the price is not attained. Bounds may be arrays."""
    price = np.asarray(price, float)
    lo = np.broadcast_to(np.asarray(low, float), price.shape).copy()
    hi = np.broadcast_to(np.asarray(high, float), price.shape).copy()
    for _ in range(iterations):
        mid = 0.5*(lo+hi)
        below = pricer(mid) < price
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    sigma = 0.5*(lo+hi)
    residual = np.abs(pricer(sigma)-price)
    return np.where(residual <= tolerance*np.maximum(1.0, price), sigma, np.nan)


def european_iv(mid, S, K, T, r, q, is_call):
    return invert(mid, lambda s: bsm_prices(S, K, T, r, q, s, is_call))


def american_iv(mid, S, K, T, r, q, is_call, steps=STEPS, european=None, iterations=26):
    """Volatility at which the American tree price equals the mid. The American implied volatility lies below the European one, so
    the bracket is [max(0.25, 0.02/sigma_E) x sigma_E, 1.05 x sigma_E] around the European inversion when it is given."""
    if european is None:
        low, high = 0.02, 5.0
        iterations = 32
    else:
        european = np.asarray(european, float)
        low, high = np.maximum(0.25*european, 0.02), 1.05*european
    return invert(mid, lambda s: tree_prices(S, K, T, r, q, s, is_call, steps)[0], low=low, high=high, iterations=iterations, tolerance=1e-6)


# ----------------------------------------------------------------------------- row classification
def tick_size(symbol, mid):
    """Quote increment inferred from the data: AAPL quotes at or above $3 in nickels, everything else in pennies."""
    symbol = np.asarray(symbol).astype(str)
    mid = np.asarray(mid, float)
    return np.where((symbol == "AAPL") & (mid >= 3.0), 0.05, 0.01)


TICK_RULE = ("0.05 for AAPL quotes with mid >= 3, 0.01 otherwise; in set A 98% of AAPL bids and asks at or above $3 are multiples of 0.05 "
             "and SPY quotes are multiples of 0.05 only 20% of the time at every level (the penny-interval program)")


def classify(chunk, moneyness_cuts):
    forward = chunk.spot.to_numpy(float)*np.exp((chunk.r.to_numpy(float)-chunk.q.to_numpy(float))*chunk["T"].to_numpy(float))
    k = np.abs(np.log(chunk.strike.to_numpy(float)/forward))
    tercile = np.where(k <= moneyness_cuts[0], TERCILE_LABELS[0], np.where(k <= moneyness_cuts[1], TERCILE_LABELS[1], TERCILE_LABELS[2]))
    days = chunk.days_to_expiry.to_numpy(float)
    maturity = np.where(days <= MATURITY_SPLIT_DAYS, "<=30d", np.where(days <= 90, "31-90d", ">90d"))
    year = chunk.evaluated_session.str.slice(0, 4).astype(int).to_numpy()
    regime = np.where(year <= 2021, REGIMES[0], REGIMES[1])
    return dict(option_type=chunk.option_type.to_numpy().astype(str), moneyness_tercile=tercile, maturity_bucket=maturity,
                symbol=chunk.symbol.to_numpy().astype(str), regime=regime, year=year.astype(str))


# ----------------------------------------------------------------------------- incremental aggregates
class PremiumAggregate:
    """Premium fractions per sigma variant as float32 vectors over int8 cell codes shared by every variant; quantiles are exact at the end."""

    def __init__(self, names):
        self.names = tuple(names)
        self.fraction = {name: [] for name in self.names}
        self.dollars = {name: [] for name in self.names}
        self.tick, self.codes, self.levels = [], {}, {}

    def add(self, keys, tick, mid, premiums, valid=None):
        """keys: cell name -> labels per row; premiums: variant -> premium in dollars per row; valid: variant -> usable-row mask."""
        self.tick.append(np.asarray(tick, np.float32))
        mid = np.asarray(mid, float)
        for name in self.names:
            dollars = np.asarray(premiums[name], float)
            if valid is not None and name in valid:
                dollars = np.where(valid[name], dollars, np.nan)
            self.dollars[name].append(dollars.astype(np.float32))
            self.fraction[name].append((dollars/mid).astype(np.float32))
        for key, values in keys.items():
            levels = self.levels.setdefault(key, {})
            unique, inverse = np.unique(np.asarray(values), return_inverse=True)
            mapping = np.array([levels.setdefault(str(level), len(levels)) for level in unique], np.int8)
            self.codes.setdefault(key, []).append(mapping[inverse])

    def finish(self):
        tick = np.concatenate(self.tick) if self.tick else np.zeros(0, np.float32)
        codes = {key: np.concatenate(values) for key, values in self.codes.items()}
        out = {}
        for name in self.names:
            fraction = np.concatenate(self.fraction[name]) if self.fraction[name] else np.zeros(0, np.float32)
            dollars = np.concatenate(self.dollars[name]) if self.dollars[name] else np.zeros(0, np.float32)
            usable = np.isfinite(fraction)
            table = dict(overall=premium_stats(fraction[usable], dollars[usable], tick[usable]))
            for key, levels in self.levels.items():
                table[f"by_{key}"] = {}
                for level, code in sorted(levels.items()):
                    mask = usable & (codes[key] == code)
                    table[f"by_{key}"][level] = premium_stats(fraction[mask], dollars[mask], tick[mask])
            out[name] = table
        return out


def premium_stats(fraction, dollars, tick):
    fraction = np.asarray(fraction, float)
    if fraction.size == 0:
        return dict(n=0)
    q = np.quantile(fraction, [.5, .9, .99])
    return dict(n=int(fraction.size), mean=float(fraction.mean()), median=float(q[0]), p90=float(q[1]), p99=float(q[2]), max=float(fraction.max()),
                share_exceeding_tick=float((dollars > tick).mean()), share_exceeding_half_tick=float((dollars > 0.5*tick).mean()),
                mean_dollars=float(np.asarray(dollars, float).mean()))


class SessionSums:
    """Per-session sums of squared spot-normalized errors for several methods, full and restricted."""

    def __init__(self, methods):
        self.methods = tuple(methods)
        self.sums, self.counts = {}, {}

    def add(self, sessions, errors, mask=None):
        mask = np.ones(len(sessions), bool) if mask is None else np.asarray(mask, bool)
        frame = pd.DataFrame({m: np.where(mask, np.asarray(errors[m], float)**2, 0.0) for m in self.methods})
        frame["_n"] = mask.astype(int)
        grouped = frame.groupby(np.asarray(sessions)).sum()
        for session, row in grouped.iterrows():
            self.counts[session] = self.counts.get(session, 0)+int(row["_n"])
            sums = self.sums.setdefault(session, dict.fromkeys(self.methods, 0.0))
            for m in self.methods:
                sums[m] += float(row[m])

    def losses(self):
        sessions = sorted(s for s, n in self.counts.items() if n > 0)
        return sessions, {m: np.array([self.sums[s][m]/self.counts[s] for s in sessions]) for m in self.methods}, np.array([self.counts[s] for s in sessions])


# ----------------------------------------------------------------------------- store lookups for the cancellation test
class PriorQuotes:
    """Eligible store rows of a session keyed by (symbol, contract), fetched once per session; the carry at t-1 under the locked configuration."""

    def __init__(self, config_path):
        config, root = LiveConfig.load(config_path)
        self.store = ObservationStore(root)
        self.carry = CarryInputs.from_config(config)
        self.cache, self.rates, self.yields = {}, {}, {}

    def lookup(self, session):
        if session not in self.cache:
            with closing(self.store.connect()) as db:
                records = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM observations WHERE session_date=? AND training_eligible=1", (session,))]
            table = {}
            for row in records:
                table.setdefault((row["symbol"], row["contractSymbol"]), (float(row["mid"]), float(row["spot"]), float(row["T"])))
            if len(self.cache) >= 8:
                self.cache.pop(next(iter(self.cache)))
            self.cache[session] = table
        return self.cache[session]

    def carry_at(self, session, symbol):
        if session not in self.rates:
            self.rates[session] = float(self.carry.rate_for(session))
        if (session, symbol) not in self.yields:
            self.yields[(session, symbol)] = float(self.carry.yield_for(symbol, session))
        return self.rates[session], self.yields[(session, symbol)]


def read_b1_sources(baselines_path, chunksize=CHUNKSIZE):
    """observation_id -> (prior_session, b1_source) from the baselines table, streamed."""
    sources = {}
    for chunk in pd.read_csv(baselines_path, usecols=["observation_id", "prior_session", "b1_source"], chunksize=chunksize):
        sources.update(zip(chunk.observation_id, zip(chunk.prior_session, chunk.b1_source, strict=True), strict=True))
    return sources


# ----------------------------------------------------------------------------- the diagnostic
def read_moneyness_cuts(breakdowns_path):
    return tuple(json.loads(Path(breakdowns_path).read_text())["cut_points"]["moneyness_terciles"])


def chunk_inputs(chunk):
    return (chunk.spot.to_numpy(float), chunk.strike.to_numpy(float), chunk["T"].to_numpy(float), chunk.r.to_numpy(float), chunk.q.to_numpy(float),
            (chunk.option_type.to_numpy() == "call"))


def run_diagnostic(config_path, set_a, set_b_rv, set_b_b1, baselines_path, comparison_path, breakdowns_path, out_path, steps=STEPS, chunksize=CHUNKSIZE,
                   replicates=REPLICATES, prior_quotes=None):
    """Stream the three prediction files and write docs/results/v2/early-exercise-diagnostic.json."""
    started = time.perf_counter()
    cuts = read_moneyness_cuts(breakdowns_path)
    timing = {}
    # ---- set A: premium at the quote's implied volatility and at each method's sigma
    t0 = time.perf_counter()
    agg_a = PremiumAggregate(("iv", "rv", "m_rv"))
    rows_a = unidentified_a = 0
    sessions_a = set()
    for chunk in pd.read_csv(set_a, compression="gzip", chunksize=chunksize):
        S, K, T, r, q, is_call = chunk_inputs(chunk)
        mid = chunk.mid.to_numpy(float)
        keys = classify(chunk, cuts)
        tick = tick_size(keys["symbol"], mid)
        sigma_iv = european_iv(mid, S, K, T, r, q, is_call)
        ok = np.isfinite(sigma_iv)
        unidentified_a += int((~ok).sum())
        premiums = {}
        for name, sigma in (("iv", np.where(ok, sigma_iv, chunk.baseline_sigma.to_numpy(float))), ("rv", chunk.baseline_sigma.to_numpy(float)),
                            ("m_rv", chunk.model_sigma.to_numpy(float))):
            american, european = tree_prices(S, K, T, r, q, sigma, is_call, steps)
            premiums[name] = np.maximum(american-european, 0.0)
        agg_a.add(keys, tick, mid, premiums, valid=dict(iv=ok))
        rows_a += len(chunk)
        sessions_a.update(chunk.evaluated_session.unique())
    set_a_result = dict(rows=rows_a, sessions=len(sessions_a), unidentified_european_iv=unidentified_a, premium=agg_a.finish())
    timing["set_a_seconds"] = round(time.perf_counter()-t0, 1)

    # ---- set B: premiums, the tick-restricted losses, and the cancellation test on same-contract B1 rows
    t0 = time.perf_counter()
    sources = read_b1_sources(baselines_path, chunksize)
    quotes = prior_quotes or PriorQuotes(config_path)
    agg_b = PremiumAggregate(("iv", "rv", "m_rv", "b1", "m_b1"))
    sums = SessionSums(("rv", "m_rv", "b1", "m_b1"))
    kept = SessionSums(("rv", "m_rv", "b1", "m_b1"))
    cancel = SessionSums(("b1_european", "b1_tree", "m_rv_european", "m_rv_tree", "rv_european", "rv_tree", "m_b1_european", "m_b1_tree"))
    rows_b = unidentified_b = same_contract = prior_missing = reinversion_mismatch = tree_unidentified = 0
    reinversion_max_abs = 0.0
    kept_rows = 0
    reader_rv = pd.read_csv(set_b_rv, compression="gzip", chunksize=chunksize)
    reader_b1 = pd.read_csv(set_b_b1, compression="gzip", chunksize=chunksize)
    for chunk, chunk_b1 in zip(reader_rv, reader_b1, strict=True):
        if not (chunk.observation_id.to_numpy() == chunk_b1.observation_id.to_numpy()).all():
            raise ValueError("The two set B prediction files are not row-aligned")
        S, K, T, r, q, is_call = chunk_inputs(chunk)
        mid = chunk.mid.to_numpy(float)
        keys = classify(chunk, cuts)
        tick = tick_size(keys["symbol"], mid)
        sigma_iv = european_iv(mid, S, K, T, r, q, is_call)
        ok = np.isfinite(sigma_iv)
        unidentified_b += int((~ok).sum())
        sigmas = dict(iv=np.where(ok, sigma_iv, chunk.baseline_sigma.to_numpy(float)), rv=chunk.baseline_sigma.to_numpy(float), m_rv=chunk.model_sigma.to_numpy(float),
                      b1=chunk_b1.baseline_sigma.to_numpy(float), m_b1=chunk_b1.model_sigma.to_numpy(float))
        tree, premiums = {}, {}
        for name, sigma in sigmas.items():
            american, european = tree_prices(S, K, T, r, q, sigma, is_call, steps)
            tree[name] = american
            premiums[name] = np.maximum(american-european, 0.0)
        agg_b.add(keys, tick, mid, premiums, valid=dict(iv=ok))
        premium_iv = premiums["iv"]
        errors = dict(rv=(chunk.baseline_price.to_numpy(float)-mid)/S, m_rv=(chunk.model_price.to_numpy(float)-mid)/S,
                      b1=(chunk_b1.baseline_price.to_numpy(float)-mid)/S, m_b1=(chunk_b1.model_price.to_numpy(float)-mid)/S)
        sessions = chunk.evaluated_session.to_numpy()
        sums.add(sessions, errors)
        below_tick = ok & (premium_iv <= tick)
        kept_rows += int(below_tick.sum())
        kept.add(sessions, errors, below_tick)
        # cancellation: same-contract rows only, where B1 is exactly the European inversion of the same contract's t-1 mid
        info = [sources.get(oid, (None, None)) for oid in chunk.observation_id]
        same = np.array([src == "same_contract" for _, src in info])
        same_contract += int(same.sum())
        if same.any():
            prior_mid, prior_spot, prior_T, prior_r, prior_q = (np.full(len(chunk), np.nan) for _ in range(5))
            contracts = chunk.contractSymbol.to_numpy()
            symbols = keys["symbol"]
            for index in np.flatnonzero(same):
                prior_session = info[index][0]
                match = quotes.lookup(prior_session).get((symbols[index], contracts[index]))
                if match is None:
                    prior_missing += 1
                    continue
                prior_mid[index], prior_spot[index], prior_T[index] = match
                prior_r[index], prior_q[index] = quotes.carry_at(prior_session, symbols[index])
            have = same & np.isfinite(prior_mid)
            if have.any():
                idx = np.flatnonzero(have)
                sigma_e = european_iv(prior_mid[idx], prior_spot[idx], K[idx], prior_T[idx], prior_r[idx], prior_q[idx], is_call[idx])
                diff = np.abs(sigma_e-sigmas["b1"][idx])
                reinversion_max_abs = max(reinversion_max_abs, float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.0)
                reinversion_mismatch += int((~np.isfinite(diff) | (diff > 1e-6)).sum())
                sigma_a = american_iv(prior_mid[idx], prior_spot[idx], K[idx], prior_T[idx], prior_r[idx], prior_q[idx], is_call[idx], steps, european=np.where(np.isfinite(sigma_e), sigma_e, sigmas["b1"][idx]))
                usable = np.isfinite(sigma_a)
                if usable.any():
                    # identifiability on the tree: where the American price sits at intrinsic it does not move with sigma, and no volatility is implied
                    sub = idx[usable]
                    bump = 0.05*sigma_a[usable]
                    upper = tree_prices(prior_spot[sub], K[sub], prior_T[sub], prior_r[sub], prior_q[sub], sigma_a[usable]+bump, is_call[sub], steps)[0]
                    lower = tree_prices(prior_spot[sub], K[sub], prior_T[sub], prior_r[sub], prior_q[sub], sigma_a[usable]-bump, is_call[sub], steps)[0]
                    flat = (upper-lower) <= 1e-6*np.maximum(1.0, prior_mid[sub])
                    tree_unidentified += int(flat.sum())
                    usable[np.flatnonzero(usable)[flat]] = False
                idx = idx[usable]
                b1_tree, _ = tree_prices(S[idx], K[idx], T[idx], r[idx], q[idx], sigma_a[usable], is_call[idx], steps)
                cancel_errors = dict(b1_european=errors["b1"][idx], b1_tree=(b1_tree-mid[idx])/S[idx],
                                     m_rv_european=errors["m_rv"][idx], m_rv_tree=(tree["m_rv"][idx]-mid[idx])/S[idx],
                                     rv_european=errors["rv"][idx], rv_tree=(tree["rv"][idx]-mid[idx])/S[idx],
                                     m_b1_european=errors["m_b1"][idx], m_b1_tree=(tree["m_b1"][idx]-mid[idx])/S[idx])
                cancel.add(sessions[idx], cancel_errors)
        rows_b += len(chunk)
    timing["set_b_seconds"] = round(time.perf_counter()-t0, 1)

    # ---- sensitivity: the pre-registered pairs on the full rows (a check) and on the below-tick rows
    t0 = time.perf_counter()
    comparison = json.loads(Path(comparison_path).read_text())
    full_sessions, full_losses, _ = sums.losses()
    kept_sessions, kept_losses, kept_counts = kept.losses()
    sensitivity = dict(rule="observations whose early-exercise premium at the quote's European implied volatility is at or below the quote's tick",
                       tick_rule=TICK_RULE, rows_kept=kept_rows, rows_total=rows_b, sessions_kept=len(kept_sessions), sessions_total=len(full_sessions),
                       sessions_skipped=len(full_sessions)-len(kept_sessions), pairs={})
    for label, model, reference, primary in (("M(RV) vs B1", "m_rv", "b1", True), ("M(B1) vs B1", "m_b1", "b1", False)):
        pre = comparison["comparisons"][label]
        full_pair = paired(full_losses[reference], full_losses[model], primary, replicates)
        kept_pair = paired(kept_losses[reference], kept_losses[model], primary, replicates)
        sensitivity["pairs"][label] = dict(
            pre_registered=dict(mean_differential=pre["mean_differential"], interval=pre["interval"], median_relative_improvement=pre["median_relative_improvement"],
                                win_rate=pre["win_rate"], label=pre["label"]),
            recomputed_from_predictions=dict(mean_differential=full_pair["mean_differential"], interval=full_pair["interval"], label=full_pair["label"],
                                             matches_pre_registered=bool(abs(full_pair["mean_differential"]-pre["mean_differential"]) <= 1e-12*max(1.0, abs(pre["mean_differential"]))
                                                                         and full_pair["label"] == pre["label"])),
            below_tick=dict(mean_differential=kept_pair["mean_differential"], interval=kept_pair["interval"], sensitivity=kept_pair["sensitivity"],
                            median_relative_improvement=kept_pair["median_relative_improvement"], win_rate=kept_pair["win_rate"], label=kept_pair["label"],
                            sessions=len(kept_sessions)),
            label_changes=bool(kept_pair["label"] != pre["label"]))
    timing["sensitivity_seconds"] = round(time.perf_counter()-t0, 1)

    # ---- cancellation summary
    cancel_sessions, cancel_losses, cancel_counts = cancel.losses()
    cancellation = dict(rule="same-contract B1 rows of set B: B1 inverted from the t-1 mid and repriced at t under the European formula (as in the study) "
                             "against the same contract inverted on the tree at t-1 conditions and repriced on the tree at t; M(RV), the RV baseline, and M(B1) "
                             "keep their sigma and are repriced on the tree",
                        rows=int(cancel_counts.sum()) if len(cancel_counts) else 0, sessions=len(cancel_sessions), same_contract_rows=same_contract,
                        prior_quote_missing=prior_missing, tree_inversion_unidentified=tree_unidentified,
                        reinversion_check=dict(max_abs_sigma_difference=reinversion_max_abs, rows_beyond_1e_6=reinversion_mismatch),
                        steps=steps, losses={}, engine_shift={}, differential={})
    if len(cancel_sessions) >= 8:
        indices = bootstrap_indices(len(cancel_sessions), replicates)
        block = min(BLOCK_LENGTH, len(cancel_sessions))
        for method in ("b1", "m_rv", "rv", "m_b1"):
            eu, tr = cancel_losses[f"{method}_european"], cancel_losses[f"{method}_tree"]
            cancellation["losses"][method] = dict(european=dict(mean=float(eu.mean()), median=float(np.median(eu)), mean_rmse=float(np.sqrt(eu).mean())),
                                                  tree=dict(mean=float(tr.mean()), median=float(np.median(tr)), mean_rmse=float(np.sqrt(tr).mean())))
            shift = tr-eu
            cancellation["engine_shift"][method] = dict(mean=float(shift.mean()), interval=list(percentile_interval(shift[indices[block]].mean(axis=1))),
                                                        share_of_sessions_worse_on_tree=float((shift > 0).mean()))
        for label, model in (("M(RV) vs B1", "m_rv"), ("M(B1) vs B1", "m_b1"), ("RV vs B1", "rv")):
            d_e = cancel_losses["b1_european"]-cancel_losses[f"{model}_european"]
            d_t = cancel_losses["b1_tree"]-cancel_losses[f"{model}_tree"]
            change = d_t-d_e
            cancellation["differential"][label] = dict(
                european=dict(mean_d=float(d_e.mean()), median_rho=float(np.median(1-np.sqrt(cancel_losses[f"{model}_european"])/np.sqrt(cancel_losses["b1_european"]))),
                              win_rate=float((cancel_losses[f"{model}_european"] < cancel_losses["b1_european"]).mean())),
                tree=dict(mean_d=float(d_t.mean()), median_rho=float(np.median(1-np.sqrt(cancel_losses[f"{model}_tree"])/np.sqrt(cancel_losses["b1_tree"]))),
                          win_rate=float((cancel_losses[f"{model}_tree"] < cancel_losses["b1_tree"]).mean())),
                change_in_mean_d=float(change.mean()), change_interval=list(percentile_interval(change[indices[block]].mean(axis=1))),
                european_favors_b1=bool(change.mean() > 0),
                share_of_european_gap=(float(change.mean()/abs(d_e.mean())) if d_e.mean() != 0 else None))
    set_b_result = dict(rows=rows_b, sessions=len(full_sessions), unidentified_european_iv=unidentified_b, premium=agg_b.finish())

    stability = tree_stability(set_a, steps, chunksize)
    peak_rss_mb = peak_rss_megabytes()
    result = dict(exploratory=True, amendment=8, note=EXPLORATORY, code_version=__version__, pricing_paths=PRICING_PATHS,
                  tree=dict(steps=steps, engine="options_engine.american CRR, vectorized over rows in early_exercise.tree_prices",
                            premium_definition="American tree price minus European tree price on the same tree, as a fraction of the market mid",
                            stability=stability),
                  tick_rule=TICK_RULE, moneyness_terciles=list(cuts), maturity_split_days=MATURITY_SPLIT_DAYS, regimes=list(REGIMES),
                  chunksize=chunksize, timing=dict(timing, total_seconds=round(time.perf_counter()-started, 1)), peak_rss_mb=round(peak_rss_mb, 1),
                  inputs={name: dict(path=str(path), sha256=file_digest(path)) for name, path in
                          (("set_a", set_a), ("set_b_m_rv", set_b_rv), ("set_b_m_b1", set_b_b1), ("baselines", baselines_path), ("comparison", comparison_path),
                           ("breakdowns", breakdowns_path))},
                  bootstrap=dict(block_length=BLOCK_LENGTH, replicates=replicates, seed=SEED, sensitivity_blocks=list(SENSITIVITY_BLOCKS)),
                  sets=dict(A=set_a_result, B=set_b_result), cancellation=cancellation, sensitivity=sensitivity)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(out_path, clean_json(result))
    return dict(result, path=str(out_path))


def peak_rss_megabytes():
    """Peak resident set size of this process; ru_maxrss is bytes on macOS and kilobytes on Linux."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value/1024**2 if sys.platform == "darwin" else value/1024


def bootstrap_indices(n, replicates):
    """Block-index matrices keyed by block length: the primary block (21, or n when shorter) and the sensitivity blocks the sample allows."""
    block = min(BLOCK_LENGTH, n)
    indices = {block: block_indices(n, block, replicates, SEED)}
    for other in SENSITIVITY_BLOCKS:
        if other != block and other <= n:
            indices[other] = block_indices(n, other, replicates, SEED)
    return indices


def paired(reference, model, primary, replicates):
    n = len(reference)
    indices = bootstrap_indices(n, replicates)
    return pair_statistics(np.asarray(reference, float), np.asarray(model, float), indices, min(BLOCK_LENGTH, n), primary=primary)


def tree_stability(set_a, steps, chunksize, sample=2000):
    """Premium fraction at `steps` against twice the steps on the first rows of set A, at the quote's implied volatility."""
    chunk = next(pd.read_csv(set_a, compression="gzip", chunksize=min(sample, chunksize)))
    S, K, T, r, q, is_call = chunk_inputs(chunk)
    mid = chunk.mid.to_numpy(float)
    sigma = european_iv(mid, S, K, T, r, q, is_call)
    ok = np.isfinite(sigma)
    out = {}
    for n in (steps, 2*steps):
        american, european = tree_prices(S[ok], K[ok], T[ok], r[ok], q[ok], sigma[ok], is_call[ok], n)
        out[n] = np.maximum(american-european, 0.0)/mid[ok]
    diff = np.abs(out[2*steps]-out[steps])
    return dict(rows=int(ok.sum()), steps=steps, doubled_steps=2*steps, max_abs_difference_in_fraction=float(diff.max()), median_abs_difference=float(np.median(diff)),
                mean_fraction_at_steps=float(out[steps].mean()), mean_fraction_at_doubled=float(out[2*steps].mean()))


# ----------------------------------------------------------------------------- reviewer extract
EXTRACT_COLUMNS = ["observation_id", "evaluated_session", "symbol", "contractSymbol", "option_type", "expiration", "strike", "spot", "mid", "bid", "ask", "T",
                   "days_to_expiry", "r", "q", "rv_sigma", "m_rv_sigma", "rv_price", "m_rv_price", "in_set_b", "b1_sigma", "m_b1_sigma", "b1_price", "m_b1_price",
                   "european_iv", "early_exercise_premium_fraction", "tick", "premium_exceeds_tick", "year", "maturity_bucket", "moneyness_tercile"]
FOLD_TABLES_GLOB = "docs/results/**/folds.csv"


def stratum_key(chunk):
    year = chunk.evaluated_session.str.slice(0, 4)
    maturity = np.where(chunk.days_to_expiry.to_numpy(float) <= MATURITY_SPLIT_DAYS, "<=30d", ">30d")
    return chunk.symbol.astype(str)+"|"+year+"|"+chunk.option_type.astype(str)+"|"+maturity


def build_extract(set_a, set_b_rv, set_b_b1, out_dir, breakdowns_path, cap_per_stratum, seed=SEED, steps=STEPS, chunksize=CHUNKSIZE, repo_root=None):
    """See the README the function writes; `repo_root` is where docs/results/ lives (default: this repository)."""
    """A deterministic stratified sample of set A's evaluated observations with the set B prices merged, plus copies of every fold table."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise ValueError(f"{out_dir} exists; the extract is written once")
    cuts = read_moneyness_cuts(breakdowns_path)
    counts = {}
    for chunk in pd.read_csv(set_a, compression="gzip", usecols=["evaluated_session", "symbol", "option_type", "days_to_expiry"], chunksize=chunksize):
        for key, n in stratum_key(chunk).value_counts().items():
            counts[key] = counts.get(key, 0)+int(n)
    rng = np.random.default_rng(seed)
    chosen = {}
    for key in sorted(counts):
        n = counts[key]
        k = min(cap_per_stratum, n)
        chosen[key] = set(np.sort(rng.choice(n, size=k, replace=False)).tolist())
    seen = dict.fromkeys(counts, 0)
    frames = []
    for chunk in pd.read_csv(set_a, compression="gzip", chunksize=chunksize):
        keys = stratum_key(chunk).to_numpy()
        take = np.zeros(len(chunk), bool)
        for i, key in enumerate(keys):
            take[i] = seen[key] in chosen[key]
            seen[key] += 1
        if take.any():
            frames.append(chunk.loc[take].copy())
    sample = pd.concat(frames, ignore_index=True)
    sample = sample.rename(columns={"baseline_sigma": "rv_sigma", "model_sigma": "m_rv_sigma", "baseline_price": "rv_price", "model_price": "m_rv_price"})
    wanted = set(sample.observation_id)
    b_rows = []
    for chunk, chunk_b1 in zip(pd.read_csv(set_b_rv, compression="gzip", usecols=["observation_id"], chunksize=chunksize),
                               pd.read_csv(set_b_b1, compression="gzip", chunksize=chunksize), strict=True):
        if not (chunk.observation_id.to_numpy() == chunk_b1.observation_id.to_numpy()).all():
            raise ValueError("The two set B prediction files are not row-aligned")
        hit = chunk_b1.observation_id.isin(wanted)
        if hit.any():
            b_rows.append(chunk_b1.loc[hit, ["observation_id", "baseline_sigma", "model_sigma", "baseline_price", "model_price"]]
                          .rename(columns={"baseline_sigma": "b1_sigma", "model_sigma": "m_b1_sigma", "baseline_price": "b1_price", "model_price": "m_b1_price"}))
    b_table = pd.concat(b_rows, ignore_index=True) if b_rows else pd.DataFrame(columns=["observation_id", "b1_sigma", "m_b1_sigma", "b1_price", "m_b1_price"])
    sample = sample.merge(b_table, on="observation_id", how="left")
    sample["in_set_b"] = sample.b1_sigma.notna()
    S, K, T, r, q, is_call = chunk_inputs(sample)
    mid = sample.mid.to_numpy(float)
    sigma = european_iv(mid, S, K, T, r, q, is_call)
    ok = np.isfinite(sigma)
    premium = np.full(len(sample), np.nan)
    if ok.any():
        american, european = tree_prices(S[ok], K[ok], T[ok], r[ok], q[ok], sigma[ok], is_call[ok], steps)
        premium[ok] = np.maximum(american-european, 0.0)
    sample["european_iv"] = sigma
    sample["early_exercise_premium_fraction"] = premium/mid
    sample["tick"] = tick_size(sample.symbol, mid)
    sample["premium_exceeds_tick"] = premium > sample.tick
    keys = classify(sample, cuts)
    sample["year"], sample["maturity_bucket"], sample["moneyness_tercile"] = keys["year"], np.where(sample.days_to_expiry <= MATURITY_SPLIT_DAYS, "<=30d", ">30d"), keys["moneyness_tercile"]
    sample = sample[EXTRACT_COLUMNS].sort_values(["evaluated_session", "symbol", "contractSymbol"]).reset_index(drop=True)
    out_dir.mkdir(parents=True)
    sample_path = out_dir/"observations-sample.csv"
    sample.to_csv(sample_path, index=False)
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    folds_dir = out_dir/"folds"
    folds_dir.mkdir()
    copied = []
    for path in sorted(root.glob(FOLD_TABLES_GLOB)):
        if out_dir in path.parents:
            continue
        relative = path.relative_to(root/"docs"/"results")
        target = folds_dir/(str(relative.parent).replace("/", "__")+".csv")
        shutil.copyfile(path, target)
        copied.append(dict(source=str(path.relative_to(root)), copy=str(target.relative_to(out_dir)), sha256=file_digest(target)))
    size = sample_path.stat().st_size
    strata = {key: dict(rows=counts[key], sampled=len(chosen[key])) for key in sorted(counts)}
    manifest = dict(exploratory=True, note="For inspection only: no reported number is computed from this sample.",
                    sampling=dict(source="set A evaluated observations (docs/results/v2/design-c/runs/set-a/full/predictions.csv.gz), which contain every set B evaluated observation",
                                  strata="symbol x year x option type x maturity bucket (30 days or fewer, more than 30 days)", cap_per_stratum=cap_per_stratum,
                                  seed=seed, rng="numpy default_rng, rows drawn without replacement by their order within the stratum in the source file",
                                  strata_count=len(strata), rows=int(len(sample)), rows_in_set_b=int(sample.in_set_b.sum()), uncompressed_bytes=int(size),
                                  premium_steps=steps),
                    files=dict(sample=dict(path=sample_path.name, sha256=file_digest(sample_path), rows=int(len(sample)), bytes=int(size)),
                               folds=copied), strata=strata)
    (out_dir/"extract.json").write_text(json.dumps(clean_json(manifest), indent=2, sort_keys=True)+"\n")
    (out_dir/"README.md").write_text(extract_readme(manifest))
    return manifest


def extract_readme(manifest):
    s = manifest["sampling"]
    lines = ["# Reviewer extract (inspection only)", "",
             "For people and agents that cannot open the full exports. No reported number comes from this sample; every reported number traces to the",
             "files listed in docs/results/manifest.json.", "",
             f"- observations-sample.csv: {s['rows']:,} evaluated observations ({s['uncompressed_bytes']:,} bytes uncompressed), a deterministic stratified sample of {s['source']}.",
             f"  Strata: {s['strata']}; at most {s['cap_per_stratum']} rows per stratum ({s['strata_count']} strata), drawn without replacement with numpy default_rng seed {s['seed']} by row order",
             "  within the stratum. Columns carry the RV baseline and M(RV) sigma and price for every row, the B1 and M(B1) sigma and price for the",
             f"  {s['rows_in_set_b']:,} rows that are also in set B, the quote's European implied volatility, the early-exercise premium on a {s['premium_steps']}-step CRR tree",
             "  as a fraction of the mid, and the quote tick (Amendment 8 diagnostic).",
             f"- folds/: verbatim copies of every fold table under docs/results/ ({len(manifest['files']['folds'])} files), named by their source directory.",
             "- extract.json: the sampling rule, per-stratum counts, and the SHA-256 of every file here.", ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- report
SECTION_START, SECTION_END = "<!-- early-exercise-diagnostic:start -->", "<!-- early-exercise-diagnostic:end -->"


def _stats_row(label, stats):
    if not stats or stats.get("n", 0) == 0:
        return f"| {label} | 0 | | | | | |"
    return (f"| {label} | {stats['n']:,} | {100*stats['mean']:.3f}% | {100*stats['median']:.3f}% | {100*stats['p90']:.3f}% | {100*stats['p99']:.3f}% | "
            f"{100*stats['share_exceeding_tick']:.1f}% |")


def render_section(result):
    lines = ["## Early-exercise diagnostic (Amendment 8, exploratory)", "", EXPLORATORY, "",
             f"Every study price is the European closed form (the trace is in early-exercise-diagnostic.json under pricing_paths). Premiums below are American "
             f"minus European price on the same {result['tree']['steps']}-step CRR tree at the quote's own European implied volatility, as a fraction of the mid; "
             f"tick rule: {result['tick_rule']}. Doubling the steps on {result['tree']['stability']['rows']:,} rows moves the fraction by at most "
             f"{100*result['tree']['stability']['max_abs_difference_in_fraction']:.4f} points. Timing {result['timing']['total_seconds']} s in total, peak resident memory "
             f"{result['peak_rss_mb']:.0f} MB, {result['chunksize']:,}-row chunks.", ""]
    for name in ("A", "B"):
        block = result["sets"][name]["premium"]["iv"]
        lines += [f"**Set {name}** ({result['sets'][name]['rows']:,} rows; {result['sets'][name]['unidentified_european_iv']} without an identified European implied volatility)", "",
                  "| Cell | Rows | Mean | Median | p90 | p99 | Share above tick |", "|---|---:|---:|---:|---:|---:|---:|", _stats_row("all", block["overall"])]
        for key, title in (("by_option_type", "type"), ("by_moneyness_tercile", "moneyness tercile"), ("by_maturity_bucket", "maturity"), ("by_symbol", "symbol"), ("by_regime", "regime")):
            for level, stats in block[key].items():
                lines.append(_stats_row(f"{title}: {level}", stats))
        others = result["sets"][name]["premium"]
        lines += ["", "At each method's own sigma (mean fraction, share above tick): "+"; ".join(
            f"{m} {100*others[m]['overall']['mean']:.3f}%, {100*others[m]['overall']['share_exceeding_tick']:.1f}%" for m in others if m != "iv"), ""]
    c = result["cancellation"]
    lines += ["**Cancellation test** (same-contract B1 rows of set B: "
              f"{c['rows']:,} rows in {c['sessions']} sessions; re-inversion check max |delta sigma| {c['reinversion_check']['max_abs_sigma_difference']:.2e})", "",
              "| Method | Session MSE, European | Session MSE, tree | Shift (tree - European) | 95% interval | Sessions worse on tree |", "|---|---:|---:|---:|---:|---:|"]
    for method, loss in c["losses"].items():
        shift = c["engine_shift"][method]
        lines.append(f"| {method} | {loss['european']['mean']:.3e} | {loss['tree']['mean']:.3e} | {shift['mean']:+.3e} | [{shift['interval'][0]:+.2e}, {shift['interval'][1]:+.2e}] | {100*shift['share_of_sessions_worse_on_tree']:.1f}% |")
    lines += ["", "| Pair | Mean d, European | Mean d, tree | Change | 95% interval | European favors B1 | Change as share of the European gap |", "|---|---:|---:|---:|---:|---|---:|"]
    for label, item in c["differential"].items():
        share = item["share_of_european_gap"]
        lines.append(f"| {label} | {item['european']['mean_d']:.3e} | {item['tree']['mean_d']:.3e} | {item['change_in_mean_d']:+.3e} | [{item['change_interval'][0]:+.2e}, {item['change_interval'][1]:+.2e}] | "
                     f"{'yes' if item['european_favors_b1'] else 'no'} | {'n/a' if share is None else f'{100*share:+.1f}%'} |")
    lines += ["", "M(B1) learned its adjustment against European B1 sigmas, so repricing it on the tree at that sigma is not a consistent treatment; its rows "
              "are reported for completeness and carry no reading. The M(RV) row is the test: its sigma comes from no option price, so the tree "
              "changes only its pricing, while B1 is inverted and repriced on the same engine in both columns."]
    s = result["sensitivity"]
    lines += ["", f"**Sensitivity** (rows with premium at or below the tick: {s['rows_kept']:,} of {s['rows_total']:,}; {s['sessions_kept']} of {s['sessions_total']} sessions keep a row)", "",
              "| Comparison | Sample | Mean L_baseline - L_model | 95% interval | Median relative improvement | Win rate | Label |", "|---|---|---:|---:|---:|---:|---|"]
    for label, pair in s["pairs"].items():
        pre, sub = pair["pre_registered"], pair["below_tick"]
        lines.append(f"| {label} | pre-registered, full set B | {pre['mean_differential']:.3e} | [{pre['interval'][0]:.2e}, {pre['interval'][1]:.2e}] | {pre['median_relative_improvement']:.4f} | {pre['win_rate']:.3f} | {pre['label']} |")
        lines.append(f"| {label} | premium at or below tick | {sub['mean_differential']:.3e} | [{sub['interval'][0]:.2e}, {sub['interval'][1]:.2e}] | {sub['median_relative_improvement']:.4f} | {sub['win_rate']:.3f} | {sub['label']} |")
    changed = [label for label, pair in s["pairs"].items() if pair["label_changes"]]
    lines += ["", ("No label changes." if not changed else "Label changes: "+", ".join(changed)+".")+" The pre-registered numbers are not replaced.", ""]
    return "\n".join(lines)


def write_report_section(result_path, report_path):
    result = json.loads(Path(result_path).read_text())
    section = SECTION_START+"\n"+render_section(result)+SECTION_END+"\n"
    report = Path(report_path)
    text = report.read_text() if report.exists() else ""
    if SECTION_START in text and SECTION_END in text:
        head, rest = text.split(SECTION_START, 1)
        _, tail = rest.split(SECTION_END, 1)
        text = head+section+tail.lstrip("\n")
    else:
        text = text.rstrip("\n")+"\n\n"+section
    report.write_text(text)
    return dict(path=str(report), section_lines=section.count("\n"))


