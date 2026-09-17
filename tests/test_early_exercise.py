"""Amendment 8 early-exercise diagnostic (options_engine.early_exercise): vectorized pricing against the scalar engines, the tick rule,
the streaming diagnostic with a fake prior-quote source, the store-backed prior quotes, the reviewer extract, and the report section."""
import json
from contextlib import closing

import numpy as np
import pandas as pd
import pytest

from options_engine import early_exercise as ee
from options_engine.american import binomial_analysis
from options_engine.cli import parser, run
from options_engine.compare import block_indices, pair_statistics
from options_engine.core import BlackScholesEngine
from options_engine.iv import implied_volatility
from options_engine.store import ObservationStore
from test_eod_import import eod_config

R, Q = .03, .01
STRIKES = [93.0, 96.0, 99.0, 102.0, 105.0, 108.0]


def test_vector_pricers_match_the_scalar_engines():
    rng = np.random.default_rng(3)
    n = 120
    S = rng.uniform(90, 500, n)
    K = S*np.exp(rng.uniform(-.12, .12, n))
    T = rng.uniform(.05, .2, n)
    r, q = rng.uniform(0, .05, n), rng.uniform(0, .02, n)
    sigma = rng.uniform(.15, .6, n)
    is_call = rng.random(n) < .5
    american, european = ee.tree_prices(S, K, T, r, q, sigma, is_call, 120)
    for i in range(n):
        ref = binomial_analysis(S[i], K[i], T[i], r[i], sigma[i], q[i], "call" if is_call[i] else "put", 120)
        assert american[i] == pytest.approx(ref.price, abs=1e-9) and european[i] == pytest.approx(ref.european_tree_price, abs=1e-9)
        assert ee.bsm_prices(S[i], K[i], T[i], r[i], q[i], sigma[i], is_call[i]) == pytest.approx(BlackScholesEngine(S[i], K[i], T[i], r[i], sigma[i], q[i]).price("call" if is_call[i] else "put"), abs=1e-10)
    prices = ee.bsm_prices(S, K, T, r, q, sigma, is_call)
    recovered = ee.european_iv(prices, S, K, T, r, q, is_call)
    scalar = np.array([implied_volatility(prices[i], S[i], K[i], T[i], r[i], q[i], "call" if is_call[i] else "put").volatility for i in range(n)])
    assert np.nanmax(np.abs(recovered-sigma)) < 1e-7 and np.nanmax(np.abs(recovered-scalar)) < 1e-7
    otm = np.where(is_call, K > S, K < S)                                       # out of the money: the American price moves with sigma
    tree_am = ee.american_iv(american[otm], S[otm], K[otm], T[otm], r[otm], q[otm], is_call[otm], 120, european=recovered[otm])
    assert np.isfinite(tree_am).all() and np.max(np.abs(tree_am-sigma[otm])) < 1e-5
    with pytest.raises(ValueError, match="T > 0"):
        ee.tree_prices([100], [100], [0.0], [.03], [.01], [.2], [True], 10)


def test_tick_rule_and_classification():
    assert list(ee.tick_size(["AAPL", "AAPL", "SPY", "SPY"], [2.5, 3.0, 2.5, 30.0])) == [.01, .05, .01, .01]
    frame = pd.DataFrame(dict(spot=[100.0]*4, strike=[100.0, 110.0, 120.0, 100.0], T=[20/365, 20/365, 40/365, 100/365], r=[.0]*4, q=[.0]*4,
                              days_to_expiry=[20.0, 20.0, 40.0, 100.0], evaluated_session=["2021-03-01", "2021-03-01", "2023-03-01", "2023-03-01"],
                              option_type=["call", "put", "call", "put"], symbol=["SPY", "AAPL", "SPY", "AAPL"]))
    keys = ee.classify(frame, (.05, .13))
    assert list(keys["moneyness_tercile"]) == ["low", "middle", "high", "low"] and list(keys["maturity_bucket"]) == ["<=30d", "<=30d", "31-90d", ">90d"]
    assert list(keys["regime"]) == [ee.REGIMES[0], ee.REGIMES[0], ee.REGIMES[1], ee.REGIMES[1]] and list(keys["year"]) == ["2021", "2021", "2023", "2023"]


def smile(spot, strike):
    m = np.log(spot/strike)
    return .2*np.exp(.1+.3*m+.5*m*m)


def synthetic_files(directory, sessions_a, sessions_b, chunk_seed=0):
    """Prediction files in the walk-forward layout: set A (RV baseline, M(RV)) over sessions_a, the aligned set B pair over sessions_b;
    the baselines table; a comparison.json whose pre-registered numbers are the full-row pair statistics; the breakdown cut points."""
    rng = np.random.default_rng(chunk_seed)
    rows_a, rows_rv, rows_b1, baselines, prior, last_sigma = [], [], [], [], {}, {}
    all_sessions = sorted(set(sessions_a) | set(sessions_b))
    for i, day in enumerate(all_sessions):
        spot = 100.0+.7*i
        T = (35-i % 5)/365
        for symbol in ("SPY", "AAPL"):
            for j, strike in enumerate(STRIKES):
                kind = "call" if j % 2 else "put"
                contract = f"{symbol}-{strike:.0f}{kind[0]}"
                iv = smile(spot, strike)
                mid = float(ee.bsm_prices(spot, strike, T, R, Q, iv, kind == "call"))
                oid = f"{day}-{contract}"
                base = dict(observation_id=oid, evaluated_session=day, symbol=symbol, contractSymbol=contract, option_type=kind, expiration="2030-01-01", strike=strike,
                            spot=spot, mid=mid, bid=mid*.99, ask=mid*1.01, T=T, days_to_expiry=T*365, r=R, q=Q)
                rv_sigma = .22
                m_sigma = iv*(1+rng.normal(0, .03))
                rv_price = float(ee.bsm_prices(spot, strike, T, R, Q, rv_sigma, kind == "call"))
                m_price = float(ee.bsm_prices(spot, strike, T, R, Q, m_sigma, kind == "call"))
                # the day's own implied volatility is what the next session's B1 inverts from its quote; the fake prior quote is priced at it
                own_sigma = iv*(1+rng.normal(0, .01))
                prior[(day, symbol, contract)] = dict(spot=spot, T=T, b1_sigma=own_sigma, kind=kind, strike=strike)
                b1_sigma = last_sigma.get((symbol, contract), own_sigma)
                last_sigma[(symbol, contract)] = own_sigma
                mb1_sigma = b1_sigma*np.exp(rng.normal(0, .01))
                b1_price = float(ee.bsm_prices(spot, strike, T, R, Q, b1_sigma, kind == "call"))
                mb1_price = float(ee.bsm_prices(spot, strike, T, R, Q, mb1_sigma, kind == "call"))
                if day in sessions_a:
                    rows_a.append(dict(base, baseline_sigma=rv_sigma, baseline_price=rv_price, model_price=m_price, model_sigma=m_sigma))
                if day in sessions_b:
                    rows_rv.append(dict(base, baseline_sigma=rv_sigma, baseline_price=rv_price, model_price=m_price, model_sigma=m_sigma))
                    rows_b1.append(dict(base, baseline_sigma=b1_sigma, baseline_price=b1_price, model_price=mb1_price, model_sigma=mb1_sigma))
                    prior_day = all_sessions[i-1] if i else None
                    baselines.append(dict(observation_id=oid, prior_session=prior_day, b1_source="same_contract" if (j % 3 and prior_day) else "interpolated"))
    paths = dict(set_a=directory/"set-a.csv.gz", set_b_rv=directory/"set-b-rv.csv.gz", set_b_b1=directory/"set-b-b1.csv.gz", baselines=directory/"baselines.csv.gz",
                 comparison=directory/"comparison.json", breakdowns=directory/"breakdowns.json")
    pd.DataFrame(rows_a).to_csv(paths["set_a"], index=False)
    pd.DataFrame(rows_rv).to_csv(paths["set_b_rv"], index=False)
    pd.DataFrame(rows_b1).to_csv(paths["set_b_b1"], index=False)
    pd.DataFrame(baselines).to_csv(paths["baselines"], index=False)
    rv, b1 = pd.DataFrame(rows_rv), pd.DataFrame(rows_b1)
    losses = {}
    for name, frame, column in (("m_rv", rv, "model_price"), ("b1", b1, "baseline_price"), ("m_b1", b1, "model_price")):
        error = ((frame[column]-frame.mid)/frame.spot)**2
        losses[name] = error.groupby(frame.evaluated_session).mean().sort_index().to_numpy()
    n = len(losses["b1"])
    indices = {min(21, n): block_indices(n, min(21, n), 200, 20260908)}
    comparison = dict(comparisons={"M(RV) vs B1": pair_statistics(losses["b1"], losses["m_rv"], indices, min(21, n), primary=True),
                                   "M(B1) vs B1": pair_statistics(losses["b1"], losses["m_b1"], indices, min(21, n), primary=False)})
    paths["comparison"].write_text(json.dumps(comparison, default=float))
    paths["breakdowns"].write_text(json.dumps(dict(cut_points=dict(moneyness_terciles=[.03, .07]))))
    return paths, prior


class FakePrior:
    """Prior-session quotes consistent with the b1 sigma: the t-1 mid is the European price at that sigma under t-1 conditions."""

    def __init__(self, prior):
        self.prior = prior

    def lookup(self, session):
        table = {}
        for (day, symbol, contract), item in self.prior.items():
            if day == session:
                mid = float(ee.bsm_prices(item["spot"], item["strike"], item["T"], R, Q, item["b1_sigma"], item["kind"] == "call"))
                table[(symbol, contract)] = (mid, item["spot"], item["T"])
        return table

    def carry_at(self, session, symbol):
        return R, Q


def test_run_diagnostic_streams_chunks_and_reports(tmp_path):
    sessions = [f"2023-01-{d:02d}" for d in range(2, 32) if d not in (7, 8, 14, 15, 16, 21, 22, 28, 29)]
    paths, prior = synthetic_files(tmp_path, sessions_a=sessions, sessions_b=sessions[1:])
    out = tmp_path/"diag.json"
    result = ee.run_diagnostic("unused-config", paths["set_a"], paths["set_b_rv"], paths["set_b_b1"], paths["baselines"], paths["comparison"], paths["breakdowns"], out,
                               steps=80, chunksize=50, replicates=200, prior_quotes=FakePrior(prior))
    assert out.exists() and json.loads(out.read_text())["exploratory"] and result["amendment"] == 8
    a = result["sets"]["A"]
    assert a["rows"] == len(sessions)*12 and a["sessions"] == len(sessions) and a["unidentified_european_iv"] == 0
    overall = a["premium"]["iv"]["overall"]
    assert overall["n"] == a["rows"] and overall["mean"] >= 0 and 0 <= overall["share_exceeding_tick"] <= 1 and overall["p99"] >= overall["median"]
    assert set(a["premium"]["iv"]["by_option_type"]) == {"call", "put"} and set(a["premium"]) == {"iv", "rv", "m_rv"}
    assert a["premium"]["iv"]["by_option_type"]["put"]["mean"] > a["premium"]["iv"]["by_option_type"]["call"]["mean"]   # r > q: puts carry the premium
    b = result["sets"]["B"]
    assert b["rows"] == (len(sessions)-1)*12 and set(b["premium"]) == {"iv", "rv", "m_rv", "b1", "m_b1"}
    sens = result["sensitivity"]
    for label in ("M(RV) vs B1", "M(B1) vs B1"):
        pair = sens["pairs"][label]
        assert pair["recomputed_from_predictions"]["matches_pre_registered"], pair["recomputed_from_predictions"]
        assert pair["below_tick"]["label"] in ("adds value", "baseline wins", "no evidence either way") and isinstance(pair["label_changes"], bool)
    assert 0 < sens["rows_kept"] <= sens["rows_total"] and sens["sessions_kept"] <= sens["sessions_total"]
    c = result["cancellation"]
    assert c["same_contract_rows"] > 0 and c["prior_quote_missing"] == 0 and c["reinversion_check"]["max_abs_sigma_difference"] < 1e-6
    assert c["rows"] > 0 and set(c["losses"]) == {"b1", "m_rv", "rv", "m_b1"} and "M(RV) vs B1" in c["differential"]
    assert isinstance(c["differential"]["M(RV) vs B1"]["european_favors_b1"], bool) and len(c["differential"]["M(RV) vs B1"]["change_interval"]) == 2
    assert result["peak_rss_mb"] > 0 and result["timing"]["total_seconds"] >= 0 and result["tree"]["steps"] == 80 and result["tree"]["stability"]["rows"] > 0
    assert set(result["pricing_paths"]) >= {"RV baseline", "M(RV)", "B1", "B2", "M(B1)", "M(B2)", "learning targets", "locked predict path"}
    report = tmp_path/"REPORT.md"
    report.write_text("# Design B\n\nexisting text\n")
    ee.write_report_section(out, report)
    ee.write_report_section(out, report)                                        # idempotent: one section, replaced in place
    text = report.read_text()
    assert text.count(ee.SECTION_START) == 1 and text.count("## Early-exercise diagnostic") == 1 and "existing text" in text and "Cancellation test" in text
    code = run(parser().parse_args(["early-exercise-diagnostic", "report", "--diagnostic", str(out), "--report", str(report)]))
    assert code == 0 and report.read_text().count(ee.SECTION_START) == 1


def test_prior_quotes_read_the_store_and_the_cli_builds(tmp_path, capsys):
    sessions = [f"2023-02-{d:02d}" for d in range(1, 29) if d not in (4, 5, 11, 12, 18, 19, 25, 26)]
    paths, prior = synthetic_files(tmp_path, sessions_a=sessions, sessions_b=sessions[1:])
    root = tmp_path/"root"
    store = ObservationStore(root)
    fake = FakePrior(prior)
    with closing(store.connect()) as db, db:
        db.execute("INSERT INTO runs(run_id, started_at, provider, status) VALUES ('r1', '2023-01-01T00:00:00+00:00', 'dolt_eod', 'ok')")
        for day in sessions:
            for (symbol, contract), (mid, spot, T) in fake.lookup(day).items():
                payload = dict(symbol=symbol, contractSymbol=contract, mid=mid, spot=spot, T=T)
                db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)", (f"{day}-{contract}", "r1", day+"T21:00:00+00:00", day, symbol, 1, "", json.dumps(payload)))
    config = tmp_path/"config.json"
    config.write_text(json.dumps(dict(eod_config(tickers=("SPY", "AAPL"), dividend_yields={"SPY": Q, "AAPL": Q}, rate=R).public_dict(), data_root="root"), indent=2))
    quotes = ee.PriorQuotes(config)
    table = quotes.lookup(sessions[0])
    assert len(table) == 12 and quotes.carry_at(sessions[0], "SPY") == (R, Q) and quotes.lookup(sessions[0]) is table
    code = run(parser().parse_args(["early-exercise-diagnostic", "build", "--config", str(config), "--set-a", str(paths["set_a"]), "--set-b-rv", str(paths["set_b_rv"]),
                                    "--set-b-b1", str(paths["set_b_b1"]), "--baselines", str(paths["baselines"]), "--comparison", str(paths["comparison"]),
                                    "--breakdowns", str(paths["breakdowns"]), "--out", str(tmp_path/"cli.json"), "--steps", "60", "--chunksize", "40", "--replicates", "100"]))
    summary = json.loads(capsys.readouterr().out)
    assert code == 0 and (tmp_path/"cli.json").exists() and set(summary["sensitivity"]) == {"M(RV) vs B1", "M(B1) vs B1"} and summary["tree"]["steps"] == 60
    diag = json.loads((tmp_path/"cli.json").read_text())
    assert diag["cancellation"]["prior_quote_missing"] == 0 and diag["cancellation"]["reinversion_check"]["max_abs_sigma_difference"] < 1e-6


def test_extract_is_deterministic_capped_and_documented(tmp_path, capsys):
    sessions = [f"2024-03-{d:02d}" for d in range(1, 30) if d not in (2, 3, 9, 10, 16, 17, 23, 24)]
    paths, _ = synthetic_files(tmp_path, sessions_a=sessions, sessions_b=sessions[1:])
    repo = tmp_path/"repo"
    for name in ("docs/results/x/folds.csv", "docs/results/y/z/folds.csv"):
        (repo/name).parent.mkdir(parents=True)
        (repo/name).write_text("evaluated_session,d\n2024-01-02,0.1\n")
    first = ee.build_extract(paths["set_a"], paths["set_b_rv"], paths["set_b_b1"], tmp_path/"extract1", paths["breakdowns"], cap_per_stratum=5, steps=60, chunksize=37, repo_root=repo)
    second = ee.build_extract(paths["set_a"], paths["set_b_rv"], paths["set_b_b1"], tmp_path/"extract2", paths["breakdowns"], cap_per_stratum=5, steps=60, chunksize=50, repo_root=repo)
    assert (tmp_path/"extract1"/"observations-sample.csv").read_bytes() == (tmp_path/"extract2"/"observations-sample.csv").read_bytes()
    sample = pd.read_csv(tmp_path/"extract1"/"observations-sample.csv")
    assert list(sample.columns) == ee.EXTRACT_COLUMNS and first["sampling"]["rows"] == len(sample) == second["sampling"]["rows"]
    assert sample.groupby(["symbol", "year", "option_type", "maturity_bucket"]).size().max() <= 5
    assert (sample.in_set_b == sample.evaluated_session.isin(sessions[1:])).all()           # set B starts one session later
    assert sample.loc[sample.in_set_b, "b1_price"].notna().all() and sample.loc[~sample.in_set_b, "b1_price"].isna().all()
    assert (sample.early_exercise_premium_fraction >= 0).all() and sample.european_iv.notna().all()
    assert sorted(p.name for p in (tmp_path/"extract1"/"folds").iterdir()) == ["x.csv", "y__z.csv"]
    readme = (tmp_path/"extract1"/"README.md").read_text()
    assert "inspection only" in readme.lower() and f"{len(sample):,} evaluated observations" in readme and "No reported number" in readme
    meta = json.loads((tmp_path/"extract1"/"extract.json").read_text())
    assert meta["sampling"]["seed"] == 20260908 and meta["sampling"]["cap_per_stratum"] == 5 and len(meta["files"]["folds"]) == 2 and meta["files"]["sample"]["rows"] == len(sample)
    with pytest.raises(ValueError, match="exists"):
        ee.build_extract(paths["set_a"], paths["set_b_rv"], paths["set_b_b1"], tmp_path/"extract1", paths["breakdowns"], cap_per_stratum=5, repo_root=repo)
    code = run(parser().parse_args(["early-exercise-diagnostic", "extract", "--set-a", str(paths["set_a"]), "--set-b-rv", str(paths["set_b_rv"]), "--set-b-b1", str(paths["set_b_b1"]),
                                    "--breakdowns", str(paths["breakdowns"]), "--out-dir", str(tmp_path/"extract3"), "--cap-per-stratum", "4", "--steps", "60", "--repo-root", str(repo)]))
    assert code == 0 and json.loads(capsys.readouterr().out)["sampling"]["cap_per_stratum"] == 4
