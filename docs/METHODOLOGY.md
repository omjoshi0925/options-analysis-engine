# Mathematics and empirical methodology

## Model and units

Inputs are spot S > 0, strike K > 0, time T >= 0 in ACT/365F years, continuously
compounded annual decimal r and q, and annual decimal volatility sigma >= 0.
Negative rates/yields are allowed; nonfinite values and negative time/volatility
are rejected. Premiums are per share. The package does not apply a contract multiplier.

For positive T and sigma:

\[
d_1=\frac{\ln(S/K)+(r-q+\sigma^2/2)T}{\sigma\sqrt{T}},\qquad d_2=d_1-\sigma\sqrt{T}.
\]

\[
C=Se^{-qT}N(d_1)-Ke^{-rT}N(d_2),\quad
P=Ke^{-rT}N(-d_2)-Se^{-qT}N(-d_1).
\]

The OTM side is computed using log-CDF values and `expm1` to reduce cancellation;
the ITM side follows from C-P = Se^(-qT)-Ke^(-rT). Thus analytic formula parity is
partly structural; independent risk-neutral payoff quadrature also tests price correctness.
At expiry return intrinsic value exactly. At zero volatility and positive time,
return max(Se^(-qT)-Ke^(-rT),0) or its put equivalent. d1/d2 are undefined at these
boundaries; the code reports NaN and declines Greek diagnostics there.

## Derivatives and verification

Let A = exp(-qT), B = exp(-rT), and phi be the standard normal density.
The identity S A phi(d1) = K B phi(d2) cancels chain-rule terms in first derivatives.
Since partial d1 / partial S = 1/(S sigma sqrt(T)), differentiating Delta gives Gamma.

| Greek | Call | Put |
|---|---|---|
| Delta = dV/dS | A N(d1) | -A N(-d1) |
| Gamma = d²V/dS² | A phi(d1)/(S sigma sqrt(T)) | Same |
| Vega = dV/dsigma | S A phi(d1) sqrt(T) | Same |
| Theta = -dV/dT | -S A phi(d1) sigma/(2 sqrt(T)) - r K B N(d2) + q S A N(d1) | -S A phi(d1) sigma/(2 sqrt(T)) + r K B N(-d2) - q S A N(-d1) |
| Rho = dV/dr | K T B N(d2) | -K T B N(-d2) |

Raw Theta is per year; raw Vega/Rho are per unit decimal change. Market display
divides Theta by 365 and Vega/Rho by 100. Numerical verification always uses raw units.

Central differences use [V(x+h_x)-V(x-h_x)]/(2h_x), with Gamma using
[V(S+h_S)-2V(S)+V(S-h_S)]/h_S². Theta has the minus sign from calendar-time decay.
The default relative h is 1e-4; each parameter uses h*max(|x|,1), capped at x/4
for positive-domain S, T, and sigma. Both sides and the denominator use that same
actual step. The convergence study spans 1e-2 through 1e-7 and records absolute
errors, relative errors only when |analytic| > 1e-10, and actual parameter steps.
Second-order truncation error competes with floating-point cancellation. A smaller
step is not necessarily more accurate, especially for Gamma and near expiration.

## Implied volatility

For European calls the bounds are [max(SA-KB,0), SA]; puts use [max(KB-SA,0), KB].
Finite IV has a strict upper price limit; a quote at the upper bound has no finite
IV. A quote within the absolute price tolerance of the lower bound is reported
as the zero-volatility limit and poorly identified, not a precisely known zero IV.
An expired contract has no identifiable IV.

Brent starts with a bracket [0,0.5] and doubles its upper side until it encloses
a root or reaches the explicit 10.0 cap. This cap is a numerical search policy,
not a claim that larger volatilities are economically impossible. Newton uses
analytical Vega, stays in the bracket, and falls back to Brent after low Vega or
non-convergence. Newton iteration counts include its iterations and any Brent
fallback. Both paths require a repricing residual <= 1e-8 currency units; step
convergence alone is insufficient. Near-zero Vega identifies unstable inversion.

The report keeps the method, iterations, residual, Vega, fallback flag,
identifiability flag, and failure status for every accepted quote. Approximate
half-spread/Vega is a first-order IV uncertainty diagnostic, not a confidence interval.

## Acquisition, time, and liquidity

Each chain records UTC retrieval time and its underlying quote. An unadjusted
daily close is a labeled fallback for spot. Adjusted daily closes are used only
for the realized-volatility baseline (falling back explicitly to unadjusted Close
if Adj Close is absent). The estimate uses the standard deviation of 60 log returns,
ddof=1, multiplied by sqrt(252), from complete sessions strictly before capture day.
Each asset's input sigma, source, history endpoint, r, and q are retained.

Expiration dates default to 16:00 America/New_York with daylight-saving conversion.
T uses fractional seconds, not integer days. Expired contracts are excluded.
This is a PM-settlement convention, not a universal contract calendar: early-close
days, AM-settled index contracts, non-US sessions, and special expirations require
appropriate timestamp/convention inputs. Exact timezone-aware expiration timestamps
in an imported raw file override the date/hour assumption.

Default quality filters require positive finite bid/ask, ask >= bid, relative
spread <= 0.5, open interest >= 10, positive finite spot/strike/baseline volatility,
and 0 < T <= 730 days. Volume defaults to an optional filter: missing volume is
allowed unless a positive threshold is requested. Duplicate contract snapshots are
all excluded to avoid silently selecting inconsistent quotes. The audit retains
every exclusion reason, so reason counts can exceed rejected-row counts.

`lastTradeDate` is trade age, not quote age. Filtering it is optional and explicit.
The provider does not supply a reliable per-row bid/ask timestamp through this
interface. Retrieval time cannot prove fresh synchronized quotes. Live collection
is best interpreted after checking market hours, spot timestamps, and delays.

## Accuracy without circular calibration

The baseline has one independent constant sigma per underlying snapshot, from
historical returns or a declared scenario. It never uses an option's solved IV
or provider IV. Contract-IV reconstruction verifies inversion only. Even this
independent historical comparator is descriptive, not an out-of-time forecasting test.

Error = midpoint - baseline price. Normalized error = error/midpoint, reported
only for midpoint >= 0.10 by default; MAPE records its own denominator and threshold.
MAE, RMSE, mean and median errors use all liquidity-accepted contracts, including
quotes whose IV cannot be solved or that violate European price bounds. This
prevents selectively discarding the largest pricing failures. The quote audit and
IV diagnostics are separate. Baseline Greeks hold sigma constant; they are not
total derivatives of a fitted volatility surface.

Metrics group by symbol, type, expiry, fixed moneyness/tenor/IV/liquidity bins, and
asset/type/expiry. Dollar errors are not scale comparable across different assets;
percentage errors and within-spread rates help, but have their own limitations.
Small groups are descriptive. No p-values, causality claims, profitable trading
signals, or forward-performance claims are inferred from these grouped snapshots.

IV is plotted against ln(S/K), so a conventional higher-IV-at-low-strikes skew has
a positive slope on this axis. Surface plots use observed points and triangular
interpolation within one asset and type, only when at least three expirations and
three distinct moneyness values are available. They are visual summaries, not
arbitrage-free calibrated surfaces. Moneyness bins are S/K bins, not ITM/OTM labels
shared between calls and puts.

## Interpreting assumption failures

Nonflat smiles challenge a shared constant volatility under the maintained model.
However, uncertain r/q, discrete dividends, American early exercise, asynchronous
quotes, and transaction costs can also explain deviations. The generated report
discusses constant rates, continuous dividends/trading, frictionless markets,
lognormal price levels, continuous paths, and European exercise separately.
One cross-section cannot identify which mechanism caused a given residual.

Matched market call-put diagnostics use [call bid-put ask, call ask-put bid].
Their European parity target is a diagnostic for stock/ETF chains, not an executable
arbitrage claim for American contracts. A genuine predictive comparison requires
calibration data separate from evaluation data and multiple observation dates.

## References

- [SciPy Brent documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html): bracketing and convergence contract.
- [SciPy Newton documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.newton.html): need to verify a root despite step convergence.
- [yfinance documentation](https://ranaroussi.github.io/yfinance/) and [Ticker API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html): provider interface and research-oriented use.
- [OIC: American and European exercise](https://www.optionseducation.org/news/what-is-the-difference-between-american-style-and): exercise-style distinction and European BSM assumptions.
- [OIC: Options exercise](https://www.optionseducation.org/referencelibrary/faq/options-exercise): dividend-related early-exercise considerations.
- [MathWorks: Black-Scholes formula](https://www.mathworks.com/help/symbolic/the-black-scholes-formula-for-call-option-price.html): reference formula and risk-neutral interpretation.
