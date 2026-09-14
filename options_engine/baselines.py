"""Prior-session baselines for Design B (Research Plan section 4, Amendment 4).

B1, prior-session implied volatility: for a contract observed at session t,
the implied volatility of the same contract (symbol, expiry, strike, type)
inverted from its mid at the prior available session t-1 under t-1 conditions
(S_{t-1}, time to expiry from t-1, r_{t-1}, q_{t-1}); that is exactly the
target apply_carry solves on the t-1 row. When the contract is absent at t-1
the volatility is interpolated linearly in strike within the same expiry and
option type at t-1, using only strikes that inverted, never beyond the
available strike range. Observations without a B1 leave set B with a reason.

B2, prior-session SVI: per (symbol, expiry) slice at t-1, raw SVI total
variance w(k) = a + b(rho(k-m) + sqrt((k-m)^2 + sigma^2)) in log-moneyness of
the t-1 forward, fitted by vega-weighted least squares to the out-of-the-money
t-1 mid implied volatilities, subject to the standard parameter bounds
(b >= 0, |rho| < 1, sigma > 0, a + b sigma sqrt(1-rho^2) >= 0, Lee's wing
bound b(1+|rho|) <= 2) and the butterfly (Gatheral-Jacquier g >= 0) check on a
grid over the fitted range. The slice is evaluated at t's strikes against t's
forward and converted back with the t-1 time to expiry, so the persisted
object is the implied-volatility smile. Slices that fail fall back to B1 and
are counted by reason.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

B1_SOURCES = ("same_contract", "interpolated")
B1_REASONS = ("no_prior_session", "expiry_absent_at_prior_session", "type_absent_at_prior_session",
              "single_strike_at_prior_session", "strike_outside_prior_range")
B2_REASONS = ("too_few_strikes", "no_convergence", "parameter_bounds", "butterfly", "evaluation_failed")
SVI_MIN_STRIKES = 6
LEE_WING_BOUND = 2.0
FRAME_COLUMNS = ["observation_id", "session_date", "symbol", "contractSymbol", "expiration", "strike", "option_type",
                 "spot", "T", "r", "q", "iv_brent_volatility", "iv_brent_vega", "baseline_sigma"]


# ----------------------------------------------------------------------------- B1
def prior_session_map(frame):
    """(symbol, session) -> the previous session present for that symbol, or None."""
    out = {}
    for symbol, group in frame.groupby("symbol"):
        sessions = sorted(group.session_date.unique())
        for index, session in enumerate(sessions):
            out[(symbol, session)] = sessions[index-1] if index else None
    return out


def b1_baseline(frame):
    """Per observation: prior session, calendar gap, B1 volatility, its source, or the reason it is unavailable."""
    if missing := set(FRAME_COLUMNS[:7]+["iv_brent_volatility"])-set(frame.columns):
        raise ValueError(f"B1 needs columns {sorted(missing)}")
    if frame.duplicated(["symbol", "session_date", "contractSymbol"]).any():
        raise ValueError("A contract appears twice in one session; the store should hold one quote per contract and session")
    prior = prior_session_map(frame)
    rows = frame[["observation_id", "session_date", "symbol", "contractSymbol", "expiration", "strike", "option_type"]].copy()
    rows["prior_session"] = [prior[(s, d)] for s, d in zip(rows.symbol, rows.session_date, strict=True)]
    rows["gap_days"] = [(pd.Timestamp(d)-pd.Timestamp(p)).days if p else np.nan for d, p in zip(rows.session_date, rows.prior_session, strict=True)]
    lookup = frame.set_index(["symbol", "session_date", "contractSymbol"]).iv_brent_volatility
    keys = pd.MultiIndex.from_arrays([rows.symbol, rows.prior_session.fillna(""), rows.contractSymbol])
    same = lookup.reindex(keys).to_numpy(float)
    rows["b1_sigma"] = same
    rows["b1_source"] = np.where(np.isfinite(same), "same_contract", "")
    rows["b1_reason"] = ""
    expiries = set(zip(frame.symbol, frame.session_date, frame.expiration, strict=True))
    slices = {}
    for key, group in frame.groupby(["symbol", "session_date", "expiration", "option_type"]):
        ordered = group.sort_values("strike")
        slices[key] = (ordered.strike.to_numpy(float), ordered.iv_brent_volatility.to_numpy(float))
    for index in np.flatnonzero(~np.isfinite(same)):
        row = rows.iloc[index]
        if row.prior_session is None:
            reason = "no_prior_session"
        elif (row.symbol, row.prior_session, row.expiration) not in expiries:
            reason = "expiry_absent_at_prior_session"
        elif (row.symbol, row.prior_session, row.expiration, row.option_type) not in slices:
            reason = "type_absent_at_prior_session"
        else:
            strikes, sigmas = slices[(row.symbol, row.prior_session, row.expiration, row.option_type)]
            if len(strikes) < 2:
                reason = "single_strike_at_prior_session"
            elif not strikes[0] <= row.strike <= strikes[-1]:
                reason = "strike_outside_prior_range"
            else:
                rows.iat[index, rows.columns.get_loc("b1_sigma")] = float(np.interp(row.strike, strikes, sigmas))
                rows.iat[index, rows.columns.get_loc("b1_source")] = "interpolated"
                continue
        rows.iat[index, rows.columns.get_loc("b1_reason")] = reason
    return rows


# ----------------------------------------------------------------------------- SVI
def svi_total_variance(k, params):
    a, b, rho, m, sigma = params
    d = np.asarray(k, float)-m
    return a+b*(rho*d+np.sqrt(d*d+sigma*sigma))


def svi_derivatives(k, params):
    a, b, rho, m, sigma = params
    d = np.asarray(k, float)-m
    root = np.sqrt(d*d+sigma*sigma)
    return b*(rho+d/root), b*sigma*sigma/root**3


def butterfly_g(k, params):
    """Gatheral-Jacquier density condition; the slice is free of butterfly arbitrage when g >= 0 and w > 0."""
    k = np.asarray(k, float)
    w = svi_total_variance(k, params)
    w1, w2 = svi_derivatives(k, params)
    return (1-k*w1/(2*w))**2-(w1*w1/4)*(1/w+.25)+w2/2, w


def parameter_bounds_hold(params, tolerance=1e-9):
    a, b, rho, m, sigma = params
    return (b >= 0 and abs(rho) < 1 and sigma > 0 and a+b*sigma*math.sqrt(1-rho*rho) >= -tolerance
            and b*(1+abs(rho)) <= LEE_WING_BOUND+tolerance)


def butterfly_free(params, k_low, k_high, points=201, margin=.1):
    g, w = butterfly_g(np.linspace(k_low-margin, k_high+margin, points), params)
    return bool(np.all(w > 0) and np.all(g >= -1e-10))


# The fit works in (w_min, b, rho, m, sigma) with w_min = a + b sigma sqrt(1 - rho^2) the slice's minimum total variance,
# so the non-negativity bound is a box constraint, and adds a penalty residual for Lee's wing bound b(1 + |rho|) <= 2.
# Without these the least-squares surface is flat along a degenerate direction (b -> 2, |rho| -> 1, a < 0) that fits the
# quoted range but is not an admissible raw SVI slice.
FIT_BOUNDS = ([0.0, 0.0, -0.999, -1.5, 1e-3], [10.0, 2.0, 0.999, 1.5, 3.0])
LEE_PENALTY = 10.0


def _to_raw(theta):
    w_min, b, rho, m, sigma = theta
    return (float(w_min-b*sigma*math.sqrt(1-rho*rho)), float(b), float(rho), float(m), float(sigma))


def _residuals(theta, k, w, scale):
    w_min, b, rho, m, sigma = theta
    d = k-m
    root = np.sqrt(d*d+sigma*sigma)
    model = w_min-b*sigma*math.sqrt(1-rho*rho)+b*(rho*d+root)
    excess = b*(1+abs(rho))-LEE_WING_BOUND
    return np.append(scale*(model-w), LEE_PENALTY*max(excess, 0.0))


def _jacobian(theta, k, w, scale):
    w_min, b, rho, m, sigma = theta
    d = k-m
    root = np.sqrt(d*d+sigma*sigma)
    q = math.sqrt(1-rho*rho)
    jac = np.empty((len(k)+1, 5))
    jac[:-1, 0] = scale
    jac[:-1, 1] = scale*(-sigma*q+rho*d+root)
    jac[:-1, 2] = scale*(b*sigma*rho/q+b*d)
    jac[:-1, 3] = scale*(-b*(rho+d/root))
    jac[:-1, 4] = scale*(-b*q+b*sigma/root)
    active = float(b*(1+abs(rho)) > LEE_WING_BOUND)
    jac[-1] = [0.0, LEE_PENALTY*(1+abs(rho))*active, LEE_PENALTY*b*np.sign(rho)*active, 0.0, 0.0]
    return jac


def fit_svi(k, w, weights):
    """Vega-weighted least squares from several starts with an analytic Jacobian; (raw params, info) or (None, reason)."""
    k, w, weights = (np.asarray(x, float) for x in (k, w, weights))
    scale = np.sqrt(np.maximum(weights, 1e-12)/np.maximum(weights, 1e-12).mean())
    floor = max(float(w.min()), 1e-10)
    at_min = float(k[np.argmin(w)])
    starts = [(floor, .05, -.5, at_min, .05), (floor, .3, -.3, at_min, .2), (floor, .1, .0, 0.0, .1), (floor, .5, -.8, at_min+.05, .3)]
    best = None
    for start in starts:
        try:
            fit = least_squares(_residuals, np.clip(start, FIT_BOUNDS[0], FIT_BOUNDS[1]), jac=_jacobian, bounds=FIT_BOUNDS, args=(k, w, scale),
                                method="trf", x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=3000)
        except (ValueError, FloatingPointError):
            continue
        if fit.status > 0 and np.isfinite(fit.cost) and (best is None or fit.cost < best.cost):
            best = fit
    if best is None:
        return None, "no_convergence"
    return _to_raw(best.x), dict(cost=float(best.cost), evaluations=int(best.nfev), status=int(best.status))


def slice_points(rows):
    """Out-of-the-money t-1 quotes of one (symbol, session, expiry): puts below the forward, calls at or above it."""
    forward = rows.spot.to_numpy(float)*np.exp((rows.r.to_numpy(float)-rows.q.to_numpy(float))*rows["T"].to_numpy(float))
    strike = rows.strike.to_numpy(float)
    otm = np.where(rows.option_type.to_numpy() == "put", strike < forward, strike >= forward)
    chosen = rows.loc[otm].sort_values("strike")
    f = float(forward[0])
    T = float(rows["T"].iloc[0])
    k = np.log(chosen.strike.to_numpy(float)/f)
    iv = chosen.iv_brent_volatility.to_numpy(float)
    vega = chosen.iv_brent_vega.to_numpy(float) if "iv_brent_vega" in chosen else np.ones(len(chosen))
    return dict(k=k, w=iv*iv*T, weights=np.where(np.isfinite(vega) & (vega > 0), vega, 1e-8), forward=f, T=T,
                distinct_strikes=int(chosen.strike.nunique()))


def fit_slice(rows):
    points = slice_points(rows)
    if points["distinct_strikes"] < SVI_MIN_STRIKES:
        return dict(ok=False, reason="too_few_strikes", **{key: points[key] for key in ("forward", "T", "distinct_strikes")})
    params, info = fit_svi(points["k"], points["w"], points["weights"])
    if params is None:
        return dict(ok=False, reason=info, forward=points["forward"], T=points["T"], distinct_strikes=points["distinct_strikes"])
    if not parameter_bounds_hold(params):
        reason = "parameter_bounds"
    elif not butterfly_free(params, float(points["k"].min()), float(points["k"].max())):
        reason = "butterfly"
    else:
        reason = ""
    return dict(ok=reason == "", reason=reason, params=params, fit=info, forward=points["forward"], T=points["T"],
                distinct_strikes=points["distinct_strikes"], k_low=float(points["k"].min()), k_high=float(points["k"].max()))


def b2_baseline(frame, b1, fit=fit_slice):
    """B2 per observation with B1 fallback, plus the slice-level accounting."""
    rows = b1.loc[b1.b1_sigma.notna(), ["observation_id", "session_date", "symbol", "expiration", "prior_session", "b1_sigma"]].copy()
    needed = rows[["symbol", "prior_session", "expiration"]].drop_duplicates()
    groups = {key: group for key, group in frame.groupby(["symbol", "session_date", "expiration"])}
    slices = {}
    for key in map(tuple, needed.to_numpy()):
        group = groups.get(key)
        slices[key] = fit(group) if group is not None else dict(ok=False, reason="too_few_strikes", forward=np.nan, T=np.nan, distinct_strikes=0)
    at_t = frame.set_index("observation_id").loc[rows.observation_id, ["spot", "strike", "T", "r", "q"]]
    forward_t = at_t.spot.to_numpy(float)*np.exp((at_t.r.to_numpy(float)-at_t.q.to_numpy(float))*at_t["T"].to_numpy(float))
    k_t = np.log(at_t.strike.to_numpy(float)/forward_t)
    b2 = np.full(len(rows), np.nan)
    source = np.full(len(rows), "fallback_b1", dtype=object)
    reason = np.full(len(rows), "", dtype=object)
    keys = list(zip(rows.symbol, rows.prior_session, rows.expiration, strict=True))
    for index, key in enumerate(keys):
        result = slices[key]
        if not result["ok"]:
            reason[index] = result["reason"]
            continue
        w = float(svi_total_variance(k_t[index], result["params"]))
        if not np.isfinite(w) or w <= 0:
            reason[index] = "evaluation_failed"
            continue
        b2[index] = math.sqrt(w/result["T"])
        source[index] = "svi"
    fallback = ~np.isfinite(b2)
    b2[fallback] = rows.b1_sigma.to_numpy(float)[fallback]
    rows["b2_sigma"], rows["b2_source"], rows["b2_reason"] = b2, source, reason
    attempted = len(slices)
    failed = {r: sum(1 for s in slices.values() if not s["ok"] and s["reason"] == r) for r in B2_REASONS}
    failed = {r: n for r, n in failed.items() if n}
    accounting = dict(slices_attempted=attempted, slices_fitted=attempted-sum(failed.values()), slices_fallback_by_reason=failed,
                      slice_fallback_rate=(sum(failed.values())/attempted if attempted else 0.0),
                      rows_by_source={k: int(v) for k, v in pd.Series(source).value_counts().sort_index().items()},
                      rows_fallback_by_reason={k: int(v) for k, v in pd.Series(reason[reason != ""]).value_counts().sort_index().items()},
                      fallback_contaminated=(sum(failed.values())/attempted if attempted else 0.0) > .2)
    return rows[["observation_id", "b2_sigma", "b2_source", "b2_reason"]], accounting


# ----------------------------------------------------------------------------- set B
def build_design_b(frame):
    """Set B keys, the per-observation baselines table, and the drop and fallback accounting for one C3 frame (set A rows)."""
    b1 = b1_baseline(frame)
    kept = b1.loc[b1.b1_sigma.notna()]
    b2, svi = b2_baseline(frame, b1)
    table = kept.merge(b2, on="observation_id", how="left").merge(frame[["observation_id", "baseline_sigma"]].rename(columns={"baseline_sigma": "rv_sigma"}),
                                                                   on="observation_id", how="left")
    table = table.sort_values(["session_date", "symbol", "observation_id"]).reset_index(drop=True)
    dropped = b1.loc[b1.b1_sigma.isna()]
    keys = table[["observation_id", "session_date", "symbol"]].reset_index(drop=True)
    gap = table.gap_days.astype(float)
    summary = dict(candidates=int(len(frame)), kept=int(len(keys)), dropped=int(len(dropped)),
                   dropped_by_reason={k: int(v) for k, v in dropped.b1_reason.value_counts().sort_index().items()},
                   dropped_by_symbol={k: int(v) for k, v in dropped.symbol.value_counts().sort_index().items()},
                   candidate_sessions=int(frame.session_date.nunique()), kept_sessions=int(keys.session_date.nunique()),
                   sessions_lost=sorted(set(frame.session_date)-set(keys.session_date)),
                   kept_by_symbol={k: int(v) for k, v in keys.symbol.value_counts().sort_index().items()},
                   b1_by_source={k: int(v) for k, v in table.b1_source.value_counts().sort_index().items()},
                   gap_days=dict(median=float(gap.median()), mean=float(gap.mean()), max=int(gap.max()),
                                 distribution={str(int(k)): int(v) for k, v in gap.value_counts().sort_index().head(12).items()}),
                   b1_vs_rv=dict(median_abs_difference=float((table.b1_sigma-table.rv_sigma).abs().median()),
                                 median_b1=float(table.b1_sigma.median()), median_rv=float(table.rv_sigma.median())),
                   b2=svi, rule="kept only if a same-contract or strike-interpolated prior-session implied volatility exists (Amendment 4 carry)")
    return keys, table, summary
