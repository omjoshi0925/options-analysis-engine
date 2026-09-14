"""Stale-quote diagnostic for Design B (Research Plan Amendment 5, exploratory).

Prior-session persistence benefits mechanically from unchanged quotes: when a
contract's mid at t equals its mid at t-1, B1 reprices the same number under
nearly the same inputs. This module measures how often that happens in set B,
how large mid changes are otherwise, and how the two Design B comparisons look
on the subset whose mid did change, with the pre-registered training windows
and models kept and only the evaluation rows restricted.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .carry_inputs import file_digest
from .compare import BLOCK_LENGTH, REPLICATES, SEED, SENSITIVITY_BLOCKS, block_indices, load_run, pair_statistics

SUBSETS = ("changed-mid", "unchanged-mid", "not-unchanged-mid")
PERCENTILES = (10, 25, 50, 75, 90)


def stale_quote_table(frame, baselines):
    """Per set B observation: the prior session's mid for the same contract, whether it is unchanged, and the breakdown keys."""
    needed = ["observation_id", "session_date", "symbol", "contractSymbol", "prior_session", "gap_days", "b1_source"]
    rows = baselines[needed].copy()
    at_t = frame[["observation_id", "mid", "spot", "strike", "T", "r", "q", "days_to_expiry"]]
    rows = rows.merge(at_t, on="observation_id", how="left")
    if rows.mid.isna().any():
        raise ValueError("Every set B observation must be in the frame")
    previous = frame[["symbol", "session_date", "contractSymbol", "mid"]].rename(columns={"session_date": "prior_session", "mid": "mid_prev"})
    rows = rows.merge(previous, on=["symbol", "prior_session", "contractSymbol"], how="left")
    rows["comparable"] = rows.mid_prev.notna()
    rows["unchanged"] = rows.comparable & ((rows.mid-rows.mid_prev).abs() < 1e-9)
    rows["relative_change"] = np.where(rows.comparable, (rows.mid-rows.mid_prev).abs()/rows.mid_prev, np.nan)
    forward = rows.spot.to_numpy(float)*np.exp((rows.r.to_numpy(float)-rows.q.to_numpy(float))*rows["T"].to_numpy(float))
    rows["abs_log_moneyness"] = np.abs(np.log(rows.strike.to_numpy(float)/forward))
    rows["maturity_bucket"] = pd.cut(rows.days_to_expiry.astype(float), [0, 30, 90, np.inf], labels=["<=30d", "31-90d", ">90d"]).astype(str)
    edges = np.quantile(rows.abs_log_moneyness, [1/3, 2/3])
    rows["moneyness_tercile"] = np.where(rows.abs_log_moneyness <= edges[0], "nearest", np.where(rows.abs_log_moneyness <= edges[1], "middle", "farthest"))
    gap = rows.gap_days.astype(float)
    rows["gap_bucket"] = np.where(gap >= 5, "5+", gap.astype(int).astype(str))
    rows.attrs["moneyness_tercile_edges"] = [float(e) for e in edges]
    return rows


def _block(sub):
    comparable = int(sub.comparable.sum())
    unchanged = int(sub.unchanged.sum())
    change = sub.relative_change.dropna()
    return dict(rows=int(len(sub)), comparable=comparable, unchanged=unchanged,
                unchanged_share_of_comparable=(unchanged/comparable if comparable else None),
                unchanged_share_of_rows=(unchanged/len(sub) if len(sub) else None),
                relative_change_percentiles={f"p{p}": (float(np.percentile(change, p)) if len(change) else None) for p in PERCENTILES},
                relative_change_mean=(float(change.mean()) if len(change) else None))


def summarize_stale(rows):
    out = dict(overall=_block(rows), moneyness_tercile_edges=rows.attrs.get("moneyness_tercile_edges"))
    for key, column in (("by_symbol", "symbol"), ("by_maturity_bucket", "maturity_bucket"), ("by_moneyness_tercile", "moneyness_tercile"),
                        ("by_gap_days", "gap_bucket"), ("by_b1_source", "b1_source")):
        order = sorted(rows[column].unique(), key=lambda v: (len(str(v)), str(v))) if column == "gap_bucket" else sorted(rows[column].unique())
        out[key] = {str(group): _block(rows.loc[rows[column] == group]) for group in order}
    return out


def write_subsets(rows, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    masks = {"changed-mid": rows.comparable & ~rows.unchanged, "unchanged-mid": rows.unchanged, "not-unchanged-mid": ~rows.unchanged}
    written = {}
    for name, mask in masks.items():
        path = out_dir/f"{name}.csv"
        if path.exists():
            raise ValueError(f"{path} exists; choose a new directory")
        keys = rows.loc[mask, ["observation_id", "session_date", "symbol"]].sort_values(["session_date", "symbol", "observation_id"])
        keys.to_csv(path, index=False)
        written[name] = dict(path=str(path), rows=int(len(keys)), sessions=int(keys.session_date.nunique()), sha256=file_digest(path),
                             definition={"changed-mid": "same contract quoted at t-1 and mid_t != mid_(t-1)",
                                         "unchanged-mid": "same contract quoted at t-1 and mid_t == mid_(t-1)",
                                         "not-unchanged-mid": "every set B row except unchanged-mid (interpolated B1 rows included)"}[name])
    return written


def build_stale_quote_stats(frame, baselines, out_dir, source_set=None, config=None):
    rows = stale_quote_table(frame, baselines)
    stats = summarize_stale(rows)
    subsets = write_subsets(rows, Path(out_dir)/"subsets")
    result = dict(amendment=5, exploratory=True, stats=stats, subsets=subsets, source_set=source_set, config=config,
                  note="Specified after the Design B result was known; no estimand, threshold, or decision rule changes.")
    path = Path(out_dir)/"stale-quote-stats.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return dict(result, path=str(path))


def _comparisons(runs, replicates):
    """M(RV) vs B1 and, when M-B1 is present, M(B1) vs B1 on the runs' common sessions."""
    sessions = [list(run["folds"].evaluated_session) for run in runs.values()]
    if any(s != sessions[0] for s in sessions[1:]):
        raise ValueError("Runs of one subset must evaluate the same sessions")
    n = len(sessions[0])
    if not np.allclose(runs["B1"]["folds"].baseline_mse, runs["B1"]["folds"].model_mse):
        raise ValueError("B1 must be a baseline-only run")
    indices = {BLOCK_LENGTH: block_indices(n, BLOCK_LENGTH, replicates, SEED)}
    for block in SENSITIVITY_BLOCKS:
        if block != BLOCK_LENGTH and block <= n:
            indices[block] = block_indices(n, block, replicates, SEED)
    b1 = runs["B1"]["folds"].baseline_mse.to_numpy(float)
    out = {"M(RV) vs B1": pair_statistics(b1, runs["M-RV"]["folds"].model_mse.to_numpy(float), indices, BLOCK_LENGTH, primary=True)}
    if "M-B1" in runs:
        if not np.allclose(runs["M-B1"]["folds"].baseline_mse, b1):
            raise ValueError("M-B1 and B1 disagree on the B1 losses")
        out["M(B1) vs B1"] = pair_statistics(b1, runs["M-B1"]["folds"].model_mse.to_numpy(float), indices, BLOCK_LENGTH, primary=False)
    return out, n


def report_stale_quote_diagnostic(stats_path, full_runs, sensitivity_dir, out_path, replicates=REPLICATES):
    stats = json.loads(Path(stats_path).read_text())
    full = {name: load_run(Path(full_runs)/name) for name in ("B1", "M-RV", "M-B1")}
    full_comparisons, full_sessions = _comparisons(full, replicates)
    sensitivity, rmse, runs_used = {}, {}, {}
    for subset in SUBSETS:
        folder = Path(sensitivity_dir)/subset
        if not folder.exists():
            continue
        runs = {name: load_run(folder/name) for name in ("B1", "M-RV", "M-B1") if (folder/name).exists()}
        if "B1" not in runs or "M-RV" not in runs:
            continue
        comparisons, n = _comparisons(runs, replicates)
        sensitivity[subset] = dict(sessions=n, comparisons=comparisons,
                                   skipped_sessions=runs["B1"]["significance"].get("evaluation_subset", {}).get("skipped_sessions"),
                                   evaluation_rows=int(runs["B1"]["folds"].evaluation_rows.sum()) if "evaluation_rows" in runs["B1"]["folds"] else None)
        rmse[subset] = dict(sessions=n, b1_median_session_rmse=float(np.median(np.sqrt(runs["B1"]["folds"].baseline_mse))),
                            m_rv_median_session_rmse=float(np.median(np.sqrt(runs["M-RV"]["folds"].model_mse))),
                            rv_median_session_rmse=float(np.median(np.sqrt(runs["M-RV"]["folds"].baseline_mse))))
        runs_used[subset] = {name: run["files"] for name, run in runs.items()}
    rmse["full set B"] = dict(sessions=full_sessions, b1_median_session_rmse=float(np.median(np.sqrt(full["B1"]["folds"].baseline_mse))),
                             m_rv_median_session_rmse=float(np.median(np.sqrt(full["M-RV"]["folds"].model_mse))),
                             rv_median_session_rmse=float(np.median(np.sqrt(full["M-RV"]["folds"].baseline_mse))))
    changes = []
    for subset, sub in sensitivity.items():
        for name, item in sub["comparisons"].items():
            if item["label"] != full_comparisons[name]["label"]:
                changes.append(f"{name} on {subset}: {full_comparisons[name]['label']} -> {item['label']}")
    result = dict(amendment=5, exploratory=True, stats=stats["stats"], subsets=stats["subsets"], moneyness_tercile_edges=stats["stats"].get("moneyness_tercile_edges"),
                  full_set_b=dict(sessions=full_sessions, comparisons=full_comparisons, runs={name: run["files"] for name, run in full.items()}),
                  sensitivity=sensitivity, b1_rmse_by_subset=rmse, label_changes=changes, sensitivity_runs=runs_used,
                  bootstrap=dict(block_length=BLOCK_LENGTH, replicates=replicates, seed=SEED, sensitivity_blocks=list(SENSITIVITY_BLOCKS)),
                  note=stats.get("note"))
    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return dict(result, path=str(out_path))
