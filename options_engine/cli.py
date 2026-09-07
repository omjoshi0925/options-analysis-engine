import argparse
from pathlib import Path
import json
import sys
from .core import BlackScholesEngine
from .data import FilterConfig, fetch_options, read_snapshot, write_snapshot
from .analysis import analyze_options, write_report
from .demo import synthetic_snapshot


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
    return p


def run(args):
    if args.command == "fetch":
        yields = {}
        for item in args.dividend_yields:
            symbol, value = item.split("=", 1)
            yields[symbol.upper()] = float(value)
        if Path(args.output).exists():
            raise ValueError("Snapshot output exists; choose a new directory")
        raw, meta, history = fetch_options(args.tickers, args.rate, yields, args.expirations,
                                           args.volatility, args.history_window, args.expiry_hour)
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
    except (ValueError, OSError, KeyError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
