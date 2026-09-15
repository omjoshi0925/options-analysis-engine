"""Design C attribution (Research Plan section 5, Amendment 5). Everything here is exploratory.

Ablations refit the learner without one feature group at a time on the same
folds and report the change in the mean loss differential against the full
model with a paired block-bootstrap interval. Breakdowns split the per-row
pricing errors of a model and a reference method into cells (symbol, maturity
bucket, moneyness tercile, VIX regime, gap to the prior available session),
aggregate to session losses inside each cell, and report d and rho per cell.
No multiplicity adjustment is applied and no claim here is confirmatory.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .carry_inputs import as_date, file_digest
from .compare import BLOCK_LENGTH, REPLICATES, SEED, SENSITIVITY_BLOCKS, block_indices, load_run, percentile_interval

EXPLORATORY = ("Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no "
               "multiplicity adjustment.")
SYMBOL_NOTE = "With two symbols the symbol ablation removes one indicator, a single SPY/AAPL contrast, not a group of features."
MIN_SESSIONS_FOR_INTERVAL = 30
TOP_SESSIONS = 10
MATURITY_EDGES = [0, 30, 90, np.inf]
MATURITY_LABELS = ["<=30d", "31-90d", ">90d"]
TERCILE_LABELS = ("low", "middle", "high")


class DatedSeries:
    """A FRED-style daily series with strictly-prior lookup; blank and "." rows are missing."""

    def __init__(self, dates, values, source=None):
        pairs = sorted(zip((as_date(d) for d in dates), (float(v) for v in values), strict=True))
        self.dates = [d for d, _ in pairs]
        self.values = [v for _, v in pairs]
        self.source = source

    @classmethod
    def from_fred_csv(cls, path):
        dates, values = [], []
        with open(path, newline="") as stream:
            for row in csv.DictReader(stream):
                text = (list(row.values())[1] or "").strip()
                if text in ("", "."):
                    continue
                dates.append(list(row.values())[0])
                values.append(float(text))
        return cls(dates, values, source=str(path))

    def value_before(self, day):
        day = as_date(day)
        index = bisect.bisect_left(self.dates, day)
        if index == 0:
            raise ValueError(f"no observation dated before {day}")
        return self.dates[index-1], self.values[index-1]


def tercile_cuts(values):
    return [float(x) for x in np.quantile(np.asarray(values, float), [1/3, 2/3])]


def assign_tercile(values, cuts):
    values = np.asarray(values, float)
    return np.where(values <= cuts[0], TERCILE_LABELS[0], np.where(values <= cuts[1], TERCILE_LABELS[1], TERCILE_LABELS[2]))


def gap_bucket(gap_days):
    gap = np.asarray(gap_days, float)
    return np.where(gap >= 5, "5+", gap.astype(int).astype(str))


# ----------------------------------------------------------------------------- ablations
def mean_d_concentration(d, top=TOP_SESSIONS):
    """How much of the mean differential a few sessions carry: the share of the sum of d held by the `top` largest sessions
    (above 1 when the remaining sessions net negative) and the mean of d with those sessions removed."""
    d = np.sort(np.asarray(d, float))[::-1]
    total = float(d.sum())
    return dict(top_sessions=int(top), share_of_sum_d=(float(d[:top].sum()/total) if total != 0 else None),
                mean_d_without_top=(float(d[top:].mean()) if len(d) > top else None))


def ablation_table(full, ablated, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED, sensitivity=SENSITIVITY_BLOCKS):
    """Delta (median rho), mean d, win rate per ablation, and the change in mean d against the full model with paired intervals."""
    sessions = list(full["folds"].evaluated_session)
    for name, run in ablated.items():
        if list(run["folds"].evaluated_session) != sessions:
            raise ValueError(f"Ablation {name} does not evaluate the full model's sessions")
    n = len(sessions)
    indices = {block_length: block_indices(n, block_length, replicates, seed)}
    for block in sensitivity:
        if block != block_length and block <= n:
            indices[block] = block_indices(n, block, replicates, seed)
    d_full = full["folds"].d.to_numpy(float)
    rho_full = full["folds"].rho.to_numpy(float)

    def summary(folds):
        d = folds.d.to_numpy(float)
        return dict(folds=int(len(folds)), delta_median_rho=float(folds.rho.median()), mean_d=float(d.mean()), median_d=float(np.median(d)),
                    win_rate=float((folds.model_mse < folds.baseline_mse).mean()),
                    learned_coverage_mean=float(folds.learned_coverage.mean()), concentration=mean_d_concentration(d))
    out = dict(full=summary(full["folds"]), ablations={}, sessions=n, first_session=sessions[0], last_session=sessions[-1])
    for name, run in ablated.items():
        d, rho = run["folds"].d.to_numpy(float), run["folds"].rho.to_numpy(float)
        change = d-d_full
        intervals = {str(block): list(percentile_interval(change[idx].mean(axis=1))) for block, idx in indices.items()}
        rho_change = {str(block): list(percentile_interval(np.median(rho[idx], axis=1)-np.median(rho_full[idx], axis=1))) for block, idx in indices.items()}
        out["ablations"][name] = dict(summary(run["folds"]), excluded_features=run["significance"].get("excluded_features"),
                                      change_in_mean_d=float(change.mean()), change_interval=intervals[str(block_length)], change_sensitivity=intervals,
                                      change_in_delta=float(np.median(rho)-np.median(rho_full)), delta_change_interval=rho_change[str(block_length)],
                                      hurts=bool(intervals[str(block_length)][1] < 0), helps=bool(intervals[str(block_length)][0] > 0))
    return out


def run_ablations(entries, out_path, replicates=REPLICATES):
    result = dict(exploratory=True, note=EXPLORATORY, symbol_note=SYMBOL_NOTE,
                  bootstrap=dict(block_length=BLOCK_LENGTH, replicates=replicates, seed=SEED, sensitivity_blocks=list(SENSITIVITY_BLOCKS),
                                 paired="the same block indices resample the ablated and full differentials, so every change is computed within a replicate"),
                  entries={})
    for entry in entries:
        label, full_dir, *ablated_dirs = entry
        full = load_run(full_dir)
        ablated = {Path(p).name: load_run(p) for p in ablated_dirs}
        table = ablation_table(full, ablated, replicates=replicates)
        table["runs"] = dict(full=dict(path=str(full_dir), files=full["files"]), **{name: dict(path=str(p), files=ablated[Path(p).name]["files"]) for name, p in
                                                                                    zip(ablated, ablated_dirs, strict=True)})
        result["entries"][label] = table
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return dict(result, path=str(out_path))


# ----------------------------------------------------------------------------- breakdowns
def load_predictions(path):
    frame = pd.read_csv(path)
    needed = {"observation_id", "evaluated_session", "symbol", "mid", "spot", "strike", "T", "r", "q", "days_to_expiry", "baseline_price", "model_price"}
    if missing := needed-set(frame.columns):
        raise ValueError(f"{path} lacks {sorted(missing)}")
    return frame


def session_gaps(calendar_sessions):
    """Gap in days from each session to the previous session in the calendar (the prior available session)."""
    days = sorted(set(str(s) for s in calendar_sessions))
    return {day: ((dt.date.fromisoformat(day)-dt.date.fromisoformat(prev)).days if prev else None) for prev, day in zip([None]+days[:-1], days, strict=True)}


def build_cells(model, reference, reference_role, vix, vix_cuts, moneyness_cuts, gaps):
    """Per-row squared spot-normalized errors of the model and the reference, plus every cell key."""
    rows = model.copy()
    if reference is None:
        rows["reference_price"] = rows.baseline_price
    else:
        column = "baseline_price" if reference_role == "baseline" else "model_price"
        merged = rows.merge(reference[["observation_id", column]].rename(columns={column: "reference_price"}), on="observation_id", how="inner")
        if len(merged) != len(rows):
            raise ValueError(f"Reference predictions cover {len(merged)} of {len(rows)} model rows; the runs must share set and folds")
        rows = merged
    spot = rows.spot.to_numpy(float)
    rows["model_error"] = ((rows.model_price.to_numpy(float)-rows.mid.to_numpy(float))/spot)**2
    rows["reference_error"] = ((rows.reference_price.to_numpy(float)-rows.mid.to_numpy(float))/spot)**2
    forward = spot*np.exp((rows.r.to_numpy(float)-rows.q.to_numpy(float))*rows["T"].to_numpy(float))
    rows["abs_log_moneyness"] = np.abs(np.log(rows.strike.to_numpy(float)/forward))
    rows["maturity_bucket"] = pd.cut(rows.days_to_expiry.astype(float), MATURITY_EDGES, labels=MATURITY_LABELS).astype(str)
    rows["moneyness_tercile"] = assign_tercile(rows.abs_log_moneyness, moneyness_cuts)
    levels = {day: vix.value_before(day)[1] for day in rows.evaluated_session.unique()}
    rows["vix_prior"] = rows.evaluated_session.map(levels)
    rows["vix_tercile"] = assign_tercile(rows.vix_prior, vix_cuts)
    rows["gap_days"] = rows.evaluated_session.map(gaps)
    if rows.gap_days.isna().any():
        raise ValueError("Every evaluated session needs a prior session in the calendar")
    rows["gap_bucket"] = gap_bucket(rows.gap_days)
    return rows


def maturity_range(rows):
    """Observed time to expiry of the evaluated rows and the section 5 maturity buckets the source leaves empty."""
    days = rows.days_to_expiry.to_numpy(float)
    counts = rows.maturity_bucket.value_counts()
    return dict(days_to_expiry_min=float(days.min()), days_to_expiry_max=float(days.max()), T_min=float(rows["T"].min()), T_max=float(rows["T"].max()),
                bucket_edges_days=[float(e) for e in MATURITY_EDGES[1:-1]], empty_buckets=[label for label in MATURITY_LABELS if int(counts.get(label, 0)) == 0],
                note="An empty bucket means the source lists no expiry in it; the study covers only the realized range (Research Plan Amendment 6).")


def cell_statistics(rows, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED):
    per_session = rows.groupby("evaluated_session").agg(reference=("reference_error", "mean"), model=("model_error", "mean"), n=("model_error", "size")).sort_index()
    d = (per_session.reference-per_session.model).to_numpy(float)
    rho = 1-np.sqrt(per_session.model.to_numpy(float))/np.sqrt(per_session.reference.to_numpy(float))
    n = len(per_session)
    out = dict(sessions=int(n), observations=int(per_session.n.sum()), median_rho=float(np.median(rho)), mean_d=float(d.mean()),
               win_rate=float((per_session.model < per_session.reference).mean()), interval=None,
               thin=bool(n < MIN_SESSIONS_FOR_INTERVAL))
    if n >= MIN_SESSIONS_FOR_INTERVAL:
        block = min(block_length, n)
        idx = block_indices(n, block, replicates, seed)
        out["interval"] = list(percentile_interval(d[idx].mean(axis=1)))
        out["interval_block_length"] = int(block)
    return out


BREAKDOWN_COLUMNS = (("symbol", "symbol"), ("maturity_bucket", "maturity bucket (calendar days to expiry)"), ("moneyness_tercile", "moneyness tercile of |log(K/F)|"),
                     ("vix_tercile", "VIX regime (VIXCLS at the prior observation, terciles)"), ("gap_bucket", "gap in days to the prior available session"))


def breakdown_tables(rows, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED):
    tables = {}
    for column, title in BREAKDOWN_COLUMNS:
        cells = {}
        if column == "maturity_bucket":
            groups = MATURITY_LABELS
        elif column in ("moneyness_tercile", "vix_tercile"):
            groups = list(TERCILE_LABELS)
        elif column == "gap_bucket":
            groups = sorted(rows[column].unique(), key=lambda v: (len(v), v))
        else:
            groups = sorted(rows[column].unique())
        for group in groups:
            sub = rows.loc[rows[column] == group]
            cells[str(group)] = cell_statistics(sub, block_length, replicates, seed) if len(sub) else dict(sessions=0, observations=0, median_rho=None, mean_d=None,
                                                                                                             win_rate=None, interval=None, thin=True)
        tables[column] = dict(title=title, cells=cells)
    return tables


def run_breakdowns(entries, out_path, vix_path, vix_cuts=None, moneyness_cuts=None, replicates=REPLICATES):
    vix = DatedSeries.from_fred_csv(vix_path)
    result = dict(exploratory=True, note=EXPLORATORY, vix=dict(path=str(vix_path), sha256=file_digest(vix_path), alignment="most recent observation dated strictly before the session"),
                  bootstrap=dict(block_length=BLOCK_LENGTH, replicates=replicates, seed=SEED, minimum_sessions_for_interval=MIN_SESSIONS_FOR_INTERVAL,
                                 paired="d_t pairs the model and the reference within each session; the block bootstrap resamples the cell's session series"),
                  entries={})
    cut_source = None
    for label, model_path, reference_path, role, calendar_path in entries:
        model = load_predictions(model_path)
        reference = None if reference_path in ("-", "") else load_predictions(reference_path)
        calendar = pd.read_csv(calendar_path).session_date
        gaps = session_gaps(calendar)
        if vix_cuts is None:
            levels = [vix.value_before(day)[1] for day in sorted(model.evaluated_session.unique())]
            vix_cuts = tercile_cuts(levels)
            cut_source = dict(vix_cuts_from=label, vix_sessions=len(levels))
        if moneyness_cuts is None:
            forward = model.spot.to_numpy(float)*np.exp((model.r.to_numpy(float)-model.q.to_numpy(float))*model["T"].to_numpy(float))
            moneyness_cuts = tercile_cuts(np.abs(np.log(model.strike.to_numpy(float)/forward)))
            cut_source = dict(cut_source or {}, moneyness_cuts_from=label, moneyness_rows=int(len(model)))
        rows = build_cells(model, reference, role, vix, vix_cuts, moneyness_cuts, gaps)
        result["entries"][label] = dict(model_predictions=dict(path=str(model_path), sha256=file_digest(model_path), rows=int(len(model))),
                                        reference=(dict(path=str(reference_path), sha256=file_digest(reference_path), role=role) if reference is not None
                                                   else dict(path=None, role="the model run's own baseline")),
                                        session_calendar=str(calendar_path), sessions=int(rows.evaluated_session.nunique()), observations=int(len(rows)),
                                        maturity_range=maturity_range(rows), overall=cell_statistics(rows, replicates=replicates),
                                        breakdowns=breakdown_tables(rows, replicates=replicates))
    result["cut_points"] = dict(vix_terciles=list(map(float, vix_cuts)), moneyness_terciles=list(map(float, moneyness_cuts)), **(cut_source or {}))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return dict(result, path=str(out_path))


# ----------------------------------------------------------------------------- report
def _fmt(value, spec):
    return "n/a" if value is None else format(value, spec)


def ablation_reading(table):
    """How Delta and the mean differential move under each ablation, and how concentrated the mean differential is."""
    full = table["full"]
    lines = []
    for name, item in table["ablations"].items():
        crossing = " and crosses zero" if (item["delta_median_rho"] < 0) != (full["delta_median_rho"] < 0) else ""
        relative = f" ({(item['mean_d']-full['mean_d'])/abs(full['mean_d']):+.1%})" if full["mean_d"] else ""
        lines.append(f"- Without {name.replace('no-', '').replace('-', ' ')}: Delta moves from {full['delta_median_rho']:+.4f} to {item['delta_median_rho']:+.4f}{crossing}; "
                     f"the mean differential moves from {full['mean_d']:.3e} to {item['mean_d']:.3e}{relative}.")
    conc = full.get("concentration") or {}
    if conc.get("share_of_sum_d") is not None:
        lines.append(f"- The mean differential is dominated by a few high-error sessions: the {conc['top_sessions']} largest of {table['sessions']} sessions carry "
                     f"{conc['share_of_sum_d']:.1%} of the sum of d in the full model (median d {full['median_d']:.3e} against mean d {full['mean_d']:.3e}; mean without "
                     f"them {_fmt(conc['mean_d_without_top'], '.3e')}). Where Delta crosses zero while the mean differential barely moves, the median describes the "
                     "typical session and the mean does not.")
    return lines


def maturity_coverage_lines(breakdowns):
    """The observed maturity range per entry and what the empty section 5 bucket means for the study (Amendment 6)."""
    ranges = {label: entry["maturity_range"] for label, entry in breakdowns["entries"].items() if entry.get("maturity_range")}
    if not ranges:
        return []
    lines = ["## Maturity coverage (Amendment 6)", "", EXPLORATORY, ""]
    for label, m in ranges.items():
        lines.append(f"- {label}: time to expiry from {m['days_to_expiry_min']:.3f} to {m['days_to_expiry_max']:.3f} days (T up to {m['T_max']:.5f} years); "
                     f"empty maturity buckets: {', '.join(m['empty_buckets']) or 'none'}.")
    lines.append("")
    if all(">90d" in m["empty_buckets"] for m in ranges.values()):
        longest = max(m["days_to_expiry_max"] for m in ranges.values())
        lines += [f"The source lists no expiry beyond {longest:.3f} days to expiry, so the plan's more-than-90-day maturity bucket is empty in every breakdown and the "
                  "realized buckets are 30 days or fewer and 31 days to that maximum. The study covers short-dated options only, and no term-structure claim can "
                  "be made from it.", ""]
    else:
        lines += ["Every section 5 maturity bucket is populated.", ""]
    return lines


def write_design_c_report(ablations_path, breakdowns_path, out_path):
    ablations = json.loads(Path(ablations_path).read_text())
    breakdowns = json.loads(Path(breakdowns_path).read_text())
    lines = ["# Design C: attribution (exploratory)", "", EXPLORATORY, "", "## Feature ablations", "", SYMBOL_NOTE, ""]
    for label, table in ablations["entries"].items():
        b = ablations["bootstrap"]
        lines += [f"### {label}", "", EXPLORATORY, "",
                  f"{table['sessions']} sessions from {table['first_session']} to {table['last_session']}; paired block bootstrap, block {b['block_length']}, "
                  f"{b['replicates']:,} replicates, seed {b['seed']}.", "",
                  "| Model | Delta (median rho) | Mean d | Win rate | Change in mean d vs full | 95% interval | Change in Delta | 95% interval |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|",
                  f"| full | {table['full']['delta_median_rho']:.4f} | {table['full']['mean_d']:.3e} | {table['full']['win_rate']:.3f} | | | | |"]
        for name, item in table["ablations"].items():
            lines.append(f"| without {name.replace('no-', '')} | {item['delta_median_rho']:.4f} | {item['mean_d']:.3e} | {item['win_rate']:.3f} | "
                         f"{item['change_in_mean_d']:+.3e} | [{item['change_interval'][0]:+.2e}, {item['change_interval'][1]:+.2e}] | "
                         f"{item['change_in_delta']:+.4f} | [{item['delta_change_interval'][0]:+.4f}, {item['delta_change_interval'][1]:+.4f}] |")
        lines += [""]+ablation_reading(table)+[""]
    lines += maturity_coverage_lines(breakdowns)
    cuts = breakdowns["cut_points"]
    lines += ["## Breakdowns of d and rho", "", EXPLORATORY, "",
              f"VIX regime: VIXCLS at the most recent observation strictly before the session, terciles cut at {cuts['vix_terciles'][0]:.2f} and {cuts['vix_terciles'][1]:.2f}. "
              f"Moneyness: |log(K/F)| terciles cut at {cuts['moneyness_terciles'][0]:.4f} and {cuts['moneyness_terciles'][1]:.4f}. "
              f"Cells with fewer than {breakdowns['bootstrap']['minimum_sessions_for_interval']} sessions report counts and point values without an interval.", ""]
    for label, entry in breakdowns["entries"].items():
        o = entry["overall"]
        lines += [f"### {label}", "", EXPLORATORY, "",
                  f"Reference: {entry['reference'].get('role')}. {entry['sessions']} sessions, {entry['observations']:,} observations; overall median rho {o['median_rho']:.4f}, "
                  f"mean d {o['mean_d']:.3e}, win rate {o['win_rate']:.3f}.", ""]
        for table in entry["breakdowns"].values():
            lines += [f"**{table['title']}**", "", "| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |", "|---|---:|---:|---:|---:|---:|---:|"]
            for cell, item in table["cells"].items():
                interval = item.get("interval")
                lines.append(f"| {cell} | {item['sessions']} | {item['observations']:,} | {_fmt(item['median_rho'], '.4f')} | {_fmt(item['mean_d'], '.3e')} | "
                             f"{_fmt(item['win_rate'], '.3f')} | {'none (fewer than 30 sessions)' if interval is None else f'[{interval[0]:+.2e}, {interval[1]:+.2e}]'} |")
            lines.append("")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines)+"\n")
    return dict(path=str(out_path), ablation_entries=list(ablations["entries"]), breakdown_entries=list(breakdowns["entries"]))
