import argparse
from pathlib import Path
import json
import sys
from .core import BlackScholesEngine
from .data import FilterConfig, fetch_options, read_snapshot, write_snapshot
from .analysis import analyze_options, write_report
from .demo import synthetic_snapshot
from .volatility import ESTIMATORS


def parser():
    p = argparse.ArgumentParser(description="European BSM engine and reproducible quote analysis")
    commands = p.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run a labeled synthetic demonstration, offline")
    demo.add_argument("--output", default="results/demo")
    fetch = commands.add_parser("fetch", help="Capture real Yahoo chains and raw history")
    fetch.add_argument("--tickers", nargs="+", required=True)
    fetch.add_argument("--rate", type=float, required=True, help="Continuously compounded annual decimal scenario rate")
    fetch.add_argument("--dividend-yields", nargs="+", required=True, metavar="SYMBOL=DECIMAL")
    fetch.add_argument("--expirations", type=int, default=3)
    fetch.add_argument("--volatility", type=float, help="Fixed independent baseline; otherwise prior 60-session realized vol")
    fetch.add_argument("--history-window", type=int, default=60)
    fetch.add_argument("--estimator", choices=ESTIMATORS, default="close_to_close",
                       help="Realized-volatility estimator for the baseline; range estimators use unadjusted OHLC")
    fetch.add_argument("--expiry-hour", type=int, choices=range(24), default=16)
    fetch.add_argument("--output", required=True, help="New snapshot directory; never overwritten")
    replay = commands.add_parser("analyze", help="Replay a saved, checksum-verified snapshot")
    replay.add_argument("--snapshot", required=True)
    replay.add_argument("--output", required=True)
    for command in (demo, replay):
        command.add_argument("--min-volume", type=int, default=0)
        command.add_argument("--min-open-interest", type=int, default=10)
        command.add_argument("--max-relative-spread", type=float, default=.5)
        command.add_argument("--min-mid", type=float, default=.10, help="Minimum midpoint included in percentage metrics")
        command.add_argument("--max-last-trade-age-days", type=float)
        command.add_argument("--no-plots", action="store_true")
    init = commands.add_parser("init-live", help="Write an editable continuous collection configuration")
    init.add_argument("--provider", choices=["yahoo", "tradier"], default="yahoo")
    init.add_argument("--config", default="config/collector.json")
    collect = commands.add_parser("collect", help="Run the continuous collector; Ctrl+C stops it")
    collect.add_argument("--config", default="config/collector.json")
    collect.add_argument("--once", action="store_true", help="One scheduled check, respecting market hours")
    collect.add_argument("--probe", action="store_true", help="One acquisition outside market hours; still respects persisted backoff")
    status = commands.add_parser("status", help="Show collection health and training progress")
    status.add_argument("--config", default="config/collector.json")
    fit = commands.add_parser("train", help="Fit and evaluate a volatility model on complete prior sessions")
    fit.add_argument("--config", default="config/collector.json")
    ingest = commands.add_parser("ingest", help="Add an existing checksum-verified snapshot to the observation store")
    ingest.add_argument("--config", default="config/collector.json")
    ingest.add_argument("--snapshot", required=True)
    select = commands.add_parser("select-model", help="Return to the baseline or roll back to a previously promoted model")
    select.add_argument("--config", default="config/collector.json")
    choice = select.add_mutually_exclusive_group(required=True)
    choice.add_argument("--baseline", action="store_true")
    choice.add_argument("--model-id")
    score = commands.add_parser("score-snapshot", help="Compare a later snapshot using the active model and baseline")
    score.add_argument("--config", default="config/collector.json")
    score.add_argument("--snapshot", required=True)
    score.add_argument("--output", required=True)
    return p


def run(args):
    if args.command in ("init-live", "collect", "status", "train", "ingest", "select-model", "score-snapshot"):
        from .live_config import LiveConfig
        from .live_utils import atomic_json, process_lock
        if args.command == "init-live":
            target = Path(args.config)
            if target.exists():
                raise ValueError("Config already exists; edit it or select another filename")
            config = LiveConfig(provider=args.provider)
            atomic_json(target, config.public_dict())
            print(f"Created {target}. Edit rate/yield assumptions before collection.")
            if args.provider == "yahoo":
                print("Yahoo data have unverified bid/ask timestamps and will not enter strict-quality model training.")
            else:
                print("Set TRADIER_TOKEN in the local environment. Production data entitlement is required.")
            return 0
        if args.command == "collect":
            from .collector import run_collector
            return run_collector(args.config, args.once, args.probe)
        config, root = LiveConfig.load(args.config)
        if args.command == "status":
            from .collector import live_status
            result = live_status(args.config)
        elif args.command == "train":
            from .learning import train
            result = train(root, config)
        elif args.command == "ingest":
            from .store import ObservationStore
            with process_lock(root/"collector.lock"):
                result = ObservationStore(root).ingest(args.snapshot, config)
        elif args.command == "score-snapshot":
            from .learning import score_snapshot
            result = score_snapshot(root, args.snapshot, args.output, config)
        else:
            from .learning import select_model
            result = select_model(root, args.model_id)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fetch":
        yields = {}
        for item in args.dividend_yields:
            symbol, value = item.split("=", 1)
            yields[symbol.upper()] = float(value)
        if Path(args.output).exists():
            raise ValueError("Snapshot output exists; choose a new directory")
        raw, meta, history = fetch_options(args.tickers, args.rate, yields, args.expirations,
                                           args.volatility, args.history_window, args.expiry_hour, args.estimator)
        if raw.empty:
            failure = Path(args.output+"-failure.json")
            failure.parent.mkdir(parents=True, exist_ok=True)
            with failure.open("x") as stream:
                json.dump(meta, stream, indent=2)
            print(f"No real quotes acquired. Diagnostics: {failure}", file=sys.stderr)
            return 2
        write_snapshot(raw, args.output, meta, history)
        print(f"Saved {len(raw)} raw option quotes to {args.output}; acquisition failures: {len(meta['failures'])}")
        return 0
    config = FilterConfig(min_volume=args.min_volume, min_open_interest=args.min_open_interest,
                          max_relative_spread=args.max_relative_spread,
                          max_last_trade_age_days=args.max_last_trade_age_days)
    if args.min_mid <= 0:
        raise ValueError("--min-mid must be positive")
    output = Path(args.output)
    # Refuse stale plots from an older run; analysis outputs are immutable run folders.
    if output.exists():
        raise ValueError("Analysis output exists; choose a new run directory")
    if args.command == "demo":
        raw, meta = synthetic_snapshot()
        write_snapshot(raw, output/"snapshot", meta)
        raw, meta = read_snapshot(output/"snapshot")
    else:
        raw, meta = read_snapshot(args.snapshot)
    df, audit = analyze_options(raw, config, args.min_mid)
    write_report(df, audit, meta, output, config, args.min_mid)
    if not args.no_plots:
        import matplotlib
        matplotlib.use("Agg")
        from .plots import save_figures
        model = BlackScholesEngine(100, 100, .25, .04, .2, .01)
        save_figures(df, model, output/"plots", meta.get("data_kind") == "synthetic")
    print(f"{'SYNTHETIC DEMO' if meta.get('data_kind') == 'synthetic' else 'MARKET SNAPSHOT'}: {len(df)}/{len(audit)} accepted. Report: {output/'REPORT.md'}")
    return 0 if len(df) else 2


def main():
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
