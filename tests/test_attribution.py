"""Design C attribution (options_engine.attribution): ablations, saved predictions, regimes, cell breakdowns, and the report."""
import json

import numpy as np
import pandas as pd
import pytest

from options_engine.attribution import (DatedSeries, EXPLORATORY, SYMBOL_NOTE, ablation_table, assign_tercile, build_cells, cell_statistics,
                                        gap_bucket, maturity_range, mean_d_concentration, run_ablations, run_breakdowns, session_gaps, tercile_cuts,
                                        write_design_c_report)
from options_engine.cli import parser, run
from options_engine.learning import FEATURE_GROUPS, basis, excluded_names, fit_ridge, predict_volatility
from options_engine.walkforward import WalkForwardSpec, walk_forward
from test_compare import design_b_runs
from test_stale_quote import persistent_frame


def test_feature_group_exclusion_is_consistent_between_fit_and_predict():
    frame, _ = persistent_frame(sessions=4)
    frame["symbol"] = np.where(np.arange(len(frame)) % 2 == 0, "TEST", "OTHER")
    _, names = basis(frame, ["OTHER", "TEST"])
    assert excluded_names(("symbol",), names) == {"symbol_OTHER", "symbol_TEST"}
    assert excluded_names(("moneyness", "maturity_interactions"), names) == set(FEATURE_GROUPS["moneyness"]) | set(FEATURE_GROUPS["maturity_interactions"])
    with pytest.raises(ValueError, match="Unknown feature groups"):
        excluded_names(("carry",), names)
    full = fit_ridge(frame, 1.0)
    without = fit_ridge(frame, 1.0, exclude=("moneyness",))
    assert without["excluded_groups"] == ["moneyness"] and len(without["feature_names"]) == len(full["feature_names"])-3
    assert not any(n.startswith("moneyness") and "sqrt" not in n or n == "log_moneyness" for n in without["feature_names"])
    sigmas_full, _ = predict_volatility(full, frame)
    sigmas_without, supported = predict_volatility(without, frame)
    assert supported.all() and not np.allclose(sigmas_full, sigmas_without)
    with pytest.raises(ValueError, match="Feature schema"):
        predict_volatility(dict(without, excluded_groups=[]), frame)                 # exclusion is part of the model schema


def test_walk_forward_ablation_and_predictions():
    frame, days = persistent_frame(sessions=9)
    spec = WalkForwardSpec(min_train_sessions=4, gap=1, validation_sessions=2)
    full = walk_forward(frame, spec, collect_predictions=True)
    ablated = walk_forward(frame, spec, exclude_features=("maturity_interactions",))
    assert ablated["excluded_features"] == ["maturity_interactions"] and full["excluded_features"] == []
    assert list(ablated["folds"].evaluated_session) == list(full["folds"].evaluated_session)
    assert not np.allclose(ablated["folds"].model_mse, full["folds"].model_mse) and np.allclose(ablated["folds"].baseline_mse, full["folds"].baseline_mse)
    predictions = full["predictions"]
    assert predictions is not None and len(predictions) == full["folds"].evaluation_rows.sum()
    for column in ("observation_id", "evaluated_session", "symbol", "mid", "spot", "strike", "T", "r", "q", "days_to_expiry", "baseline_price", "model_price", "model_sigma"):
        assert column in predictions
    # the per-row prices reproduce the fold losses exactly
    error = ((predictions.model_price-predictions.mid)/predictions.spot)**2
    by_session = error.groupby(predictions.evaluated_session).mean()
    assert np.allclose(by_session.loc[full["folds"].evaluated_session].to_numpy(), full["folds"].model_mse)
    assert walk_forward(frame, spec)["predictions"] is None


def test_dated_series_terciles_and_gaps(tmp_path):
    path = tmp_path/"VIXCLS.csv"
    path.write_text("observation_date,VIXCLS\n2024-01-02,13.0\n2024-01-03,\n2024-01-04,.\n2024-01-05,15.5\n2024-01-08,20.0\n")
    series = DatedSeries.from_fred_csv(path)
    assert series.value_before("2024-01-05") == (pd.Timestamp("2024-01-02").date(), 13.0)            # blanks skipped, strictly prior
    assert series.value_before("2024-01-08")[1] == 15.5 and series.value_before("2024-01-09")[1] == 20.0
    with pytest.raises(ValueError):
        series.value_before("2024-01-02")
    cuts = tercile_cuts([1, 2, 3, 4, 5, 6])
    assert list(assign_tercile([1, 3, 6], cuts)) == ["low", "middle", "high"]
    assert list(gap_bucket([1, 2, 4, 5, 9])) == ["1", "2", "4", "5+", "5+"]
    gaps = session_gaps(["2024-01-02", "2024-01-03", "2024-01-08"])
    assert gaps == {"2024-01-02": None, "2024-01-03": 1, "2024-01-08": 5}


def test_ablation_table_pairs_the_change():
    runs = design_b_runs(n=200, seed=5)
    full = runs["M-RV"]
    shifted = dict(full, folds=full["folds"].copy())
    shifted["folds"]["d"] = shifted["folds"]["d"]-1e-6                                              # ablation loses exactly 1e-6 everywhere
    shifted["folds"]["model_mse"] = shifted["folds"]["baseline_mse"]-shifted["folds"]["d"]
    shifted["folds"]["rho"] = 1-np.sqrt(shifted["folds"].model_mse)/np.sqrt(shifted["folds"].baseline_mse)
    shifted["significance"] = dict(excluded_features=["moneyness"])
    table = ablation_table(full, {"no-moneyness": shifted}, replicates=200)
    item = table["ablations"]["no-moneyness"]
    assert item["change_in_mean_d"] == pytest.approx(-1e-6) and item["change_interval"] == pytest.approx([-1e-6, -1e-6])
    assert item["hurts"] and not item["helps"] and item["excluded_features"] == ["moneyness"] and item["delta_median_rho"] < table["full"]["delta_median_rho"]
    assert item["median_d"] == pytest.approx(table["full"]["median_d"]-1e-6) and item["concentration"]["top_sessions"] == 10
    concentration = mean_d_concentration([5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1])
    assert concentration == dict(top_sessions=10, share_of_sum_d=pytest.approx(14/15), mean_d_without_top=pytest.approx((1+1-1)/3))
    assert mean_d_concentration([0.0, 0.0])["share_of_sum_d"] is None and mean_d_concentration([1.0])["mean_d_without_top"] is None
    misaligned = dict(shifted, folds=shifted["folds"].iloc[1:].reset_index(drop=True))
    with pytest.raises(ValueError, match="sessions"):
        ablation_table(full, {"bad": misaligned}, replicates=20)


def synthetic_predictions(sessions, rows_per_session=12, seed=0, reference_scale=None):
    rng = np.random.default_rng(seed)
    out = []
    for i, day in enumerate(sessions):
        spot = 100+i
        for j in range(rows_per_session):
            strike = spot*(.9+.02*j)
            mid = 5+rng.uniform(0, 3)
            out.append(dict(observation_id=f"{day}-{j}", evaluated_session=day, symbol="SPY" if j % 2 else "AAPL", mid=mid, spot=spot, strike=strike,
                            T=(15+10*(j % 3))/365, r=.04, q=.01, days_to_expiry=15+10*(j % 3), baseline_price=mid+rng.normal(0, .3),
                            model_price=mid+rng.normal(0, .1)))
    frame = pd.DataFrame(out)
    if reference_scale is not None:
        frame["baseline_price"] = frame.mid+(frame.baseline_price-frame.mid)*reference_scale
    return frame


def test_breakdowns_cells_and_thin_rule(tmp_path):
    import exchange_calendars as xc
    sessions = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2024-01-02", "2024-04-30")][:60]
    model = synthetic_predictions(sessions)
    vix_path = tmp_path/"vix.csv"
    vix_path.write_text("observation_date,VIXCLS\n"+"".join(f"{d},{12+i*.2:.2f}\n" for i, d in enumerate(["2023-12-29"]+sessions)))
    vix = DatedSeries.from_fred_csv(vix_path)
    gaps = session_gaps(["2023-12-29"]+sessions)                                                  # the calendar holds a session before the window
    levels = [vix.value_before(d)[1] for d in sessions]
    cuts = tercile_cuts(levels)
    rows = build_cells(model, None, "baseline", vix, cuts, tercile_cuts(np.abs(np.log(model.strike/model.spot))), gaps)
    assert set(rows.vix_tercile) == {"low", "middle", "high"} and set(rows.maturity_bucket) == {"<=30d", "31-90d"}
    first = rows.loc[rows.evaluated_session == sessions[1]]
    assert first.vix_prior.iloc[0] == 12+.2                                                       # the observation strictly before session 2 is session 1's
    overall = cell_statistics(rows, replicates=100)
    assert overall["sessions"] == 60 and overall["observations"] == 720 and overall["interval"] is not None and not overall["thin"]
    thin = cell_statistics(rows.loc[rows.evaluated_session.isin(sessions[:10])], replicates=100)
    assert thin["thin"] and thin["interval"] is None and thin["sessions"] == 10 and thin["median_rho"] is not None
    coverage = maturity_range(rows)
    assert coverage["days_to_expiry_min"] == 15 and coverage["days_to_expiry_max"] == 35 and coverage["T_max"] == pytest.approx(35/365)
    assert coverage["empty_buckets"] == [">90d"] and coverage["bucket_edges_days"] == [30.0, 90.0]
    # a reference run whose baseline is the model's own reference: identical cell losses give d = 0 exactly
    same = build_cells(model, model, "baseline", vix, cuts, tercile_cuts(np.abs(np.log(model.strike/model.spot))), gaps)
    assert np.allclose(same.reference_error, rows.reference_error)
    with pytest.raises(ValueError, match="cover"):
        build_cells(model, model.iloc[:-1], "model", vix, cuts, [.05, .1], gaps)


def test_design_c_cli_end_to_end(tmp_path, capsys):
    import exchange_calendars as xc
    sessions = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2024-01-02", "2024-06-30")][:80]
    runs = design_b_runs(n=80, seed=7)
    for name in ("M-RV", "M-B1"):
        folds = runs[name]["folds"].copy()
        folds["evaluated_session"] = sessions
        (tmp_path/"runs"/name).mkdir(parents=True)
        folds.to_csv(tmp_path/"runs"/name/"folds.csv", index=False)
    ablated = runs["M-RV"]["folds"].copy()
    ablated["evaluated_session"] = sessions
    ablated["d"] = ablated["d"]*.5
    (tmp_path/"runs"/"no-symbol").mkdir()
    ablated.to_csv(tmp_path/"runs"/"no-symbol"/"folds.csv", index=False)
    (tmp_path/"runs"/"no-symbol"/"significance.json").write_text(json.dumps(dict(excluded_features=["symbol"])))
    code = run(parser().parse_args(["design-c", "ablations", "--entry", "M(RV) on set A", str(tmp_path/"runs"/"M-RV"), str(tmp_path/"runs"/"no-symbol"),
                                    "--out", str(tmp_path/"ablations.json"), "--replicates", "100"]))
    capsys.readouterr()
    assert code == 0
    ablations = json.loads((tmp_path/"ablations.json").read_text())
    assert ablations["exploratory"] and ablations["entries"]["M(RV) on set A"]["ablations"]["no-symbol"]["excluded_features"] == ["symbol"]
    model = synthetic_predictions(sessions, seed=1)
    reference = synthetic_predictions(sessions, seed=2)
    model.to_csv(tmp_path/"model.csv", index=False)
    reference.to_csv(tmp_path/"reference.csv.gz", index=False)
    calendar = ["2023-12-29"]+sessions
    pd.DataFrame(dict(session_date=calendar, symbol="SPY", observation_id=calendar)).to_csv(tmp_path/"calendar.csv", index=False)
    vix_path = tmp_path/"vix.csv"
    vix_path.write_text("observation_date,VIXCLS\n"+"".join(f"{d},{12+i*.2:.2f}\n" for i, d in enumerate(["2023-12-29"]+sessions)))
    code = run(parser().parse_args(["design-c", "breakdowns", "--entry", "M(RV) vs RV", str(tmp_path/"model.csv"), "-", "baseline", str(tmp_path/"calendar.csv"),
                                    "--entry", "M(RV) vs B1", str(tmp_path/"model.csv"), str(tmp_path/"reference.csv.gz"), "baseline", str(tmp_path/"calendar.csv"),
                                    "--vix", str(vix_path), "--out", str(tmp_path/"breakdowns.json"), "--replicates", "100"]))
    capsys.readouterr()
    assert code == 0
    breakdowns = json.loads((tmp_path/"breakdowns.json").read_text())
    assert breakdowns["exploratory"] and len(breakdowns["cut_points"]["vix_terciles"]) == 2 and breakdowns["cut_points"]["vix_cuts_from"] == "M(RV) vs RV"
    entry = breakdowns["entries"]["M(RV) vs B1"]
    assert entry["reference"]["role"] == "baseline" and set(entry["breakdowns"]) == {"symbol", "maturity_bucket", "moneyness_tercile", "vix_tercile", "gap_bucket"}
    assert entry["breakdowns"]["maturity_bucket"]["cells"][">90d"]["sessions"] == 0 and entry["breakdowns"]["symbol"]["cells"]["SPY"]["interval"] is not None
    assert entry["maturity_range"]["days_to_expiry_max"] == 35 and entry["maturity_range"]["empty_buckets"] == [">90d"]
    code = run(parser().parse_args(["design-c", "report", "--ablations", str(tmp_path/"ablations.json"), "--breakdowns", str(tmp_path/"breakdowns.json"),
                                    "--out", str(tmp_path/"REPORT.md")]))
    capsys.readouterr()
    report = (tmp_path/"REPORT.md").read_text()
    assert code == 0 and report.count(EXPLORATORY) >= 4 and SYMBOL_NOTE in report and "| >90d | 0 | 0 |" in report and "none (fewer than 30 sessions)" in report
    assert "## Maturity coverage (Amendment 6)" in report and "no expiry beyond 35.000 days" in report and "short-dated options only" in report
    assert "dominated by a few high-error sessions" in report and "Delta moves from" in report
    again = write_design_c_report(tmp_path/"ablations.json", tmp_path/"breakdowns.json", tmp_path/"again.md")
    assert set(again["breakdown_entries"]) == {"M(RV) vs RV", "M(RV) vs B1"}                     # JSON entries are written with sorted keys
    direct = run_ablations([["x", str(tmp_path/"runs"/"M-RV"), str(tmp_path/"runs"/"no-symbol")]], tmp_path/"a2.json", replicates=50)
    assert direct["entries"]["x"]["ablations"]["no-symbol"]["change_in_mean_d"] < 0
    direct_b = run_breakdowns([["y", str(tmp_path/"model.csv"), "-", "baseline", str(tmp_path/"calendar.csv")]], tmp_path/"b2.json", vix_path=vix_path,
                              vix_cuts=[13.0, 20.0], moneyness_cuts=[.03, .06], replicates=50)
    assert direct_b["cut_points"]["vix_terciles"] == [13.0, 20.0]
