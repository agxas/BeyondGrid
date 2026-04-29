# ============================================================
# app.py — BeyondGrid Dashboard
# ============================================================

import os
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from supabase import create_client

st.set_page_config(page_title="BeyondGrid", page_icon="📈", layout="wide")

@st.cache_resource
def init_db():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

supabase = init_db()

# ============================================================
# DATA
# ============================================================

@st.cache_data(ttl=600)
def fetch_snapshots_agg():
    res = supabase.table("snapshots").select(
        "date, total_value, invested_capital, cash"
    ).execute()

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["date"])

    return (
        df.groupby("date")[["total_value", "invested_capital", "cash"]]
        .sum()
        .reset_index()
        .sort_values("date")
    )

@st.cache_data(ttl=600)
def fetch_settings():
    res = supabase.table("settings").select("*").eq("id", 1).execute()
    return res.data[0] if res.data else {}

# ============================================================
# CALCULS
# ============================================================

def compute_kpis(df):
    latest = df.iloc[-1]
    invested = float(latest["invested_capital"])
    total = float(latest["total_value"])

    return {
        "total": total,
        "invested": invested,
        "cash": float(latest["cash"]),
        "gain": total - invested,
        "perf": (total - invested) / invested * 100 if invested > 0 else 0
    }

def compute_perf_chart(df):
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["invested_capital"],
        name="Capital investi",
        line=dict(color="#888", dash="dot"),
    ))

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["total_value"],
        name="Valeur",
        fill="tonexty",
        fillcolor="rgba(76,155,232,0.15)",
        line=dict(color="#4C9BE8"),
    ))

    fig.update_layout(height=400, margin=dict(l=0,r=0,t=20,b=0))
    return fig

def compute_dca_projection(current_value, monthly_dca, annual_return, inflation, months):
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    dates, invested, portfolio, real = [], [], [], []

    value = current_value
    total = current_value
    now = datetime.today()

    r = (1+annual_return)**(1/12)-1
    inf = (1+inflation)**(1/12)-1

    for i in range(months):
        now += relativedelta(months=1)

        total += monthly_dca
        value = (value + monthly_dca)*(1+r)

        real_val = value / ((1+inf)**(i+1))

        dates.append(now)
        invested.append(total)
        portfolio.append(value)
        real.append(real_val)

    return pd.DataFrame({
        "date": dates,
        "invested": invested,
        "portfolio": portfolio,
        "real": real
    })

# ============================================================
# PAGE ANALYSE
# ============================================================

def page_analyses():
    st.title("📊 Analyses")

    df = fetch_snapshots_agg()
    settings = fetch_settings()

    if df.empty:
        st.warning("Pas de données")
        return

    st.plotly_chart(compute_perf_chart(df), use_container_width=True)

    st.divider()

    # =======================
    # DCA PROJECTION
    # =======================

    st.subheader("📈 Projection DCA")

    col1, col2 = st.columns(2)

    with col1:
        years = st.slider("Durée (années)", 1, 30, 10)

    with col2:
        monthly_dca = st.number_input(
            "DCA mensuel",
            value=int(settings.get("monthly_dca") or 500),
            step=50
        )

    if df.empty:
        st.warning("Pas assez de données")
        return

    latest_value = df["total_value"].iloc[-1]

    if monthly_dca == 0:
        st.info("Entre un DCA")
        return

    dca_df = compute_dca_projection(
        latest_value,
        monthly_dca,
        float(settings.get("estimated_annual_return") or 0.07),
        float(settings.get("inflation_rate") or 0.02),
        years*12
    )

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dca_df["date"], y=dca_df["invested"], name="Investi",
        line=dict(color="#888", dash="dot")
    ))

    fig.add_trace(go.Scatter(
        x=dca_df["date"], y=dca_df["portfolio"], name="Portefeuille",
        fill="tonexty", fillcolor="rgba(76,155,232,0.15)",
        line=dict(color="#4C9BE8")
    ))

    fig.add_trace(go.Scatter(
        x=dca_df["date"], y=dca_df["real"], name="Réel",
        line=dict(color="#2ECC71", dash="dash")
    ))

    st.plotly_chart(fig, use_container_width=True)

    final = dca_df.iloc[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("Final", f"{final['portfolio']:,.0f} €".replace(",", " "))
    c2.metric("Investi", f"{final['invested']:,.0f} €".replace(",", " "))
    c3.metric("Gain", f"{final['portfolio']-final['invested']:,.0f} €".replace(",", " "))

# ============================================================
# ROUTING
# ============================================================

menu = st.sidebar.radio(
    "Menu",
    ["Analyses"]
)

if menu == "Analyses":
    page_analyses()
