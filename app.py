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

def compute_drawdown(df_snap: pd.DataFrame) -> tuple[go.Figure, float]:
    """
    Calcule et trace le drawdown depuis le plus haut historique.
    Retourne (figure, drawdown_max_en_pct).
    """
    values = df_snap["total_value"].astype(float)
    dates  = df_snap["date"]

    # Maximum glissant (peak)
    peak     = values.cummax()
    drawdown = (values - peak) / peak * 100  # en %, toujours ≤ 0

    max_dd = drawdown.min()  # le pire drawdown (valeur la plus négative)

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

    # Ligne zéro pour référence visuelle
    fig.add_hline(
        y=0,
        line_dash="dot",
        line_color="#888888",
        line_width=1,
    )

    # Annotation du pire drawdown
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
        yaxis=dict(
            ticksuffix=" %",
            tickformat=".1f",
            gridcolor="#f0f0f0",
        ),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig, max_dd

def compute_volatility(df_snap: pd.DataFrame) -> float:
    """
    Volatilité annualisée des rendements journaliers (en %).
    Retourne 0.0 si pas assez de données.
    """
    if len(df_snap) < 2:
        return 0.0

    returns = df_snap["total_value"].astype(float).pct_change().dropna()

    if returns.empty:
        return 0.0

    return float(returns.std() * (252 ** 0.5) * 100)  # en %


def compute_sharpe(df_snap: pd.DataFrame, risk_free_rate: float) -> float:
    """
    Ratio de Sharpe annualisé.
    risk_free_rate : taux annuel en décimal (ex: 0.03 pour 3%)
    Retourne 0.0 si pas assez de données.
    """
    if len(df_snap) < 2:
        return 0.0

    returns = df_snap["total_value"].astype(float).pct_change().dropna()

    if returns.empty or returns.std() == 0:
        return 0.0

    # Taux journalier sans risque
    daily_rf = risk_free_rate / 252

    excess_returns     = returns - daily_rf
    sharpe_annualized  = (excess_returns.mean() / returns.std()) * (252 ** 0.5)

    return float(sharpe_annualized)

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
    
    # ── Drawdown ───────────────────────────────────────────────
    st.subheader("📉 Drawdown")

    fig_dd, max_dd = compute_drawdown(df_filtered)

    # Couleur de la métrique selon la sévérité
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
            options=["3 mois", "6 mois", "1 an", "3 ans", "Tout"],
            index=2,
        )

    today = df_snap["date"].max()
    periode_map = {
        "3 mois": today - pd.DateOffset(months=3),
        "6 mois": today - pd.DateOffset(months=6),
        "1 an":   today - pd.DateOffset(years=1),
        "3 ans":  today - pd.DateOffset(years=3),
        "Tout":   df_snap["date"].min(),
    }
    df_filtered = df_snap[df_snap["date"] >= periode_map[periode]]

    st.divider()

    # ── 4a : Sharpe & Volatilité ───────────────────────────────
    st.subheader("⚡ Risque & Performance")

    volatility = compute_volatility(df_filtered)
    sharpe     = compute_sharpe(df_filtered, risk_free_rate)

    # Interprétation automatique du Sharpe
    if sharpe >= 2:
        sharpe_label = "🟢 Excellent"
    elif sharpe >= 1:
        sharpe_label = "🟢 Bon"
    elif sharpe >= 0:
        sharpe_label = "🟡 Acceptable"
    else:
        sharpe_label = "🔴 Négatif"

    # Interprétation automatique de la volatilité
    if volatility < 10:
        vol_label = "🟢 Faible"
    elif volatility < 20:
        vol_label = "🟡 Modérée"
    else:
        vol_label = "🔴 Élevée"

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Ratio de Sharpe",
        f"{sharpe:.2f}",
        sharpe_label,
        delta_color="off",
    )
    col2.metric(
        "Volatilité annualisée",
        f"{volatility:.1f} %",
        vol_label,
        delta_color="off",
    )
    col3.metric(
        "Taux sans risque (Livret A)",
        f"{risk_free_rate * 100:.1f} %",
    )
    col4.metric(
        "Nb jours analysés",
        f"{len(df_filtered)}",
    )

    # Aide à la lecture discrète
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

    # (4b Livret A et 4c Benchmark à venir)
    st.divider()
    st.caption(f"Analyse sur {len(df_filtered)} jours · "
               f"du {df_filtered.iloc[0]['date'].strftime('%d/%m/%Y')} "
               f"au {df_filtered.iloc[-1]['date'].strftime('%d/%m/%Y')}")


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
