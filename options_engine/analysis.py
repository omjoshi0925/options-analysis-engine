"""Separate independent-baseline pricing errors from in-sample IV reconstruction."""
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .core import BlackScholesEngine
from .iv import implied_volatility
from .data import FilterConfig, filter_options


def metrics(frame, min_mid=0.10):
    if not np.isfinite(min_mid) or min_mid <= 0:
        raise ValueError("min_mid must be finite and positive")
    error = frame["error"].to_numpy(float)
    mask = frame["mid"] >= min_mid
    percentage = frame.loc[mask, "error"]/frame.loc[mask, "mid"]
    return dict(n=len(frame), mae=float(np.mean(np.abs(error))) if len(frame) else np.nan,
                rmse=float(np.sqrt(np.mean(error**2))) if len(frame) else np.nan,
                median_error=float(np.median(error)) if len(frame) else np.nan,
                mean_error=float(np.mean(error)) if len(frame) else np.nan,
                mape_pct=float(100*np.mean(np.abs(percentage))) if len(percentage) else np.nan,
                n_mape=int(mask.sum()), mape_min_mid=min_mid,
                within_bid_ask_pct=float(100*frame["baseline_within_spread"].mean()) if len(frame) else np.nan)


def analyze_options(raw, config=None, min_mid=0.10):
    if not np.isfinite(min_mid) or min_mid <= 0:
        raise ValueError("min_mid must be finite and positive")
    config = config or FilterConfig()
    accepted, audit = filter_options(raw, config)
    if accepted.empty:
        return accepted, audit
    records = []
    for row in accepted.to_dict("records"):
        m = BlackScholesEngine(row["spot"], row["strike"], row["T"], row["r"], row["baseline_sigma"], row["q"])
        kind = row["option_type"]
        baseline = m.price(kind)
        lo, hi = m.bounds(kind)
        error = row["mid"]-baseline
        row.update(baseline_price=baseline, error=error, absolute_error=abs(error),
                   normalized_error=error/row["mid"] if row["mid"] >= min_mid else np.nan,
                   baseline_within_spread=row["bid"] <= baseline <= row["ask"],
                   baseline_distance_to_spread=max(row["bid"]-baseline, baseline-row["ask"], 0),
                   european_lower_bound=lo, european_upper_bound=hi,
                   european_bound_violation=not lo-1e-8 <= row["mid"] <= hi+1e-8,
                   parity_residual=m.verify_parity())
        for greek, value in m.analytical_greeks(kind).items():
            row["baseline_"+greek.lower()] = value
        for method in ("brent", "newton"):
            result = implied_volatility(row["mid"], m.S, m.K, m.T, m.r, m.q, kind, method)
            for key, value in asdict(result).items():
                row[f"iv_{method}_{key}"] = value
        brent = row["iv_brent_volatility"]
        newton = row["iv_newton_volatility"]
        row["iv_solver_difference"] = brent-newton
        provider_iv = row["impliedVolatility"]
        row["provider_iv_valid"] = np.isfinite(provider_iv) and provider_iv > 0
        row["iv_minus_provider"] = brent-provider_iv if row["provider_iv_valid"] else np.nan
        # Do not fit this IV back into the empirical baseline.
        row["iv_reconstruction_price"] = row["mid"]+row["iv_brent_residual"] if row["iv_brent_converged"] else np.nan
        if row["iv_brent_vega"] > 1e-6:
            row["approx_iv_uncertainty_half_spread"] = row["spread"]/2/row["iv_brent_vega"]
        else:
            row["approx_iv_uncertainty_half_spread"] = np.nan
        records.append(row)
    df = pd.DataFrame(records)
    df["moneyness_bucket"] = pd.cut(df.log_moneyness, [-np.inf, -.1, -.025, .025, .1, np.inf],
                                    labels=["S/K < 0.905", "0.905-0.975", "near ATM", "1.025-1.105", "S/K > 1.105"])
    df["tenor_bucket"] = pd.cut(df.days_to_expiry, [0, 7, 30, 90, 365, np.inf], labels=["0-7d", "7-30d", "30-90d", "90-365d", ">365d"])
    df["identified_iv"] = df.iv_brent_volatility.where(df.iv_brent_converged & ~df.iv_brent_poorly_identified & (df.iv_brent_volatility > 0))
    df["iv_bucket"] = pd.cut(df.identified_iv, [-np.inf, .15, .25, .4, .75, np.inf],
                             labels=["<=15%", "15-25%", "25-40%", "40-75%", ">75%"]).astype("object").fillna("IV unavailable or poorly identified")
    df["volume_bucket"] = pd.cut(df.volume, [-np.inf, 0, 10, 100, 1000, np.inf],
                                 labels=["0", "1-10", "11-100", "101-1000", ">1000"]).astype("object").fillna("missing")
    df["open_interest_bucket"] = pd.cut(df.openInterest, [-np.inf, 10, 100, 1000, np.inf],
                                        labels=["<=10", "11-100", "101-1000", ">1000"]).astype("object").fillna("missing")
    df["spread_bucket"] = pd.cut(df.relative_spread, [-np.inf, .05, .1, .25, np.inf],
                                 labels=["<=5%", "5-10%", "10-25%", ">25%"])
    return df, audit


def grouped_metrics(df, min_mid=0.10):
    rows = [{"dimension": "overall", "group": "all", **metrics(df, min_mid)}]
    dimensions = ("symbol", "option_type", "expiration", "moneyness_bucket", "tenor_bucket", "iv_bucket",
                  "volume_bucket", "open_interest_bucket", "spread_bucket")
    for dimension in dimensions:
        for group, sub in df.groupby(dimension, observed=True, dropna=False):
            rows.append(dict(dimension=dimension, group=str(group), **metrics(sub, min_mid)))
    for keys, sub in df.groupby(["symbol", "option_type", "expiration"], observed=True):
        rows.append(dict(dimension="asset_type_expiry", group=" / ".join(map(str, keys)), **metrics(sub, min_mid)))
    return pd.DataFrame(rows)


def smile_summary(df):
    rows = []
    for keys, sub in df.groupby(["symbol", "option_type", "expiration"]):
        eligible = sub.loc[sub.iv_brent_converged & ~sub.iv_brent_poorly_identified & (sub.iv_brent_volatility > 0)]
        # ATM range limits a straight-line skew to a descriptive local statistic.
        local = eligible.loc[eligible.log_moneyness.abs() <= .15]
        slope = np.nan
        if len(local) >= 3 and local.log_moneyness.nunique() >= 3:
            slope = float(np.polyfit(local.log_moneyness, local.iv_brent_volatility, 1)[0])
        rows.append(dict(symbol=keys[0], option_type=keys[1], expiration=keys[2], n=len(eligible),
                         local_n=len(local), local_skew_slope=slope,
                         iv_min=eligible.iv_brent_volatility.min(), iv_max=eligible.iv_brent_volatility.max()))
    return pd.DataFrame(rows)


def market_parity_diagnostics(df):
    """Executable bid/ask interval for C-P; diagnostic only for American contracts."""
    keys = ["symbol", "expiration", "strike", "as_of", "spot", "r", "q", "T"]
    calls = df.loc[df.option_type == "call"]
    puts = df.loc[df.option_type == "put"]
    merged = calls.merge(puts, on=keys, suffixes=("_call", "_put"), validate="one_to_one")
    rows = []
    for row in merged.to_dict("records"):
        theory = row["spot"]*np.exp(-row["q"]*row["T"])-row["strike"]*np.exp(-row["r"]*row["T"])
        low = row["bid_call"]-row["ask_put"]
        high = row["ask_call"]-row["bid_put"]
        rows.append({**{key: row[key] for key in keys}, "european_parity": theory,
                     "market_mid_difference": row["mid_call"]-row["mid_put"],
                     "bid_ask_lower": low, "bid_ask_upper": high,
                     "theory_inside_interval": low <= theory <= high})
    return pd.DataFrame(rows, columns=keys+["european_parity", "market_mid_difference", "bid_ask_lower", "bid_ask_upper", "theory_inside_interval"])


def implied_forward_diagnostics(df, min_pairs=3):
    """Per asset, expiry, and capture: fit C - P = a + b*K across matched strikes (European parity).

    a estimates S*exp(-qT), the discounted forward, and -b estimates exp(-rT), so the fit
    yields a market-implied rate and dividend yield to compare with the assumed inputs.
    American puts carry an early-exercise premium that lowers C - P and biases the implied
    forward down; treat the output as a check on the r/q scenario, not an executable forward.
    """
    keys = ["symbol", "expiration", "as_of", "spot", "r", "q", "T"]
    calls = df.loc[df.option_type == "call", keys+["strike", "mid"]]
    puts = df.loc[df.option_type == "put", keys+["strike", "mid"]]
    merged = calls.merge(puts, on=keys+["strike"], suffixes=("_call", "_put"), validate="one_to_one")
    columns = keys+["n_pairs", "implied_discount", "implied_rate", "implied_forward", "implied_yield",
                    "rate_difference", "yield_difference", "fit_rmse", "r_squared", "status"]
    rows = []
    for key, group in merged.groupby(keys, sort=True):
        record = dict(zip(keys, key, strict=True))
        record["n_pairs"] = len(group)
        strikes = group.strike.to_numpy(float)
        difference = (group.mid_call-group.mid_put).to_numpy(float)
        if len(group) < min_pairs or np.unique(strikes).size < 2 or record["T"] <= 0:
            rows.append({**record, "status": "insufficient_pairs"})
            continue
        slope, intercept = np.polyfit(strikes, difference, 1)
        residual = difference-(intercept+slope*strikes)
        total = float(np.sum((difference-difference.mean())**2))
        record.update(fit_rmse=float(np.sqrt(np.mean(residual**2))),
                      r_squared=float(1-np.sum(residual**2)/total) if total > 0 else np.nan)
        discount, discounted_forward = -float(slope), float(intercept)
        if discount <= 0 or discounted_forward <= 0:
            rows.append({**record, "status": "no_valid_parity_fit"})
            continue
        record.update(implied_discount=discount, implied_rate=-np.log(discount)/record["T"],
                      implied_forward=discounted_forward/discount,
                      implied_yield=-np.log(discounted_forward/record["spot"])/record["T"])
        record.update(rate_difference=record["implied_rate"]-record["r"], yield_difference=record["implied_yield"]-record["q"], status="ok")
        rows.append(record)
    return pd.DataFrame(rows, columns=columns)


def write_report(df, audit, metadata, output, config=None, min_mid=0.10):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output/"filter_audit.csv", index=False)
    df.to_csv(output/"analyzed_options.csv", index=False)
    filters = asdict(config or FilterConfig())
    (output/"analysis_config.json").write_text(json.dumps(dict(filters=filters, min_mid=min_mid, source=metadata), indent=2)+"\n")
    synthetic = metadata.get("data_kind") == "synthetic"
    label = "SYNTHETIC DEMONSTRATION - NOT MARKET EVIDENCE" if synthetic else "Observed quotes; European-equivalent BSM diagnostics"
    lines = ["# Options analysis report", "", f"**{label}**", "",
             f"Raw contracts: {len(audit)}. Accepted: {len(df)}. Rejected: {len(audit)-len(df)}.", "",
             "Errors are midpoint minus the independent baseline price, in currency units per share.",
             "Contract-specific IV reconstruction is an inversion check, not independent pricing accuracy.", ""]
    counts = audit.loc[~audit.accepted, "filter_reasons"].str.split(";").explode().value_counts()
    lines += ["## Quote audit", "", "Exclusion reasons can overlap.", ""]
    lines += [f"- {name}: {count}" for name, count in counts.items()] or ["- No exclusions."]
    if df.empty:
        lines += ["", "No usable quotes remain. No accuracy metrics or market conclusions were produced."]
        (output/"REPORT.md").write_text("\n".join(lines)+"\n")
        return
    summary = grouped_metrics(df, min_mid)
    summary.to_csv(output/"metrics.csv", index=False)
    smile_summary(df).to_csv(output/"smile_summary.csv", index=False)
    market_parity_diagnostics(df).to_csv(output/"market_parity.csv", index=False)
    forwards = implied_forward_diagnostics(df)
    forwards.to_csv(output/"implied_forward.csv", index=False)
    headline = metrics(df, min_mid)
    lines += ["", "## Baseline comparison", "", "| Metric | Value |", "|---|---:|"]
    lines += [f"| {key} | {value:.6g} |" for key, value in headline.items()]
    baselines = df[["symbol", "baseline_sigma", "r", "q"]].drop_duplicates()
    lines += ["", "Baseline inputs (annual decimal units):", "", baselines.to_string(index=False), "",
              f"MAPE excludes midpoint < {min_mid:g}; n_mape records its denominator. All accepted quotes remain in MAE/RMSE, including IV failures.",
              "Pooled dollar errors are scale dependent; compare asset/type/expiry groups before pooling assets.", "",
              "## IV solver diagnostics", ""]
    for method in ("brent", "newton"):
        status = df[f"iv_{method}_status"].value_counts()
        lines += [f"- {method}: "+", ".join(f"{key}={value}" for key, value in status.items())]
    valid = df.loc[df.iv_brent_converged & ~df.iv_brent_poorly_identified]
    lines += [f"- Newton-to-Brent fallbacks: {int(df.iv_newton_fallback_used.sum())}.",
              f"- Identified Brent solves: {len(valid)}. Max absolute repricing residual: {valid.iv_brent_residual.abs().max():.6g}.",
              f"- Max numerical formula parity residual: {df.parity_residual.max():.6g}.",
              f"- Accepted midpoints outside European bounds: {int(df.european_bound_violation.sum())}.", ""]
    lines += ["## Where does the baseline perform best and worst?", "",
              "Ranked by descriptive MAE within asset/type/expiry groups with at least 5 quotes; this is not a forecast or causal test.", ""]
    eligible = summary.loc[(summary.dimension == "asset_type_expiry") & (summary.n >= 5)].sort_values("mae")
    if len(eligible):
        best, worst = eligible.iloc[0], eligible.iloc[-1]
        lines += [f"- Lowest MAE: {best['group']}, MAE {best.mae:.6g}, n={int(best.n)}.",
                  f"- Highest MAE: {worst['group']}, MAE {worst.mae:.6g}, n={int(worst.n)}."]
    else:
        lines += ["No group has at least 5 observations."]
    lines += ["", "## Implied forward, rate, and yield from put-call parity", "",
              "Per asset and expiry, call-minus-put midpoints are regressed on strike across matched pairs (implied_forward.csv).",
              "The slope implies the discount factor and rate; the intercept implies the discounted forward and the dividend yield.",
              "Compare these with the assumed r and q. American early exercise, stale quotes, and wide spreads bias the fit.", ""]
    fitted = forwards.loc[forwards.status == "ok"]
    lines += [f"- {row.symbol} {row.expiration}: n={int(row.n_pairs)}, implied r {row.implied_rate:.4f} (assumed {row.r:.4f}), "
              f"implied q {row.implied_yield:.4f} (assumed {row.q:.4f}), forward {row.implied_forward:.4f}, R² {row.r_squared:.6f}"
              for row in fitted.itertuples()] or ["- No asset/expiry has enough matched call-put pairs for a parity fit."]
    lines += ["", "## Moneyness, maturity, and liquidity", "",
              "metrics.csv reports fixed moneyness, tenor, IV, volume, open-interest, and relative-spread groups with sample sizes.",
              "plots/market_diagnostics.png displays these relationships. Correlation with liquidity does not isolate transaction costs or establish causation.",
              "smile_summary.csv reports local IV slopes versus ln(S/K) over |ln(S/K)| <= 0.15. Positive slope on this axis corresponds to IV increasing toward lower strikes.",
              "Provider-IV differences may reflect different spot, rate, dividend, exercise, or quote conventions; provider IV is not ground truth.", "",
              "## Assumptions and limits", "",
              "- Constant volatility: a nonflat IV curve is inconsistent with one common BSM volatility under the other maintained assumptions.",
              "- Constant rates and continuous dividend yield: r and q are explicit scenario inputs; discrete dividends and a term structure are not modeled.",
              "- European exercise: American early-exercise effects can contribute to residuals. European bounds/parity failures are not proof of market arbitrage.",
              "- Continuous trading and frictionless markets: spreads, discrete hedging, transaction costs, and asynchronous/delayed observations matter.",
              "- Lognormal price levels and continuous paths: jumps, fat-tailed returns, and stochastic volatility are omitted; one snapshot cannot identify their separate effects.",
              "- Yahoo capture time is not bid/ask quote time. lastTradeDate measures trade age only. PM expiry at the configured hour is an assumption; no holiday/early-close calendar is applied.",
              "- Historical realized volatility is a backward-looking independent comparator, not a risk-neutral forecast. A fixed volatility is a declared scenario.",
              "- BSM remains useful as a transparent benchmark, IV coordinate system, and local sensitivity model, even when assumptions fail.", "",
              "## Next empirical step", "",
              "Collect multiple dated snapshots across assets and market regimes; inspect spot/quote synchronization, rate/dividend sensitivity, and exclusion counts before interpreting market performance."]
    if synthetic:
        lines += ["", "The synthetic data deliberately contain a volatility skew and known bad quotes. Every result above demonstrates software behavior only."]
    if metadata.get("failures"):
        lines += ["", "Acquisition failures were recorded in snapshot metadata; requested coverage may be incomplete."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
