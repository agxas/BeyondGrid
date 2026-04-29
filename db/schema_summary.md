# Database Schema Summary

This database is designed for a multi-portfolio investment tracking dashboard.

## Tables Overview

### accounts
Represents investment accounts (PEA, CTO, crypto, etc.)
- One account = one portfolio container

### assets
Financial instruments held in portfolios
- Stocks, ETFs, crypto, cash, etc.
- Can include benchmark assets

### transactions
All financial operations
- Buy, sell, deposit, withdrawal, dividends, fees
- Core table for portfolio reconstruction

### snapshots
Daily aggregated portfolio values
- Total value
- Invested capital
- Cash
- Generated automatically (GitHub Actions)

### settings
Global configuration (single row)
- FIRE target
- DCA amount
- Inflation
- Expected return
- Livret A rate

---

## Key Concepts

- **Multi-account architecture** (PEA, CTO, etc.)
- **Snapshot-based tracking** for time-series analysis
- **Transaction-driven portfolio reconstruction**
- **Benchmark support** via assets table
- **FIRE metrics support** (target, withdrawal rate, etc.)

---

## Usage Notes

- `settings` is a singleton table (only one row with id = 1)
- `snapshots` are generated daily
- `assets.auto_price` indicates if price is updated automatically
- `assets.is_benchmark` is used for comparison charts
