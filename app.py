import streamlit as st
import pandas as pd
import os
from supabase import create_client
import plotly.express as px

# =========================
# CONFIG
# =========================

st.set_page_config(layout="wide")
st.title("📊 Portfolio Dashboard")

# =========================
# DB
# =========================

@st.cache_resource
def init_db():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

supabase = init_db()

# =========================
# LOAD DATA
# =========================

@st.cache_data(ttl=3600)
def load_all():
    snapshots = supabase.table("snapshots").select("*").execute().data
    assets = supabase.table("assets").select("*").execute().data
    transactions = supabase.table("transactions").select("*").execute().data
    settings = supabase.table("settings").select("*").single().execute().data

    return (
        pd.DataFrame(snapshots),
        pd.DataFrame(assets),
        pd.DataFrame(transactions),
        settings
    )

snapshots, assets, transactions, settings = load_all()

snapshots["date"] = pd.to_datetime(snapshots["date"])

# =========================
# SIDEBAR
# =========================

page = st.sidebar.radio(
    "Navigation",
    ["Overview", "Performance", "Allocation", "Dividendes", "Rééquilibrage"]
)

# =========================
# COMMON PREP
# =========================

df = snapshots.groupby("date").agg({
    "total_value": "sum",
    "invested_capital": "sum"
}).reset_index()

df = df.sort_values("date")
df["returns"] = df["total_value"].pct_change()
df["cummax"] = df["total_value"].cummax()
df["drawdown"] = (df["total_value"] - df["cummax"]) / df["cummax"]

latest = df.iloc[-1]

total = latest["total_value"]
invested = latest["invested_capital"]

# =========================
# OVERVIEW
# =========================

if page == "Overview":

    fire_target = settings.get("fire_target_amount") or 1
    monthly_dca = settings.get("monthly_dca") or 0

    performance = total / invested - 1 if invested else 0
    fire_progress = total / fire_target
    passive_income = total * 0.04 / 12

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Net Worth", f"{total:,.0f}€")
    col2.metric("Performance", f"{performance:.1%}")
    col3.metric("FIRE", f"{fire_progress:.1%}")
    col4.metric("Passive Income", f"{passive_income:,.0f}€/mo")

    st.plotly_chart(px.line(df, x="date", y=["total_value", "invested_capital"]))

# =========================
# PERFORMANCE
# =========================

elif page == "Performance":

    livret = settings.get("livret_a_rate") or 0.03

    returns = df["returns"].dropna()
    vol = returns.std() * (252 ** 0.5)

    sharpe = (returns.mean() * 252 - livret) / vol if vol else 0

    st.metric("Sharpe Ratio", f"{sharpe:.2f}")
    st.metric("Max Drawdown", f"{df['drawdown'].min():.1%}")

    st.plotly_chart(px.line(df, x="date", y="drawdown"))

    # ===== BENCHMARK =====
    benchmark_assets = assets[assets["is_benchmark"] == True]

    if not benchmark_assets.empty:
        st.subheader("Benchmark comparison")

        # ⚠️ simplifié (tu pourras améliorer avec yfinance)
        benchmark_value = df["invested_capital"] * (1 + 0.07)  # fake placeholder

        df["benchmark"] = benchmark_value

        st.plotly_chart(
            px.line(df, x="date", y=["total_value", "benchmark"])
        )

# =========================
# ALLOCATION
# =========================

elif page == "Allocation":

    merged = transactions.merge(assets, left_on="asset_id", right_on="id")

    allocation = merged.groupby("asset_class")["total_amount"].sum().reset_index()

    st.plotly_chart(px.pie(allocation, names="asset_class", values="total_amount"))

# =========================
# DIVIDENDES
# =========================

elif page == "Dividendes":

    divs = transactions[transactions["type"] == "dividend"]

    if not divs.empty:
        divs["date"] = pd.to_datetime(divs["date"])

        monthly = divs.groupby(divs["date"].dt.to_period("M"))["total_amount"].sum()

        st.metric("Total Dividendes", f"{divs['total_amount'].sum():,.0f}€")

        st.plotly_chart(px.bar(monthly))

# =========================
# REBALANCING
# =========================

elif page == "Rééquilibrage":

    st.subheader("Rééquilibrage DCA")

    merged = transactions.merge(assets, left_on="asset_id", right_on="id")

    current = merged.groupby("name")["total_amount"].sum().reset_index()

    total_portfolio = current["total_amount"].sum()
    current["weight"] = current["total_amount"] / total_portfolio

    # ⚠️ exemple simple de target
    targets = {
        "ETF World": 0.7,
        "ETF EM": 0.2,
        "Small Cap": 0.1
    }

    current["target"] = current["name"].map(targets).fillna(0)
    current["delta"] = current["target"] - current["weight"]

    monthly_dca = settings.get("monthly_dca") or 0
    current["suggested_buy"] = current["delta"] * monthly_dca

    st.dataframe(current[["name", "weight", "target", "suggested_buy"]])
