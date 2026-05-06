#!/usr/bin/env python3
"""
backfill.py — Reconstruction des snapshots historiques.

À exécuter UNE SEULE FOIS après un TRUNCATE de la table snapshots,
pour reconstituer l'historique depuis la première transaction jusqu'à hier.
Aujourd'hui est géré par snapshot.py (GitHub Actions).

Méthode :
  - Assets auto_price=True  → prix historiques via yfinance
  - Assets auto_price=False → last_known_price utilisé comme proxy constant
    (approximation : sous-estime légèrement les perfs passées, mais
     invested_capital reste toujours exact)

Usage :
  python scripts/backfill.py
  python scripts/backfill.py --dry-run    # simule sans écrire en base
  python scripts/backfill.py --from 2024-01-01  # date de départ forcée
"""

import os
import sys
import logging
import argparse
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from supabase import create_client, Client

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BATCH_SIZE = 100   # lignes par upsert


# ── Helpers ────────────────────────────────────────────────────────────────

def fetch_price_history(
    assets: list[dict],
    start: str,
    end: str,
) -> dict[int, pd.Series]:
    """
    Télécharge l'historique de prix pour tous les assets auto_price.
    Retourne {asset_id: Series(date → prix)} avec forward-fill.
    Les assets manuels reçoivent une série plate à last_known_price.
    """
    auto_assets  = {a["id"]: a["yahoo_ticker"] for a in assets
                    if a["auto_price"] and a["yahoo_ticker"]}
    manual_assets = {a["id"]: float(a["last_known_price"] or 0) for a in assets
                     if not a["auto_price"] or not a["yahoo_ticker"]}

    price_map: dict[int, pd.Series] = {}

    # ── Assets automatiques ─────────────────────────────────────
    if auto_assets:
        tickers = list(auto_assets.values())
        log.info(f"  Téléchargement yfinance : {len(tickers)} ticker(s) "
                 f"du {start} au {end}")

        hist = yf.download(
            tickers,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )

        if hist.empty:
            log.warning("  yfinance n'a retourné aucune donnée.")
        else:
            close = hist["Close"]

            # yfinance retourne une Series si un seul ticker, DataFrame sinon
            if isinstance(close, pd.Series):
                close = close.to_frame(name=tickers[0])

            # Strip timezone pour cohérence avec nos dates
            if close.index.tz is not None:
                close.index = close.index.tz_localize(None)

            close = close.ffill()   # combler les jours non tradés

            for asset_id, ticker in auto_assets.items():
                if ticker in close.columns:
                    series = close[ticker].dropna()
                    if not series.empty:
                        price_map[asset_id] = series
                        log.info(f"  ✓ {ticker:<20} {len(series)} jours")
                    else:
                        log.warning(f"  ⚠ {ticker} — série vide, fallback prix courant")
                        price_map[asset_id] = pd.Series(dtype=float)
                else:
                    log.warning(f"  ⚠ {ticker} — absent des résultats yfinance")
                    price_map[asset_id] = pd.Series(dtype=float)

    # ── Assets manuels ──────────────────────────────────────────
    if manual_assets:
        log.info(f"  {len(manual_assets)} asset(s) manuel(s) → prix courant utilisé comme proxy")
        for asset_id, price in manual_assets.items():
            # Série plate : même prix sur toute la plage
            idx = pd.date_range(start=start, end=end, freq="B")
            price_map[asset_id] = pd.Series(price, index=idx)

    return price_map


def get_price(
    asset_id: int,
    day: pd.Timestamp,
    price_map: dict[int, pd.Series],
) -> float:
    """
    Retourne le prix d'un asset à une date donnée.
    Si la date exacte n'est pas disponible, prend le dernier prix connu
    (forward-fill depuis le début de série).
    """
    series = price_map.get(asset_id)
    if series is None or series.empty:
        return 0.0

    available = series[series.index <= day]
    if available.empty:
        # Pas encore de données à cette date → premier prix connu
        return float(series.iloc[0])

    return float(available.iloc[-1])


def compute_snapshot_for_date(
    account_id: int,
    day: str,
    transactions: list[dict],
    price_map: dict[int, pd.Series],
) -> dict | None:
    """
    Calcule total_value et invested_capital pour un compte à une date donnée.
    Retourne None si le compte n'a aucune transaction à cette date.
    """
    day_ts  = pd.Timestamp(day)
    acc_txns = [
        t for t in transactions
        if t["account_id"] == account_id
        and pd.Timestamp(t["date"]) <= day_ts
    ]

    if not acc_txns:
        return None

    # Capital net investi = −Σ total_amount (buy + sell)
    invested_capital = -sum(
        float(t["total_amount"])
        for t in acc_txns
        if t["type"] in ("buy", "sell")
    )

    # Quantités nettes par asset
    positions: dict[int, float] = defaultdict(float)
    for t in acc_txns:
        if not t["asset_id"] or not t["quantity"]:
            continue
        if t["type"] == "buy":
            positions[t["asset_id"]] += float(t["quantity"])
        elif t["type"] == "sell":
            positions[t["asset_id"]] -= float(t["quantity"])

    # Valorisation
    total_value = sum(
        qty * get_price(aid, day_ts, price_map)
        for aid, qty in positions.items()
        if qty > 1e-9
    )

    return {
        "date":             day,
        "account_id":       account_id,
        "total_value":      round(total_value, 2),
        "invested_capital": round(invested_capital, 2),
    }


def upsert_batch(sb: Client, rows: list[dict], dry_run: bool) -> int:
    """Upsert un batch de snapshots. Retourne le nombre de lignes écrites."""
    if dry_run or not rows:
        return len(rows)
    sb.table("snapshots").upsert(
        rows, on_conflict="date,account_id"
    ).execute()
    return len(rows)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill des snapshots historiques")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans écrire en base")
    parser.add_argument("--from", dest="start_date", default=None,
                        help="Date de départ forcée (YYYY-MM-DD)")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        log.info("🔍 MODE DRY-RUN — aucune écriture en base")

    sb: Client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

    # ── 1. Chargement des données ──────────────────────────────
    log.info("── 1/4  Chargement des données ───────────────────────────────")

    transactions = sb.table("transactions").select("*").execute().data
    if not transactions:
        log.error("Aucune transaction en base. Rien à backfiller.")
        sys.exit(1)
    log.info(f"  {len(transactions)} transaction(s) chargée(s)")

    accounts = (
        sb.table("accounts").select("id, name")
        .eq("is_active", True).execute().data
    )
    log.info(f"  {len(accounts)} compte(s) actif(s) : "
             f"{', '.join(a['name'] for a in accounts)}")

    assets = (
        sb.table("assets")
        .select("id, name, yahoo_ticker, auto_price, last_known_price")
        .execute().data
    )
    log.info(f"  {len(assets)} asset(s) en base")

    # ── 2. Plage de dates ─────────────────────────────────────
    log.info("── 2/4  Calcul de la plage de dates ──────────────────────────")

    if args.start_date:
        start = pd.Timestamp(args.start_date)
    else:
        first_txn_date = min(pd.Timestamp(t["date"]) for t in transactions)
        start = first_txn_date
    end   = pd.Timestamp(date.today() - timedelta(days=1))   # hier

    if start > end:
        log.info("Aucune date à backfiller (déjà à jour).")
        sys.exit(0)

    business_days = pd.bdate_range(start=start, end=end)
    log.info(f"  Du {start.date()} au {end.date()} "
             f"→ {len(business_days)} jour(s) ouvré(s)")

    # ── 3. Téléchargement des prix ────────────────────────────
    log.info("── 3/4  Téléchargement des prix historiques ──────────────────")

    price_map = fetch_price_history(
        assets,
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=2)).strftime("%Y-%m-%d"),  # marge pour ffill
    )

    # ── 4. Calcul et écriture des snapshots ───────────────────
    log.info("── 4/4  Calcul et écriture des snapshots ─────────────────────")

    total_written = 0
    batch: list[dict] = []
    skipped = 0

    for day in business_days:
        day_str = day.strftime("%Y-%m-%d")

        for account in accounts:
            snap = compute_snapshot_for_date(
                account["id"], day_str, transactions, price_map
            )
            if snap is None:
                skipped += 1
                continue

            batch.append(snap)

            if len(batch) >= BATCH_SIZE:
                total_written += upsert_batch(sb, batch, dry_run)
                batch = []

    # Écriture du dernier batch
    if batch:
        total_written += upsert_batch(sb, batch, dry_run)

    # ── Résumé ────────────────────────────────────────────────
    log.info("─" * 60)
    action = "simulés" if dry_run else "écrits"
    log.info(f"✓ {total_written} snapshot(s) {action} "
             f"({skipped} ignorés — comptes sans transaction à cette date)")

    if dry_run:
        log.info("  Relancer sans --dry-run pour écrire en base.")


if __name__ == "__main__":
    main()
