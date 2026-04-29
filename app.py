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
    Trié par date ASC, index = date (datetime).
    """
    res = supabase.table("snapshots").select(
        "date, total_value, invested_capital, cash"
    ).execute()

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["date"])

    # Agrégation : somme de tous les comptes pour chaque date
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


@st.cache_data(ttl=3600)
def fetch_benchmark_history(ticker: str, start: str, end: str) -> pd.Series:
    """
    Récupère l'historique de prix d'un benchmark via yfinance.
    Rebasé à 1.0 au point de départ pour comparaison de perf.
    """
    try:
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if hist.empty:
            return pd.Series(dtype=float)
        prices = hist["Close"].squeeze()
        return prices / prices.iloc[0]  # rebasé à 1.0
    except Exception:
        return pd.Series(dtype=float)


# ============================================================
# 3. CALCULS
# ============================================================

def compute_kpis(df_snap: pd.DataFrame) -> dict:
    """
    KPIs de base à partir des snapshots agrégés.
    Nécessite au moins une ligne dans df_snap.
    """
    latest = df_snap.iloc[-1]
    total_value      = float(latest["total_value"])
    invested_capital = float(latest["invested_capital"])
    cash             = float(latest["cash"])
    plus_value       = total_value - invested_capital
    perf_pct         = (plus_value / invested_capital * 100) if invested_capital > 0 else 0.0

    # Performance depuis le début (première snapshot)
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


def compute_fire(kpis: dict, settings: dict) -> dict:
    """
    Indicateurs FIRE à partir des KPIs et des settings.
    Règle des 4% (Safe Withdrawal Rate).
    """
    total_value  = kpis["total_value"]
    fire_target  = settings.get("fire_target_amount") or 0
    monthly_income = settings.get("monthly_income") or 0

    # Revenu passif théorique annuel (règle des 4%)
    passive_income_annual = total_value * 0.04
    passive_income_monthly = passive_income_annual / 12

    # % d'atteinte de l'objectif FIRE
    fire_pct = (total_value / fire_target * 100) if fire_target > 0 else 0.0

    # Jours de liberté financière
    # = combien de jours on pourrait vivre avec le patrimoine actuel (sans rendement)
    daily_expense = (monthly_income / 30) if monthly_income > 0 else None
    freedom_days  = (total_value / daily_expense) if daily_expense else None

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
    dates        = df_snap["date"]
    total_value  = df_snap["total_value"]
    invested     = df_snap["invested_capital"]

    fig = go.Figure()

    # Zone remplie entre les deux courbes
    # On fait d'abord la courbe du bas (capital investi) en "fill to next y"
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
        fill="tonexty",  # remplissage vers la courbe précédente
        fillcolor="rgba(76, 155, 232, 0.15)",
    ))

    fig.update_layout(
        height=400,
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

    return fig


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
        f"{kpis['total_value']:,.0f} €".replace(",", " "),
    )
    col2.metric(
        "Capital investi",
        f"{kpis['invested_capital']:,.0f} €".replace(",", " "),
    )
    col3.metric(
        "Plus-value latente",
        f"{kpis['plus_value']:,.0f} €".replace(",", " "),
        f"{kpis['perf_pct']:+.2f} %",
        delta_color="normal",
    )
    col4.metric(
        "Cash disponible",
        f"{kpis['cash']:,.0f} €".replace(",", " "),
    )

    st.divider()

    # ── FIRE ───────────────────────────────────────────────────
    st.subheader("🎯 Objectif FIRE")

    if fire["fire_target"] > 0:
        st.progress(
            min(fire["fire_pct"] / 100, 1.0),
            text=f"{fire['fire_pct']:.1f} % de l'objectif atteint "
                 f"({kpis['total_value']:,.0f} € / {fire['fire_target']:,.0f} €)".replace(",", " "),
        )
    else:
        st.info("Objectif FIRE non défini — renseigne-le dans Saisie manuelle.")

    col_f1, col_f2, col_f3 = st.columns(3)

    col_f1.metric(
        "Revenu passif mensuel (4%)",
        f"{fire['passive_income_monthly']:,.0f} €/mois".replace(",", " "),
    )
    col_f2.metric(
        "Revenu passif annuel (4%)",
        f"{fire['passive_income_annual']:,.0f} €/an".replace(",", " "),
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

    # Filtre de période
    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période",
            options=["1 mois", "3 mois", "6 mois", "1 an", "Tout"],
            index=4,
            label_visibility="collapsed",
        )

    # Filtrage du DataFrame selon la période choisie
    today = df_snap["date"].max()
    periode_map = {
        "1 mois":  today - pd.DateOffset(months=1),
        "3 mois":  today - pd.DateOffset(months=3),
        "6 mois":  today - pd.DateOffset(months=6),
        "1 an":    today - pd.DateOffset(years=1),
        "Tout":    df_snap["date"].min(),
    }
    df_filtered = df_snap[df_snap["date"] >= periode_map[periode]]

    fig = compute_perf_chart(df_filtered)
    st.plotly_chart(fig, use_container_width=True)
    st.divider()
    st.caption(
        f"Dernière donnée : {df_snap.iloc[-1]['date'].strftime('%d/%m/%Y')} "
        f"· {len(df_snap)} snapshots disponibles"
    )


def page_analyses():
    st.title("📈 Analyses & Graphiques")
    st.info("À venir — Étape 4")


def page_reequilibrage():
    st.title("⚖️ Rééquilibrage PEA")
    st.info("À venir — Étape 7")


def page_saisie():
    st.title("✍️ Saisie manuelle")
    st.info("À venir — Étape 8")


# ============================================================
# 5. ROUTING
# ============================================================

st.sidebar.title("BeyondGrid 📈")
st.sidebar.caption("Suivi d'investissement")

menu = st.sidebar.radio(
    "Navigation",
    options=[
        "Vue Globale",
        "Analyses & Graphiques",
        "Rééquilibrage PEA",
        "Saisie manuelle",
    ],
    format_func=lambda x: {
        "Vue Globale":          "🏠 Vue Globale",
        "Analyses & Graphiques":"📊 Analyses",
        "Rééquilibrage PEA":   "⚖️ Rééquilibrage PEA",
        "Saisie manuelle":     "✍️ Saisie manuelle",
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
