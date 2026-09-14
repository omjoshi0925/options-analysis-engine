"""Design A comparison across carry configurations (Research Plan sections 3 and 6, Amendment 1).

Reads the fold tables of a control run (C0) and treatment runs (C1, C2, C3)
that share the same evaluated sessions, and computes, all at the session
level:

- per configuration: median rho, mean d, win rate, median session MSE for
  baseline and model, learned-coverage statistics, and the Diebold-Mariano
  (HLN) and Newey-West statistics on d, reported but not used for decisions;
- S_k = median(rho_k) / median(rho_0) with a paired circular block bootstrap
  interval: the same block indices resample numerator and denominator, so
  every ratio is computed within a replicate (block 21, 10,000 replicates,
  seed 20260908, percentile 95%), with sensitivity at blocks 10, 63, 126;
- the carry-only check, median(L_base,3) - median(L_model,0), paired the same
  way; the interval for the mean of d_3; and the section 3 decision label,
  applied mechanically.

All statistics use the session series exactly as written in folds.csv; no
fold is excluded.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .carry_inputs import file_digest
from .walkforward import hln_diebold_mariano

BLOCK_LENGTH = 21
REPLICATES = 10_000
SEED = 20260908
CONFIDENCE = .95
SENSITIVITY_BLOCKS = (10, 63, 126)


def load_run(path):
    path = Path(path)
    folds = pd.read_csv(path/"folds.csv")
    needed = {"evaluated_session", "baseline_mse", "model_mse", "rho", "d", "learned_coverage"}
    if missing := needed-set(folds.columns):
        raise ValueError(f"{path/'folds.csv'} lacks columns {sorted(missing)}")
    significance = json.loads((path/"significance.json").read_text()) if (path/"significance.json").exists() else {}
    return dict(name=path.name, path=str(path), folds=folds, significance=significance,
                files={name: dict(path=str(path/name), sha256=file_digest(path/name)) for name in ("folds.csv", "significance.json", "REPORT.md")
                       if (path/name).exists()})


def aligned_sessions(runs):
    sessions = [list(run["folds"].evaluated_session) for run in runs.values()]
    if any(s != sessions[0] for s in sessions[1:]):
        raise ValueError("Runs must evaluate the same sessions in the same order; the observation set guarantees this")
    return sessions[0]


def block_indices(n, block_length, replicates, seed):
    """Circular block bootstrap index matrix (replicates x n); one matrix serves every paired statistic."""
    if not 1 <= block_length <= n:
        raise ValueError("block_length must be between 1 and the number of sessions")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n/block_length)
    starts = rng.integers(0, n, size=(replicates, blocks))
    offsets = np.arange(block_length)
    return ((starts[:, :, None]+offsets[None, None, :]) % n).reshape(replicates, blocks*block_length)[:, :n]


def percentile_interval(values, confidence=CONFIDENCE):
    lo, hi = np.quantile(values, [(1-confidence)/2, 1-(1-confidence)/2])
    return float(lo), float(hi)


def paired_ratio_of_medians(numerator, denominator, indices):
    return np.median(numerator[indices], axis=1)/np.median(denominator[indices], axis=1)


def summarize(run):
    folds = run["folds"]
    coverage = folds.learned_coverage.to_numpy(float)
    d = folds.d.to_numpy(float)
    n = len(folds)
    lags = max(1, math.floor(1.5*n**(1/3)))
    dm = hln_diebold_mariano(folds.baseline_mse.to_numpy(float), folds.model_mse.to_numpy(float))
    nw = hln_diebold_mariano(folds.baseline_mse.to_numpy(float), folds.model_mse.to_numpy(float), hac_lags=lags)
    return dict(folds=int(n), first_session=str(folds.evaluated_session.iloc[0]), last_session=str(folds.evaluated_session.iloc[-1]),
                median_rho=float(folds.rho.median()), mean_d=float(d.mean()),
                win_rate=float((folds.model_mse < folds.baseline_mse).mean()),
                median_baseline_mse=float(folds.baseline_mse.median()), median_model_mse=float(folds.model_mse.median()),
                mean_baseline_rmse=float(np.sqrt(folds.baseline_mse).mean()), mean_model_rmse=float(np.sqrt(folds.model_mse).mean()),
                learned_coverage=dict(mean=float(coverage.mean()), zero_coverage_folds=int((coverage == 0).sum()),
                                      partial_coverage_folds=int(((coverage > 0) & (coverage < 1)).sum())),
                diebold_mariano_hln=dict(statistic=dm["statistic"], p_value=dm["p_value"], lag1_autocorrelation=dm["lag1_autocorrelation"]),
                newey_west=dict(statistic=nw["statistic"], p_value=nw["p_value"], hac_lags=lags),
                config=run["significance"].get("config"), carry=run["significance"].get("carry"))


def decision(s3, s3_interval, mean_d3_interval):
    """Section 3 decision rule, applied mechanically."""
    low, high = s3_interval
    if s3 < .5 and high < .75:
        label = "compensation dominant"
    elif s3 >= .75 and low > .5:
        label = "structure dominant"
    else:
        label = "mixed or inconclusive"
    survived = not (mean_d3_interval[0] <= 0 <= mean_d3_interval[1])
    return dict(label=label, s3=s3, s3_interval=list(s3_interval),
                v1_improvement_survives_carry_correction=survived,
                headline=("the v1 improvement did not survive carry correction: the 95% interval for the mean of d_3 includes zero"
                          if not survived else f"S_3 = {s3:.3f} with 95% interval [{low:.3f}, {high:.3f}]: {label}"))


def compare_configs(runs, control="C0", treatment="C3", block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED,
                    sensitivity=SENSITIVITY_BLOCKS):
    if control not in runs or treatment not in runs:
        raise ValueError(f"Need runs named {control} and {treatment}; have {sorted(runs)}")
    sessions = aligned_sessions(runs)
    n = len(sessions)
    rho = {name: run["folds"].rho.to_numpy(float) for name, run in runs.items()}
    others = [name for name in runs if name != control]
    indices = {block_length: block_indices(n, block_length, replicates, seed)}
    skipped = []
    for block in sensitivity:
        if block == block_length:
            continue
        if block > n:
            skipped.append(block)                       # a block longer than the sample cannot be resampled; reported as n/a
            continue
        indices[block] = block_indices(n, block, replicates, seed)
    control_median = float(np.median(rho[control]))
    if control_median == 0:
        raise ValueError("The control's median rho is zero, so S_k is undefined")
    ratios = {}
    for name in others:
        point = float(np.median(rho[name]))/control_median
        intervals = {str(block): list(percentile_interval(paired_ratio_of_medians(rho[name], rho[control], idx)))
                     for block, idx in indices.items()}
        intervals.update({str(block): None for block in skipped})
        ratios[name] = dict(s=point, median_rho=float(np.median(rho[name])), interval=intervals[str(block_length)], sensitivity=intervals)
    base_t = runs[treatment]["folds"].baseline_mse.to_numpy(float)
    model_c = runs[control]["folds"].model_mse.to_numpy(float)
    carry_only = dict(definition=f"median(L_base,{treatment}) - median(L_model,{control})",
                      value=float(np.median(base_t)-np.median(model_c)),
                      interval=list(percentile_interval(np.median(base_t[indices[block_length]], axis=1)-np.median(model_c[indices[block_length]], axis=1))),
                      median_baseline_mse_treatment=float(np.median(base_t)), median_model_mse_control=float(np.median(model_c)))
    d_t = runs[treatment]["folds"].d.to_numpy(float)
    mean_d = dict(value=float(d_t.mean()), interval=list(percentile_interval(d_t[indices[block_length]].mean(axis=1))),
                  sensitivity={**{str(block): list(percentile_interval(d_t[idx].mean(axis=1))) for block, idx in indices.items()},
                               **{str(block): None for block in skipped}})
    label = decision(ratios[treatment]["s"], tuple(ratios[treatment]["interval"]), tuple(mean_d["interval"]))
    return dict(control=control, treatment=treatment, sessions=n, first_session=sessions[0], last_session=sessions[-1],
                bootstrap=dict(kind="circular block, paired (identical block indices for every series)", block_length=block_length,
                               replicates=replicates, seed=seed, confidence=CONFIDENCE, sensitivity_blocks=list(sensitivity),
                               sensitivity_blocks_skipped=skipped),
                configurations={name: summarize(run) for name, run in runs.items()},
                s=ratios, carry_only_check=carry_only, mean_d_treatment=mean_d, decision=label,
                runs={name: dict(path=run["path"], files=run["files"]) for name, run in runs.items()})


def _fmt(value, spec):
    return "n/a" if value is None else format(value, spec)


def write_report(result, path):
    lines = [f"# Design A: carry robustness ({result['control']} control, {result['treatment']} full correction)", "",
             f"{result['sessions']} evaluated sessions from {result['first_session']} to {result['last_session']}, identical across runs. "
             f"Intervals: paired circular block bootstrap, block {result['bootstrap']['block_length']}, {result['bootstrap']['replicates']:,} replicates, "
             f"seed {result['bootstrap']['seed']}, percentile {result['bootstrap']['confidence']:.0%}.", "",
             "| Run | Folds | Median rho | Mean d | Win rate | Median baseline MSE | Median model MSE | Coverage mean | Zero-coverage folds | DM (HLN) | Newey-West |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, item in result["configurations"].items():
        dm, nw = item["diebold_mariano_hln"], item["newey_west"]
        lines.append(f"| {name} | {item['folds']} | {item['median_rho']:.4f} | {item['mean_d']:.3e} | {item['win_rate']:.3f} | "
                     f"{item['median_baseline_mse']:.3e} | {item['median_model_mse']:.3e} | {item['learned_coverage']['mean']:.4f} | "
                     f"{item['learned_coverage']['zero_coverage_folds']} | {_fmt(dm['statistic'], '.2f')} (p = {_fmt(dm['p_value'], '.2g')}) | "
                     f"{_fmt(nw['statistic'], '.2f')} (p = {_fmt(nw['p_value'], '.2g')}, {nw['hac_lags']} lags) |")
    lines += ["", "## S_k = median rho_k / median rho_0", "", "| k | S_k | 95% interval (block 21) | " +
              " | ".join(f"block {b}" for b in result["bootstrap"]["sensitivity_blocks"]) + " |",
              "|---|---:|---:|" + "---:|"*len(result["bootstrap"]["sensitivity_blocks"])]
    for name, item in result["s"].items():
        row = f"| {name} | {item['s']:.3f} | [{item['interval'][0]:.3f}, {item['interval'][1]:.3f}] |"
        for b in result["bootstrap"]["sensitivity_blocks"]:
            bounds = item["sensitivity"].get(str(b))
            row += " n/a (block longer than the sample) |" if bounds is None else f" [{bounds[0]:.3f}, {bounds[1]:.3f}] |"
        lines.append(row)
    carry, mean_d = result["carry_only_check"], result["mean_d_treatment"]
    lines += ["", "## Carry-only check and the full-correction differential", "",
              f"- {carry['definition']} = {carry['value']:.3e}, 95% interval [{carry['interval'][0]:.3e}, {carry['interval'][1]:.3e}] "
              f"(median baseline MSE under {result['treatment']} {carry['median_baseline_mse_treatment']:.3e}; median model MSE under {result['control']} "
              f"{carry['median_model_mse_control']:.3e}).",
              f"- Mean d_{result['treatment'][-1]} = {mean_d['value']:.3e}, 95% interval [{mean_d['interval'][0]:.3e}, {mean_d['interval'][1]:.3e}]; "
              + "; ".join(f"block {b}: [{bounds[0]:.3e}, {bounds[1]:.3e}]" if bounds else f"block {b}: n/a"
                          for b, bounds in mean_d["sensitivity"].items() if int(b) != result["bootstrap"]["block_length"]) + ".",
              "", "## Decision (section 3 rule, applied mechanically)", "",
              f"**{result['decision']['label']}**: {result['decision']['headline']}.", "",
              "Compensation dominant if S_3 < 0.5 and the upper bound is below 0.75; structure dominant if S_3 >= 0.75 and the lower bound is above 0.5; "
              "otherwise mixed or inconclusive. Separately, a mean d_3 interval that includes zero means the v1 improvement did not survive carry correction.",
              "", "Diebold-Mariano and Newey-West values are reported for continuity with v1 and are not used for decisions."]
    Path(path).write_text("\n".join(lines)+"\n")


def run_comparison(run_dirs, output, control="C0", treatment="C3", block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED):
    runs = {Path(p).name: load_run(p) for p in run_dirs}
    result = compare_configs(runs, control=control, treatment=treatment, block_length=block_length, replicates=replicates, seed=seed)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/"comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    write_report(result, output/"REPORT.md")
    return result


# ----------------------------------------------------------------------------- Design B
DESIGN_B_RUNS = ("B1", "B2", "M-RV", "M-B1", "M-B2")
DESIGN_B_PAIRS = (("M(RV)", "B1", True), ("M(RV)", "B2", False), ("M(B1)", "B1", False), ("M(B2)", "B2", False))


def design_b_series(runs):
    """Session-level loss series for every competitor, with the consistency checks the five-run layout implies."""
    for name in DESIGN_B_RUNS:
        if name not in runs:
            raise ValueError(f"Design B needs runs named {DESIGN_B_RUNS}; missing {name}")
    aligned_sessions(runs)
    folds = {name: run["folds"] for name, run in runs.items()}
    for alone, learned in (("B1", "M-B1"), ("B2", "M-B2")):
        if not np.allclose(folds[alone].baseline_mse, folds[learned].baseline_mse):
            raise ValueError(f"{alone} alone and {learned} disagree on the {alone} baseline losses; the runs must share set B and folds")
        if not np.allclose(folds[alone].model_mse, folds[alone].baseline_mse):
            raise ValueError(f"{alone} alone must be a baseline-only run")
    return {"B1": folds["B1"].baseline_mse.to_numpy(float), "B2": folds["B2"].baseline_mse.to_numpy(float),
            "RV": folds["M-RV"].baseline_mse.to_numpy(float), "M(RV)": folds["M-RV"].model_mse.to_numpy(float),
            "M(B1)": folds["M-B1"].model_mse.to_numpy(float), "M(B2)": folds["M-B2"].model_mse.to_numpy(float)}


def pair_statistics(baseline, model, indices, block_length, primary=False):
    """Mean of L_baseline - L_model with paired block-bootstrap intervals, the median relative improvement, and the label."""
    diff = baseline-model
    rho = 1-np.sqrt(model)/np.sqrt(baseline)
    intervals = {str(block): list(percentile_interval(diff[idx].mean(axis=1))) for block, idx in indices.items()}
    rho_intervals = {str(block): list(percentile_interval(np.median(rho[idx], axis=1))) for block, idx in indices.items()}
    low, high = intervals[str(block_length)]
    n = len(diff)
    lags = max(1, math.floor(1.5*n**(1/3)))
    dm = hln_diebold_mariano(baseline, model)
    nw = hln_diebold_mariano(baseline, model, hac_lags=lags)
    median_rho = float(np.median(rho))
    if primary:
        holds = low > 0 and median_rho > 0
        label = "adds value" if holds else ("baseline wins" if high < 0 else "no evidence either way")
    else:
        label = "adds value" if low > 0 else ("baseline wins" if high < 0 else "no evidence either way")
        holds = low > 0
    return dict(mean_differential=float(diff.mean()), interval=list(intervals[str(block_length)]), sensitivity=intervals,
                median_relative_improvement=median_rho, median_relative_improvement_interval=rho_intervals[str(block_length)],
                win_rate=float((model < baseline).mean()), label=label, claim_holds=bool(holds),
                diebold_mariano_hln=dict(statistic=dm["statistic"], p_value=dm["p_value"], lag1_autocorrelation=dm["lag1_autocorrelation"]),
                newey_west=dict(statistic=nw["statistic"], p_value=nw["p_value"], hac_lags=lags))


def section_8_reading(primary, incremental):
    """What the primary result means, per Research Plan section 8."""
    if primary["claim_holds"]:
        return "The learned model adds value beyond the prior-session implied volatility: the interval for the mean of L_B1 - L_M(RV) lies above zero and the median relative improvement is positive."
    if primary["label"] == "baseline wins":
        reading = ("B1 beats M(RV): the v1 model captured structure that a flat baseline lacks but no more than persistence of the previous smile provides; "
                   "the value claim is downgraded to that statement and M(B1) versus B1 becomes the relevant test of incremental value. ")
        if incremental["claim_holds"]:
            return reading+"M(B1) versus B1 excludes zero above, so the adjustment adds value beyond persistence when learned relative to it."
        return reading+"M(B1) versus B1 does not exclude zero above: no incremental value beyond persistence."
    return ("Inconclusive: the interval for the mean of L_B1 - L_M(RV) includes zero, so neither the value claim nor its downgrade is established; "
            "the interval is reported as is and no setting is changed.")


def compare_baselines(runs, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED, sensitivity=SENSITIVITY_BLOCKS,
                      b2_fallback=None, design_a=None):
    series = design_b_series(runs)
    sessions = aligned_sessions(runs)
    n = len(sessions)
    indices = {block_length: block_indices(n, block_length, replicates, seed)}
    skipped = []
    for block in sensitivity:
        if block == block_length:
            continue
        if block > n:
            skipped.append(block)
            continue
        indices[block] = block_indices(n, block, replicates, seed)
    contaminated = bool(b2_fallback and b2_fallback.get("fallback_contaminated"))
    comparisons = {}
    for model, baseline, primary in DESIGN_B_PAIRS:
        item = pair_statistics(series[baseline], series[model], indices, block_length, primary=primary)
        item.update(model=model, baseline=baseline, primary=primary)
        for key in ("sensitivity",):
            item[key].update({str(block): None for block in skipped})
        if baseline == "B2" and contaminated:
            item["note"] = "B2 is fallback-contaminated (Amendment 4): reported, not used for the secondary claim"
            item["claim_holds"] = False
        comparisons[f"{model} vs {baseline}"] = item
    primary = comparisons["M(RV) vs B1"]
    reading = section_8_reading(primary, comparisons["M(B1) vs B1"])
    control = dict(set_b=dict(M_RV=summarize(runs["M-RV"]), RV_median_mse=float(np.median(series["RV"])), M_RV_median_mse=float(np.median(series["M(RV)"]))))
    if design_a:
        c3 = design_a.get("configurations", {}).get("C3")
        control["set_a_C3"] = {k: c3[k] for k in ("folds", "median_rho", "mean_d", "win_rate", "median_baseline_mse", "median_model_mse")} if c3 else None
    return dict(sessions=n, first_session=sessions[0], last_session=sessions[-1],
                bootstrap=dict(kind="circular block, paired (identical block indices for every series)", block_length=block_length,
                               replicates=replicates, seed=seed, confidence=CONFIDENCE, sensitivity_blocks=list(sensitivity),
                               sensitivity_blocks_skipped=skipped),
                runs={name: summarize(run) for name, run in runs.items()},
                comparisons=comparisons, primary_claim=dict(holds=primary["claim_holds"], label=primary["label"], reading=reading),
                b2_fallback=b2_fallback, b2_fallback_contaminated=contaminated, set_b_control=control,
                files={name: dict(path=run["path"], files=run["files"]) for name, run in runs.items()})


def write_baselines_report(result, path):
    b = result["bootstrap"]
    lines = ["# Design B: stronger baselines on set B", "",
             f"{result['sessions']} evaluated sessions from {result['first_session']} to {result['last_session']}, identical across the five runs. "
             f"Intervals: paired circular block bootstrap, block {b['block_length']}, {b['replicates']:,} replicates, seed {b['seed']}, percentile {b['confidence']:.0%}.",
             "", "| Comparison | Mean L_baseline - L_model | 95% interval (block 21) | " + " | ".join(f"block {x}" for x in b["sensitivity_blocks"]) +
             " | Median relative improvement | Win rate | DM (HLN) | Newey-West | Label |",
             "|---|---:|---:|" + "---:|"*len(b["sensitivity_blocks"]) + "---:|---:|---:|---:|---|"]
    for name, item in result["comparisons"].items():
        row = f"| {name}{' (primary)' if item['primary'] else ''} | {item['mean_differential']:.3e} | [{item['interval'][0]:.3e}, {item['interval'][1]:.3e}] |"
        for x in b["sensitivity_blocks"]:
            bounds = item["sensitivity"].get(str(x))
            row += " n/a |" if bounds is None else f" [{bounds[0]:.2e}, {bounds[1]:.2e}] |"
        dm, nw = item["diebold_mariano_hln"], item["newey_west"]
        row += (f" {item['median_relative_improvement']:.4f} [{item['median_relative_improvement_interval'][0]:.3f}, {item['median_relative_improvement_interval'][1]:.3f}] | "
                f"{item['win_rate']:.3f} | {_fmt(dm['statistic'], '.2f')} (p = {_fmt(dm['p_value'], '.2g')}) | {_fmt(nw['statistic'], '.2f')} (p = {_fmt(nw['p_value'], '.2g')}, {nw['hac_lags']} lags) | "
                f"{item['label']}{' (fallback-contaminated B2)' if item.get('note') else ''} |")
        lines.append(row)
    lines += ["", "## Primary claim (section 4 rule, applied mechanically)", "",
              f"**{'holds' if result['primary_claim']['holds'] else 'does not hold'}**: {result['primary_claim']['reading']}", "",
              "The claim requires the interval for the mean of L_B1 - L_M(RV) to lie entirely above zero and the median relative improvement to be positive. "
              "Secondary labels attach only where the interval excludes zero.", ""]
    caveats = []
    for name, item in result["comparisons"].items():
        if item["label"] != "adds value":
            continue
        weak = []
        if item["median_relative_improvement"] <= 0:
            weak.append(f"the median relative improvement is {item['median_relative_improvement']:.4f}, so the mean gain comes from a minority of sessions")
        if item["win_rate"] < .5:
            weak.append(f"the model loses in {1-item['win_rate']:.1%} of sessions")
        wide = [b for b, bounds in item["sensitivity"].items() if bounds and bounds[0] <= 0 <= bounds[1]]
        if wide:
            weak.append("the interval includes zero at block length" + ("s " if len(wide) > 1 else " ") + ", ".join(wide))
        if weak:
            caveats.append(f"- {name}: labeled by the block-21 interval alone; " + "; ".join(weak) + ".")
    if caveats:
        lines += ["## Caveats on labels that rest on the mean alone", "", *caveats, ""]
    fb = result.get("b2_fallback") or {}
    if fb:
        lines += ["## B2 fallback accounting (Amendment 4)", "",
                  f"- SVI slices attempted {fb.get('slices_attempted')}, fitted {fb.get('slices_fitted')}, fallback rate {fb.get('slice_fallback_rate', 0):.1%} by reason {fb.get('slices_fallback_by_reason')}; "
                  f"rows by source {fb.get('rows_by_source')}. Fallback-contaminated: {result['b2_fallback_contaminated']}.", ""]
    control = result["set_b_control"]
    m_rv = control["set_b"]["M_RV"]
    lines += ["## Set B control (Amendment 4)", "",
              "| Run | Folds | Median rho | Mean d | Win rate | Median baseline MSE | Median model MSE |", "|---|---:|---:|---:|---:|---:|---:|",
              f"| M(RV) on set B | {m_rv['folds']} | {m_rv['median_rho']:.4f} | {m_rv['mean_d']:.3e} | {m_rv['win_rate']:.3f} | {m_rv['median_baseline_mse']:.3e} | {m_rv['median_model_mse']:.3e} |"]
    if control.get("set_a_C3"):
        c3 = control["set_a_C3"]
        lines.append(f"| C3 on set A (Design A) | {c3['folds']} | {c3['median_rho']:.4f} | {c3['mean_d']:.3e} | {c3['win_rate']:.3f} | {c3['median_baseline_mse']:.3e} | {c3['median_model_mse']:.3e} |")
    lines += ["", "Diebold-Mariano and Newey-West values are reported for continuity with v1 and are not used for decisions."]
    Path(path).write_text("\n".join(lines)+"\n")


def run_baseline_comparison(run_dirs, output, set_b_sidecar=None, design_a=None, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED):
    runs = {Path(p).name: load_run(p) for p in run_dirs}
    b2_fallback = json.loads(Path(set_b_sidecar).read_text()).get("b2") if set_b_sidecar else None
    design = json.loads(Path(design_a).read_text()) if design_a else None
    result = compare_baselines(runs, block_length=block_length, replicates=replicates, seed=seed, b2_fallback=b2_fallback, design_a=design)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/"comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    write_baselines_report(result, output/"REPORT.md")
    return result

