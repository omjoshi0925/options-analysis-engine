"""Reproducible Matplotlib figures; no implicit display or network access."""
from dataclasses import replace
from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from .numerics import greek_error_study


def sensitivity_figure(model, parameter="S", points=160):
    if parameter not in ("S", "K", "T", "sigma"):
        raise ValueError("parameter must be S, K, T, or sigma")
    if model.T <= 0 or model.sigma <= 0:
        raise ValueError("Sensitivity curves require positive T and sigma")
    reference = getattr(model, parameter)
    if parameter in ("S", "K"):
        x = np.linspace(reference*.5, reference*1.5, points)
    elif parameter == "T":
        x = np.geomspace(1/3650, max(1, 2*reference), points)
    else:
        x = np.linspace(.01, max(1, 2*reference), points)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    labels = ["Price", "Delta", "Gamma", "Theta", "Vega", "Rho"]
    units = ["currency/share", "per spot unit", "per spot unit²", "currency/share/year",
             "per 1.0 volatility", "per 1.0 rate"]
    for kind, color in (("call", "#146A9A"), ("put", "#CE6B30")):
        records = []
        for value in x:
            m = replace(model, **{parameter: value})
            records.append({"Price": m.price(kind), **m.analytical_greeks(kind)})
        for ax, label, unit in zip(axes.flat, labels, units, strict=True):
            ax.plot(x, [row[label] for row in records], label=kind.title(), color=color)
            ax.set(title=label, xlabel={"S": "Underlying price S", "K": "Strike K", "T": "Time T (years)", "sigma": "Volatility (decimal)"}[parameter], ylabel=unit)
            ax.axvline(reference, color="gray", ls=":", lw=.8)
            ax.grid(alpha=.2)
            if parameter == "T":
                ax.set_xscale("log")
    axes.flat[0].legend()
    fig.suptitle(f"Black-Scholes-Merton sensitivities | varying {parameter}", fontsize=15)
    fig.tight_layout()
    return fig


def numerical_error_figure(study):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for kind, ax in zip(("call", "put"), axes, strict=True):
        for name, group in study.loc[study.option_type == kind].groupby("greek"):
            ax.loglog(group.relative_step, group.absolute_error.clip(lower=1e-16), marker=".", label=name)
        ax.set(title=f"{kind.title()}: analytic vs finite difference", xlabel="Relative step h", ylabel="Absolute error (raw Greek units)")
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def market_figure(df, synthetic=False):
    fig, axes = plt.subplots(2, 4, figsize=(17, 8))
    for (symbol, kind), sub in df.groupby(["symbol", "option_type"]):
        label = f"{symbol} {kind}"
        axes.flat[0].scatter(sub.baseline_price, sub.mid, s=12, alpha=.5, label=label)
        for ax, field, title in zip(list(axes.flat)[1:],
                                   ["log_moneyness", "strike", "days_to_expiry", "identified_iv", "volume", "openInterest", "relative_spread"],
                                   ["ln(S/K)", "Strike", "Days to expiry", "Calculated IV (decimal)", "Volume", "Open interest", "Relative spread"], strict=True):
            ax.scatter(sub[field], sub.error, s=12, alpha=.5)
            ax.axhline(0, color="gray", lw=.8)
            ax.set(xlabel=title, ylabel="Midpoint - baseline")
            if field in ("volume", "openInterest"):
                ax.set_xscale("symlog", linthresh=1)
    lo, hi = min(df.mid.min(), df.baseline_price.min()), max(df.mid.max(), df.baseline_price.max())
    axes.flat[0].plot([lo, hi], [lo, hi], ls="--", color="black", lw=.8)
    axes.flat[0].set(xlabel="Independent baseline price", ylabel="Observed midpoint")
    axes.flat[0].legend(fontsize=7)
    for ax in axes.flat:
        ax.grid(alpha=.15)
    fig.suptitle("SYNTHETIC DEMO - NOT MARKET EVIDENCE" if synthetic else "Observed quote diagnostics | European BSM comparator")
    fig.tight_layout()
    return fig


def smile_figure(df, symbol, synthetic=False):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    eligible = df.loc[(df.symbol == symbol) & df.iv_brent_converged &
                      ~df.iv_brent_poorly_identified & (df.iv_brent_volatility > 0)]
    for kind, ax in zip(("call", "put"), axes, strict=True):
        for expiry, sub in eligible.loc[eligible.option_type == kind].groupby("expiration"):
            sub = sub.sort_values("log_moneyness")
            ax.plot(sub.log_moneyness, sub.iv_brent_volatility, ".-", label=expiry)
        ax.axvline(0, color="gray", ls="--", lw=.8)
        ax.set(title=f"{symbol} {kind}", xlabel="ln(S/K): lower strikes to the right", ylabel="Implied volatility (decimal)")
        ax.grid(alpha=.2)
        if len(ax.lines) > 1:
            ax.legend(fontsize=8)
    fig.suptitle("SYNTHETIC volatility smiles" if synthetic else "European-equivalent implied-volatility smiles")
    fig.tight_layout()
    return fig


def strategy_figure(strategy, S, T, r, sigma, q=0.0, points=241):
    """Expiry payoff (exact) and the closed-form mark before expiry across a spot grid around the strikes."""
    anchors = [S]+strategy.strikes
    lo, hi = 0.7*min(anchors), 1.3*max(anchors)
    grid = np.linspace(lo, hi, points)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(grid, strategy.payoff(grid), color="#146A9A", lw=2, label="Profit at expiry")
    if T > 0 and sigma > 0:
        ax.plot(grid, [strategy.value(x, T, r, sigma, q) for x in grid], color="#CE6B30", ls="--", label=f"Closed-form mark, T={T:.3g}y")
    ax.axhline(0, color="gray", lw=.8)
    ax.axvline(S, color="gray", ls=":", lw=.8, label="Spot")
    for root in strategy.breakevens():
        ax.axvline(root, color="#5B8C5A", ls="-.", lw=.8)
    ax.set(title=f"{strategy.name.replace('_', ' ')} | net premium {strategy.net_premium:+.4f}/share",
           xlabel="Underlying price at expiry", ylabel="Profit per share")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def save_figures(df, model, output, synthetic=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.savefig(output/name, dpi=160, bbox_inches="tight")
        plt.close(fig)

    for parameter in ("S", "K", "T", "sigma"):
        save(sensitivity_figure(model, parameter), f"sensitivities_{parameter}.png")
    study = pd.concat([greek_error_study(model, kind) for kind in ("call", "put")], ignore_index=True)
    study.to_csv(output.parent/"greek_step_study.csv", index=False)
    save(numerical_error_figure(study), "greek_error_convergence.png")
    if df.empty:
        return
    save(market_figure(df, synthetic), "market_diagnostics.png")
    for symbol in df.symbol.unique():
        safe_symbol = re.sub(r"[^A-Za-z0-9_-]", "_", str(symbol))
        save(smile_figure(df, symbol, synthetic), f"smile_{safe_symbol}.png")
        # Surface only within an asset and option type, with adequate noncollinear data.
        for kind in ("call", "put"):
            sub = df.loc[(df.symbol == symbol) & (df.option_type == kind) & df.iv_brent_converged &
                         ~df.iv_brent_poorly_identified & (df.iv_brent_volatility > 0)]
            sub = sub.groupby(["log_moneyness", "days_to_expiry"], as_index=False).iv_brent_volatility.mean()
            if len(sub) < 6 or sub.days_to_expiry.nunique() < 3 or sub.log_moneyness.nunique() < 3:
                continue
            fig = plt.figure(figsize=(9, 6))
            ax = fig.add_subplot(projection="3d")
            ax.plot_trisurf(sub.log_moneyness, sub.days_to_expiry, sub.iv_brent_volatility, cmap="viridis", alpha=.7)
            ax.scatter(sub.log_moneyness, sub.days_to_expiry, sub.iv_brent_volatility, color="black", s=6)
            prefix = "SYNTHETIC | " if synthetic else ""
            ax.set(title=f"{prefix}{symbol} {kind} | triangular IV interpolation", xlabel="ln(S/K)", ylabel="Days to expiry")
            fig.subplots_adjust(left=.02, right=.87, top=.9, bottom=.08)
            fig.text(.91, .52, "IV (decimal)", rotation=90, va="center")
            save(fig, f"surface_{safe_symbol}_{kind}.png")
