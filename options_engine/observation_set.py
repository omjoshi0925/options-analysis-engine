"""Frozen observation sets: the rows that pass the v1 gates and price under every carry configuration.

A set is built once from the store's training-eligible rows, written as keys
with its hash, and reused by every run so that sessions, fold boundaries, and
rows are identical across configurations (docs/RESEARCH_PLAN.md section 2).
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

from .carry_inputs import apply_carry, file_digest

KEY_COLUMNS = ["observation_id", "session_date", "symbol"]
CARRY_KEYS = ("rate", "dividend", "dividend_yields", "data_root")


def sidecar_path(path):
    """<name>.drops.json beside the keys file, for both name.csv and name.csv.gz."""
    path = Path(path)
    name = path.name.removesuffix(".gz").removesuffix(".csv")
    return path.with_name(name+".drops.json")


def uncompressed_digest(path):
    path = Path(path)
    if path.suffix != ".gz":
        return file_digest(path)
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def drop_composition(frame):
    """Where the dropped rows sit: by year, symbol, option type, moneyness, and maturity."""
    if frame.empty:
        return {}
    out = dict(by_year={k: int(v) for k, v in frame.session_date.astype(str).str[:4].value_counts().sort_index().items()},
               by_symbol={k: int(v) for k, v in frame.symbol.value_counts().sort_index().items()})
    if "option_type" in frame:
        out["by_option_type"] = {k: int(v) for k, v in frame.option_type.value_counts().sort_index().items()}
    if "log_moneyness" in frame:
        buckets = pd.cut(frame.log_moneyness.astype(float), [-float("inf"), -.15, -.05, .05, .15, float("inf")],
                         labels=["below -0.15", "-0.15 to -0.05", "-0.05 to 0.05", "0.05 to 0.15", "above 0.15"])
        out["by_log_moneyness"] = {str(k): int(v) for k, v in buckets.value_counts().sort_index().items()}
    if "days_to_expiry" in frame:
        buckets = pd.cut(frame.days_to_expiry.astype(float), [0, 30, 90, float("inf")], labels=["<=30d", "31-90d", ">90d"])
        out["by_days_to_expiry"] = {str(k): int(v) for k, v in buckets.value_counts().sort_index().items()}
    return out


def build_observation_set(frame, carries):
    """Keep rows that survive apply_carry under every configuration in `carries` (name -> CarryInputs)."""
    if frame.empty:
        raise ValueError("No candidate observations")
    frame = frame.copy()
    if "observation_id" not in frame:
        raise ValueError("Candidate rows need an observation_id")
    if frame.observation_id.duplicated().any():
        raise ValueError("Duplicate observation ids in the candidate frame")
    failed, by_config = set(), {}
    for name, carry in carries.items():
        _, failures = apply_carry(frame, carry)
        failed |= set(failures.observation_id)
        dropped_rows = frame.loc[frame.observation_id.isin(failures.observation_id)]
        by_config[name] = dict(dropped=int(len(failures)), by_reason={k: int(v) for k, v in failures.reason.value_counts().sort_index().items()},
                               composition=drop_composition(dropped_rows), carry=carry.describe())
    dropped = frame.loc[frame.observation_id.isin(failed)]
    keys = frame.loc[~frame.observation_id.isin(failed), KEY_COLUMNS].sort_values(["session_date", "symbol", "observation_id"]).reset_index(drop=True)
    summary = dict(candidates=int(len(frame)), kept=int(len(keys)), dropped_under_any_config=int(len(failed)),
                   candidate_sessions=int(frame.session_date.nunique()), kept_sessions=int(keys.session_date.nunique()),
                   sessions_lost=sorted(set(frame.session_date)-set(keys.session_date)),
                   kept_by_symbol={k: int(v) for k, v in keys.symbol.value_counts().sort_index().items()},
                   dropped_by_symbol={k: int(v) for k, v in dropped.symbol.value_counts().sort_index().items()},
                   dropped_composition=drop_composition(dropped),
                   by_config=by_config, rule="kept only if apply_carry succeeds under every listed configuration")
    return keys, summary


def write_observation_set(keys, summary, out_path):
    """Write the keys CSV and a sidecar <stem>.drops.json holding the summary and the CSV's SHA-256."""
    out_path = Path(out_path)
    if out_path.exists():
        raise ValueError("Observation set exists; choose a new path")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    keys.to_csv(out_path, index=False)
    digest = uncompressed_digest(out_path)
    sidecar = sidecar_path(out_path)
    payload = dict(summary, observation_set=dict(path=str(out_path), rows=int(len(keys)), sha256=digest, columns=KEY_COLUMNS,
                                                 note="sha256 is of the uncompressed CSV bytes"))
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")
    return dict(path=str(out_path), rows=int(len(keys)), sha256=digest, drops=str(sidecar))


def read_observation_set(path):
    """Return (ids, description); the description carries the hash of the file as read."""
    path = Path(path)
    keys = pd.read_csv(path, usecols=["observation_id"])
    ids = set(keys.observation_id)
    if len(ids) != len(keys):
        raise ValueError("Observation set has duplicate ids")
    description = dict(path=str(path), rows=int(len(keys)), sha256=file_digest(path), uncompressed_sha256=uncompressed_digest(path))
    sidecar = sidecar_path(path)
    if sidecar.exists():
        payload = json.loads(sidecar.read_text())
        recorded = payload.get("observation_set", {})
        description["recorded_rows"], description["recorded_sha256"] = recorded.get("rows"), recorded.get("sha256")
        description["sidecar"] = str(sidecar)
        description["configs"] = {name: item.get("sha256") for name, item in payload.get("configs", {}).items()}
        if recorded.get("rows") not in (None, len(keys)):
            raise ValueError("Observation set row count does not match its sidecar")
        if recorded.get("sha256") not in (None, description["uncompressed_sha256"]):
            raise ValueError("Observation set content does not match the hash its sidecar recorded")
    return ids, description


def restrict_to_observation_set(frame, ids):
    kept = frame.loc[frame.observation_id.isin(ids)].reset_index(drop=True)
    return kept, dict(candidate_rows=int(len(frame)), matched_rows=int(len(kept)), set_size=int(len(ids)))


def carry_neutral_settings(config):
    """Everything in a config except the carry fields and the (path-relative) data root."""
    return {k: v for k, v in config.public_dict().items() if k not in CARRY_KEYS}
