"""Design A comparison: paired block bootstrap, S_k, the carry-only check, and the decision rule."""
import json

import numpy as np
import pandas as pd
import pytest

from options_engine.cli import parser, run
from options_engine.compare import block_indices, compare_configs, decision, load_run, paired_ratio_of_medians, run_comparison


def synthetic_run(name, rho, d, seed=0):
    rng = np.random.default_rng(seed)
    n = len(rho)
    baseline = rng.uniform(1e-5, 5e-5, n)
    model = baseline-d
    folds = pd.DataFrame(dict(evaluated_session=[f"2024-{1+i//28:02d}-{1+i%28:02d}" for i in range(n)], baseline_mse=baseline, model_mse=model,
                              rho=rho, d=d, learned_coverage=1.0))
    return dict(name=name, path=name, folds=folds, significance={}, files={})


def test_block_indices_are_circular_shared_and_seeded():
    idx = block_indices(10, 4, 5, 7)
    assert idx.shape == (5, 10) and idx.min() >= 0 and idx.max() <= 9
    for row in idx:                                          # consecutive positions inside a block step by one, modulo n
        for start in range(0, 8, 4):
            assert np.all((row[start+1:start+4]-row[start:start+3]) % 10 == 1)
    assert np.array_equal(idx, block_indices(10, 4, 5, 7)) and not np.array_equal(idx, block_indices(10, 4, 5, 8))
    with pytest.raises(ValueError):
        block_indices(10, 11, 5, 7)


def test_s_is_exact_when_series_are_proportional():
    rng = np.random.default_rng(1)
    rho0 = rng.normal(.1, .2, 300)
    runs = {"C0": synthetic_run("C0", rho0, rng.normal(4e-6, 1e-6, 300)),
            "C1": synthetic_run("C1", .5*rho0, rng.normal(2e-6, 1e-6, 300)),
            "C3": synthetic_run("C3", rho0.copy(), rng.normal(4e-6, 1e-6, 300))}
    result = compare_configs(runs, replicates=200)
    assert result["s"]["C1"]["s"] == pytest.approx(.5) and result["s"]["C1"]["interval"] == pytest.approx([.5, .5])   # same blocks: exact ratio
    assert result["s"]["C3"]["s"] == pytest.approx(1.0) and result["s"]["C3"]["sensitivity"]["63"] == pytest.approx([1.0, 1.0])
    assert result["decision"]["label"] == "structure dominant" and result["decision"]["v1_improvement_survives_carry_correction"]
    assert result["configurations"]["C0"]["newey_west"]["hac_lags"] == 10 and result["bootstrap"]["replicates"] == 200
    idx = block_indices(300, 21, 50, 20260908)
    ratios = paired_ratio_of_medians(runs["C1"]["folds"].rho.to_numpy(), rho0, idx)
    assert np.allclose(ratios, .5)


def test_decision_rule_branches():
    assert decision(.3, (.1, .6), (1e-6, 3e-6))["label"] == "compensation dominant"
    assert decision(.3, (.1, .8), (1e-6, 3e-6))["label"] == "mixed or inconclusive"          # upper bound not below 0.75
    assert decision(.9, (.6, 1.2), (1e-6, 3e-6))["label"] == "structure dominant"
    assert decision(.9, (.4, 1.2), (1e-6, 3e-6))["label"] == "mixed or inconclusive"         # lower bound not above 0.5
    negative = decision(.9, (.6, 1.2), (-1e-6, 3e-6))
    assert not negative["v1_improvement_survives_carry_correction"] and "did not survive" in negative["headline"]


def test_misaligned_runs_are_refused():
    rng = np.random.default_rng(2)
    a = synthetic_run("C0", rng.normal(.1, .1, 50), rng.normal(1e-6, 1e-7, 50))
    b = synthetic_run("C3", rng.normal(.1, .1, 50), rng.normal(1e-6, 1e-7, 50))
    b["folds"] = b["folds"].iloc[1:].reset_index(drop=True)
    with pytest.raises(ValueError, match="same sessions"):
        compare_configs({"C0": a, "C3": b}, replicates=10)
    with pytest.raises(ValueError, match="Need runs"):
        compare_configs({"C0": a}, replicates=10)


def test_cli_writes_comparison_and_report(tmp_path, capsys):
    rng = np.random.default_rng(3)
    rho0 = rng.normal(.1, .2, 120)
    for name, scale in (("C0", 1.0), ("C1", .8), ("C2", .9), ("C3", .4)):
        folds = synthetic_run(name, scale*rho0, rng.normal(4e-6*scale, 5e-7, 120))["folds"]
        (tmp_path/name).mkdir()
        folds.to_csv(tmp_path/name/"folds.csv", index=False)
        (tmp_path/name/"significance.json").write_text(json.dumps(dict(config=dict(path=f"{name}.json", sha256="x"))))
    code = run(parser().parse_args(["compare-configs", "--runs", *[str(tmp_path/n) for n in ("C0", "C1", "C2", "C3")],
                                    "--out", str(tmp_path/"cmp"), "--replicates", "300"]))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and set(out["s"]) == {"C1", "C2", "C3"} and out["s"]["C3"]["s"] == pytest.approx(.4)
    saved = json.loads((tmp_path/"cmp"/"comparison.json").read_text())
    assert saved["decision"]["label"] == "compensation dominant" and saved["runs"]["C0"]["files"]["folds.csv"]["sha256"]
    report = (tmp_path/"cmp"/"REPORT.md").read_text()
    assert "compensation dominant" in report and "| C3 |" in report and "block 126" in report
    loaded = load_run(tmp_path/"C3")
    assert loaded["files"]["folds.csv"]["path"].endswith("C3/folds.csv")
    assert run_comparison([tmp_path/n for n in ("C0", "C3")], tmp_path/"two", replicates=50)["s"]["C3"]["s"] == pytest.approx(.4)


from options_engine.compare import compare_baselines, run_baseline_comparison, section_8_reading  # noqa: E402


def design_b_runs(n=200, seed=4, rv_gain=.7, b1_gain=1.0, learn_gain=.9):
    """Five synthetic runs: losses of B1, B2, RV and the three learned models, consistent across runs."""
    rng = np.random.default_rng(seed)
    sessions = [f"2024-{1+i//28:02d}-{1+i%28:02d}" for i in range(n)]
    rv = rng.uniform(2e-5, 4e-5, n)
    b1 = rv*b1_gain*rng.uniform(.8, 1.2, n)
    b2 = b1*rng.uniform(.95, 1.05, n)
    m_rv, m_b1, m_b2 = rv*rv_gain, b1*learn_gain, b2*learn_gain

    def run(name, baseline, model, coverage=1.0):
        folds = pd.DataFrame(dict(evaluated_session=sessions, baseline_mse=baseline, model_mse=model, rho=1-np.sqrt(model)/np.sqrt(baseline),
                                  d=baseline-model, learned_coverage=coverage))
        return dict(name=name, path=name, folds=folds, significance={}, files={})
    return {"B1": run("B1", b1, b1, 0.0), "B2": run("B2", b2, b2, 0.0), "M-RV": run("M-RV", rv, m_rv), "M-B1": run("M-B1", b1, m_b1), "M-B2": run("M-B2", b2, m_b2)}


def test_design_b_primary_holds_when_the_model_beats_b1():
    runs = design_b_runs()
    result = compare_baselines(runs, replicates=300)
    primary = result["comparisons"]["M(RV) vs B1"]
    assert primary["primary"] and primary["claim_holds"] and primary["label"] == "adds value" and primary["interval"][0] > 0
    assert primary["median_relative_improvement"] > 0 and result["primary_claim"]["holds"] and "adds value beyond" in result["primary_claim"]["reading"]
    assert set(result["comparisons"]) == {"M(RV) vs B1", "M(RV) vs B2", "M(B1) vs B1", "M(B2) vs B2"}
    assert result["comparisons"]["M(B1) vs B1"]["label"] == "adds value"                      # learned relative to B1 with a 10% gain
    assert result["runs"]["B1"]["learned_coverage"]["zero_coverage_folds"] == 200 and result["set_b_control"]["set_b"]["M_RV"]["folds"] == 200
    assert result["comparisons"]["M(RV) vs B1"]["newey_west"]["hac_lags"] == 8


def test_design_b_downgrade_and_contamination():
    runs = design_b_runs(rv_gain=1.3, b1_gain=.6, learn_gain=1.0)                  # B1 beats M(RV); M(B1) equals B1
    result = compare_baselines(runs, replicates=300, b2_fallback=dict(fallback_contaminated=True, slice_fallback_rate=.4))
    primary = result["comparisons"]["M(RV) vs B1"]
    assert primary["label"] == "baseline wins" and not result["primary_claim"]["holds"]
    assert "downgraded" in result["primary_claim"]["reading"] and "no incremental value" in result["primary_claim"]["reading"]
    assert result["b2_fallback_contaminated"] and result["comparisons"]["M(RV) vs B2"]["note"] and not result["comparisons"]["M(RV) vs B2"]["claim_holds"]
    inconclusive = section_8_reading(dict(claim_holds=False, label="no evidence either way"), dict(claim_holds=False))
    assert inconclusive.startswith("Inconclusive")


def test_design_b_consistency_checks():
    runs = design_b_runs()
    broken = {k: dict(v, folds=v["folds"].copy()) for k, v in runs.items()}
    broken["M-B1"]["folds"]["baseline_mse"] *= 1.01
    with pytest.raises(ValueError, match="disagree"):
        compare_baselines(broken, replicates=20)
    not_alone = {k: dict(v, folds=v["folds"].copy()) for k, v in runs.items()}
    not_alone["B1"]["folds"]["model_mse"] *= .5
    with pytest.raises(ValueError, match="baseline-only"):
        compare_baselines(not_alone, replicates=20)
    with pytest.raises(ValueError, match="missing"):
        compare_baselines({k: v for k, v in runs.items() if k != "B2"}, replicates=20)


def test_compare_baselines_cli(tmp_path, capsys):
    for name, synthetic in design_b_runs(n=150).items():
        (tmp_path/name).mkdir()
        synthetic["folds"].to_csv(tmp_path/name/"folds.csv", index=False)
    (tmp_path/"set-B.drops.json").write_text(json.dumps(dict(b2=dict(slices_attempted=10, slices_fitted=9, slice_fallback_rate=.1, slices_fallback_by_reason={"butterfly": 1},
                                                                    rows_by_source={"svi": 90, "fallback_b1": 10}, fallback_contaminated=False))))
    (tmp_path/"design-a.json").write_text(json.dumps(dict(configurations=dict(C3=dict(folds=1056, median_rho=.107, mean_d=4.7e-4, win_rate=.646,
                                                                                       median_baseline_mse=1.4e-5, median_model_mse=1.15e-5)))))
    code = run(parser().parse_args(["compare-baselines", "--runs", *[str(tmp_path/n) for n in ("B1", "B2", "M-RV", "M-B1", "M-B2")],
                                    "--out", str(tmp_path/"cmp"), "--set-b-sidecar", str(tmp_path/"set-B.drops.json"),
                                    "--design-a", str(tmp_path/"design-a.json"), "--replicates", "200"]))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["primary_claim"]["holds"] and not out["b2_fallback_contaminated"]
    saved = json.loads((tmp_path/"cmp"/"comparison.json").read_text())
    assert saved["set_b_control"]["set_a_C3"]["folds"] == 1056 and saved["b2_fallback"]["slice_fallback_rate"] == .1
    report = (tmp_path/"cmp"/"REPORT.md").read_text()
    assert "M(RV) vs B1 (primary)" in report and "Set B control" in report and "C3 on set A" in report and "holds" in report
    assert "Caveats" not in report                                                    # every label here is backed by the median and win rate
    fragile = design_b_runs(n=150, seed=9)
    fragile["M-B1"]["folds"]["model_mse"] = fragile["B1"]["folds"]["baseline_mse"]*np.where(np.arange(150) % 10 == 0, .2, 1.01)
    fragile_result = compare_baselines(fragile, replicates=200)
    if fragile_result["comparisons"]["M(B1) vs B1"]["label"] == "adds value":
        from options_engine.compare import write_baselines_report
        write_baselines_report(fragile_result, tmp_path/"fragile.md")
        assert "Caveats" in (tmp_path/"fragile.md").read_text() and "minority of sessions" in (tmp_path/"fragile.md").read_text()
    again = run_baseline_comparison([tmp_path/n for n in ("B1", "B2", "M-RV", "M-B1", "M-B2")], tmp_path/"again", replicates=50)
    assert again["comparisons"]["M(RV) vs B1"]["claim_holds"]

