import streamlit as st
import pandas as pd
import os
from supabase import create_client
import plotly.express as px

# =========================
# CONFIG
# =========================

st.set_page_config(
    page_title="Portfolio Dashboard",
    layout="wide"
)

# =========================
# AUTH (simple)
# =========================

PASSWORD = os.environ.get("APP_PASSWORD")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pwd = st.text_input("Password", type="password")
    if pwd == PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
    else:
        st.stop()

# =========================
# DB CONNECTION
# =========================

@st.cache_resource
def init_db():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_db()

# =========================
# DATA LOADING
# =========================

@st.cache_data
def load_data():
    snapshots = supabase.table("snapshots").select("*").execute().data
    settings = supabase.table("settings").select("*").single().execute().data

    df = pd.DataFrame(snapshots)
    df["date"] = pd.to_datetime(df["date"])

    return df, settings

df, settings = load_data()

# =========================
# PREP DATA
# =========================

df_grouped = df.groupby("date").agg({
    "total_value": "sum",
    "invested_capital": "sum"
}).reset_index()

df_grouped = df_grouped.sort_values("date")

# returns
df_grouped["returns"] = df_grouped["total_value"].pct_change()

# drawdown
df_grouped["cummax"] = df_grouped["total_value"].cummax()
df_grouped["drawdown"] = (df_grouped["total_value"] - df_grouped["cummax"]) / df_grouped["cummax"]

# =========================
# METRICS
# =========================

latest = df_grouped.iloc[-1]

total_value = latest["total_value"]
invested = latest["invested_capital"]

fire_target = settings.get("fire_target_amount") or 1
monthly_income = settings.get("monthly_income") or 0
livret_rate = settings.get("livret_a_rate") or 0.03

# KPIs
performance = (total_value / invested - 1) if invested > 0 else 0
fire_progress = total_value / fire_target if fire_target > 0 else 0
passive_income = total_value * 0.04 / 12

# Sharpe (approx)
returns = df_grouped["returns"].dropna()
volatility = returns.std() * (252 ** 0.5)

if volatility > 0:
    sharpe = (returns.mean() * 252 - livret_rate) / volatility
else:
    sharpe = 0

# =========================
# UI
# =========================

st.title("📊 Portfolio Dashboard")

# KPIs
col1, col2, col3, col4 = st.columns(4)

col1.metric("Net Worth", f"{total_value:,.0f} €")
col2.metric("Performance", f"{performance:.1%}")
col3.metric("FIRE Progress", f"{fire_progress:.1%}")
col4.metric("Passive Income", f"{passive_income:,.0f} €/mo")

col5, col6 = st.columns(2)
col5.metric("Sharpe Ratio", f"{sharpe:.2f}")
col6.metric("Drawdown", f"{df_grouped['drawdown'].min():.1%}")

st.divider()

# =========================
# GRAPH - VALUE
# =========================

fig = px.line(
    df_grouped,
    x="date",
    y=["total_value", "invested_capital"],
    title="Portfolio Value vs Invested"
)

st.plotly_chart(fig, use_container_width=True)

# =========================
# GRAPH - DRAWDOWN
# =========================

fig_dd = px.line(
    df_grouped,
    x="date",
    y="drawdown",
    title="Drawdown"
)

st.plotly_chart(fig_dd, use_container_width=True)
