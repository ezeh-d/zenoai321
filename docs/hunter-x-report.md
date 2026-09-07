# HUNTER X initial research / paper release — 2026-09-07

Status: initial implementation, UNPROVEN. This does not complete every
capability in the 115-section master prompt or establish live readiness.

## Implemented

One lazy HUNTER X specialist reuses ZENO's existing tool registry, runtime,
capability router, Event Bus and panel manager. The `hunter_x` tool exposes
status, historical analysis, bounded scans, risk calculations, backtesting,
fixed-parameter walk-forward tests, paper account/journal/stop/resume,
attributed research records and a foundational arithmetic exam.

Market metadata supports stocks, crypto spot and forex. All accounting is
single-currency and cash-backed; no implicit NGN/USD conversion or leverage.
The existing investing tools and legacy account tables are preserved. HUNTER
X uses a separately labeled paper ledger because its cost/accounting semantics
differ; old trades are not silently migrated or relabeled.

Data: Yahoo public daily historical OHLCV with instrument-type, currency,
chronology and OHLC validation; incomplete recent daily bars excluded.
Frankfurter daily reference rates provide a separate forex analysis fallback.
Reference: https://frankfurter.dev/v1/ . Neither source is an executable quote.
No additional packages, API keys or paid subscription required for this scope.

Risk: finite positive arithmetic, stop direction, cost-adjusted reward/risk,
lot rounding, currency, freshness, per-position/per-trade/portfolio caps,
daily loss and drawdown checks. Default simulation policy: 1% per trade,
2% daily loss, 5% portfolio risk, 10% drawdown, 20% position allocation,
minimum 2:1 cost-adjusted reward/risk. These are explicit simulation defaults,
not financial recommendations or validated live policies.

Paper: atomic SQLite transactions, Decimal cash/cost arithmetic, modeled
fees/slippage, duplicate request IDs, restart persistence, journal,
cross-process global stop gate. Resume requires an explicit paper-only
acknowledgment. No live order transport exists.

Research: bounded attributed notes with classification/source-quality labels
and explicit unverified-source state. They cannot promote a strategy or run
code. Arithmetic exams score actual answers and never promote readiness.

Backtesting: SMA baseline v1, next-bar execution, fees/slippage, final
liquidation explicitly marked; return/drawdown/expectancy/profit factor,
cost-matched buy-and-hold benchmark, data hash, disjoint fixed-parameter
walk-forward windows, seeded IID resampling and higher-cost stress comparison.
Future-price perturbation tests guard past decisions.

Panel: one on-demand event-driven result view, working/error states, escaped
output, no polling, charts, hidden animation loops or floating agent windows.
There is no newly added microphone, model client or idle scanner service.

## Verification evidence

New tests reproduced missing components and safety defects before code.
137 focused tests passed after preserving existing agent roster ordering:
HUNTER X, agent identity/runtime, capability routing, panels and Phase 22.
The additional paper-resume test was subsequently run against its change.
Both panel JavaScript files pass Node syntax checking.

The registered-tool CLI exercised status, training, isolated paper initialization,
buy, identical retry, sell, journal and global stop. Two same-price units at
100 with modeled costs produced -0.6 simulated P&L, rather than fabricated
profit. Temporary databases were cleaned after the Event Bus writer stopped.
Concurrent duplicate requests result in one order. No user's account was traded.

Observed one-shot tool wall times in that run: cold status 415 ms; first paper
status 468 ms; paper buy 102 ms; duplicate retry 16 ms; later status 10 ms;
sell 73 ms; journal 7 ms; stop 74 ms. These are samples on this workstation,
not p95 guarantees or broker execution timings.

Real public data checks successfully retrieved AAPL and BTC-USD historical
observations and an EUR/USD reference rate dated 2026-09-04. Yahoo forex OHLC
failed quality checks. Subsequent combined runs encountered request timeouts
and DNS errors for crypto/forex and the real-data backtest. Failures returned
ERROR/NO_TRADE. No successful real-data backtest is claimed from that run.

## Remaining limitations

- No live broker/demo adapter, real-time quote/order book, order submission,
  partial fills, protective broker orders, or broker reconciliation.
- No short selling, leverage, options/futures, cross-currency portfolio, sector
  correlation model or weekly loss policy. Cash-backed simulation only.
- The paper ledger records explicit scenario prices; it does not run automatic
  mark-to-market, stop execution or background autonomous strategies. Portfolio
  valuation is explicitly cost basis; drawdown gate uses realized accounting.
- The SMA baseline is not production validated; no strategy optimizer,
  champion/challenger promotion, survivorship/corporate-action correction,
  gap/stop execution model or statistically certified edge exists.
- Training currently covers four arithmetic questions. Full market-mechanics
  curriculum, elite-trader source study and persistent exam scorecard remain.
- Research notes are stored but sources are not independently verified.
  No automated ingest or exhaustive knowledge base has been fabricated.
- Panel syntax and integration tested; physical Windows drag/visibility and
  full voice-delegation interaction still need manual verification. No chart
  or persistent panel snapshot is claimed.
- Market-data reliability remains provider/network-dependent. Cancellation is
  checked between requests; blocking requests use bounded transport timeouts.
- Full prompt compliance, hour-long load measurements, complete market chaos
  matrix and paper-proven/live-proven classification remain outstanding.

## Commands

From the ZENO project root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_hunter_x.py tests/test_agent_identity.py tests/test_dynamic_agent_runtime.py tests/test_capability_router.py tests/test_panels.py tests/test_phase22_stability.py -q
.\.venv\Scripts\python.exe scripts/verify_hunter_x.py
.\.venv\Scripts\python.exe scripts/verify_hunter_x.py --live-data
```

Suggested ZENO requests: "Hunter X, status", "Hunter X, analyze AAPL as
stocks", "Hunter X, analyze BTC-USD as crypto", "Hunter X, analyze EURUSD=X
as forex", "Hunter X, show training questions", "Hunter X, stop paper trading".
