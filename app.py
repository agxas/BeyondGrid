import streamlit as st
import os
from supabase import create_client
import pandas as pd


# =========================
# CONFIG
# =========================

st.set_page_config(page_title="Wealth Dashboard", layout="wide")

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

@st.cache_data(ttl=600)
def fetch_table(table_name):
    res = supabase.table(table_name).select("*").execute()
    return pd.DataFrame(res.data)

# =========================
# SIDEBAR
# =========================

st.sidebar.title("💰 Wealth Dash")
menu = st.sidebar.radio("Navigation", [
    "Vue Globale", 
    "Analyses & Graphiques", 
    "Rééquilibrage PEA", 
    "Saisie manuelle",
])

# =========================
# VUE GLOBALE
# =========================

if menu == "Vue Globale":
    st.title("Synthèse du Patrimoine")

# 1. Récupération des données nécessaires
    with st.spinner("Chargement des données..."):
        df_settings = fetch_table("settings")
        df_snapshots = fetch_table("snapshots")
        df_accounts = fetch_table("accounts")
        
    if not df_snapshots.empty:
        # On va chercher la date la plus récente pour chaque compte
        # Pour avoir une vision "actuelle"
        latest_date = df_snapshots['date'].max()
        df_latest = df_snapshots[df_snapshots['date'] == latest_date]
        
        # Calculs de base
        total_patrimoine = df_latest['total_value'].sum()
        total_investi = df_latest['invested_capital'].sum()
        plus_value_latente = total_patrimoine - total_investi
        perf_globale = (plus_value_latente / total_investi) * 100 if total_investi > 0 else 0
        
        # Affichage des 3 métriques principales en haut
        col1, col2, col3 = st.columns(3)
        col1.metric("Valeur Totale", f"{total_patrimoine:,.0f} €".replace(",", " "))
        col2.metric("Plus-value", f"{plus_value_latente:,.0f} €".replace(",", " "), f"{perf_globale:.2f} %")
        col3.metric("Capital Investi", f"{total_investi:,.0f} €".replace(",", " "))

    else:
        st.info("Aucune donnée de snapshot trouvée.")

# =========================
# ANALYSES & GRAPHIQUES
# =========================

if menu == "Analyses & Graphiques":
    st.title("stats")

# =========================
# REEQUILIBRAGE PEA
# =========================

if menu == "Rééquilibrage PEA":
    st.title("prochains ordres PEA")

# =========================
# SAISIE MANUELLE (prix des actifs non auto et transactions)
# =========================

if menu == "Saisie manuelle":
    st.title("Prix des actifs")
    
