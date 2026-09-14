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
