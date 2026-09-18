#!/usr/bin/env python
"""Amendment 3 guard sensitivity: Design A with the v1 support guard (r and q guarded) against the committed guard-off runs.

Reads the committed Design A comparison (guard off), the comparison of the guard-on runs produced by `compare-configs`
(the locked machinery, unchanged), and the guard-on runs' abstention records; writes
docs/results/v2/design-a/guard-sensitivity.json and inserts a marker-delimited section into docs/results/v2/design-a/REPORT.md.
Touches no locked module.

    python scripts/guard_sensitivity.py [--design-a docs/results/v2/design-a] [--guard-on guard-v1]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

START, END = "<!-- guard-sensitivity:start -->", "<!-- guard-sensitivity:end -->"
CONFIGS = ("C1", "C2", "C3")


def sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def abstentions(run_dir):
    sig = json.loads((run_dir/"significance.json").read_text())
    block = sig.get("abstentions") or {}
    return dict(rows=block.get("rows"), abstaining=block.get("abstaining"), by_key=block.get("by_key"), only_key=block.get("only_key"),
                sessions_with_any=block.get("sessions_with_any"), sessions_fully_abstaining=block.get("sessions_fully_abstaining"),
                learned_coverage_mean=sig.get("learned_coverage", {}).get("mean"), zero_coverage_folds=sig.get("learned_coverage", {}).get("zero_coverage_folds"),
                support_guard=sig.get("support_guard"), config=sig.get("config"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design-a", default="docs/results/v2/design-a")
    parser.add_argument("--guard-on", default="guard-v1", help="Directory under design-a holding the compare-configs output of the guard-on runs")
    parser.add_argument("--suffix", default="-guard-v1")
    args = parser.parse_args()
    root = Path(args.design_a)
    off = json.loads((root/"comparison.json").read_text())
    on = json.loads((root/args.guard_on/"comparison.json").read_text())
    table = {}
    for name in CONFIGS:
        guard_off = off["s"][name]
        guard_on = on["s"][name+args.suffix]
        table[name] = dict(guard_off=dict(s=guard_off["s"], interval=guard_off["interval"], median_rho=guard_off["median_rho"], sensitivity=guard_off["sensitivity"]),
                           guard_on=dict(s=guard_on["s"], interval=guard_on["interval"], median_rho=guard_on["median_rho"], sensitivity=guard_on["sensitivity"]),
                           difference_in_s=guard_on["s"]-guard_off["s"])
    runs = {name: abstentions(root/(name+args.suffix)) for name in CONFIGS}
    runs["C0"] = abstentions(root/"C0")
    agree = on["decision"]["label"] == off["decision"]["label"]
    line = (f"The decision label {'agrees' if agree else 'DISAGREES'} with the guard-off runs: guard off {off['decision']['label']} "
            f"(S_3 = {off['decision']['s3']:.3f}, interval [{off['decision']['s3_interval'][0]:.3f}, {off['decision']['s3_interval'][1]:.3f}]); "
            f"guard on {on['decision']['label']} (S_3 = {on['decision']['s3']:.3f}, interval [{on['decision']['s3_interval'][0]:.3f}, {on['decision']['s3_interval'][1]:.3f}]).")
    result = dict(exploratory=False, amendment=3, executed="2026-09-17",
                  note="Design A rerun with the v1 support guard (T, baseline_sigma, log_moneyness, r, q) from the code at the commit that produced the committed runs, "
                       "with a config key selecting the guard; C0 was rerun first and required to be byte-identical to the committed C0. Amendment 3's text stands.",
                  control=dict(off=off["control"], on=on["control"]), treatment=dict(off=off["treatment"], on=on["treatment"]),
                  sessions=dict(off=off["sessions"], on=on["sessions"]), bootstrap=on["bootstrap"], s=table,
                  mean_d_treatment=dict(off=off["mean_d_treatment"], on=on["mean_d_treatment"]),
                  carry_only_check=dict(off=off["carry_only_check"], on=on["carry_only_check"]),
                  decision=dict(off=off["decision"], on=on["decision"], agrees=agree, line=line), abstentions=runs,
                  files=dict(guard_off_comparison=dict(path=str(root/"comparison.json"), sha256=sha256(root/"comparison.json")),
                             guard_on_comparison=dict(path=str(root/args.guard_on/"comparison.json"), sha256=sha256(root/args.guard_on/"comparison.json"))))
    out = root/"guard-sensitivity.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    lines = ["## Guard sensitivity (Amendment 3, executed 2026-09-17)", "",
             "Design A rerun with the v1 support guard, which also guards r and q, from the code at the commit that produced the committed runs; "
             "C0 reran byte-identically first. Same set A, folds, and bootstrap settings; S_k against the same C0.", "",
             "| Correction | S_k, guard off | 95% CI | S_k, guard on (v1) | 95% CI | Abstaining rows, guard on (of rows) | Sessions fully abstaining |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name in CONFIGS:
        t, a = table[name], runs[name]
        lines.append(f"| {name} | {t['guard_off']['s']:.3f} | [{t['guard_off']['interval'][0]:.3f}, {t['guard_off']['interval'][1]:.3f}] | {t['guard_on']['s']:.3f} | "
                     f"[{t['guard_on']['interval'][0]:.3f}, {t['guard_on']['interval'][1]:.3f}] | {a['abstaining']:,} of {a['rows']:,} | {a['sessions_fully_abstaining']} |")
    lines += ["", "Abstentions by guarded feature (a row may fail several; the second figure counts rows failing only that feature):", ""]
    for name in CONFIGS:
        a = runs[name]
        by = ", ".join(f"{k} {v:,} ({a['only_key'].get(k, 0):,} only)" for k, v in a["by_key"].items())
        lines.append(f"- {name}: {by}; sessions with any abstention {a['sessions_with_any']}.")
    lines += ["", line, ""]
    section = START+"\n"+"\n".join(lines)+END+"\n"
    report = root/"REPORT.md"
    text = report.read_text()
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        text = head+section+tail.lstrip("\n")
    else:
        text = text.rstrip("\n")+"\n\n"+section
    report.write_text(text)
    print(json.dumps(dict(path=str(out), decision=result["decision"]["line"], s={k: dict(off=v["guard_off"]["s"], on=v["guard_on"]["s"]) for k, v in table.items()}), indent=2))


if __name__ == "__main__":
    main()
