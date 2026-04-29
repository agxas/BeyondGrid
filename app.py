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
            text=(
                f"{fire['fire_pct']:.1f} % de l'objectif atteint "
                f"({kpis['total_value']:,.0f} € / {fire['fire_target']:,.0f} €)"
                .replace(",", " ")
            ),
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

    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période",
            options=["1 mois", "3 mois", "6 mois", "1 an", "Tout"],
            index=4,
            label_visibility="collapsed",
        )

    today = df_snap["date"].max()
    periode_map = {
        "1 mois": today - pd.DateOffset(months=1),
        "3 mois": today - pd.DateOffset(months=3),
        "6 mois": today - pd.DateOffset(months=6),
        "1 an":   today - pd.DateOffset(years=1),
        "Tout":   df_snap["date"].min(),
    }
    df_filtered = df_snap[df_snap["date"] >= periode_map[periode]]

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

    # FIX : un seul pied de page (suppression du doublon)
    st.divider()
    st.caption(
        f"Analyse sur {len(df_filtered)} jours · "
        f"du {df_filtered.iloc[0]['date'].strftime('%d/%m/%Y')} "
        f"au {df_filtered.iloc[-1]['date'].strftime('%d/%m/%Y')}"
    )


def page_reequilibrage():
    st.title("⚖️ Rééquilibrage PEA")
    st.info("À venir — Étape 6")


def page_saisie():
    st.title("✍️ Saisie manuelle")
    st.info("À venir — Étape 7")


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
