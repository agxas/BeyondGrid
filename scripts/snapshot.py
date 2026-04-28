#!/usr/bin/env python3
"""
Daily snapshot — màj des prix + photo par compte.
Lancé chaque soir de semaine via GitHub Actions.
"""

import os
import sys
import logging
from datetime import date, datetime, timezone
from collections import defaultdict

import yfinance as yf
from supabase import create_client, Client

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def get_yahoo_price(ticker: str) -> float | None:
    """Retourne le dernier cours de clôture disponible via Yahoo Finance."""
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            log.warning(f"    Historique vide pour {ticker}")
            return None
        return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        log.warning(f"    yfinance erreur ({ticker}): {e}")
        return None


def update_prices(sb: Client) -> dict[int, float]:
    """
    Met à jour last_known_price pour les assets auto_price=True.
    Retourne un dict {asset_id: prix} pour TOUS les assets (fallback inclus).
    """
    assets = (
        sb.table("assets")
        .select("id, name, yahoo_ticker, auto_price, last_known_price")
        .execute()
        .data
    )
    now_utc = datetime.now(timezone.utc).isoformat()
    price_map: dict[int, float] = {}

    for asset in assets:
        aid = asset["id"]
        name = asset["name"]

        if asset["auto_price"] and asset["yahoo_ticker"]:
            price = get_yahoo_price(asset["yahoo_ticker"])
            if price is not None:
                sb.table("assets").update(
                    {"last_known_price": price, "last_price_updated_at": now_utc}
                ).eq("id", aid).execute()
                price_map[aid] = price
                log.info(f"  ✓ {name:<52} {price:.4f}")
            else:
                # Fallback sur le dernier prix connu
                fallback = float(asset["last_known_price"] or 0)
                price_map[aid] = fallback
                log.warning(f"  ⚠ {name:<52} fallback {fallback:.4f}")
        else:
            # Prix manuel — on lit sans toucher
            manual = float(asset["last_known_price"] or 0)
            price_map[aid] = manual
            log.info(f"  · {name:<52} {manual:.4f}  (manuel)")

    return price_map


def compute_snapshot(
    account_id: int,
    transactions: list[dict],
    price_map: dict[int, float],
    today: str,
) -> dict | None:
    """
    Calcule total_value, invested_capital et cash pour un compte.

    Conventions (voir schema.sql) :
      total_amount > 0  →  entrée d'argent dans l'enveloppe
      total_amount < 0  →  sortie d'argent de l'enveloppe

    cash             = Σ total_amount  (tous types confondus)
    invested_capital = Σ total_amount  (deposit + withdrawal uniquement)
    total_value      = cash + Σ (quantité_nette × prix_actuel)
    """
    acc_txns = [t for t in transactions if t["account_id"] == account_id]

    if not acc_txns:
        log.warning(f"  Aucune transaction pour le compte {account_id}, ignoré.")
        return None

    # Liquidités disponibles
    cash_raw = sum(float(t["total_amount"]) for t in acc_txns)
    if cash_raw < 0:
        log.warning(
            f"  Compte {account_id} : cash calculé négatif ({cash_raw:.2f} €) — "
            "probable incohérence dans les transactions historiques. Corrigé à 0."
        )
    cash = max(0.0, cash_raw)

    # Capital net investi (hors rendement)
    invested_capital = sum(
        float(t["total_amount"])
        for t in acc_txns
        if t["type"] in ("deposit", "withdrawal")
    )

    # Quantité nette par asset (achats - ventes)
    positions: dict[int, float] = defaultdict(float)
    for t in acc_txns:
        if not t["asset_id"] or not t["quantity"]:
            continue
        if t["type"] == "buy":
            positions[t["asset_id"]] += float(t["quantity"])
        elif t["type"] == "sell":
            positions[t["asset_id"]] -= float(t["quantity"])

    # Valorisation
    market_value = sum(
        qty * price_map.get(aid, 0.0)
        for aid, qty in positions.items()
        if qty > 1e-9
    )

    total_value = round(cash + market_value, 2)

    return {
        "date": today,
        "account_id": account_id,
        "total_value": total_value,
        "invested_capital": round(invested_capital, 2),
        "cash": round(cash, 2),
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    today = date.today().isoformat()
    log.info(f"══ Snapshot {today} {'═' * 45}")

    sb: Client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

    # 1 ─ Mise à jour des prix
    log.info("── 1/3  Mise à jour des prix ─────────────────────────────────")
    price_map = update_prices(sb)

    # 2 ─ Chargement de toutes les transactions
    log.info("── 2/3  Chargement des transactions ──────────────────────────")
    transactions = sb.table("transactions").select("*").execute().data
    log.info(f"  {len(transactions)} transactions chargées")

    # 3 ─ Snapshot par compte actif
    log.info("── 3/3  Calcul + écriture des snapshots ──────────────────────")
    accounts = (
        sb.table("accounts")
        .select("id, name")
        .eq("is_active", True)
        .execute()
        .data
    )

    errors = 0
    for account in accounts:
        acc_id, acc_name = account["id"], account["name"]

        snapshot = compute_snapshot(acc_id, transactions, price_map, today)
        if snapshot is None:
            errors += 1
            continue

        try:
            sb.table("snapshots").upsert(
                snapshot, on_conflict="date,account_id"
            ).execute()
            log.info(
                f"  [{acc_name}]  "
                f"total={snapshot['total_value']:>10.2f} €  |  "
                f"investi={snapshot['invested_capital']:>10.2f} €  |  "
                f"cash={snapshot['cash']:>8.2f} €"
            )
        except Exception as e:
            log.error(f"  [{acc_name}]  Erreur upsert: {e}")
            errors += 1

    # Résultat final
    log.info("─" * 60)
    if errors:
        log.error(f"Terminé avec {errors} erreur(s). Vérifier les logs.")
        sys.exit(1)
    log.info("✓ Snapshot complet, aucune erreur.")


if __name__ == "__main__":
    main()
