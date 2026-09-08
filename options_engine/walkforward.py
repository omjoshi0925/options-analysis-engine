"""Rolling-origin walk-forward evaluation with significance tests.

The single chronological split in `learning.train` answers the promotion
question for one deployment moment. This module answers the research question:
across every available origin, does the learned volatility adjustment price the
next unseen session better than the independent baseline, and is the
improvement statistically distinguishable from zero?

Design choices, stated so they can be challenged:
- One fold per evaluated session. Quotes within a session are heavily
  dependent, so per-quote losses are averaged to a single session loss before
  any test is run; tests then operate on the session-level loss differential.
- An embargo of `gap` sessions separates each training window from its
  evaluation session, matching the promotion pipeline's leakage discipline.
- Hyperparameters are re-selected inside every fold on the tail of that fold's
  own training window; the evaluation session is never touched before scoring.
- Diebold-Mariano uses the Harvey-Leybourne-Newbold small-sample correction and
  a Student-t reference. The block bootstrap is circular, resampling whole
  blocks of consecutive sessions to respect serial dependence.
All of this measures contemporaneous pricing accuracy on later sessions. It is
not a forecast of option returns and not a tradable claim.
"""
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .learning import evaluate, fit_ridge
from .live_utils import atomic_json, clean_json

DEFAULT_ALPHAS = (.01, 1.0, 100.0)


@dataclass(frozen=True)
class WalkForwardSpec:
    min_train_sessions: int = 12
    gap: int = 1
    validation_sessions: int = 2
    window: str = "expanding"
    max_train_sessions: int | None = None
    alphas: tuple = DEFAULT_ALPHAS

    def __post_init__(self):
        if self.window not in ("expanding", "rolling"):
            raise ValueError("window must be expanding or rolling")
        if self.min_train_sessions < 4 or self.gap < 0 or self.validation_sessions < 1:
            raise ValueError("Need min_train_sessions >= 4, gap >= 0, validation_sessions >= 1")
        if self.validation_sessions >= self.min_train_sessions:
            raise ValueError("validation_sessions must be smaller than min_train_sessions")
        if self.window == "rolling" and (self.max_train_sessions or 0) < self.min_train_sessions:
            raise ValueError("A rolling window needs max_train_sessions >= min_train_sessions")
        if not self.alphas or any(not math.isfinite(a) or a < 0 for a in self.alphas):
            raise ValueError("alphas must be nonnegative and finite")


def fit_fold(train_frame, spec):
    """Select alpha on the training tail, then refit on the whole training window."""
    sessions = sorted(train_frame.session_date.unique())
    tail = sessions[-spec.validation_sessions:]
    inner_train = train_frame.loc[~train_frame.session_date.isin(tail)]
    inner_validation = train_frame.loc[train_frame.session_date.isin(tail)]
    scored = []
    for alpha in spec.alphas:
        candidate = fit_ridge(inner_train, alpha)
        metrics, _, _ = evaluate(candidate, inner_validation)
        scored.append((metrics["spot_normalized_rmse"], alpha))
    _, best_alpha = min(scored)
    return fit_ridge(train_frame, best_alpha), best_alpha


def walk_forward(frame, spec=None):
    """One fold per evaluable session; returns fold table and session-level loss series."""
    spec = spec or WalkForwardSpec()
    if frame.empty or "session_date" not in frame:
        raise ValueError("Walk-forward needs a training frame with session_date")
    sessions = sorted(frame.session_date.unique())
    first_eval = spec.min_train_sessions+spec.gap
    if len(sessions) < first_eval+1:
        raise ValueError(f"Need at least {first_eval+1} sessions for one fold; have {len(sessions)}")
    by_session = {day: group for day, group in frame.groupby("session_date")}
    folds = []
    for j in range(first_eval, len(sessions)):
        train_sessions = sessions[:j-spec.gap]
        if spec.window == "rolling":
            train_sessions = train_sessions[-spec.max_train_sessions:]
        train_frame = pd.concat([by_session[day] for day in train_sessions], ignore_index=True)
        evaluation = by_session[sessions[j]]
        model, alpha = fit_fold(train_frame, spec)
        base_metrics, base_prices, _ = evaluate(None, evaluation)
        model_metrics, model_prices, _ = evaluate(model, evaluation)
        mid, spot = evaluation.mid.to_numpy(float), evaluation.spot.to_numpy(float)
        folds.append(dict(evaluated_session=sessions[j], train_start=train_sessions[0],
                          train_end=train_sessions[-1], train_sessions=len(train_sessions),
                          train_rows=len(train_frame), evaluation_rows=len(evaluation), alpha=alpha,
                          baseline_loss=float(np.mean(((base_prices-mid)/spot)**2)),
                          model_loss=float(np.mean(((model_prices-mid)/spot)**2)),
                          baseline_rmse=base_metrics["spot_normalized_rmse"],
                          model_rmse=model_metrics["spot_normalized_rmse"],
                          model_within_spread=model_metrics["within_spread"],
                          baseline_within_spread=base_metrics["within_spread"],
                          learned_coverage=model_metrics["learned_coverage"]))
    table = pd.DataFrame(folds)
    return dict(folds=table, spec=asdict(spec), sessions=list(table.evaluated_session),
                baseline_losses=table.baseline_loss.to_numpy(), model_losses=table.model_loss.to_numpy())


def hln_diebold_mariano(baseline_losses, model_losses, horizon=1):
    """DM test on the loss differential (baseline minus model; positive favors the model).

    HAC variance with `horizon-1` lags, Harvey-Leybourne-Newbold correction,
    and a Student-t(n-1) reference distribution. Two-sided p-value.
    """
    from scipy import stats
    differential = np.asarray(baseline_losses, float)-np.asarray(model_losses, float)
    n = len(differential)
    if n < 8:
        raise ValueError("Diebold-Mariano needs at least 8 folds")
    if horizon < 1 or horizon > n//2:
        raise ValueError("horizon must be between 1 and half the fold count")
    mean = float(differential.mean())
    centered = differential-mean
    variance = float(centered@centered)/n
    for lag in range(1, horizon):
        cov = float(centered[lag:]@centered[:-lag])/n
        variance += 2.0*cov
    correction = math.sqrt(max((n+1-2*horizon+horizon*(horizon-1)/n)/n, 0.0))
    if variance <= 0:
        # A constant differential: direction is certain within the sample, scale is not testable.
        statistic = math.inf*np.sign(mean) if mean else 0.0
        p_value = 0.0 if mean else 1.0
    else:
        statistic = correction*mean/math.sqrt(variance/n)
        p_value = float(2*stats.t.sf(abs(statistic), df=n-1))
    return dict(statistic=float(statistic), p_value=p_value, folds=n, horizon=horizon,
                mean_differential=mean, hln_correction=correction,
                favors="model" if mean > 0 else ("baseline" if mean < 0 else "neither"))


def circular_block_bootstrap_ci(values, n_boot=2000, block_length=None, confidence=.95, seed=0):
    """Percentile CI for the mean of a serially dependent series via circular block resampling."""
    values = np.asarray(values, float)
    n = len(values)
    if n < 8:
        raise ValueError("Bootstrap needs at least 8 observations")
    block_length = int(block_length) if block_length is not None else max(1, round(n**(1/3)))
    if not 1 <= block_length <= n:
        raise ValueError("block_length must be between 1 and the series length")
    if not .5 < confidence < 1:
        raise ValueError("confidence must be in (0.5, 1)")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n/block_length)
    doubled = np.concatenate([values, values])
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=blocks)
        sample = np.concatenate([doubled[s:s+block_length] for s in starts])[:n]
        means[b] = sample.mean()
    lo, hi = np.quantile(means, [(1-confidence)/2, 1-(1-confidence)/2])
    return dict(mean=float(values.mean()), low=float(lo), high=float(hi), confidence=confidence,
                block_length=block_length, replications=n_boot,
                excludes_zero=bool(lo > 0 or hi < 0))


def walk_forward_report(result, output, n_boot=2000, seed=0):
    """folds.csv, significance.json, and a REPORT.md with the honest interpretation."""
    output = Path(output)
    if output.exists():
        raise ValueError("Walk-forward output exists; choose a new directory")
    output.mkdir(parents=True)
    table = result["folds"]
    table.to_csv(output/"folds.csv", index=False)
    differential = result["baseline_losses"]-result["model_losses"]
    dm = hln_diebold_mariano(result["baseline_losses"], result["model_losses"])
    ci = circular_block_bootstrap_ci(differential, n_boot=n_boot, seed=seed)
    wins = float((table.model_loss < table.baseline_loss).mean())
    significance = dict(diebold_mariano=dm, bootstrap_mean_differential=ci, model_win_rate=wins,
                        spec=result["spec"], sessions_evaluated=len(table))
    atomic_json(output/"significance.json", clean_json(significance))
    lines = ["# Walk-forward evaluation", "",
             f"{len(table)} folds, one held-out session each, from {table.evaluated_session.iloc[0]} "
             f"to {table.evaluated_session.iloc[-1]}. Window: {result['spec']['window']}, "
             f"embargo gap: {result['spec']['gap']} session(s).", "",
             "| Quantity | Value |", "|---|---:|",
             f"| Model win rate (session loss) | {wins:.3f} |",
             f"| Mean loss differential (baseline - model) | {dm['mean_differential']:.3e} |",
             f"| Diebold-Mariano statistic (HLN) | {dm['statistic']:.3f} |",
             f"| Two-sided p-value | {dm['p_value']:.4g} |",
             f"| Bootstrap {ci['confidence']:.0%} CI for the differential | [{ci['low']:.3e}, {ci['high']:.3e}] |",
             f"| CI excludes zero | {ci['excludes_zero']} |", "",
             "Losses are session means of squared spot-normalized pricing errors against",
             "contemporaneous midpoints. A positive differential favors the learned model.",
             "This measures pricing accuracy on later sessions under the maintained",
             "assumptions; it is not a forecast of option returns and not a tradable claim.",
             "Session-level aggregation and the block bootstrap address serial dependence,",
             "but overlapping contract lives still link adjacent sessions."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    return significance
