# ============================================================
# app.py — BeyondGrid Dashboard
# ============================================================
# STRUCTURE GÉNÉRALE :
#   1. CONFIG & CONNEXION
#   2. DATA LAYER    (fetch_*)
#   3. CALCULS       (compute_*)
#   4. PAGES         (page_*)
#   5. ROUTING       (sidebar + appel de page)
# ============================================================

import math
import os

import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from supabase import create_client

# ============================================================
# 1. CONFIG & CONNEXION
# ============================================================

st.set_page_config(
    page_title="BeyondGrid",
    page_icon="📈",
    layout="wide",
)

# ============================================================
# VERSION
# ============================================================
APP_VERSION = "1.0"
PATCH_NOTES = {
    "1.0": [
        "Vue Globale : KPIs, objectif FIRE, évolution patrimoine, drawdown",
        "Analyses : Sharpe, volatilité, Livret A, benchmark, projection DCA",
        "Rééquilibrage PEA : allocations cibles et ordres Trade Republic",
        "Saisie manuelle : paramètres, prix manuels, transactions",
    ],
}

# ============================================================
# LIENS PRIX MANUELS
# Mapping ISIN → URL de la page de cours.
# Pour les ETFs, justETF est généré automatiquement depuis l'ISIN.
# Renseigner ici les fonds OPCVM sans lien automatique possible.
# ============================================================
PRICE_LINKS: dict[str, str] = {
    "LU0292095535": "https://www.justetf.com/fr/etf-profile.html?isin=LU0292095535#apercu",
    "LU1832174962": "https://www.boursorama.com/bourse/opcvm/cours/0P0001DKPM/",
    "QS0004088926": "https://investir.lesechos.fr/cours/opcvm/impact-isr-performance-i-qs0004088926",
    "QS0004036743": "https://investir.lesechos.fr/cours/opcvm/selection-mirova-actions-interntl-i-qs0004036743",
}


def fmt_eur(x: float) -> str:
    """Formate un montant en euros avec séparateurs de milliers français."""
    return f"{x:,.0f} €".replace(",", " ")


# Options de période partagées entre toutes les pages
PERIODE_OPTIONS  = ["1 mois", "3 mois", "6 mois", "1 an", "3 ans", "Tout"]
PERIODE_DEFAULT  = "1 an"   # index calculé dynamiquement depuis la liste


@st.cache_resource
def init_db():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

supabase = init_db()


# ============================================================
# 2. DATA LAYER
# ============================================================

@st.cache_data(ttl=600)
def fetch_snapshots_agg() -> pd.DataFrame:
    """
    Snapshots agrégés par date (somme de tous les comptes).
    Retourne un DataFrame avec colonnes :
      date | total_value | invested_capital | cash
    Trié par date ASC.
    """
    res = supabase.table("snapshots").select(
        "date, total_value, invested_capital, cash"
    ).execute()

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["date"])

    df = (
        df.groupby("date")[["total_value", "invested_capital", "cash"]]
        .sum()
        .reset_index()
        .sort_values("date")
    )
    return df


@st.cache_data(ttl=600)
def fetch_snapshots_by_account() -> pd.DataFrame:
    """
    Snapshots bruts avec nom du compte (pour vue par compte).
    """
    res = supabase.table("snapshots").select(
        "date, total_value, invested_capital, cash, account_id, accounts(name, type)"
    ).execute()

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["date"])
    df["account_name"] = df["accounts"].apply(lambda x: x["name"] if x else None)
    df["account_type"] = df["accounts"].apply(lambda x: x["type"] if x else None)
    df = df.drop(columns=["accounts"])
    return df


@st.cache_data(ttl=600)
def fetch_settings() -> dict:
    """
    Récupère le singleton settings (id = 1).
    Retourne un dict vide si pas encore configuré.
    """
    res = supabase.table("settings").select("*").eq("id", 1).execute()
    if res.data:
        return res.data[0]
    return {}


@st.cache_data(ttl=600)
def fetch_accounts() -> pd.DataFrame:
    res = supabase.table("accounts").select("*").eq("is_active", True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_assets() -> pd.DataFrame:
    res = supabase.table("assets").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_transactions() -> pd.DataFrame:
    res = supabase.table("transactions").select("*").execute()
    if not res.data:
        return pd.DataFrame()
    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["date"])
    return df


# FIX BENCHMARK : +5j de marge + strip timezone
@st.cache_data(ttl=3600)
def fetch_benchmark_history(ticker: str, start: str, end: str) -> pd.Series:
    """
    Récupère l'historique de prix d'un benchmark via yfinance.
    Rebasé à 1.0 au point de départ pour comparaison de perf.
    Ajoute 5 jours de marge sur end pour couvrir weekends/jours fériés.
    """
    try:
        end_extended = (
            pd.to_datetime(end) + pd.Timedelta(days=5)
        ).strftime("%Y-%m-%d")

        hist = yf.download(
            ticker, start=start, end=end_extended,
            progress=False, auto_adjust=True
        )
        if hist.empty:
            return pd.Series(dtype=float)

        prices = hist["Close"].squeeze()

        # Strip timezone pour compatibilité avec nos dates timezone-naive
        if prices.index.tz is not None:
            prices.index = prices.index.tz_localize(None)

        return prices / prices.iloc[0]  # rebasé à 1.0
    except Exception:
        return pd.Series(dtype=float)


# ============================================================
# 3. CALCULS
# ============================================================

def filter_by_period(df: pd.DataFrame, periode: str) -> pd.DataFrame:
    """
    Filtre un DataFrame de snapshots selon une période choisie.
    La colonne 'date' doit être de type datetime.
    """
    today = df["date"].max()
    periode_map = {
        "1 mois": today - pd.DateOffset(months=1),
        "3 mois": today - pd.DateOffset(months=3),
        "6 mois": today - pd.DateOffset(months=6),
        "1 an":   today - pd.DateOffset(years=1),
        "3 ans":  today - pd.DateOffset(years=3),
        "Tout":   df["date"].min(),
    }
    cutoff = periode_map.get(periode, df["date"].min())
    return df[df["date"] >= cutoff]


def compute_kpis(df_snap: pd.DataFrame) -> dict:
    """
    KPIs de base à partir des snapshots agrégés.
    """
    latest = df_snap.iloc[-1]
    total_value      = float(latest["total_value"])
    invested_capital = float(latest["invested_capital"])
    cash             = float(latest["cash"])
    plus_value       = total_value - invested_capital
    perf_pct         = (plus_value / invested_capital * 100) if invested_capital > 0 else 0.0

    first = df_snap.iloc[0]
    perf_since_start = (
        (float(latest["total_value"]) / float(first["total_value"]) - 1) * 100
        if float(first["total_value"]) > 0 else 0.0
    )

    return {
        "total_value":      total_value,
        "invested_capital": invested_capital,
        "cash":             cash,
        "plus_value":       plus_value,
        "perf_pct":         perf_pct,
        "perf_since_start": perf_since_start,
    }

def compute_perf_over_period(df_snap: pd.DataFrame, months: int) -> float:
    """
    Calcule la performance (%) sur une période donnée en mois.
    """
    if df_snap.empty or len(df_snap) < 2:
        return 0.0

    latest_date = df_snap["date"].max()
    start_date = latest_date - pd.DateOffset(months=months)

    df_period = df_snap[df_snap["date"] >= start_date]

    if len(df_period) < 2:
        return 0.0

    start_value = float(df_period.iloc[0]["total_value"])
    end_value = float(df_period.iloc[-1]["total_value"])

    if start_value == 0:
        return 0.0

    return (end_value / start_value - 1) * 100


def compute_fire(kpis: dict, settings: dict) -> dict:
    """
    Indicateurs FIRE à partir des KPIs et des settings.
    Règle des 4% (Safe Withdrawal Rate).
    """
    total_value    = kpis["total_value"]
    fire_target    = settings.get("fire_target_amount") or 0
    monthly_income = settings.get("monthly_income") or 0

    passive_income_annual  = total_value * 0.04
    passive_income_monthly = passive_income_annual / 12
    fire_pct               = (total_value / fire_target * 100) if fire_target > 0 else 0.0
    daily_expense          = (monthly_income / 30) if monthly_income > 0 else None
    freedom_days           = (total_value / daily_expense) if daily_expense else None

    return {
        "passive_income_annual":  passive_income_annual,
        "passive_income_monthly": passive_income_monthly,
        "fire_pct":               fire_pct,
        "fire_target":            fire_target,
        "freedom_days":           freedom_days,
    }


def compute_perf_chart(df_snap: pd.DataFrame) -> go.Figure:
    """
    Graphique Valeur totale vs Capital investi.
    Zone colorée entre les deux courbes = plus-value latente.
    """
    dates       = df_snap["date"]
    total_value = df_snap["total_value"]
    invested    = df_snap["invested_capital"]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates, y=invested,
        name="Capital investi",
        line=dict(color="#888888", width=2, dash="dot"),
        fill=None,
    ))

    fig.add_trace(go.Scatter(
        x=dates, y=total_value,
        name="Valeur totale",
        line=dict(color="#4C9BE8", width=2.5),
        fill="tonexty",
        fillcolor="rgba(76, 155, 232, 0.15)",
    ))

    fig.update_layout(
        height=400,
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=" €", tickformat=",.0f", gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def compute_drawdown(df_snap: pd.DataFrame) -> tuple[go.Figure, float]:
    """
    Calcule et trace le drawdown depuis le plus haut historique.
    Retourne (figure, drawdown_max_en_pct).
    """
    values   = df_snap["total_value"].astype(float)
    dates    = df_snap["date"]
    peak     = values.cummax()
    drawdown = (values - peak) / peak * 100
    max_dd   = drawdown.min()

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=drawdown,
        name="Drawdown",
        line=dict(color="#E84C4C", width=2),
        fill="tozeroy",
        fillcolor="rgba(232, 76, 76, 0.15)",
        hovertemplate="%{y:.2f} %<extra></extra>",
    ))

    fig.add_hline(y=0, line_dash="dot", line_color="#888888", line_width=1)

    idx_max_dd = drawdown.idxmin()
    fig.add_annotation(
        x=dates.iloc[idx_max_dd],
        y=max_dd,
        text=f"  Max DD : {max_dd:.1f} %",
        showarrow=True,
        arrowhead=2,
        arrowcolor="#E84C4C",
        font=dict(color="#E84C4C", size=12),
        bgcolor="rgba(255,255,255,0.8)",
    )

    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=20, b=0),
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=" %", tickformat=".1f", gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig, max_dd


# FIX SHARPE/VOLATILITÉ : retourne None si pas assez de données
def compute_volatility(df_snap: pd.DataFrame) -> float | None:
    """
    Volatilité annualisée des rendements journaliers (en %).
    Retourne None si pas assez de données (< 3 snapshots).
    """
    if len(df_snap) < 3:
        return None
    returns = df_snap["total_value"].astype(float).pct_change().dropna()
    if len(returns) < 2 or returns.std() == 0:
        return None
    return float(returns.std() * (252 ** 0.5) * 100)


def compute_sharpe(df_snap: pd.DataFrame, risk_free_rate: float) -> float | None:
    """
    Ratio de Sharpe annualisé.
    Retourne None si pas assez de données (< 3 snapshots).
    """
    if len(df_snap) < 3:
        return None
    returns = df_snap["total_value"].astype(float).pct_change().dropna()
    if len(returns) < 2 or returns.std() == 0:
        return None
    daily_rf          = risk_free_rate / 252
    excess_returns    = returns - daily_rf
    sharpe_annualized = (excess_returns.mean() / returns.std()) * (252 ** 0.5)
    return float(sharpe_annualized)


def compute_livret_a_comparison(
    df_snap: pd.DataFrame,
    livret_a_rate: float,
) -> tuple[go.Figure, float, float, float]:
    """
    Compare la valeur totale du portefeuille à un placement Livret A
    équivalent, partant du même capital initial.
    """
    df          = df_snap.copy().reset_index(drop=True)
    dates       = df["date"]
    values      = df["total_value"].astype(float)
    start_value = values.iloc[0]

    daily_rate = (1 + livret_a_rate) ** (1 / 365) - 1
    n_days     = (dates - dates.iloc[0]).dt.days
    livret_a   = start_value * (1 + daily_rate) ** n_days

    perf_portef = (values.iloc[-1] / start_value - 1) * 100
    perf_livret = (livret_a.iloc[-1] / start_value - 1) * 100
    ecart       = perf_portef - perf_livret

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates, y=values,
        name="Mon portefeuille",
        line=dict(color="#4C9BE8", width=2.5),
        hovertemplate="%{y:,.0f} €<extra>Portefeuille</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=dates, y=livret_a,
        name=f"Livret A ({livret_a_rate * 100:.1f} %)",
        line=dict(color="#F5A623", width=2, dash="dash"),
        hovertemplate="%{y:,.0f} €<extra>Livret A</extra>",
    ))

    ecart_color = "#2ECC71" if ecart >= 0 else "#E84C4C"
    ecart_signe = "+" if ecart >= 0 else ""
    fig.add_annotation(
        x=dates.iloc[-1],
        y=values.iloc[-1],
        text=f"  {ecart_signe}{ecart:.2f} % vs Livret A",
        showarrow=False,
        xanchor="left",
        font=dict(color=ecart_color, size=13),
    )

    fig.update_layout(
        height=380,
        margin=dict(l=0, r=80, t=20, b=0),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=" €", tickformat=",.0f", gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig, perf_portef, perf_livret, ecart


# FIX BENCHMARK : correction du reindex timezone-aware vs naive
def compute_benchmark_comparison(
    df_snap: pd.DataFrame,
    benchmark_ticker: str,
    benchmark_name: str,
) -> tuple[go.Figure, float, float | None, float | None]:
    """
    Compare la performance relative du portefeuille vs un benchmark.
    Les deux courbes sont rebasées à 100% au point de départ.
    """
    df     = df_snap.copy().reset_index(drop=True)
    dates  = df["date"]
    values = df["total_value"].astype(float)

    portef_rebased = (values / values.iloc[0]) * 100
    perf_portef    = float(portef_rebased.iloc[-1] - 100)

    start_str = dates.iloc[0].strftime("%Y-%m-%d")
    end_str   = dates.iloc[-1].strftime("%Y-%m-%d")

    bench_series = fetch_benchmark_history(benchmark_ticker, start_str, end_str)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=portef_rebased,
        name="Mon portefeuille",
        line=dict(color="#4C9BE8", width=2.5),
        hovertemplate="%{y:.1f}%<extra>Portefeuille</extra>",
    ))

    fig.add_hline(y=100, line_dash="dot", line_color="#cccccc", line_width=1)

    perf_bench = None
    ecart      = None

    if not bench_series.empty:
        bench_rebased = bench_series * 100

        # Strip timezone pour aligner avec nos dates timezone-naive
        if bench_rebased.index.tz is not None:
            bench_rebased.index = bench_rebased.index.tz_localize(None)

        port_index    = pd.DatetimeIndex(dates)
        bench_rebased = bench_rebased.reindex(port_index, method="ffill")

        # Vérifier qu'on a des valeurs exploitables après reindex
        if not bench_rebased.isna().all():
            bench_rebased = bench_rebased.ffill().bfill()
            perf_bench    = float(bench_rebased.iloc[-1] - 100)
            ecart         = perf_portef - perf_bench
            ecart_color   = "#2ECC71" if ecart >= 0 else "#E84C4C"
            ecart_signe   = "+" if ecart >= 0 else ""

            fig.add_trace(go.Scatter(
                x=dates,
                y=bench_rebased.values,
                name=benchmark_name,
                line=dict(color="#9B59B6", width=2, dash="dash"),
                hovertemplate="%{y:.1f}%<extra>" + benchmark_name + "</extra>",
            ))

            fig.add_annotation(
                x=dates.iloc[-1],
                y=portef_rebased.iloc[-1],
                text=f"  {ecart_signe}{ecart:.1f} % vs benchmark",
                showarrow=False,
                xanchor="left",
                font=dict(color=ecart_color, size=13),
            )
        else:
            fig.add_annotation(
                x=dates.iloc[len(dates) // 2],
                y=portef_rebased.mean(),
                text="⚠️ Données benchmark indisponibles (reindex échoué)",
                showarrow=False,
                font=dict(color="#888888", size=12),
            )
    else:
        fig.add_annotation(
            x=dates.iloc[len(dates) // 2],
            y=portef_rebased.mean(),
            text="⚠️ Données benchmark indisponibles (yfinance)",
            showarrow=False,
            font=dict(color="#888888", size=12),
        )

    fig.update_layout(
        height=380,
        margin=dict(l=0, r=100, t=20, b=0),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=" %", tickformat=".0f", gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig, perf_portef, perf_bench, ecart


def compute_dca_projection(
    current_value: float,
    current_invested: float,
    monthly_dca: float,
    annual_return: float,
    inflation_rate: float,
    years: int = 20,
) -> go.Figure:
    """
    Projection DCA sur `years` années à partir de la situation actuelle.
    3 courbes :
      - Capital investi (linéaire)
      - Valeur théorique du portefeuille (croissance composée)
      - Valeur ajustée à l'inflation (pouvoir d'achat réel)
    """
    months         = years * 12
    monthly_return = (1 + annual_return) ** (1 / 12) - 1
    monthly_infl   = (1 + inflation_rate) ** (1 / 12) - 1

    # Vecteurs de résultats
    capital_list   = []
    theorique_list = []
    reel_list      = []
    dates_list     = []

    today          = pd.Timestamp.today().normalize()
    portfolio_val  = current_value
    capital        = current_invested

    for m in range(months + 1):
        date = today + pd.DateOffset(months=m)
        dates_list.append(date)
        capital_list.append(capital)

        # Valeur nominale : croissance + apport mensuel
        theorique_list.append(portfolio_val)

        # Valeur réelle : déflation par l'inflation cumulée
        deflateur = (1 + monthly_infl) ** m
        reel_list.append(portfolio_val / deflateur)

        # Mise à jour pour le mois suivant
        portfolio_val = portfolio_val * (1 + monthly_return) + monthly_dca
        capital      += monthly_dca

    fig = go.Figure()

    # Capital investi (linéaire)
    fig.add_trace(go.Scatter(
        x=dates_list,
        y=capital_list,
        name="Capital investi",
        line=dict(color="#888888", width=2, dash="dot"),
        hovertemplate="%{y:,.0f} €<extra>Capital investi</extra>",
    ))

    # Valeur ajustée inflation (en dessous de théorique → fill entre les deux)
    fig.add_trace(go.Scatter(
        x=dates_list,
        y=reel_list,
        name="Valeur réelle (inflation déduite)",
        line=dict(color="#F5A623", width=2),
        fill=None,
        hovertemplate="%{y:,.0f} €<extra>Valeur réelle</extra>",
    ))

    # Valeur théorique nominale
    fig.add_trace(go.Scatter(
        x=dates_list,
        y=theorique_list,
        name="Valeur théorique",
        line=dict(color="#4C9BE8", width=2.5),
        fill="tonexty",
        fillcolor="rgba(76, 155, 232, 0.10)",
        hovertemplate="%{y:,.0f} €<extra>Valeur théorique</extra>",
    ))

    fig.update_layout(
        height=450,
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(
            ticksuffix=" €",
            tickformat=",.0f",
            gridcolor="#f0f0f0",
        ),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig, theorique_list, reel_list, capital_list


def compute_pea_positions(
    df_transactions: pd.DataFrame,
    df_assets: pd.DataFrame,
    account_id: int,
) -> pd.DataFrame:
    """
    Reconstruit les positions actuelles du PEA depuis les transactions.
    Retourne un DataFrame :
      asset_id | name | yahoo_ticker | last_known_price | quantity | value
    """
    df_txn = df_transactions[
        (df_transactions["account_id"] == account_id) &
        (df_transactions["asset_id"].notna())
    ].copy()

    if df_txn.empty:
        return pd.DataFrame()

    # Quantité nette par asset
    positions = {}
    for _, row in df_txn.iterrows():
        aid = int(row["asset_id"])
        qty = float(row["quantity"] or 0)
        if row["type"] == "buy":
            positions[aid] = positions.get(aid, 0) + qty
        elif row["type"] == "sell":
            positions[aid] = positions.get(aid, 0) - qty

    # Filtrer les positions > 0
    positions = {k: v for k, v in positions.items() if v > 1e-9}

    if not positions:
        return pd.DataFrame()

    # Enrichir avec les infos assets
    df_pos = pd.DataFrame([
        {"asset_id": k, "quantity": v}
        for k, v in positions.items()
    ])
    df_pos = df_pos.merge(
        df_assets[["id", "name", "yahoo_ticker", "last_known_price"]],
        left_on="asset_id", right_on="id", how="left"
    ).drop(columns=["id"])

    df_pos["last_known_price"] = df_pos["last_known_price"].astype(float)
    df_pos["value"] = df_pos["quantity"] * df_pos["last_known_price"]

    return df_pos.reset_index(drop=True)


def compute_rebalancing_orders(
    df_positions: pd.DataFrame,
    targets: dict[str, float],   # {asset_id (str): target_pct (0-100)}
    dca_amount: float,
) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """
    Algorithme de rééquilibrage avec répartition intelligente du reliquat.

    Retourne :
      df_summary  → tableau de situation (actuel vs cible)
      orders      → liste de dicts {name, nb_titres, prix, montant_reel, a_saisir}
      warnings    → liste de messages d'alerte
    """
    warnings_list = []
    total_pea     = df_positions["value"].sum()

    # ── Tableau de situation ────────────────────────────────────
    rows = []
    for _, row in df_positions.iterrows():
        aid      = str(row["asset_id"])
        poids    = (row["value"] / total_pea * 100) if total_pea > 0 else 0
        cible    = targets.get(aid, 0)
        ecart    = cible - poids  # positif = sous-pondéré
        rows.append({
            "asset_id":   aid,
            "name":       row["name"],
            "prix":       row["last_known_price"],
            "quantity":   row["quantity"],
            "value":      row["value"],
            "poids_pct":  round(poids, 2),
            "cible_pct":  round(cible, 2),
            "ecart_pct":  round(ecart, 2),
        })

    df_summary = pd.DataFrame(rows)

    # ── ÉTAPE 1 : assets sous-pondérés avec cible définie ──────
    df_under = df_summary[
        (df_summary["ecart_pct"] > 0) &
        (df_summary["cible_pct"] > 0)
    ].copy()

    if df_under.empty:
        warnings_list.append("✅ Portefeuille déjà à l'équilibre, rien à acheter.")
        return df_summary, [], warnings_list

    somme_ecarts = df_under["ecart_pct"].sum()

    # ── ÉTAPE 2 : allocation initiale (floor) ──────────────────
    df_under["montant_ideal"] = dca_amount * (df_under["ecart_pct"] / somme_ecarts)
    df_under["nb_titres"]     = (df_under["montant_ideal"] / df_under["prix"]).apply(
        lambda x: int(x) if x >= 1 else 0
    )

    # Retirer les assets dont 1 titre coûte plus que l'allocation idéale
    ineligibles = df_under[df_under["nb_titres"] == 0]
    for _, row in ineligibles.iterrows():
        warnings_list.append(
            f"⚠️ **{row['name']}** : 1 titre = {row['prix']:.2f} € "
            f"> allocation idéale ({row['montant_ideal']:.0f} €) — exclu de ce DCA."
        )

    df_eligible = df_under[df_under["nb_titres"] > 0].copy()

    if df_eligible.empty:
        warnings_list.append(
            "⚠️ Aucun asset éligible : le DCA est insuffisant pour acheter "
            "au moins 1 titre de chaque asset sous-pondéré."
        )
        return df_summary, [], warnings_list

    # Calcul du reliquat après floor
    df_eligible["montant_floor"] = df_eligible["nb_titres"] * df_eligible["prix"]
    reliquat = dca_amount - df_eligible["montant_floor"].sum()

    # ── ÉTAPE 3 : greedy sur le reliquat ───────────────────────
    nb_titres_dict = df_eligible.set_index("asset_id")["nb_titres"].to_dict()
    prix_dict      = df_eligible.set_index("asset_id")["prix"].to_dict()
    ecart_dict     = df_eligible.set_index("asset_id")["ecart_pct"].to_dict()
    value_dict     = df_positions.set_index(
        df_positions["asset_id"].astype(str)
    )["value"].to_dict()

    MAX_ITER = 1000
    iteration = 0
    while reliquat > 0 and iteration < MAX_ITER:
        iteration += 1
        # Assets éligibles dont le prix ≤ reliquat
        candidats = {
            aid: prix for aid, prix in prix_dict.items()
            if prix <= reliquat
        }
        if not candidats:
            break

        # Choisir l'asset dont l'achat d'1 titre corrige le mieux l'écart
        # Score = écart restant après achat (on choisit le max)
        best_aid   = None
        best_score = -999

        for aid in candidats:
            # Simulation : nouveau poids après achat d'1 titre supplémentaire
            nouvelle_valeur  = value_dict.get(aid, 0) + (nb_titres_dict[aid] + 1) * prix_dict[aid]
            nouveau_total    = total_pea + dca_amount
            nouveau_poids    = nouvelle_valeur / nouveau_total * 100
            ecart_restant    = ecart_dict[aid] - (nouveau_poids - (
                value_dict.get(aid, 0) / total_pea * 100
            ))
            score = ecart_restant
            if score > best_score:
                best_score = score
                best_aid   = aid

        if best_aid is None:
            break

        nb_titres_dict[best_aid] += 1
        reliquat -= prix_dict[best_aid]

    # ── ÉTAPE 4 : reliquat résiduel → répartition équitable ────
    if reliquat > 0.5:
        n = len(df_eligible)
        reliquat_par_asset = reliquat / n
    else:
        reliquat_par_asset = 0

    # ── ÉTAPE 5 : arrondi au multiple de 5€ supérieur ──────────
    orders = []
    for _, row in df_eligible.iterrows():
        aid          = row["asset_id"]
        nb           = nb_titres_dict[aid]
        prix         = prix_dict[aid]
        montant_reel = nb * prix
        # Montant à saisir = montant réel + part reliquat, arrondi 5€ sup
        montant_saisir = math.ceil((montant_reel + reliquat_par_asset) / 5) * 5

        orders.append({
            "asset_id":      aid,
            "name":          row["name"],
            "prix":          prix,
            "nb_titres":     nb,
            "montant_reel":  round(montant_reel, 2),
            "a_saisir":      montant_saisir,
        })

    return df_summary, orders, warnings_list


# ============================================================
# 4. PAGES
# ============================================================

def page_vue_globale():
    st.title("📊 Synthèse du Patrimoine")

    df_snap  = fetch_snapshots_agg()
    settings = fetch_settings()

    if df_snap.empty:
        st.warning("Aucun snapshot disponible. Lance le script de snapshot pour commencer.")
        return

    kpis = compute_kpis(df_snap)
    fire = compute_fire(kpis, settings)

    # ── KPIs principaux ────────────────────────────────────────
    st.subheader("Situation actuelle")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Valeur totale",
        fmt_eur(kpis["total_value"]),
    )
    col2.metric(
        "Capital investi",
        fmt_eur(kpis["invested_capital"]),
    )
    col3.metric(
        "Plus-value latente",
        fmt_eur(kpis["plus_value"]),
        f"{kpis['perf_pct']:+.2f} %",
        delta_color="normal",
    )
    col4.metric(
        "Cash disponible",
        fmt_eur(kpis["cash"]),
    )

    st.divider()

    # ── Performance par période ───────────────────────────────
    st.subheader("📅 Performance récente")
    
    perf_1m  = compute_perf_over_period(df_snap, 1)
    perf_3m  = compute_perf_over_period(df_snap, 3)
    perf_12m = compute_perf_over_period(df_snap, 12)
    
    col1, col2, col3 = st.columns(3)
    
    col1.metric("1 mois", f"{perf_1m:+.2f} %")
    col2.metric("3 mois", f"{perf_3m:+.2f} %")
    col3.metric("1 an", f"{perf_12m:+.2f} %")

    # ── FIRE ───────────────────────────────────────────────────
    st.subheader("🎯 Objectif FIRE")

    if fire["fire_target"] > 0:
        st.progress(
            min(fire["fire_pct"] / 100, 1.0),
            text=(
                f"{fire['fire_pct']:.1f} % de l'objectif atteint "
                f"({fmt_eur(kpis['total_value'])} / {fmt_eur(fire['fire_target'])})"
            ),
        )
    else:
        st.info("Objectif FIRE non défini — renseigne-le dans Saisie manuelle.")

    col_f1, col_f2, col_f3 = st.columns(3)

    col_f1.metric(
        "Revenu passif mensuel (4%)",
        f"{fmt_eur(fire['passive_income_monthly'])}/mois",
    )
    col_f2.metric(
        "Revenu passif annuel (4%)",
        f"{fmt_eur(fire['passive_income_annual'])}/an",
    )
    if fire["freedom_days"] is not None:
        col_f3.metric(
            "Jours de liberté financière",
            f"{fire['freedom_days']:,.0f} jours".replace(",", " "),
        )
    else:
        col_f3.info("Définis ton revenu mensuel pour ce calcul.")

    # ── Graphique valeur vs capital ────────────────────────────
    st.subheader("📈 Évolution du patrimoine")

    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période",
            options=PERIODE_OPTIONS,
            index=PERIODE_OPTIONS.index(PERIODE_DEFAULT),
            label_visibility="collapsed",
        )

    df_filtered = filter_by_period(df_snap, periode)

    fig = compute_perf_chart(df_filtered)
    st.plotly_chart(fig, use_container_width=True)

    # ── Drawdown ───────────────────────────────────────────────
    st.subheader("📉 Drawdown")

    fig_dd, max_dd = compute_drawdown(df_filtered)

    if max_dd > -10:
        dd_label = "🟢 Faible"
    elif max_dd > -20:
        dd_label = "🟡 Modéré"
    else:
        dd_label = "🔴 Sévère"

    col_dd1, col_dd2, _ = st.columns([1, 1, 5])
    col_dd1.metric("Pire drawdown", f"{max_dd:.1f} %")
    col_dd2.metric("Niveau de risque", dd_label)

    st.plotly_chart(fig_dd, use_container_width=True)

    st.divider()
    st.caption(
        f"Dernière donnée : {df_snap.iloc[-1]['date'].strftime('%d/%m/%Y')} "
        f"· {len(df_snap)} snapshots disponibles"
    )


def page_analyses():
    st.title("📊 Analyses & Graphiques")

    df_snap  = fetch_snapshots_agg()
    settings = fetch_settings()

    if df_snap.empty:
        st.warning("Aucun snapshot disponible.")
        return

    risk_free_rate = float(settings.get("livret_a_rate") or 0.03)

    # ── Filtre de période (partagé sur toute la page) ──────────
    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période d'analyse",
            options=PERIODE_OPTIONS,
            index=PERIODE_OPTIONS.index(PERIODE_DEFAULT),
        )

    df_filtered = filter_by_period(df_snap, periode)

    st.divider()

    # ── 4a : Sharpe & Volatilité ───────────────────────────────
    st.subheader("⚡ Risque & Performance")

    # FIX : seuil minimum pour des métriques fiables
    MIN_POINTS = 20

    if len(df_filtered) < MIN_POINTS:
        st.warning(
            f"⏳ Données insuffisantes pour Sharpe et Volatilité "
            f"({len(df_filtered)} snapshot(s) disponible(s), minimum recommandé : {MIN_POINTS}). "
            "Ces métriques s'afficheront automatiquement au fil des jours."
        )
        col3, col4 = st.columns(2)
        col3.metric("Taux sans risque (Livret A)", f"{risk_free_rate * 100:.1f} %")
        col4.metric("Nb jours analysés", f"{len(df_filtered)}")
    else:
        volatility = compute_volatility(df_filtered)
        sharpe     = compute_sharpe(df_filtered, risk_free_rate)

        sharpe_label = (
            "🟢 Excellent"  if sharpe >= 2  else
            "🟢 Bon"        if sharpe >= 1  else
            "🟡 Acceptable" if sharpe >= 0  else
            "🔴 Négatif"
        )
        vol_label = (
            "🟢 Faible"  if volatility < 10 else
            "🟡 Modérée" if volatility < 20 else
            "🔴 Élevée"
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Ratio de Sharpe", f"{sharpe:.2f}", sharpe_label, delta_color="off")
        col2.metric("Volatilité annualisée", f"{volatility:.1f} %", vol_label, delta_color="off")
        col3.metric("Taux sans risque (Livret A)", f"{risk_free_rate * 100:.1f} %")
        col4.metric("Nb jours analysés", f"{len(df_filtered)}")

    with st.expander("💡 Comment lire ces indicateurs ?"):
        st.markdown("""
        **Ratio de Sharpe** — mesure le rendement obtenu *par unité de risque pris*
        - `> 2` : excellent, rendement très bien rémunéré
        - `1 → 2` : bon, performance solide pour le risque
        - `0 → 1` : acceptable, mais le risque est peu rémunéré
        - `< 0` : le portefeuille fait moins bien que le taux sans risque

        **Volatilité annualisée** — amplitude moyenne des fluctuations
        - `< 10 %` : faible (profil obligataire)
        - `10–20 %` : modérée (profil actions diversifié)
        - `> 20 %` : élevée (profil agressif ou concentré)

        *Le taux sans risque utilisé est le Livret A, paramétrable dans Saisie manuelle.*
        """)

    # ── 4b : Performance vs Livret A ──────────────────────────
    st.subheader("🏦 Portefeuille vs Livret A")

    fig_la, perf_portef, perf_livret, ecart = compute_livret_a_comparison(
        df_filtered, risk_free_rate
    )

    # FIX : format adaptatif selon la magnitude (évite +0.00% sur courtes périodes)
    def format_perf(pct: float) -> str:
        if abs(pct) < 0.01:
            return f"{pct:+.4f} %"
        return f"{pct:+.2f} %"

    col1, col2, col3 = st.columns(3)
    col1.metric("Performance portefeuille", format_perf(perf_portef))
    col2.metric(
        f"Performance Livret A ({risk_free_rate*100:.1f} %)",
        format_perf(perf_livret),
        delta_color="off",
    )
    col3.metric(
        "Écart (alpha vs Livret A)",
        format_perf(ecart),
        "✅ Tu bats le Livret A" if ecart >= 0 else "⚠️ Sous le Livret A",
        delta_color="off",
    )

    st.plotly_chart(fig_la, use_container_width=True)

    # ── 4c : Performance vs Benchmark ─────────────────────────
    st.subheader("🏁 Portefeuille vs Benchmark")

    df_assets     = fetch_assets()
    df_benchmarks = df_assets[
        df_assets["is_benchmark"] == True
    ][["name", "yahoo_ticker"]].dropna(subset=["yahoo_ticker"])

    if df_benchmarks.empty:
        st.info(
            "Aucun benchmark configuré. "
            "Dans ta table `assets`, passe `is_benchmark = TRUE` "
            "sur un ETF (ex: IWDA.AS pour MSCI World)."
        )
    else:
        if len(df_benchmarks) == 1:
            selected = df_benchmarks.iloc[0]
        else:
            bench_choice = st.selectbox(
                "Benchmark",
                options=df_benchmarks["name"].tolist(),
            )
            selected = df_benchmarks[
                df_benchmarks["name"] == bench_choice
            ].iloc[0]

        with st.spinner(f"Chargement de {selected['name']}..."):
            fig_bench, perf_portef, perf_bench, ecart = compute_benchmark_comparison(
                df_filtered,
                selected["yahoo_ticker"],
                selected["name"],
            )

        col1, col2, col3 = st.columns(3)
        col1.metric("Performance portefeuille", f"{perf_portef:+.2f} %")

        if perf_bench is not None:
            col2.metric(
                f"Performance {selected['name']}",
                f"{perf_bench:+.2f} %",
                delta_color="off",
            )
            col3.metric(
                "Alpha généré",
                f"{ecart:+.2f} %",
                "✅ Tu bats le benchmark" if ecart >= 0 else "⚠️ Sous le benchmark",
                delta_color="off",
            )
        else:
            col2.warning("Données benchmark indisponibles")

        st.plotly_chart(fig_bench, use_container_width=True)

    # ── 5 : Projection DCA ────────────────────────────────────
    st.subheader("🔭 Projection DCA")

    monthly_dca    = float(settings.get("monthly_dca") or 0)
    annual_return  = float(settings.get("estimated_annual_return") or 0.07)
    inflation_rate = float(settings.get("inflation_rate") or 0.02)
    fire_target    = float(settings.get("fire_target_amount") or 0)

    # Vérification que les paramètres sont renseignés
    if monthly_dca == 0:
        st.info(
            "💡 Renseigne ton DCA mensuel dans **Saisie manuelle** "
            "pour activer la projection."
        )
    else:
        # Sélecteur d'horizon temporel
        col_horizon, col_info = st.columns([2, 5])
        with col_horizon:
            years = st.slider(
                "Horizon (années)",
                min_value=1,
                max_value=40,
                value=20,
                step=1,
            )

        # Paramètres utilisés (transparence)
        with col_info:
            st.caption(
                f"DCA mensuel : **{fmt_eur(monthly_dca)}** · "
                f"Rendement estimé : **{annual_return*100:.1f} %/an** · "
                f"Inflation : **{inflation_rate*100:.1f} %/an**"
            )

        # Calcul à partir de la situation actuelle (pas filtrée)
        kpis_full = compute_kpis(df_snap)
        fig_dca, theorique, reel, capital = compute_dca_projection(
            current_value    = kpis_full["total_value"],
            current_invested = kpis_full["invested_capital"],
            monthly_dca      = monthly_dca,
            annual_return    = annual_return,
            inflation_rate   = inflation_rate,
            years            = years,
        )

        # Métriques à l'horizon choisi
        val_finale_nom  = theorique[-1]
        val_finale_reel = reel[-1]
        capital_final   = capital[-1]
        gain_total      = val_finale_nom - capital_final

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            f"Valeur dans {years} ans",
            fmt_eur(val_finale_nom),
        )
        col2.metric(
            "Valeur réelle (pouvoir d'achat)",
            fmt_eur(val_finale_reel),
        )
        col3.metric(
            "Capital total investi",
            fmt_eur(capital_final),
        )
        col4.metric(
            "Gain généré par les intérêts",
            fmt_eur(gain_total),
            f"{(gain_total / capital_final * 100):+.0f} % du capital",
            delta_color="off",
        )

        # Ligne FIRE sur le graphique si target définie
        if fire_target > 0:
            fig_dca.add_hline(
                y=fire_target,
                line_dash="dash",
                line_color="#2ECC71",
                line_width=1.5,
                annotation_text=f"  🎯 Objectif FIRE : {fmt_eur(fire_target)}",
                annotation_position="top left",
                annotation_font_color="#2ECC71",
            )

        st.plotly_chart(fig_dca, use_container_width=True)

        # Revenu passif à l'horizon
        revenu_passif_nom  = val_finale_nom * 0.04 / 12
        revenu_passif_reel = val_finale_reel * 0.04 / 12

        st.caption(
            f"📌 À cet horizon, la règle des 4% générerait "
            f"**{fmt_eur(revenu_passif_nom)}/mois** nominaux "
            f"(soit **{fmt_eur(revenu_passif_reel)}/mois** en euros d'aujourd'hui)"
        )

    # FIX : un seul pied de page (suppression du doublon)
    st.divider()
    st.caption(
        f"Analyse sur {len(df_filtered)} jours · "
        f"du {df_filtered.iloc[0]['date'].strftime('%d/%m/%Y')} "
        f"au {df_filtered.iloc[-1]['date'].strftime('%d/%m/%Y')}"
    )


def page_reequilibrage():
    st.title("⚖️ Rééquilibrage PEA")

    # ── Chargement des données ──────────────────────────────────
    settings      = fetch_settings()
    df_accounts   = fetch_accounts()
    df_assets     = fetch_assets()
    df_txn        = fetch_transactions()

    dca_amount    = float(settings.get("monthly_dca") or 0)

    # Compte PEA
    pea_accounts  = df_accounts[df_accounts["type"] == "PEA"]

    if pea_accounts.empty:
        st.warning("Aucun compte de type PEA trouvé dans la base.")
        return

    pea_account   = pea_accounts.iloc[0]
    pea_id        = int(pea_account["id"])

    # Positions actuelles
    df_positions  = compute_pea_positions(df_txn, df_assets, pea_id)

    if df_positions.empty:
        st.warning("Aucune position trouvée sur le PEA. Vérifie tes transactions.")
        return

    total_pea     = df_positions["value"].sum()

    # ── Infos compte ───────────────────────────────────────────
    col2, col3 = st.columns(2)
    col2.metric("Valeur totale PEA", fmt_eur(total_pea))
    col3.metric(
        "DCA mensuel (settings)",
        fmt_eur(dca_amount) if dca_amount > 0 else "⚠️ Non défini",
    )

    if dca_amount == 0:
        st.info("Définis ton DCA mensuel dans **Saisie manuelle** pour utiliser cette page.")
        return

    st.divider()

    # ── Saisie des allocations cibles ──────────────────────────
    st.subheader("🎯 Allocations cibles")
    st.caption("Renseigne le pourcentage cible pour chaque ligne. Le total doit faire 100 %.")

    targets     = {}
    total_cible = 0.0

    # Formulaire par asset
    for _, row in df_positions.iterrows():
        aid          = str(int(row["asset_id"]))
        poids_actuel = row["value"] / total_pea * 100

        col_name, col_actuel, col_cible = st.columns([3, 1, 1])
        col_name.markdown(f"**{row['name']}**")
        col_actuel.metric("Actuel", f"{poids_actuel:.1f} %")

        cible = col_cible.number_input(
            "Cible %",
            min_value=0.0,
            max_value=100.0,
            value=float(round(poids_actuel)),
            step=1.0,
            key=f"target_{aid}",
            label_visibility="collapsed",
        )
        targets[aid] = cible
        total_cible += cible

    # Indicateur du total
    if abs(total_cible - 100) < 0.1:
        st.success(f"✅ Total : {total_cible:.1f} % — prêt à calculer")
    else:
        st.error(f"❌ Total : {total_cible:.1f} % — doit être égal à 100 %")

    st.divider()

    # ── Calcul ─────────────────────────────────────────────────
    if abs(total_cible - 100) < 0.1:

        df_summary, orders, warnings_list = compute_rebalancing_orders(
            df_positions, targets, dca_amount
        )

        # ── Tableau de situation ────────────────────────────────
        st.subheader("📊 Situation actuelle vs cible")

        def color_ecart(val):
            if val > 0.5:
                return "color: #2ECC71"   # sous-pondéré → vert (à acheter)
            elif val < -0.5:
                return "color: #E84C4C"   # sur-pondéré → rouge
            return "color: #888888"

        df_display = df_summary[[
            "name", "value", "poids_pct", "cible_pct", "ecart_pct"
        ]].copy()
        df_display.columns = ["Asset", "Valeur (€)", "Actuel %", "Cible %", "Écart %"]
        df_display["Valeur (€)"] = df_display["Valeur (€)"].map(fmt_eur)

        st.dataframe(
            df_display.style.map(color_ecart, subset=["Écart %"]),
            use_container_width=True,
            hide_index=True,
        )

        # ── Warnings ───────────────────────────────────────────
        for w in warnings_list:
            if w.startswith("✅"):
                st.success(w)
            elif w.startswith("⚠️"):
                st.warning(w)
            elif w.startswith("ℹ️"):
                st.info(w)

        # ── Récap des ordres ───────────────────────────────────
        if orders:
            st.subheader("🛒 Ordres à passer sur Trade Republic")

            # Récap visuel principal
            st.markdown("### 👉 Ce mois-ci, saisis :")

            cols = st.columns(len(orders))
            for i, order in enumerate(orders):
                cols[i].metric(
                    order["name"],
                    f"{order['a_saisir']} €",
                    f"{order['nb_titres']} titre(s) × {order['prix']:.2f} €",
                    delta_color="off",
                )

            # Tableau détaillé
            with st.expander("📋 Détail des ordres"):
                df_orders = pd.DataFrame(orders)[[
                    "name", "nb_titres", "prix", "montant_reel", "a_saisir"
                ]]
                df_orders.columns = [
                    "Asset", "Titres", "Prix unitaire", "Montant réel", "À saisir (TR)"
                ]
                df_orders["Prix unitaire"] = df_orders["Prix unitaire"].map(
                    lambda x: f"{x:.2f} €"
                )
                df_orders["Montant réel"] = df_orders["Montant réel"].map(
                    lambda x: f"{x:,.2f} €".replace(",", " ")
                )
                df_orders["À saisir (TR)"] = df_orders["À saisir (TR)"].map(
                    lambda x: f"{x} €"
                )
                st.dataframe(df_orders, use_container_width=True, hide_index=True)

            # Récap financier
            total_reel   = sum(o["montant_reel"] for o in orders)
            total_saisir = sum(o["a_saisir"] for o in orders)

            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("DCA disponible", fmt_eur(dca_amount))
            col2.metric(
                "Total réellement investi",
                f"{total_reel:,.2f} €".replace(",", " "),
            )
            col3.metric(
                "Total à saisir sur TR",
                f"{total_saisir} €",
                f"Marge : +{total_saisir - total_reel:.2f} €",
                delta_color="off",
            )


def compute_total_amount(
    type_: str,
    quantity: float,
    unit_price: float,
    fees: float,
    manual_amount: float,
) -> float:
    """
    Calcule total_amount selon le type de transaction.
    Conventions alignées avec snapshot.py :
      total_amount > 0 → entrée d'argent dans l'enveloppe
      total_amount < 0 → sortie d'argent
    """
    if type_ == "buy":
        return -((quantity * unit_price) + fees)
    elif type_ == "sell":
        return (quantity * unit_price) - fees
    elif type_ == "deposit":
        return abs(manual_amount)
    elif type_ == "withdrawal":
        return -abs(manual_amount)
    elif type_ == "dividend":
        return abs(manual_amount)
    elif type_ == "fee":
        return -abs(manual_amount)
    return 0.0


def page_saisie():
    st.title("✍️ Saisie manuelle")

    settings    = fetch_settings()
    df_accounts = fetch_accounts()
    df_assets   = fetch_assets()

    tab_settings, tab_prix, tab_transaction = st.tabs([
        "⚙️ Paramètres",
        "💲 Prix manuels",
        "➕ Nouvelle transaction",
    ])

    # ══════════════════════════════════════════════════════════
    # ONGLET 1 — PARAMÈTRES
    # ══════════════════════════════════════════════════════════
    with tab_settings:
        st.subheader("⚙️ Paramètres globaux")
        st.caption("Ces valeurs sont utilisées dans les calculs FIRE, Sharpe et projection DCA.")

        with st.form("form_settings"):
            col1, col2 = st.columns(2)

            with col1:
                livret_a = st.number_input(
                    "Taux Livret A (%)",
                    min_value=0.0, max_value=20.0,
                    value=float((settings.get("livret_a_rate") or 0.03) * 100),
                    step=0.25,
                    help="Taux annuel en %, ex : 3.0 pour 3%",
                )
                dca = st.number_input(
                    "DCA mensuel (€)",
                    min_value=0.0,
                    value=float(settings.get("monthly_dca") or 0),
                    step=50.0,
                )
                revenu = st.number_input(
                    "Revenu mensuel (€)",
                    min_value=0.0,
                    value=float(settings.get("monthly_income") or 0),
                    step=100.0,
                    help="Utilisé pour calculer les jours de liberté financière",
                )

            with col2:
                rendement = st.number_input(
                    "Rendement annuel estimé (%)",
                    min_value=0.0, max_value=50.0,
                    value=float((settings.get("estimated_annual_return") or 0.07) * 100),
                    step=0.5,
                    help="Hypothèse pour la projection DCA",
                )
                inflation = st.number_input(
                    "Taux d'inflation (%)",
                    min_value=0.0, max_value=20.0,
                    value=float((settings.get("inflation_rate") or 0.02) * 100),
                    step=0.25,
                )
                fire_target = st.number_input(
                    "Objectif FIRE (€)",
                    min_value=0.0,
                    value=float(settings.get("fire_target_amount") or 0),
                    step=10000.0,
                    help="Patrimoine cible pour atteindre l'indépendance financière",
                )

            submitted_settings = st.form_submit_button(
                "💾 Enregistrer les paramètres",
                use_container_width=True,
            )

        if submitted_settings:
            try:
                supabase.table("settings").upsert({
                    "id":                      1,
                    "livret_a_rate":           round(livret_a / 100, 4),
                    "monthly_dca":             dca,
                    "monthly_income":          revenu,
                    "estimated_annual_return": round(rendement / 100, 4),
                    "inflation_rate":          round(inflation / 100, 4),
                    "fire_target_amount":      fire_target,
                    "updated_at":              pd.Timestamp.now(tz="UTC").isoformat(),
                }).execute()
                fetch_settings.clear()
                st.success("✅ Paramètres enregistrés avec succès !")
            except Exception as e:
                st.error(f"❌ Erreur lors de la sauvegarde : {e}")

    # ══════════════════════════════════════════════════════════
    # ONGLET 2 — PRIX MANUELS
    # ══════════════════════════════════════════════════════════
    with tab_prix:
        st.subheader("💲 Mise à jour des prix manuels")
        st.caption("Assets avec `auto_price = FALSE` — à mettre à jour manuellement.")

        df_manual = df_assets[df_assets["auto_price"] == False].copy()

        if df_manual.empty:
            st.info("Aucun asset en prix manuel dans la base.")
        else:
            for _, row in df_manual.iterrows():
                aid           = int(row["id"])
                current_price = float(row["last_known_price"] or 0)
                last_updated  = row.get("last_price_updated_at", None)

                col_name, col_price, col_date, col_btn = st.columns([3, 2, 2, 1])

                # Lien vers la page de cours selon le type d'asset et l'ISIN
                isin      = row.get("isin") or ""
                asset_cls = row.get("asset_class") or ""
                if isin and asset_cls in ("etf", "fonds"):
                    url = PRICE_LINKS.get(
                        isin,
                        f"https://www.justetf.com/fr/etf-profile.html?isin={isin}#apercu",
                    )
                    col_name.markdown(f"**{row['name']}** — [📊 Voir le cours]({url})")
                elif isin and isin in PRICE_LINKS:
                    col_name.markdown(f"**{row['name']}** — [📊 Voir le cours]({PRICE_LINKS[isin]})")
                else:
                    col_name.markdown(f"**{row['name']}**")

                if last_updated:
                    try:
                        dt = pd.to_datetime(last_updated).strftime("%d/%m/%Y")
                    except Exception:
                        dt = "—"
                    col_date.caption(f"Mis à jour le {dt}")

                new_price = col_price.number_input(
                    "Prix (€)",
                    min_value=0.0,
                    value=current_price,
                    step=0.01,
                    key=f"price_{aid}",
                    label_visibility="collapsed",
                )

                if col_btn.button("💾", key=f"save_price_{aid}", help="Enregistrer"):
                    try:
                        supabase.table("assets").update({
                            "last_known_price":      new_price,
                            "last_price_updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        }).eq("id", aid).execute()
                        fetch_assets.clear()
                        st.success(f"✅ Prix de **{row['name']}** mis à jour : {new_price:.2f} €")
                    except Exception as e:
                        st.error(f"❌ Erreur : {e}")

    # ══════════════════════════════════════════════════════════
    # ONGLET 3 — NOUVELLE TRANSACTION
    # FIX : pas de st.form ici — les widgets libres permettent
    # la mise à jour en temps réel du total_amount affiché.
    # ══════════════════════════════════════════════════════════
    with tab_transaction:
        st.subheader("➕ Nouvelle transaction")

        if df_accounts.empty:
            st.warning("Aucun compte actif trouvé.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                date_txn = st.date_input(
                    "Date",
                    value=pd.Timestamp.today().date(),
                    key="txn_date",
                )
                type_txn = st.selectbox(
                    "Type",
                    options=["buy", "sell", "deposit", "withdrawal", "dividend", "fee"],
                    format_func=lambda x: {
                        "buy":        "🟢 Achat",
                        "sell":       "🔴 Vente",
                        "deposit":    "💰 Dépôt",
                        "withdrawal": "🏧 Retrait",
                        "dividend":   "🎁 Dividende",
                        "fee":        "💸 Frais",
                    }[x],
                    key="txn_type",
                )
                account = st.selectbox(
                    "Compte",
                    options=df_accounts["id"].tolist(),
                    format_func=lambda x: df_accounts.set_index("id").loc[x, "name"],
                    key="txn_account",
                )

            with col2:
                asset_options = [None] + df_assets["id"].tolist()
                asset_labels  = {None: "— (sans asset)"}
                asset_labels.update({
                    row["id"]: row["name"]
                    for _, row in df_assets.iterrows()
                })
                asset = st.selectbox(
                    "Asset (optionnel)",
                    options=asset_options,
                    format_func=lambda x: asset_labels[x],
                    key="txn_asset",
                )
                comment = st.text_input(
                    "Commentaire (optionnel)",
                    key="txn_comment",
                )

            st.divider()

            # FIX prix unitaire : détecter le changement d'asset et
            # mettre à jour le session_state AVANT le rendu du widget.
            # Sans ça, Streamlit ignore le paramètre value après le 1er rendu.
            default_price = 0.0
            if asset is not None:
                asset_row = df_assets[df_assets["id"] == asset]
                if not asset_row.empty:
                    default_price = float(asset_row.iloc[0].get("last_known_price") or 0.0)

            prev_asset_key = "txn_prev_asset"
            if st.session_state.get(prev_asset_key) != asset:
                st.session_state["txn_price"] = default_price
                st.session_state[prev_asset_key] = asset

            # Champs selon le type — mis à jour en temps réel
            is_trade = type_txn in ("buy", "sell")
            col3, col4, col5 = st.columns(3)

            if is_trade:
                quantity = col3.number_input(
                    "Quantité",
                    min_value=0.0, value=1.0, step=1.0,
                    key="txn_qty",
                )
                unit_price = col4.number_input(
                    "Prix unitaire (€)",
                    min_value=0.0, value=default_price, step=0.01,
                    key="txn_price",
                )
                fees = col5.number_input(
                    "Frais (€)",
                    min_value=0.0, value=0.0, step=0.01,
                    key="txn_fees",
                )
                manual_amount = 0.0
            else:
                quantity      = 0.0
                unit_price    = 0.0
                fees          = 0.0
                manual_amount = col3.number_input(
                    "Montant (€)",
                    min_value=0.0, value=0.0, step=10.0,
                    help="Montant brut, le signe est calculé automatiquement",
                    key="txn_amount",
                )

            # Aperçu temps réel — fonctionne car hors st.form
            total = compute_total_amount(type_txn, quantity, unit_price, fees, manual_amount)
            signe = "+" if total >= 0 else ""

            st.info(
                f"**total_amount calculé : {signe}{total:.2f} €** "
                f"({'entrée' if total >= 0 else 'sortie'} d'argent dans l'enveloppe)"
            )

            # Validation et soumission
            errors = []
            if is_trade and unit_price == 0:
                errors.append("Le prix unitaire ne peut pas être 0 pour un achat/vente.")
            if is_trade and quantity == 0:
                errors.append("La quantité ne peut pas être 0 pour un achat/vente.")
            if not is_trade and manual_amount == 0:
                errors.append("Le montant ne peut pas être 0.")

            if errors:
                for err in errors:
                    st.warning(f"⚠️ {err}")

            btn_disabled = len(errors) > 0
            if st.button(
                "➕ Enregistrer la transaction",
                use_container_width=True,
                disabled=btn_disabled,
                key="txn_submit",
            ):
                try:
                    row_data = {
                        "date":         date_txn.isoformat(),
                        "type":         type_txn,
                        "account_id":   int(account),
                        "asset_id":     int(asset) if asset is not None else None,
                        "quantity":     quantity if is_trade else None,
                        "unit_price":   unit_price if is_trade else None,
                        "fees":         fees,
                        "total_amount": round(total, 4),
                        "comment":      comment or None,
                    }
                    supabase.table("transactions").insert(row_data).execute()
                    fetch_transactions.clear()
                    st.success(
                        f"✅ Transaction enregistrée — "
                        f"{type_txn.upper()} · {signe}{total:.2f} €"
                    )
                except Exception as e:
                    st.error(f"❌ Erreur lors de l'insertion : {e}")


# ============================================================
# 5. ROUTING
# ============================================================

st.sidebar.title("BeyondGrid 📈")
st.sidebar.caption("Suivi d'investissement")

# ── Bouton de rafraîchissement manuel ──────────────────────
if st.sidebar.button("🔄 Actualiser les données", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

menu = st.sidebar.radio(
    "Navigation",
    options=[
        "Vue Globale",
        "Analyses & Graphiques",
        "Rééquilibrage PEA",
        "Saisie manuelle",
    ],
    format_func=lambda x: {
        "Vue Globale":           "🏠 Vue Globale",
        "Analyses & Graphiques": "📊 Analyses",
        "Rééquilibrage PEA":    "⚖️ Rééquilibrage PEA",
        "Saisie manuelle":      "✍️ Saisie manuelle",
    }[x],
)

if menu == "Vue Globale":
    page_vue_globale()
elif menu == "Analyses & Graphiques":
    page_analyses()
elif menu == "Rééquilibrage PEA":
    page_reequilibrage()
elif menu == "Saisie manuelle":
    page_saisie()

# ── Version en bas de sidebar ──────────────────────────────
st.sidebar.divider()
with st.sidebar.expander(f"📋 v{APP_VERSION} — Patch notes"):
    for version, notes in PATCH_NOTES.items():
        st.markdown(f"**v{version}**")
        for note in notes:
            st.markdown(f"- {note}")
st.sidebar.caption(f"BeyondGrid v{APP_VERSION}")
