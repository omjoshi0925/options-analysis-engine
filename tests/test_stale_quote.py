"""Amendment 5 stale-quote diagnostic (options_engine.stale_quotes): the mid-change table, the evaluation-subset walk-forward, and the report assembly."""
import json

import numpy as np
import pandas as pd
import pytest

from options_engine import BlackScholesEngine
from options_engine.analysis import analyze_options
from options_engine.cli import parser, run
from options_engine.data import time_to_expiry
from options_engine.stale_quotes import build_stale_quote_stats, report_stale_quote_diagnostic, stale_quote_table, summarize_stale, write_subsets
from options_engine.walkforward import WalkForwardSpec, walk_forward
from test_compare import design_b_runs


def persistent_frame(sessions=3, frozen_from=None, seed=0):
    """Sessions sharing the same contracts; from `frozen_from` on, the even strikes keep the previous session's bid and ask."""
    import exchange_calendars as xc
    rng = np.random.default_rng(seed)
    days = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2026-03-02", "2026-04-30")[:sessions]]
    frames, previous = [], {}
    for index, day in enumerate(days):
        stamp = pd.Timestamp(day+"T15:00:00Z")
        spot = 100*(1+.002*index)
        rows = []
        for expiration in ("2026-06-19", "2026-09-18"):
            T = time_to_expiry(expiration, stamp)
            for strike in np.linspace(90, 110, 6):
                iv = .22+.5*np.log(spot/strike)**2+.01*rng.normal()
                for kind in ("call", "put"):
                    key = (expiration, strike, kind)
                    mid = BlackScholesEngine(spot, strike, T, .04, iv, .01).price(kind)
                    bid, ask = round(mid*.995, 2), round(mid*1.005, 2)
                    if frozen_from is not None and index >= frozen_from and int(strike) % 4 == 0 and key in previous:
                        bid, ask = previous[key]
                    previous[key] = (bid, ask)
                    rows.append(dict(symbol="TEST", contractSymbol=f"T{expiration}{strike}{kind}", option_type=kind, expiration=expiration,
                                     as_of=stamp.isoformat(), spot=spot, strike=strike, bid=bid, ask=ask, volume=500, openInterest=1000,
                                     r=.04, q=.01, baseline_sigma=.2, baseline_source="fixture", data_kind="market"))
        analyzed, _ = analyze_options(pd.DataFrame(rows), american_steps=None)
        analyzed["session_date"] = day
        frames.append(analyzed)
    frame = pd.concat(frames, ignore_index=True)
    frame["observation_id"] = [f"obs-{i}" for i in range(len(frame))]
    return frame, days


def baselines_for(frame, days):
    """A baselines-B-like table: every row from the second session on, with the previous session as prior."""
    rows = frame.loc[frame.session_date != days[0], ["observation_id", "session_date", "symbol", "contractSymbol"]].copy()
    prior = {day: days[i-1] for i, day in enumerate(days) if i}
    rows["prior_session"] = rows.session_date.map(prior)
    rows["gap_days"] = [(pd.Timestamp(d)-pd.Timestamp(p)).days for d, p in zip(rows.session_date, rows.prior_session, strict=True)]
    rows["b1_source"] = "same_contract"
    return rows.reset_index(drop=True)


def test_stale_quote_table_summary_and_subsets(tmp_path):
    frame, days = persistent_frame(sessions=3, frozen_from=2)
    baselines = baselines_for(frame, days)
    # one row whose contract has no quote at the prior session (an interpolated B1)
    extra = frame.loc[frame.session_date == days[2]].iloc[:1].copy()
    extra["observation_id"], extra["contractSymbol"] = "obs-interp", "T-absent"
    frame = pd.concat([frame, extra], ignore_index=True)
    baselines = pd.concat([baselines, pd.DataFrame([dict(observation_id="obs-interp", session_date=days[2], symbol="TEST", contractSymbol="T-absent",
                                                          prior_session=days[1], gap_days=1, b1_source="interpolated")])], ignore_index=True)
    rows = stale_quote_table(frame, baselines)
    at_2 = rows.loc[rows.session_date == days[2]]
    frozen = at_2.loc[at_2.contractSymbol.str.contains(r"(?:92|96|100|104|108)\.0", regex=True)]
    assert frozen.unchanged.all() and not at_2.loc[~at_2.contractSymbol.isin(frozen.contractSymbol) & at_2.comparable].unchanged.any()
    assert not rows.loc[rows.observation_id == "obs-interp"].comparable.iloc[0]
    assert not rows.loc[rows.session_date == days[1]].unchanged.any()                     # nothing frozen before session 2
    changed = at_2.loc[at_2.comparable & ~at_2.unchanged].iloc[0]
    assert changed.relative_change == pytest.approx(abs(changed.mid-changed.mid_prev)/changed.mid_prev)
    stats = summarize_stale(rows)
    overall = stats["overall"]
    assert overall["rows"] == len(baselines) and overall["comparable"] == len(baselines)-1 and overall["unchanged"] == len(frozen)
    assert overall["unchanged_share_of_comparable"] == pytest.approx(len(frozen)/(len(baselines)-1))
    assert set(stats["by_symbol"]) == {"TEST"} and set(stats["by_maturity_bucket"]) <= {"<=30d", "31-90d", ">90d"}
    assert set(stats["by_moneyness_tercile"]) == {"nearest", "middle", "farthest"} and set(stats["by_gap_days"]) <= {"1", "2", "3", "4", "5+"}
    assert stats["by_b1_source"]["interpolated"]["comparable"] == 0 and stats["by_b1_source"]["interpolated"]["unchanged_share_of_comparable"] is None
    assert len(stats["moneyness_tercile_edges"]) == 2
    written = write_subsets(rows, tmp_path/"subsets")
    assert written["unchanged-mid"]["rows"] == len(frozen) and written["changed-mid"]["rows"] == overall["comparable"]-len(frozen)
    assert written["not-unchanged-mid"]["rows"] == overall["rows"]-len(frozen)
    assert set(pd.read_csv(written["changed-mid"]["path"]).observation_id).isdisjoint(pd.read_csv(written["unchanged-mid"]["path"]).observation_id)
    with pytest.raises(ValueError, match="exists"):
        write_subsets(rows, tmp_path/"subsets")
    result = build_stale_quote_stats(frame, baselines, tmp_path/"build", source_set=dict(rows=len(baselines)), config="K.json")
    assert result["exploratory"] and result["stats"]["overall"]["unchanged"] == len(frozen) and (tmp_path/"build"/"stale-quote-stats.json").exists()


def test_walk_forward_evaluation_subset_keeps_training_and_skips_empty_sessions():
    frame, days = persistent_frame(sessions=9)
    spec = WalkForwardSpec(min_train_sessions=4, gap=1, validation_sessions=2)
    full = walk_forward(frame, spec)["folds"]
    keep = frame.loc[(frame.session_date != days[7]) & (np.arange(len(frame)) % 2 == 0), "observation_id"]
    outcome = walk_forward(frame, spec, evaluation_ids=set(keep))
    subset = outcome["folds"]
    assert outcome["skipped_sessions"] == [days[7]] and days[7] not in set(subset.evaluated_session)
    merged = subset.merge(full, on="evaluated_session", suffixes=("_sub", "_full"))
    assert (merged.train_rows_sub == merged.train_rows_full).all() and (merged.alpha_sub == merged.alpha_full).all()   # same models
    expected = frame.loc[frame.observation_id.isin(keep)].groupby("session_date").size()
    assert all(row.evaluation_rows_sub == expected[row.evaluated_session] for row in merged.itertuples())
    assert not np.allclose(merged.baseline_mse_sub, merged.baseline_mse_full)
    with pytest.raises(ValueError, match="No session"):
        walk_forward(frame, spec, evaluation_ids={"nothing"})


def test_report_assembly_and_rendered_section(tmp_path, capsys):
    full = design_b_runs(n=120, seed=1)
    for name in ("B1", "M-RV", "M-B1", "B2", "M-B2"):
        (tmp_path/"full"/name).mkdir(parents=True)
        full[name]["folds"].to_csv(tmp_path/"full"/name/"folds.csv", index=False)
    for subset, names, scale in (("changed-mid", ("B1", "M-RV", "M-B1"), 1.0), ("unchanged-mid", ("B1", "M-RV"), .05)):
        runs = design_b_runs(n=100, seed=2, b1_gain=scale)
        for name in names:
            (tmp_path/"sens"/subset/name).mkdir(parents=True)
            folds = runs[name]["folds"].copy()
            folds.to_csv(tmp_path/"sens"/subset/name/"folds.csv", index=False)
            (tmp_path/"sens"/subset/name/"significance.json").write_text(json.dumps(dict(evaluation_subset=dict(skipped_sessions=["2024-02-01"]))))
    stats = dict(amendment=5, exploratory=True, note="test",
                 stats=dict(overall=dict(rows=100, comparable=90, unchanged=30, unchanged_share_of_comparable=1/3, unchanged_share_of_rows=.3,
                                         relative_change_percentiles={"p10": .0, "p25": .01, "p50": .03, "p75": .06, "p90": .1}, relative_change_mean=.04),
                            by_symbol={}, by_maturity_bucket={}, by_moneyness_tercile={}, by_gap_days={}, by_b1_source={}, moneyness_tercile_edges=[.02, .05]),
                 subsets={})
    (tmp_path/"stats.json").write_text(json.dumps(stats))
    result = report_stale_quote_diagnostic(tmp_path/"stats.json", tmp_path/"full", tmp_path/"sens", tmp_path/"diag.json", replicates=100)
    assert set(result["sensitivity"]) == {"changed-mid", "unchanged-mid"} and "M(B1) vs B1" in result["sensitivity"]["changed-mid"]["comparisons"]
    assert "M(B1) vs B1" not in result["sensitivity"]["unchanged-mid"]["comparisons"] and result["sensitivity"]["changed-mid"]["skipped_sessions"] == ["2024-02-01"]
    assert result["b1_rmse_by_subset"]["unchanged-mid"]["b1_median_session_rmse"] < result["b1_rmse_by_subset"]["changed-mid"]["b1_median_session_rmse"]
    assert "full set B" in result["b1_rmse_by_subset"] and isinstance(result["label_changes"], list)
    code = run(parser().parse_args(["compare-baselines", "--runs", *[str(tmp_path/"full"/n) for n in ("B1", "B2", "M-RV", "M-B1", "M-B2")],
                                    "--out", str(tmp_path/"cmp"), "--replicates", "100", "--stale-diagnostic", str(tmp_path/"diag.json")]))
    capsys.readouterr()
    assert code == 0
    report = (tmp_path/"cmp"/"REPORT.md").read_text()
    assert "Stale-quote diagnostic (exploratory, Amendment 5)" in report and "| changed-mid |" in report and "Label changes" in report
    assert json.loads((tmp_path/"cmp"/"comparison.json").read_text())["stale_quote_diagnostic"]["exploratory"]
