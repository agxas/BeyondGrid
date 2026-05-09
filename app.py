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
import json
import requests

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
APP_VERSION = "5.0"
PATCH_NOTES = {
    "5.0": [
        "Nouveau : Import CSV Trade Republic — onglet 'Import TR' dans Saisie manuelle, filtre automatique des achats (TRADING/BUY), correspondance ISIN → asset, détection des doublons, aperçu avant import",
    ],
    "4.6": [
        "Amélioration Analyse IA : prompt enrichi avec la liste complète des actifs détenus (nom, classe, géographie) et les opérations du mois — Gemini contextualise les perfs avec sa connaissance des marchés",
        "Correctif : modèle Gemini mis à jour → gemini-2.5-flash (seul modèle disponible gratuitement dans AI Studio)",
        "Correctif : réponse IA coupée en milieu de phrase — maxOutputTokens 1024 → 4096",
        "Correctif : message d'erreur 429 (quota) plus explicite avec délai conseillé",
    ],
    "4.5": [
        "Nouveau : page Synthèse mensuelle — sélecteur de mois, évolution de la valeur (début/fin/variation), transactions du mois avec barre de progression DCA, dividendes reçus",
        "Nouveau : Analyse IA mensuelle via Gemini (gratuit) — bouton 'Générer l'analyse' avec résumé personnalisé en français (performance, DCA, dividendes, trajectoire FIRE)",
        "Nouveau : champ clé API Gemini dans Saisie manuelle → Paramètres — stockée en base, masquée, résultat mis en cache par session",
        "Nouveau : colonne gemini_api_key ajoutée dans la table settings (migration : ALTER TABLE settings ADD COLUMN gemini_api_key TEXT)",
    ],
    "4.4": [
        "Refactoring : page_compte() découpée en 3 sous-fonctions (_pc_render_kpis, _pc_render_evolution, _pc_render_details) avec séparateurs visuels",
        "Optimisation : compute_positions_with_pru() appelé une seule fois dans _pc_render_details (positions et allocation partagent le même résultat)",
        "Refactoring : page_reequilibrage() découpée en 3 sous-fonctions (_rq_render_overview, _rq_render_targets, _rq_render_orders) avec séparateurs visuels",
        "Thème graphiques : helper _chart_layout() appliqué à tous les graphiques Plotly — cohérence visuelle garantie (perf, drawdown, Livret A, benchmark, DCA, évolution par compte)",
        "Optimisation cache : fetch_settings, fetch_accounts, fetch_assets passent de ttl=600 à ttl=3600 (1h) — réduit les requêtes Supabase sur les données rarement modifiées",
    ],
    "4.3": [
        "Refactoring : page_vue_globale() découpée en 5 sous-fonctions (_vg_render_kpis, _vg_render_performance, _vg_render_evolution, _vg_render_fire, _vg_render_portfolio) — fonction principale réduite à ~30 lignes",
        "Refactoring : page_analyses() découpée en 5 sous-fonctions (_an_render_annual_performance, _an_render_risk_metrics, _an_render_comparisons, _an_render_dca, _an_render_dividends) — fonction principale réduite à ~30 lignes",
        "UI : séparateurs visuels (st.divider) entre chaque section des deux pages pour une meilleure lisibilité",
        "Optimisation : compute_positions_with_pru() appelé une seule fois dans _vg_render_portfolio (positions + allocation partagent le même résultat mis en cache)",
    ],
    "4.2": [
        "Nouveau : alerte drawdown sévère dans la sidebar — visible sur toutes les pages si le portefeuille chute de plus de 20 % depuis son plus haut",
        "Amélioration FIRE : disclaimer sous la date estimée rappelant les hypothèses du calcul (rendement constant, DCA fixe, hors inflation)",
        "Refactoring : suppression de compute_global_positions() — compute_positions_with_pru() unifié avec ajout de la géographie, utilisé pour tous les tableaux et graphiques d'allocation",
    ],
    "4.1": [
        "Correctif : itertuples() + pré-indexation assets dans compute_positions_with_pru (fix annoncé en v4.0 mais non appliqué)",
        "Nouveau : Date estimée FIRE — calcul exact par formule de valeur future (Vue Globale, section FIRE)",
        "Nouveau : Projection DCA multi-scénarios — pessimiste/neutre/optimiste ±3 % sur un même graphique (Analyses)",
        "Correctif UI : suppression du signe + redondant sur les deltas positifs (la flèche ↑ suffit à indiquer la direction) — affecte tous les KPIs (plus-value, performance, alpha, etc.)",
        "Correctif calcul : Sharpe ratio — taux sans risque (Livret A) ramené à 365 jours calendaires au lieu de 252 jours de bourse, annualisation corrigée en conséquence",
        "Nouveau : suppression de transaction depuis la page Historique (expander avec confirmation, irréversible)",
        "Nouveau : alerte snapshot périmé sur la page Saisie manuelle — avertissement si > 2 jours ouvrés sans mise à jour",
        "Nouveau : signalement des assets à prix 0 € dans le tableau des positions (avertissement global + indicateur ⚠️ dans la colonne Prix actuel)",
    ],
    "4.0": [
        "Nouveau : CAGR (rendement annualisé composé) — Vue Globale (4ème KPI perf) et Vue par compte",
        "Nouveau : Yield on Cost (YoC) — colonne dividendes TTM / capital investi dans le tableau positions",
        "Nouveau : Plafond PEA (150k€) — barre de progression (Vue par compte PEA + Rééquilibrage)",
        "Nouveau : Filtre par asset dans l'historique Transactions",
        "Nouveau : Alerte snapshot manquant globale — sidebar visible sur toutes les pages",
        "Nouveau : Titre de page dynamique selon l'onglet actif (onglet navigateur)",
        "Perf : compute_positions_with_pru — @st.cache_data + itertuples (~5× plus rapide) + pré-indexation assets",
        "Robustesse : _to_naive_datetime — uniformisation timezone dans les 3 fetch de dates",
        "Validation : asset requis pour buy/sell, sell sans position, sell en excès (déjà présent — conservé)",
    ],
    "3.10": [
        "Correction : bouton Actualiser — invalidation chirurgicale par table (fetch_snapshots_agg, _by_account, settings, accounts, assets, transactions)",
        "Préservé : fetch_benchmark_history (yfinance, TTL 1h) n'est plus effacé inutilement",
    ],
    "3.9": [
        "Correction : compute_kpis() — guard ajouté si df_snap vide (retourne dict de zéros au lieu de crasher)",
        "Correction : page Analyses — section dividendes utilisait fetch_snapshots_agg() redondant au lieu du df_snap déjà chargé",
    ],
    "3.8": [
        "Refactor : render_positions_table() — tableau positions mutualisé (Vue Globale + Vue par compte)",
        "Suppression : ~55 lignes dupliquées (PRU, PV latente, Rend. div., formatage)",
    ],
    "3.7": [
        "Robustesse : toutes les fetch_*() Supabase protégées par try/except → RuntimeError propre",
        "Robustesse : chaque page intercepte RuntimeError au chargement → st.error + st.stop() au lieu d'un crash",
        "Comportement : si Supabase revient, le prochain rendu retente automatiquement (exception non mise en cache)",
    ],
    "3.6": [
        "Perf : _build_perf_index() réduit de ×10 à ×3 par rendu (Vue Globale) et de ×3 à ×1 (Analyses)",
        "Refactor : compute_perf_over_period / compute_perf_value_over_period / compute_sparkline acceptent un perf_index pré-calculé",
        "Refactor : compute_drawdown / compute_livret_a_comparison / compute_benchmark_comparison / compute_annual_performance idem",
        "Correction : guard 'données insuffisantes' ajouté dans compute_perf_chart et compute_drawdown (évite crash si df < 2 lignes)",
        "Correction : footer page Analyses sécurisé contre df_filtered vide (IndexError)",
    ],
    "3.5": [
        "Ajout : rendement dividendes TTM — global (Vue Globale, Analyses, Vue par compte)",
        "Ajout : colonne Rend. div. dans les tableaux de positions (Vue Globale, Vue par compte)",
        "Amélioration : compute_dividends() enrichi avec TTM et by_asset_ttm",
        "Amélioration : compute_positions_with_pru() retourne désormais asset_id",
    ],
    "3.4": [
        "Correction : persistance cibles rééquilibrage via DB (settings.pea_targets) — session_state retiré",
        "Ajout : bouton Enregistrer les cibles avec sauvegarde en base Supabase",
    ],
    "3.3": [
        "Ajout : page Vue par compte (KPIs, évolution, positions, allocation, dividendes par enveloppe)",
        "Ajout : total return (PV latente + dividendes) en subline sur Vue Globale et Vue par compte",
        "Amélioration : cibles rééquilibrage persistées via session_state (survivent aux reruns)",
    ],
    "3.2": [
        "Ajout : visualisation des dividendes (Vue Globale + Analyses)",
        "Ajout : compute_dividends() — KPIs total/YTD/nb versements + graphiques par source et par année",
        "Nettoyage : df_txn et df_assets remontés dans le spinner de page_analyses",
    ],
    "3.1": [
        "Refonte Vue Globale : structure en 5 sections + tabs Évolution et Portefeuille",
        "Suppression du drawdown de Vue Globale (déjà présent dans Analyses)",
        "Perf par compte : corrigée des apports via Modified Dietz par compte",
        "Correction : delta redondant supprimé sur Performance portefeuille (Livret A / Benchmark)",
        "Nettoyage : perf_since_start supprimé de compute_kpis (jamais utilisé)",
        "display_kpi / display_kpi_block : nouveau paramètre delta_color",
    ],
    "3.0": [
        "Refonte du moteur de performance : toutes les métriques sont désormais nettes des apports en capital",
        "Ajout de _build_perf_index() : indice TWR-like (rendement ajusté jour par jour de ΔI_t)",
        "Correction : perf 1M/3M/1A, variation du jour, volatilité, Sharpe, drawdown — plus jamais gonflés par un DCA",
        "Correction : graphiques Livret A et Benchmark utilisent la courbe de performance ajustée",
        "Correction : performance annuelle et YTD recalculées sur l'indice chaîné",
        "Correction : sparklines basées sur l'indice de perf (plus sur la valeur brute)",
    ],
    "2.5": [
        "Modèle : suppression des transactions deposit et withdrawal",
        "Modèle : invested_capital désormais calculé depuis les buy/sell uniquement (−Σ total_amount)",
        "Modèle : total_value = valorisation marché uniquement (plus de cash idle)",
        "snapshot.py : compute_snapshot simplifié, cohérent avec le nouveau modèle",
        "app.py : formulaire saisie restreint à buy, sell, dividend, fee",
        "app.py : résumé des flux transactions mis à jour (achats/ventes/dividendes/frais)",
    ],
    "2.4": [
        "Nettoyage : colonne cash supprimée de la table snapshots et de tous les fichiers",
        "Nettoyage : fetch_transactions() et fetch_assets() remontés au spinner initial de Vue Globale",
        "Nettoyage : suppression du double fetch redondant dans page_vue_globale",
        "Nettoyage : suppression de la variable orpheline by_class/by_geo dans page_vue_globale",
    ],
    "2.3": [
        "Ajout : graphique en barres horizontal pour la performance annuelle (vert/rouge)",
        "Correction : coloring du tableau annuel désormais appliqué sur les valeurs numériques",
        "Correction : color_perf_row appliquée via Styler.format() au lieu de post-formatage string",
    ],
    "2.2": [
        "Nettoyage : suppression du dict orphelin dans compute_global_positions",
        "Ajout : tableau de performance par année calendaire (YTD + historique)",
        "Ajout : résumé des flux financiers en tête de l'historique transactions",
    ],
    "2.1": [
        "Correction : TypeError potentiel sur les labels Sharpe/Volatilité (valeur None)",
        "Correction : IndexError dans le filtre par compte de l'historique transactions",
        "Correction : crash au démarrage si variables d'environnement Supabase manquantes",
        "Correction : KPIs par compte désormais cohérents avec la période sélectionnée",
        "Refactor : helper _slice_period mutualisé (perf, valeur, sparkline)",
        "Refactor : positions PEA et globales recalculées avec groupby (plus performant)",
        "Refactor : donuts d'allocation mutualisés via render_allocation_charts()",
        "Refactor : format_perf() déplacée dans les utilitaires globaux",
        "Refactor : page Rééquilibrage retourne tôt si DCA non défini (UX cohérente)",
        "Ajout : export CSV dans l'historique des transactions",
        "Ajout : indicateur de fraîcheur des données (alerte si snapshot > 2 jours ouvrés)",
    ],
    "2.0": [
        "Refonte complète de l’interface utilisateur avec un système de composants KPI réutilisables",
        "Uniformisation de l’affichage sur l’ensemble du dashboard (performances, comptes, analyses)",
        "Amélioration majeure de la lisibilité avec un design plus compact et cohérent",
        "Suppression du rendu HTML custom au profit de composants Streamlit natifs",
        "Correction des incohérences visuelles (flèches, deltas, interprétation des performances)",
        "Structure du code améliorée pour une meilleure maintenabilité et évolutivité",
        "Nettoyage global et suppression des fonctions obsolètes",
    ],
    "1.6": [
        "Ajout de l’allocation globale multi-comptes",
        "Visualisation de la répartition patrimoniale (classe d’actifs et géographie)",
    ],
    "1.5": [
        "Ajout de la répartition du portefeuille (classe d’actifs et géographie)",
        "Visualisation en graphique donut interactive",
    ],
    "1.4": [
        "Ajout de l’historique des transactions avec filtres",
        "Affichage du nom des assets au lieu des IDs",
    ],
    "1.3": [
        "Ajout de sparklines pour visualiser la tendance des performances",
        "Amélioration visuelle de la section Performance",
    ],
    "1.2": [
        "Ajout de la variation en € sur les performances (1M, 3M, 1Y)",
        "Amélioration de la lisibilité des performances",
    ],
    "1.1": [
        "Ajout des performances par période (1M, 3M, 1Y)",
        "Coloration automatique des performances (vert/rouge)",
        "Ajout d’un indicateur visuel de tendance (🟢🔴)",
    ],
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

def fmt_pct(x: float) -> str:
    if abs(x) < 0.005:
        x = 0.0
    return f"{x:+.2f} %"

def format_perf(pct: float) -> str:
    """Format adaptatif : 4 décimales si < 0.01 %, 2 sinon."""
    if abs(pct) < 0.01:
        return f"{pct:+.4f} %"
    return f"{pct:+.2f} %"


def display_kpi(
    label: str,
    value: str,
    delta: float | None = None,
    is_percent: bool = False,
    delta_color: str = "normal",
):
    """KPI homogène avec flèche directionnelle et formatage automatique."""
    delta_display = None
    if delta is not None:
        if is_percent:
            delta_display = f"{delta:.2f}%"
        else:
            delta_display = f"{delta:,.0f} €".replace(",", " ")

    st.metric(
        label=label,
        value=value,
        delta=delta_display,
        delta_color=delta_color,
    )

def _chart_layout(
    height: int = 380,
    r: int = 0,
    t: int = 20,
    yaxis_suffix: str = " €",
    yaxis_format: str = ",.0f",
) -> dict:
    """Paramètres Plotly communs à tous les graphiques de l'application."""
    return dict(
        height=height,
        margin=dict(l=0, r=r, t=t, b=0),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=yaxis_suffix, tickformat=yaxis_format, gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )


def display_kpi_block(
    col,
    label: str,
    value: str,
    delta: float | None = None,
    is_percent: bool = False,
    subline: str | None = None,
    delta_color: str = "normal",
):
    """Bloc KPI complet : KPI principal + ligne secondaire compacte."""
    with col:
        display_kpi(label, value, delta, is_percent=is_percent, delta_color=delta_color)
        if subline:
            st.caption(subline)


# Options de période partagées entre toutes les pages
PERIODE_OPTIONS  = ["1 mois", "3 mois", "6 mois", "1 an", "3 ans", "Tout"]
PERIODE_DEFAULT  = "1 an"   # index calculé dynamiquement depuis la liste


@st.cache_resource
def init_db():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        st.error("❌ Variables d'environnement SUPABASE_URL / SUPABASE_KEY manquantes.")
        st.stop()
    return create_client(url, key)

supabase = init_db()


# ============================================================
# 2. DATA LAYER
# ============================================================

def _to_naive_datetime(series: pd.Series) -> pd.Series:
    """
    Normalise une série de dates en datetime timezone-naive.
    Gère les deux cas : dates Supabase naive (YYYY-MM-DD) et
    timestamps UTC aware (ex: retour d'un autre provider).
    """
    result = pd.to_datetime(series)
    if hasattr(result, "dt") and result.dt.tz is not None:
        return result.dt.tz_convert(None)
    return result

@st.cache_data(ttl=600)
def fetch_snapshots_agg() -> pd.DataFrame:
    """
    Snapshots agrégés par date (somme de tous les comptes).
    Retourne un DataFrame avec colonnes :
      date | total_value | invested_capital
    Trié par date ASC.
    Lève RuntimeError si Supabase est inaccessible.
    """
    try:
        res = supabase.table("snapshots").select(
            "date, total_value, invested_capital"
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les snapshots : {e}") from e

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = _to_naive_datetime(df["date"])

    df = (
        df.groupby("date")[["total_value", "invested_capital"]]
        .sum()
        .reset_index()
        .sort_values("date")
    )
    return df


@st.cache_data(ttl=600)
def fetch_snapshots_by_account() -> pd.DataFrame:
    """
    Snapshots bruts avec nom du compte (pour vue par compte).
    Lève RuntimeError si Supabase est inaccessible.
    """
    try:
        res = supabase.table("snapshots").select(
            "date, total_value, invested_capital, account_id, accounts(name, type)"
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les snapshots par compte : {e}") from e

    if not res.data:
        return pd.DataFrame()

    df = pd.DataFrame(res.data)
    df["date"] = _to_naive_datetime(df["date"])
    df["account_name"] = df["accounts"].apply(lambda x: x["name"] if x else None)
    df["account_type"] = df["accounts"].apply(lambda x: x["type"] if x else None)
    df = df.drop(columns=["accounts"])
    return df


@st.cache_data(ttl=3600)
def fetch_settings() -> dict:
    """
    Récupère le singleton settings (id = 1).
    Retourne un dict vide si pas encore configuré.
    Lève RuntimeError si Supabase est inaccessible.
    """
    try:
        res = supabase.table("settings").select("*").eq("id", 1).execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les paramètres : {e}") from e
    if res.data:
        return res.data[0]
    return {}


@st.cache_data(ttl=3600)
def fetch_accounts() -> pd.DataFrame:
    """Lève RuntimeError si Supabase est inaccessible."""
    try:
        res = supabase.table("accounts").select("*").eq("is_active", True).execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les comptes : {e}") from e
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_assets() -> pd.DataFrame:
    """Lève RuntimeError si Supabase est inaccessible."""
    try:
        res = supabase.table("assets").select("*").execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les assets : {e}") from e
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_transactions() -> pd.DataFrame:
    """Lève RuntimeError si Supabase est inaccessible."""
    try:
        res = supabase.table("transactions").select("*").execute()
    except Exception as e:
        raise RuntimeError(f"Impossible de charger les transactions : {e}") from e
    if not res.data:
        return pd.DataFrame()
    df = pd.DataFrame(res.data)
    df["date"] = _to_naive_datetime(df["date"])
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

def get_period_start(df: pd.DataFrame, months: int) -> pd.Timestamp:
    """
    Retourne la date de début correspondant à X mois en arrière.
    """
    if df.empty:
        return pd.Timestamp.min
    return df["date"].max() - pd.DateOffset(months=months)


def safe_value(x: float | None, default: float = 0.0) -> float:
    """
    Convertit None en valeur par défaut pour affichage UI.
    """
    return x if x is not None else default


def compute_kpis(df_snap: pd.DataFrame) -> dict:
    """
    KPIs de base à partir des snapshots agrégés.
    Retourne un dict de zéros si df_snap est vide (défense en profondeur).
    """
    if df_snap.empty:
        return {
            "total_value":      0.0,
            "invested_capital": 0.0,
            "plus_value":       0.0,
            "perf_pct":         0.0,
        }
    latest           = df_snap.iloc[-1]
    total_value      = float(latest["total_value"])
    invested_capital = float(latest["invested_capital"])
    plus_value       = total_value - invested_capital
    perf_pct         = (plus_value / invested_capital * 100) if invested_capital > 0 else 0.0

    return {
        "total_value":      total_value,
        "invested_capital": invested_capital,
        "plus_value":       plus_value,
        "perf_pct":         perf_pct,
    }

def compute_cagr(
    df_snap: pd.DataFrame,
    perf_index: pd.Series | None = None,
) -> float | None:
    """
    CAGR — rendement annualisé composé depuis le premier snapshot.
    Basé sur l'indice de performance ajusté (net des apports).
    Retourne None si moins de 30 jours de données disponibles.

    Si perf_index est fourni (pré-calculé), il est réutilisé directement.
    """
    if df_snap.empty or len(df_snap) < 2:
        return None
    nb_days = (df_snap["date"].max() - df_snap["date"].min()).days
    if nb_days < 30:
        return None
    idx          = perf_index if perf_index is not None else _build_perf_index(df_snap)
    total_return = float(idx.iloc[-1]) - 1.0
    years        = nb_days / 365.25
    return ((1 + total_return) ** (1 / years) - 1) * 100


def compute_daily_change(df_snap: pd.DataFrame) -> tuple[float, float] | None:
    """
    Variation journalière nette des apports (€ et %).
    Si tu as acheté pour 500 € aujourd'hui, ça n'apparaît pas comme un gain.
    Retourne None si pas assez de données.
    """
    if df_snap is None or len(df_snap) < 2:
        return None

    last_val  = float(df_snap.iloc[-1]["total_value"])
    prev_val  = float(df_snap.iloc[-2]["total_value"])
    last_inv  = float(df_snap.iloc[-1]["invested_capital"])
    prev_inv  = float(df_snap.iloc[-2]["invested_capital"])

    if prev_val == 0:
        return None

    new_capital = last_inv - prev_inv
    delta_eur   = last_val - prev_val - new_capital
    delta_pct   = ((last_val - new_capital) / prev_val - 1) * 100

    return delta_eur, delta_pct

def compute_annual_performance(
    df_snap: pd.DataFrame,
    perf_index: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Performance par année calendaire + YTD, nette des apports.
    Retourne : Année | Début | Fin | Perf % | Perf €
    Trié du plus récent au plus ancien.

    Si perf_index est fourni (pré-calculé sur df_snap), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    if df_snap.empty or len(df_snap) < 2:
        return pd.DataFrame()

    # Indice de perf sur l'historique complet (chaîné — permet de comparer
    # les sous-périodes annuelles sans biais de capital injecté)
    full_index   = (perf_index if perf_index is not None else _build_perf_index(df_snap)).reset_index(drop=True)
    df           = df_snap.reset_index(drop=True).copy()
    df["year"]   = df["date"].dt.year
    df["pidx"]   = full_index.values
    current_year = pd.Timestamp.today().year

    rows = []
    for year, group in df.groupby("year"):
        group     = group.sort_values("date")
        idx_start = float(group.iloc[0]["pidx"])
        idx_end   = float(group.iloc[-1]["pidx"])
        start_val = float(group.iloc[0]["total_value"])
        end_val   = float(group.iloc[-1]["total_value"])
        perf_pct  = (idx_end / idx_start - 1) * 100 if idx_start > 0 else 0.0
        perf_eur  = start_val * (idx_end / idx_start - 1) if idx_start > 0 else 0.0
        rows.append({
            "Année":  "YTD" if year == current_year else str(year),
            "Début":  start_val,
            "Fin":    end_val,
            "Perf %": round(perf_pct, 2),
            "Perf €": round(perf_eur, 2),
        })

    # Plus récent en premier
    return pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)

def check_data_freshness(df_snap: pd.DataFrame) -> tuple[int, bool]:
    """
    Retourne (nb_jours_ouvrés_depuis_dernier_snapshot, is_stale).
    is_stale = True si le dernier snapshot date de plus de 2 jours ouvrés.
    """
    if df_snap.empty:
        return 0, False
    last_date = df_snap["date"].max().date()
    today = pd.Timestamp.today().date()
    # Compte les jours ouvrés entre le dernier snapshot et aujourd'hui
    business_days = pd.bdate_range(start=last_date, end=today)
    # -1 car le jour du snapshot lui-même est compté
    nb = max(0, len(business_days) - 1)
    return nb, nb > 2

def _slice_period(df_snap: pd.DataFrame, months: int) -> pd.DataFrame:
    """Retourne le sous-DataFrame correspondant aux X derniers mois. Vide si < 2 points."""
    if df_snap.empty or len(df_snap) < 2:
        return pd.DataFrame()
    start_date = get_period_start(df_snap, months)
    df_period = df_snap[df_snap["date"] >= start_date]
    return df_period if len(df_period) >= 2 else pd.DataFrame()


def _build_perf_index(df_snap: pd.DataFrame) -> pd.Series:
    """
    Construit un indice de performance pure, net des apports en capital.

    Pour chaque jour t :
      r_t = (V_t - ΔI_t) / V_{t-1} - 1
      où ΔI_t = invested_capital_t - invested_capital_{t-1}

    L'indice est le produit cumulé des (1 + r_t), commence à 1.0.
    Ainsi, si tu injectes 500 € un lundi, ça n'affecte pas la performance.
    """
    df = df_snap.reset_index(drop=True)
    values   = df["total_value"].astype(float)
    invested = df["invested_capital"].astype(float)

    delta_invested = invested.diff().fillna(0)
    prev_values    = values.shift(1)

    # r_t = (V_t - ΔI_t) / V_{t-1} - 1
    adj_returns = (values - delta_invested) / prev_values - 1
    adj_returns.iloc[0] = 0.0                   # premier point = base
    adj_returns = adj_returns.fillna(0).clip(lower=-1)

    perf_index = (1 + adj_returns).cumprod()
    perf_index.index = df["date"]
    return perf_index


def compute_perf_over_period(
    df_snap: pd.DataFrame,
    months: int,
    perf_index: pd.Series | None = None,
) -> float:
    """Performance pure sur la période (nette des apports).

    Si perf_index est fourni (pré-calculé sur df_period), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    df_period = _slice_period(df_snap, months)
    if df_period.empty:
        return 0.0
    idx = perf_index if perf_index is not None else _build_perf_index(df_period)
    return (idx.iloc[-1] - 1) * 100


def compute_perf_value_over_period(
    df_snap: pd.DataFrame,
    months: int,
    perf_index: pd.Series | None = None,
) -> float:
    """Gain marché en € sur la période (hors capital injecté).

    Si perf_index est fourni (pré-calculé sur df_period), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    df_period = _slice_period(df_snap, months)
    if df_period.empty:
        return 0.0
    idx         = perf_index if perf_index is not None else _build_perf_index(df_period)
    start_value = float(df_period.iloc[0]["total_value"])
    return start_value * (idx.iloc[-1] - 1)


def compute_sparkline(
    df_snap: pd.DataFrame,
    months: int,
    perf_index: pd.Series | None = None,
) -> str:
    """Sparkline basée sur l'indice de performance ajusté.

    Si perf_index est fourni (pré-calculé sur df_period), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    df_period = _slice_period(df_snap, months)
    if df_period.empty:
        return ""
    values        = (perf_index if perf_index is not None else _build_perf_index(df_period)).values
    min_v, max_v  = values.min(), values.max()
    if max_v == min_v:
        return "▁" * len(values)
    ticks = "▁▂▃▄▅▆▇█"
    return "".join(
        ticks[int((v - min_v) / (max_v - min_v) * (len(ticks) - 1))]
        for v in values
    )


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


def compute_fire_date(
    current_value: float,
    monthly_dca: float,
    annual_return: float,
    fire_target: float,
) -> pd.Timestamp | None:
    """
    Estime la date d'atteinte de l'objectif FIRE via la formule de valeur future.

    Avec DCA mensuel constant :
      V_t = V_0 * (1+r)^t + DCA * ((1+r)^t − 1) / r
    Soit :
      t = log((fire_target + DCA/r) / (V_0 + DCA/r)) / log(1+r)

    Retourne None si le target est déjà atteint, non calculable, ou > 100 ans.
    """
    if fire_target <= 0 or current_value >= fire_target:
        return None

    monthly_return = (1 + annual_return) ** (1 / 12) - 1
    if monthly_return <= 0:
        return None

    try:
        if monthly_dca > 0:
            numerator   = fire_target + monthly_dca / monthly_return
            denominator = current_value + monthly_dca / monthly_return
        else:
            numerator   = fire_target
            denominator = max(current_value, 1e-9)

        if denominator <= 0 or numerator / denominator <= 1:
            return None

        months = math.log(numerator / denominator) / math.log(1 + monthly_return)
    except (ValueError, ZeroDivisionError):
        return None

    months_int = int(math.ceil(months))
    if months_int > 1200:   # > 100 ans → on n'affiche pas
        return None

    return pd.Timestamp.today() + pd.DateOffset(months=months_int)


def compute_perf_chart(df_snap: pd.DataFrame) -> go.Figure:
    """
    Graphique Valeur totale vs Capital investi.
    Zone colorée entre les deux courbes = plus-value latente.
    Retourne une figure vide si moins de 2 points disponibles.
    """
    if df_snap.empty or len(df_snap) < 2:
        fig = go.Figure()
        fig.update_layout(**_chart_layout(height=400, t=30))
        fig.add_annotation(
            x=0.5, y=0.5, xref="paper", yref="paper",
            text="Données insuffisantes pour afficher le graphique.",
            showarrow=False, font=dict(color="#888888", size=13),
        )
        return fig

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

    fig.update_layout(**_chart_layout(height=400, t=30))

    return fig


def compute_drawdown(
    df_snap: pd.DataFrame,
    perf_index: pd.Series | None = None,
) -> tuple[go.Figure, float]:
    """
    Calcule et trace le drawdown depuis le plus haut historique.
    Basé sur l'indice de perf ajusté (sans effet des apports).
    Retourne (figure, drawdown_max_en_pct).

    Si perf_index est fourni (pré-calculé sur df_snap), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    if df_snap.empty or len(df_snap) < 2:
        fig = go.Figure()
        fig.update_layout(**_chart_layout(height=280))
        return fig, 0.0

    perf_index = perf_index if perf_index is not None else _build_perf_index(df_snap)
    perf_index = perf_index.reset_index(drop=True)
    dates      = df_snap["date"].reset_index(drop=True)
    peak       = perf_index.expanding().max()
    drawdown   = (perf_index / peak - 1) * 100
    max_dd     = drawdown.min()

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

    fig.update_layout(**_chart_layout(height=280, yaxis_suffix=" %", yaxis_format=".1f"))

    return fig, max_dd


def compute_volatility(df_snap: pd.DataFrame) -> float | None:
    """
    Volatilité annualisée des rendements journaliers ajustés (en %).
    Utilise l'indice de perf pour éliminer l'effet des apports.
    Retourne None si pas assez de données (< 3 snapshots).
    """
    if len(df_snap) < 3:
        return None
    returns = _build_perf_index(df_snap).pct_change().dropna()
    if len(returns) < 2 or returns.std() == 0:
        return None
    return float(returns.std() * (252 ** 0.5) * 100)


def compute_sharpe(df_snap: pd.DataFrame, risk_free_rate: float) -> float | None:
    """
    Ratio de Sharpe annualisé sur rendements ajustés.
    Utilise l'indice de perf pour éliminer l'effet des apports.
    Retourne None si pas assez de données (< 3 snapshots).
    """
    if len(df_snap) < 3:
        return None
    returns = _build_perf_index(df_snap).pct_change().dropna()
    if len(returns) < 2 or returns.std() == 0:
        return None
    daily_rf          = risk_free_rate / 365
    excess_returns    = returns - daily_rf
    sharpe_annualized = (excess_returns.mean() / returns.std()) * (365 ** 0.5)
    return float(sharpe_annualized)


def compute_livret_a_comparison(
    df_snap: pd.DataFrame,
    livret_a_rate: float,
    perf_index: pd.Series | None = None,
) -> tuple[go.Figure, float, float, float]:
    """
    Compare la performance ajustée du portefeuille à un placement Livret A.
    La courbe portefeuille utilise l'indice de perf (sans effet des apports)
    rebased sur la valeur initiale, pour une comparaison équitable.

    Si perf_index est fourni (pré-calculé sur df_snap), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    df          = df_snap.copy().reset_index(drop=True)
    dates       = df["date"]
    start_value = float(df["total_value"].iloc[0])

    # Courbe portefeuille ajustée : start_value × indice de perf
    _idx            = perf_index if perf_index is not None else _build_perf_index(df_snap)
    portef_adjusted = start_value * _idx.reset_index(drop=True)

    daily_rate = (1 + livret_a_rate) ** (1 / 365) - 1
    n_days     = (dates - dates.iloc[0]).dt.days
    livret_a   = start_value * (1 + daily_rate) ** n_days

    perf_portef = (_idx.reset_index(drop=True).iloc[-1] - 1) * 100
    perf_livret = (livret_a.iloc[-1] / start_value - 1) * 100
    ecart       = perf_portef - perf_livret

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates, y=portef_adjusted,
        name="Mon portefeuille (perf ajustée)",
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
        y=portef_adjusted.iloc[-1],
        text=f"  {ecart_signe}{ecart:.2f} % vs Livret A",
        showarrow=False,
        xanchor="left",
        font=dict(color=ecart_color, size=13),
    )

    fig.update_layout(**_chart_layout(r=80))

    return fig, perf_portef, perf_livret, ecart


def compute_benchmark_comparison(
    df_snap: pd.DataFrame,
    benchmark_ticker: str,
    benchmark_name: str,
    perf_index: pd.Series | None = None,
) -> tuple[go.Figure, float, float | None, float | None]:
    """
    Compare la performance ajustée du portefeuille vs un benchmark.
    Les deux courbes sont rebasées à 100 au point de départ.
    Le portefeuille utilise l'indice de perf (sans effet des apports).

    Si perf_index est fourni (pré-calculé sur df_snap), il est utilisé
    directement — évite de rappeler _build_perf_index inutilement.
    """
    df     = df_snap.copy().reset_index(drop=True)
    dates  = df["date"]

    # Indice ajusté rebased à 100
    _idx           = perf_index if perf_index is not None else _build_perf_index(df_snap)
    portef_rebased = _idx.reset_index(drop=True) * 100
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

    fig.update_layout(**_chart_layout(r=100, yaxis_suffix=" %", yaxis_format=".0f"))

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

    fig.update_layout(**_chart_layout(height=450, t=30))

    return fig, theorique_list, reel_list, capital_list


def compute_dca_projection_multi(
    current_value: float,
    current_invested: float,
    monthly_dca: float,
    annual_return: float,
    inflation_rate: float,
    fire_target: float,
    years: int = 20,
) -> tuple[go.Figure, list, list, list]:
    """
    Projection DCA sur 3 scénarios (pessimiste / neutre / optimiste) sur un seul graphique.

    Les écarts sont fixes : ±3 % par rapport au rendement de base.
    Retourne (figure, theorique_neutre, reel_neutre, capital) pour que les KPIs
    restent calculés sur le scénario de base.
    """
    scenarios = [
        ("Pessimiste",  annual_return - 0.03, "#E84C4C", "dot"),
        ("Neutre",      annual_return,         "#4C9BE8", "solid"),
        ("Optimiste",   annual_return + 0.03,  "#2ECC71", "dot"),
    ]

    monthly_infl = (1 + inflation_rate) ** (1 / 12) - 1
    today        = pd.Timestamp.today().normalize()
    months       = years * 12

    fig = go.Figure()
    theorique_neutre, reel_neutre, capital_neutre = [], [], []

    for label, rate, color, dash in scenarios:
        monthly_r  = (1 + max(rate, 0.001)) ** (1 / 12) - 1
        val        = current_value
        cap        = current_invested
        dates, capital_l, theorique_l, reel_l = [], [], [], []

        for m in range(months + 1):
            dates.append(today + pd.DateOffset(months=m))
            capital_l.append(cap)
            theorique_l.append(val)
            reel_l.append(val / (1 + monthly_infl) ** m)
            val = val * (1 + monthly_r) + monthly_dca
            cap += monthly_dca

        if label == "Neutre":
            theorique_neutre, reel_neutre, capital_neutre = theorique_l, reel_l, capital_l
            # Capital investi (tracé une seule fois)
            fig.add_trace(go.Scatter(
                x=dates, y=capital_l,
                name="Capital investi",
                line=dict(color="#888888", width=2, dash="dot"),
                hovertemplate="%{y:,.0f} €<extra>Capital investi</extra>",
            ))

        fig.add_trace(go.Scatter(
            x=dates, y=theorique_l,
            name=f"{label} ({rate*100:+.0f} %/an)" if label != "Neutre" else f"Neutre ({rate*100:.0f} %/an)",
            line=dict(color=color, width=2.5 if label == "Neutre" else 1.8, dash=dash),
            hovertemplate=f"%{{y:,.0f}} €<extra>{label}</extra>",
        ))

    # Ligne objectif FIRE
    if fire_target > 0:
        fig.add_hline(
            y=fire_target,
            line_dash="dash", line_color="#2ECC71", line_width=1.5,
            annotation_text=f"  🎯 FIRE : {fmt_eur(fire_target)}",
            annotation_position="top left",
            annotation_font_color="#2ECC71",
        )

    fig.update_layout(**_chart_layout(height=450, t=30))

    return fig, theorique_neutre, reel_neutre, capital_neutre


def compute_pea_positions(
    df_transactions: pd.DataFrame,
    df_assets: pd.DataFrame,
    account_id: int,
) -> pd.DataFrame:
    df_txn = df_transactions[
        (df_transactions["account_id"] == account_id) &
        (df_transactions["asset_id"].notna()) &
        (df_transactions["type"].isin(["buy", "sell"]))
    ].copy()

    if df_txn.empty:
        return pd.DataFrame()

    # Quantité nette vectorisée : buy = +qty, sell = -qty
    df_txn["signed_qty"] = df_txn["quantity"].fillna(0).astype(float)
    df_txn.loc[df_txn["type"] == "sell", "signed_qty"] *= -1

    df_pos = (
        df_txn.groupby("asset_id")["signed_qty"]
        .sum()
        .reset_index()
        .rename(columns={"signed_qty": "quantity"})
    )

    # Filtrer les positions nulles ou négatives
    df_pos = df_pos[df_pos["quantity"] > 1e-9]

    if df_pos.empty:
        return pd.DataFrame()

    df_pos = df_pos.merge(
        df_assets[["id", "name", "yahoo_ticker", "last_known_price", "asset_class", "geography"]],
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

def compute_allocation(df_positions: pd.DataFrame):
    """
    Retourne la répartition par classe d'actifs et géographie
    """
    if df_positions.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = df_positions.copy()

    df["asset_class"] = df["asset_class"].fillna("Autre")
    df["geography"] = df["geography"].fillna("Autre")

    by_class = df.groupby("asset_class")["value"].sum().reset_index()
    by_geo   = df.groupby("geography")["value"].sum().reset_index()

    return by_class, by_geo

def render_allocation_charts(df_positions: pd.DataFrame, col1, col2):
    """Affiche les deux donuts classe d'actifs / géographie dans les colonnes fournies."""
    by_class, by_geo = compute_allocation(df_positions)

    for col, data, label_col, title in [
        (col1, by_class, "asset_class", "Classe d'actifs"),
        (col2, by_geo,   "geography",   "Géographie"),
    ]:
        if not data.empty:
            fig = go.Figure(go.Pie(
                labels=data[label_col],
                values=data["value"],
                hole=0.4,
                textinfo="label+percent",
            ))
            fig.update_layout(title=title, margin=dict(l=0, r=0, t=40, b=0))
            col.plotly_chart(fig, use_container_width=True)


def render_positions_table(
    df_pos: pd.DataFrame,
    by_asset_ttm: dict,
    label_capital: str = "Capital investi",
) -> None:
    """
    Affiche les KPIs de synthèse + le tableau détaillé des positions (PRU, PV, Rend. div.).
    Mutualisé entre page_vue_globale et page_compte pour éviter la duplication.

    Paramètres
    ----------
    df_pos        : résultat de compute_positions_with_pru()
    by_asset_ttm  : dict {asset_id: dividendes_ttm} — peut être {} si aucun dividende
    label_capital : libellé du KPI "capital investi" (légèrement différent selon la page)
    """
    if df_pos.empty:
        st.info("Aucune position ouverte.")
        return

    total_pv      = df_pos["pv_latente"].sum()
    total_inv_pos = df_pos["invested"].sum()
    pv_pct        = (total_pv / total_inv_pos * 100) if total_inv_pos > 0 else 0.0

    col1, col2, col3 = st.columns(3)
    display_kpi_block(col1, "Lignes ouvertes",        str(len(df_pos)))
    display_kpi_block(col2, "Plus-value latente totale", fmt_eur(total_pv),
                      pv_pct, is_percent=True)
    display_kpi_block(col3, label_capital,            fmt_eur(total_inv_pos))

    zero_price = df_pos[df_pos["last_known_price"] == 0]["name"].tolist()
    if zero_price:
        st.warning(
            f"⚠️ Prix manquant (0 €) pour : **{', '.join(zero_price)}** "
            "— valeur et performance inexactes pour ces positions."
        )

    with st.expander("Voir le tableau détaillé"):
        df_display = df_pos.copy()

        # Rendement dividendes TTM par position
        df_display["div_ttm"]    = df_display["asset_id"].map(by_asset_ttm).fillna(0.0)
        df_display["Rend. div."] = df_display.apply(
            lambda r: f"{r['div_ttm'] / r['value'] * 100:.2f} %"
            if r["value"] > 0 and r["div_ttm"] > 0 else "—",
            axis=1,
        )
        # Yield on Cost : dividendes TTM / capital investi (PRU × quantité)
        df_display["YoC"] = df_display.apply(
            lambda r: f"{r['div_ttm'] / r['invested'] * 100:.2f} %"
            if r["invested"] > 0 and r["div_ttm"] > 0 else "—",
            axis=1,
        )

        df_display["PRU"]         = df_display["pru"].map(lambda x: f"{x:.2f} €")
        df_display["Prix actuel"] = df_display["last_known_price"].map(
            lambda x: f"⚠️ {x:.2f} €" if x == 0 else f"{x:.2f} €"
        )
        df_display["Valeur"]      = df_display["value"].map(fmt_eur)
        df_display["Investi"]     = df_display["invested"].map(fmt_eur)
        df_display["PV latente"]  = df_display["pv_latente"].map(
            lambda x: f"{x:+,.0f} €".replace(",", " ")
        )
        df_display["PV %"]        = df_display["pv_pct"].map(lambda x: f"{x:+.2f} %")
        df_display = df_display.rename(columns={
            "name": "Asset", "asset_class": "Classe", "quantity": "Quantité",
        })
        df_display = df_display[[
            "Asset", "Classe", "Quantité",
            "PRU", "Prix actuel", "Investi", "Valeur",
            "PV latente", "PV %", "Rend. div.", "YoC",
        ]]
        st.dataframe(df_display, use_container_width=True, hide_index=True)


@st.cache_data
def compute_positions_with_pru(
    df_txn: pd.DataFrame,
    df_assets: pd.DataFrame,
) -> pd.DataFrame:
    """
    Reconstruit toutes les positions avec leur PRU (Prix de Revient Unitaire)
    via la méthode PRMP et calcule la plus-value latente par ligne.

    Retourne : name | asset_class | quantity | pru | last_known_price
               | value | invested | pv_latente | pv_pct

    Optimisations :
    - @st.cache_data   : résultat mis en cache par contenu des DataFrames d'entrée
    - itertuples()     : ~5× plus rapide qu'iterrows (pas de création de Series)
    - asset_index      : pré-indexation assets → lookup O(1) au lieu de O(n) par asset
    """
    trades = df_txn[
        df_txn["type"].isin(["buy", "sell"]) &
        df_txn["asset_id"].notna()
    ].copy().sort_values("date")

    if trades.empty:
        return pd.DataFrame()

    # Pré-indexer les assets une seule fois (évite df_assets[id == x] dans la boucle)
    asset_index = df_assets.set_index("id")

    rows = []

    for asset_id, group in trades.groupby("asset_id"):
        qty_held   = 0.0
        total_cost = 0.0

        # itertuples est ~5× plus rapide qu'iterrows car il ne crée pas de Series
        for row in group.itertuples(index=False):
            qty   = float(row.quantity or 0)
            price = float(row.unit_price or 0)
            fees  = float(row.fees or 0)

            if row.type == "buy":
                total_cost += qty * price + fees
                qty_held   += qty
            elif row.type == "sell" and qty_held > 0:
                avg_cost    = total_cost / qty_held
                total_cost -= avg_cost * min(qty, qty_held)
                qty_held    = max(0.0, qty_held - qty)

        if qty_held < 1e-9:
            continue

        pru = total_cost / qty_held if qty_held > 0 else 0.0

        if asset_id not in asset_index.index:
            continue

        asset_row     = asset_index.loc[asset_id]
        name          = asset_row["name"]
        asset_class   = asset_row["asset_class"]
        geography     = asset_row.get("geography")
        current_price = float(asset_row["last_known_price"] or 0)
        value         = qty_held * current_price
        invested      = qty_held * pru
        pv_latente    = value - invested
        pv_pct        = (pv_latente / invested * 100) if invested > 0 else 0.0

        rows.append({
            "asset_id":          int(asset_id),
            "name":              name,
            "asset_class":       asset_class or "Autre",
            "geography":         geography,
            "quantity":          round(qty_held, 4),
            "pru":               round(pru, 4),
            "last_known_price":  round(current_price, 4),
            "value":             round(value, 2),
            "invested":          round(invested, 2),
            "pv_latente":        round(pv_latente, 2),
            "pv_pct":            round(pv_pct, 2),
        })

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values("value", ascending=False)
        .reset_index(drop=True)
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

def compute_accounts_evolution(df_snap_acc: pd.DataFrame) -> pd.DataFrame:
    if df_snap_acc.empty:
        return pd.DataFrame()

    df = df_snap_acc.copy()

    # ✅ FIX 1 : supprimer comptes nulls
    df = df.dropna(subset=["account_name"])

    df_pivot = df.pivot_table(
        index="date",
        columns="account_name",
        values="total_value",
        aggfunc="sum"
    ).sort_index()

    # ✅ FIX 2 : pandas moderne
    df_pivot = df_pivot.ffill()

    # ✅ FIX 3 : éviter colonnes vides
    df_pivot = df_pivot.dropna(axis=1, how="all")

    return df_pivot

# ============================================================
# 4. PAGES
# ============================================================

def _call_gemini(api_key: str, prompt: str) -> str:
    """Appel à l'API Gemini 1.5 Flash. Lève une exception en cas d'erreur."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        f"/models/gemini-2.5-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

# ── Constantes métier ─────────────────────────────────────
PEA_PLAFOND = 150_000   # € — plafond légal de versements PEA


def _set_page_title(subtitle: str) -> None:
    """
    Met à jour le titre de l'onglet navigateur pour la page active.
    (Streamlit ne permet pas de changer set_page_config dynamiquement,
    mais l'injection <title> est supportée par les navigateurs modernes.)
    """
    st.markdown(f"<title>BeyondGrid — {subtitle}</title>", unsafe_allow_html=True)


def compute_dividends(
    df_txn: pd.DataFrame,
    df_assets: pd.DataFrame,
) -> dict:
    """
    Agrège les transactions de type dividend.
    Retourne un dict avec KPIs et figures Plotly.
    Si aucun dividende, retourne {"empty": True}.
    """
    div = df_txn[df_txn["type"] == "dividend"].copy()

    if div.empty:
        return {"empty": True}

    asset_map        = df_assets.set_index("id")["name"].to_dict()
    div["asset_name"] = div["asset_id"].map(asset_map).fillna("Non précisé")
    div["year"]       = div["date"].dt.year

    today        = pd.Timestamp.today()
    total        = float(div["total_amount"].sum())
    current_year = today.year
    ytd          = float(div[div["year"] == current_year]["total_amount"].sum())
    nb           = len(div)

    # TTM (Trailing Twelve Months) — base du yield annualisé
    ttm_start    = today - pd.DateOffset(years=1)
    div_ttm      = div[div["date"] >= ttm_start]
    ttm          = float(div_ttm["total_amount"].sum())

    # Dividendes TTM par asset_id (pour yield par position)
    by_asset_ttm: dict[int, float] = (
        div_ttm.dropna(subset=["asset_id"])
        .groupby(div_ttm["asset_id"].astype(int))["total_amount"]
        .sum()
        .to_dict()
    )

    # ── Par asset (barres horizontales) ─────────────────────
    by_asset = (
        div.groupby("asset_name")["total_amount"]
        .sum()
        .sort_values(ascending=True)
        .reset_index()
    )
    fig_asset = go.Figure(go.Bar(
        x=by_asset["total_amount"],
        y=by_asset["asset_name"],
        orientation="h",
        marker_color="#2ECC71",
        text=[fmt_eur(v) for v in by_asset["total_amount"]],
        textposition="outside",
        hovertemplate="%{y} : %{x:,.2f} €<extra></extra>",
    ))
    fig_asset.update_layout(
        height=max(180, len(by_asset) * 52),
        margin=dict(l=0, r=90, t=10, b=0),
        xaxis=dict(ticksuffix=" €", showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(showgrid=False),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    # ── Par année (barres verticales) ───────────────────────
    by_year = (
        div.groupby("year")["total_amount"]
        .sum()
        .reset_index()
    )
    fig_year = go.Figure(go.Bar(
        x=by_year["year"].astype(str),
        y=by_year["total_amount"],
        marker_color="#4C9BE8",
        text=[fmt_eur(v) for v in by_year["total_amount"]],
        textposition="outside",
        hovertemplate="%{x} : %{y:,.2f} €<extra></extra>",
    ))
    fig_year.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(ticksuffix=" €", tickformat=",.0f", gridcolor="#f0f0f0"),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return {
        "empty":        False,
        "total":        total,
        "ytd":          ytd,
        "ttm":          ttm,
        "nb":           nb,
        "by_asset_ttm": by_asset_ttm,
        "fig_asset":    fig_asset,
        "fig_year":     fig_year,
    }


def _vg_render_kpis(kpis: dict, daily_change, div_data: dict) -> None:
    """KPIs de situation : valeur totale, capital investi, plus-value latente."""
    total_dividends  = div_data["total"] if not div_data.get("empty") else 0.0
    total_return     = kpis["plus_value"] + total_dividends
    total_return_pct = (
        total_return / kpis["invested_capital"] * 100
        if kpis["invested_capital"] > 0 else 0.0
    )
    pv_subline = (
        f"Total return (÷ dividendes) : {fmt_eur(total_return)} · {total_return_pct:+.2f} %"
        if total_dividends > 0 else None
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        display_kpi("Valeur totale", fmt_eur(kpis["total_value"]))
        if daily_change is not None:
            delta_eur, delta_pct = daily_change
            signe = "▲" if delta_eur >= 0 else "▼"
            st.caption(f"{signe} {fmt_eur(delta_eur)} aujourd'hui ({delta_pct:+.2f} %)")
    display_kpi_block(col2, "Capital investi", fmt_eur(kpis["invested_capital"]))
    display_kpi_block(col3, "Plus-value latente", fmt_eur(kpis["plus_value"]),
                      kpis["perf_pct"], is_percent=True, subline=pv_subline)


def _vg_render_performance(df_snap: pd.DataFrame) -> None:
    """Perfs 1m / 3m / 1an / CAGR avec sparklines pré-calculées."""
    st.subheader("📅 Performance récente")
    _period_months = [1, 3, 12]
    _period_slices = {m: _slice_period(df_snap, m) for m in _period_months}
    _period_idx    = {
        m: _build_perf_index(df_s) if not df_s.empty else pd.Series(dtype=float)
        for m, df_s in _period_slices.items()
    }
    _full_idx = _build_perf_index(df_snap)
    cagr      = compute_cagr(df_snap, perf_index=_full_idx)

    perf_1m   = compute_perf_over_period(df_snap, 1,  perf_index=_period_idx[1])
    perf_3m   = compute_perf_over_period(df_snap, 3,  perf_index=_period_idx[3])
    perf_12m  = compute_perf_over_period(df_snap, 12, perf_index=_period_idx[12])
    val_1m    = compute_perf_value_over_period(df_snap, 1,  perf_index=_period_idx[1])
    val_3m    = compute_perf_value_over_period(df_snap, 3,  perf_index=_period_idx[3])
    val_12m   = compute_perf_value_over_period(df_snap, 12, perf_index=_period_idx[12])
    spark_1m  = compute_sparkline(df_snap, 1,  perf_index=_period_idx[1])
    spark_3m  = compute_sparkline(df_snap, 3,  perf_index=_period_idx[3])
    spark_12m = compute_sparkline(df_snap, 12, perf_index=_period_idx[12])

    col1, col2, col3, col4 = st.columns(4)
    display_kpi_block(col1, "1 mois",  fmt_pct(perf_1m),  subline=f"{fmt_eur(val_1m)} • {spark_1m}")
    display_kpi_block(col2, "3 mois",  fmt_pct(perf_3m),  subline=f"{fmt_eur(val_3m)} • {spark_3m}")
    display_kpi_block(col3, "1 an",    fmt_pct(perf_12m), subline=f"{fmt_eur(val_12m)} • {spark_12m}")
    display_kpi_block(
        col4, "CAGR (depuis le début)",
        fmt_pct(cagr) if cagr is not None else "—",
        subline=f"{len(df_snap)} snapshots" if cagr is not None else "< 30j de données",
    )


def _vg_render_evolution(df_snap: pd.DataFrame, df_snap_acc: pd.DataFrame) -> None:
    """Graphe d'évolution patrimoine + vue par compte avec filtre période."""
    st.subheader("📈 Évolution")
    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période",
            options=PERIODE_OPTIONS,
            index=PERIODE_OPTIONS.index(PERIODE_DEFAULT),
            label_visibility="collapsed",
        )

    df_filtered          = filter_by_period(df_snap, periode)
    df_snap_acc_filtered = filter_by_period(df_snap_acc, periode)
    df_acc_evo           = compute_accounts_evolution(df_snap_acc_filtered)

    tab_global, tab_comptes = st.tabs(["📈 Patrimoine global", "🏦 Par compte"])

    with tab_global:
        st.plotly_chart(compute_perf_chart(df_filtered), use_container_width=True)

    with tab_comptes:
        if df_acc_evo.empty:
            st.info("Aucune donnée par compte pour cette période.")
        else:
            total = df_acc_evo.iloc[-1].sum()
            cols  = st.columns(len(df_acc_evo.columns))
            for i, col_name in enumerate(df_acc_evo.columns):
                values  = df_acc_evo[col_name].dropna()
                current = float(values.iloc[-1])
                pct     = (current / total * 100) if total > 0 else 0
                if len(values) < 2:
                    with cols[i]:
                        display_kpi(col_name, fmt_eur(current))
                    continue
                start       = float(values.iloc[0])
                acc_rows    = df_snap_acc_filtered[
                    df_snap_acc_filtered["account_name"] == col_name
                ].sort_values("date")
                new_capital = (
                    float(acc_rows.iloc[-1]["invested_capital"]) -
                    float(acc_rows.iloc[0]["invested_capital"])
                    if len(acc_rows) >= 2 else 0.0
                )
                perf_market_eur = current - start - new_capital
                perf_pct        = (perf_market_eur / start * 100) if start > 0 else 0
                display_kpi_block(
                    cols[i], col_name, fmt_eur(current), perf_pct,
                    is_percent=True,
                    subline=f"{fmt_eur(perf_market_eur)} • {pct:.1f} %",
                )

            fig_acc = go.Figure()
            for col_name in df_acc_evo.columns:
                fig_acc.add_trace(go.Scatter(
                    x=df_acc_evo.index,
                    y=df_acc_evo[col_name].fillna(0),
                    name=col_name,
                    stackgroup="one",
                    hovertemplate=f"{col_name} : %{{y:,.0f}} €<extra></extra>",
                ))
            fig_acc.update_layout(**_chart_layout(height=300))
            st.plotly_chart(fig_acc, use_container_width=True)


def _vg_render_fire(fire: dict, kpis: dict, settings: dict, div_data: dict) -> None:
    """Barre FIRE, date estimée, revenu passif et résumé dividendes."""
    st.subheader("🎯 Objectif FIRE")
    if fire["fire_target"] > 0:
        st.progress(
            min(fire["fire_pct"] / 100, 1.0),
            text=(
                f"{fire['fire_pct']:.1f} % — "
                f"{fmt_eur(kpis['total_value'])} / {fmt_eur(fire['fire_target'])}"
            ),
        )
        fire_date = compute_fire_date(
            current_value = kpis["total_value"],
            monthly_dca   = float(settings.get("monthly_dca") or 0),
            annual_return = float(settings.get("estimated_annual_return") or 0.07),
            fire_target   = fire["fire_target"],
        )
        if fire_date is not None:
            delta_years = (fire_date - pd.Timestamp.today()).days / 365.25
            years_int   = int(delta_years)
            months_int  = int((delta_years - years_int) * 12)
            delta_str   = f"{years_int} an{'s' if years_int > 1 else ''}"
            if months_int > 0:
                delta_str += f" {months_int} mois"
            _MOIS_FR = [
                "", "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            ]
            st.caption(f"📅 Date estimée : **{_MOIS_FR[fire_date.month]} {fire_date.year}** — dans {delta_str}")
            _ret_pct = float(settings.get("estimated_annual_return") or 0.07) * 100
            _dca_eur = float(settings.get("monthly_dca") or 0)
            st.caption(
                f"ℹ️ Projection indicative — hypothèses : rendement annuel constant à {_ret_pct:.1f} %, "
                f"DCA mensuel de {fmt_eur(_dca_eur)}, hors inflation et aléas de marché."
            )
        elif kpis["total_value"] >= fire["fire_target"]:
            st.success("🎉 Objectif FIRE atteint !")
    else:
        st.info("Objectif FIRE non défini — renseigne-le dans Saisie manuelle.")

    col_f1, col_f2, col_f3 = st.columns(3)
    display_kpi_block(col_f1, "Revenu passif mensuel (4 %)",
                      f"{fmt_eur(fire['passive_income_monthly'])}/mois")
    display_kpi_block(col_f2, "Revenu passif annuel (4 %)",
                      f"{fmt_eur(fire['passive_income_annual'])}/an")
    if fire["freedom_days"] is not None:
        display_kpi_block(col_f3, "Jours de liberté financière",
                          f"{fire['freedom_days']:,.0f} jours".replace(",", " "))
    else:
        col_f3.info("Définis ton revenu mensuel pour ce calcul.")

    if not div_data.get("empty"):
        yield_global = (
            div_data["ttm"] / kpis["total_value"] * 100
            if kpis["total_value"] > 0 else 0.0
        )
        col_d1, col_d2, col_d3 = st.columns(3)
        display_kpi_block(col_d1, "Dividendes reçus (total)", fmt_eur(div_data["total"]))
        display_kpi_block(col_d2, "Dividendes YTD",           fmt_eur(div_data["ytd"]))
        display_kpi_block(col_d3, "Rendement dividendes (TTM)", f"{yield_global:.2f} %")


def _vg_render_portfolio(df_txn: pd.DataFrame, df_assets: pd.DataFrame, div_data: dict) -> None:
    """Onglets Positions et Allocation."""
    st.subheader("📋 Portefeuille")
    df_pos = compute_positions_with_pru(df_txn, df_assets)
    by_ttm = div_data.get("by_asset_ttm", {}) if not div_data.get("empty") else {}

    tab_pos, tab_alloc = st.tabs(["📋 Positions", "📊 Allocation"])
    with tab_pos:
        render_positions_table(df_pos, by_asset_ttm=by_ttm,
                               label_capital="Capital investi (positions)")
    with tab_alloc:
        if not df_pos.empty:
            col1, col2 = st.columns(2)
            render_allocation_charts(df_pos, col1, col2)
        else:
            st.info("Aucune position détectée.")


def page_vue_globale():
    st.title("📊 Synthèse du Patrimoine")
    _set_page_title("Vue Globale")

    try:
        with st.spinner("Chargement des données..."):
            df_snap     = fetch_snapshots_agg()
            settings    = fetch_settings()
            df_txn      = fetch_transactions()
            df_assets   = fetch_assets()
            df_snap_acc = fetch_snapshots_by_account()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    if df_snap.empty:
        st.warning("Aucun snapshot disponible. Lance le script de snapshot pour commencer.")
        return

    kpis         = compute_kpis(df_snap)
    daily_change = compute_daily_change(df_snap)
    fire         = compute_fire(kpis, settings)
    div_data     = compute_dividends(df_txn, df_assets)

    nb_days, is_stale = check_data_freshness(df_snap)
    if is_stale:
        st.warning(
            f"⚠️ Dernier snapshot il y a **{nb_days} jours ouvrés** "
            f"({df_snap.iloc[-1]['date'].strftime('%d/%m/%Y')}) — "
            "vérifie que GitHub Actions s'est bien déclenché."
        )

    _vg_render_kpis(kpis, daily_change, div_data)
    st.divider()
    _vg_render_performance(df_snap)
    st.divider()
    _vg_render_evolution(df_snap, df_snap_acc)
    st.divider()
    _vg_render_fire(fire, kpis, settings, div_data)
    st.divider()
    _vg_render_portfolio(df_txn, df_assets, div_data)

    st.caption(
        f"Dernière donnée : {df_snap.iloc[-1]['date'].strftime('%d/%m/%Y')} "
        f"· {len(df_snap)} snapshots disponibles"
    )

def _an_render_annual_performance(df_snap: pd.DataFrame, perf_idx_full: pd.Series) -> None:
    """Graphe et tableau de performance par année civile."""
    st.subheader("📅 Performance par année")
    df_annual = compute_annual_performance(df_snap, perf_index=perf_idx_full)
    if df_annual.empty:
        st.info("Pas encore assez de données pour calculer les performances annuelles.")
        return

    def _color(val):
        if isinstance(val, (int, float)):
            return "color: #2ECC71" if val > 0 else ("color: #E84C4C" if val < 0 else "")
        return ""

    df_chart   = df_annual.iloc[::-1].reset_index(drop=True)
    bar_colors = ["#2ECC71" if v >= 0 else "#E84C4C" for v in df_chart["Perf %"]]
    fig_annual = go.Figure(go.Bar(
        x=df_chart["Perf %"], y=df_chart["Année"], orientation="h",
        marker_color=bar_colors,
        text=[f"{v:+.2f} %" for v in df_chart["Perf %"]],
        textposition="outside",
        hovertemplate="%{y} : %{x:+.2f} %<extra></extra>",
    ))
    fig_annual.update_layout(
        height=max(180, len(df_chart) * 48),
        margin=dict(l=0, r=70, t=10, b=0),
        xaxis=dict(ticksuffix=" %", showgrid=True, gridcolor="#f0f0f0",
                   zeroline=True, zerolinecolor="#cccccc", zerolinewidth=1.5),
        yaxis=dict(showgrid=False),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_annual, use_container_width=True)

    styled = (
        df_annual.style
        .map(_color, subset=["Perf %", "Perf €"])
        .format({
            "Début":  fmt_eur, "Fin": fmt_eur,
            "Perf €": lambda x: f"{x:+,.0f} €".replace(",", " "),
            "Perf %": lambda x: f"{x:+.2f} %",
        })
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _an_render_risk_metrics(
    df_filtered: pd.DataFrame,
    risk_free_rate: float,
    perf_idx_filtered: pd.Series,
) -> None:
    """Sharpe, volatilité et drawdown."""
    st.subheader("⚡ Risque & Performance")
    MIN_POINTS = 20
    if len(df_filtered) < MIN_POINTS:
        st.warning(
            f"⏳ Données insuffisantes ({len(df_filtered)} snapshot(s), "
            f"minimum recommandé : {MIN_POINTS}). "
            "Sharpe et Volatilité s'afficheront automatiquement au fil des jours."
        )
        c1, c2 = st.columns(2)
        c1.metric("Taux sans risque (Livret A)", f"{risk_free_rate * 100:.1f} %")
        c2.metric("Nb jours analysés", f"{len(df_filtered)}")
    else:
        volatility         = compute_volatility(df_filtered)
        sharpe             = compute_sharpe(df_filtered, risk_free_rate)
        volatility_display = safe_value(volatility)
        sharpe_display     = safe_value(sharpe)
        sharpe_label = (
            "🟢 Excellent"  if sharpe_display >= 2 else
            "🟢 Bon"        if sharpe_display >= 1 else
            "🟡 Acceptable" if sharpe_display >= 0 else "🔴 Négatif"
        )
        vol_label = (
            "🟢 Faible"  if volatility_display < 10 else
            "🟡 Modérée" if volatility_display < 20 else "🔴 Élevée"
        )
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            display_kpi("Ratio de Sharpe", f"{sharpe_display:.2f}")
            st.caption(sharpe_label)
        with col2:
            display_kpi("Volatilité annualisée", f"{volatility_display:.1f} %")
            st.caption(vol_label)
        with col3:
            display_kpi("Taux sans risque (Livret A)", f"{risk_free_rate * 100:.1f} %")
        with col4:
            display_kpi("Nb jours analysés", f"{len(df_filtered)}")

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

    st.subheader("📉 Drawdown")
    fig_dd, max_dd = compute_drawdown(df_filtered, perf_index=perf_idx_filtered)
    dd_label = (
        "🟢 Faible" if max_dd > -10 else
        "🟡 Modéré" if max_dd > -20 else "🔴 Sévère"
    )
    col_dd1, col_dd2, _ = st.columns([1, 1, 5])
    display_kpi_block(col_dd1, "Pire drawdown", f"{max_dd:.1f} %")
    col_dd2.metric("Niveau de risque", dd_label)
    st.plotly_chart(fig_dd, use_container_width=True)


def _an_render_comparisons(
    df_filtered: pd.DataFrame,
    df_assets: pd.DataFrame,
    risk_free_rate: float,
    perf_idx_filtered: pd.Series,
) -> None:
    """Comparaisons : Livret A puis benchmark."""
    st.subheader("🏦 Portefeuille vs Livret A")
    fig_la, perf_portef, perf_livret, ecart = compute_livret_a_comparison(
        df_filtered, risk_free_rate, perf_index=perf_idx_filtered
    )
    col1, col2, col3 = st.columns(3)
    display_kpi_block(col1, "Performance portefeuille", format_perf(perf_portef))
    display_kpi_block(col2, f"Performance Livret A ({risk_free_rate*100:.1f} %)",
                      format_perf(perf_livret))
    display_kpi_block(col3, "Écart (alpha vs Livret A)",
                      format_perf(ecart), ecart, is_percent=True)
    st.plotly_chart(fig_la, use_container_width=True)

    st.subheader("🏁 Portefeuille vs Benchmark")
    df_benchmarks = df_assets[
        df_assets["is_benchmark"] == True
    ][["name", "yahoo_ticker"]].dropna(subset=["yahoo_ticker"])

    if df_benchmarks.empty:
        st.info(
            "Aucun benchmark configuré. "
            "Dans ta table `assets`, passe `is_benchmark = TRUE` "
            "sur un ETF (ex: IWDA.AS pour MSCI World)."
        )
        return

    selected = (
        df_benchmarks.iloc[0] if len(df_benchmarks) == 1
        else df_benchmarks[
            df_benchmarks["name"] == st.selectbox("Benchmark", df_benchmarks["name"].tolist())
        ].iloc[0]
    )
    with st.spinner(f"Chargement de {selected['name']}..."):
        fig_bench, perf_portef, perf_bench, ecart = compute_benchmark_comparison(
            df_filtered, selected["yahoo_ticker"], selected["name"],
            perf_index=perf_idx_filtered,
        )
    col1, col2, col3 = st.columns(3)
    display_kpi_block(col1, "Performance portefeuille", f"{perf_portef:+.2f} %")
    if perf_bench is not None:
        display_kpi_block(col2, f"Performance {selected['name']}", f"{perf_bench:+.2f} %")
        display_kpi_block(col3, "Alpha généré", f"{ecart:+.2f} %", ecart, is_percent=True)
    else:
        col2.warning("Données benchmark indisponibles")
    st.plotly_chart(fig_bench, use_container_width=True)


def _an_render_dca(df_snap: pd.DataFrame, settings: dict) -> None:
    """Projection DCA multi-scénarios."""
    st.subheader("🔭 Projection DCA")
    monthly_dca    = float(settings.get("monthly_dca") or 0)
    annual_return  = float(settings.get("estimated_annual_return") or 0.07)
    inflation_rate = float(settings.get("inflation_rate") or 0.02)
    fire_target    = float(settings.get("fire_target_amount") or 0)

    if monthly_dca == 0:
        st.info("💡 Renseigne ton DCA mensuel dans **Saisie manuelle** pour activer la projection.")
        return

    col_horizon, col_info = st.columns([2, 5])
    with col_horizon:
        years = st.slider("Horizon (années)", min_value=1, max_value=40, value=20, step=1)
    with col_info:
        st.caption(
            f"DCA mensuel : **{fmt_eur(monthly_dca)}** · "
            f"Rendement neutre : **{annual_return*100:.1f} %/an** · "
            f"Scénarios : ±3 % · Inflation : **{inflation_rate*100:.1f} %/an**"
        )

    kpis_full = compute_kpis(df_snap)
    fig_dca, theorique, reel, capital = compute_dca_projection_multi(
        current_value    = kpis_full["total_value"],
        current_invested = kpis_full["invested_capital"],
        monthly_dca      = monthly_dca,
        annual_return    = annual_return,
        inflation_rate   = inflation_rate,
        fire_target      = fire_target,
        years            = years,
    )
    val_finale_nom  = theorique[-1]
    val_finale_reel = reel[-1]
    capital_final   = capital[-1]
    gain_total      = val_finale_nom - capital_final
    gain_pct        = (gain_total / capital_final * 100) if capital_final > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    display_kpi_block(col1, f"Valeur dans {years} ans",       fmt_eur(val_finale_nom))
    display_kpi_block(col2, "Valeur réelle (pouvoir d'achat)", fmt_eur(val_finale_reel))
    display_kpi_block(col3, "Capital total investi",           fmt_eur(capital_final))
    display_kpi_block(col4, "Gain généré par les intérêts",
                      fmt_eur(gain_total), gain_pct, is_percent=True)
    st.plotly_chart(fig_dca, use_container_width=True)
    st.caption(
        f"📌 À cet horizon, la règle des 4% générerait "
        f"**{fmt_eur(val_finale_nom * 0.04 / 12)}/mois** nominaux "
        f"(soit **{fmt_eur(val_finale_reel * 0.04 / 12)}/mois** en euros d'aujourd'hui)"
    )


def _an_render_dividends(
    df_txn: pd.DataFrame,
    df_assets: pd.DataFrame,
    df_snap: pd.DataFrame,
) -> None:
    """Analyse des dividendes reçus."""
    st.subheader("💰 Dividendes")
    div_data = compute_dividends(df_txn, df_assets)
    if div_data.get("empty"):
        st.info("Aucun dividende enregistré. Saisis-les dans Saisie manuelle (type : Dividende).")
        return

    kpis_full = compute_kpis(df_snap)
    yield_ttm = (
        div_data["ttm"] / kpis_full["total_value"] * 100
        if kpis_full["total_value"] > 0 else 0.0
    )
    col1, col2, col3, col4 = st.columns(4)
    display_kpi_block(col1, "Total reçu (all time)",   fmt_eur(div_data["total"]))
    display_kpi_block(col2, "Reçu cette année (YTD)", fmt_eur(div_data["ytd"]))
    display_kpi_block(col3, "Rendement TTM",           f"{yield_ttm:.2f} %")
    display_kpi_block(col4, "Nombre de versements",    str(div_data["nb"]))

    col_left, col_right = st.columns(2)
    with col_left:
        st.caption("Par source")
        st.plotly_chart(div_data["fig_asset"], use_container_width=True)
    with col_right:
        st.caption("Par année")
        st.plotly_chart(div_data["fig_year"], use_container_width=True)


def page_analyses():
    st.title("📊 Analyses & Graphiques")
    _set_page_title("Analyses")

    try:
        with st.spinner("Chargement des données..."):
            df_snap   = fetch_snapshots_agg()
            settings  = fetch_settings()
            df_txn    = fetch_transactions()
            df_assets = fetch_assets()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    if df_snap.empty:
        st.warning("Aucun snapshot disponible.")
        return

    risk_free_rate = float(settings.get("livret_a_rate") or 0.03)

    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période d'analyse",
            options=PERIODE_OPTIONS,
            index=PERIODE_OPTIONS.index(PERIODE_DEFAULT),
        )

    df_filtered        = filter_by_period(df_snap, periode)
    _perf_idx_full     = _build_perf_index(df_snap)     if len(df_snap)     >= 2 else pd.Series(dtype=float)
    _perf_idx_filtered = _build_perf_index(df_filtered) if len(df_filtered) >= 2 else pd.Series(dtype=float)

    st.divider()
    _an_render_annual_performance(df_snap, _perf_idx_full)
    st.divider()
    _an_render_risk_metrics(df_filtered, risk_free_rate, _perf_idx_filtered)
    st.divider()
    _an_render_comparisons(df_filtered, df_assets, risk_free_rate, _perf_idx_filtered)
    st.divider()
    _an_render_dca(df_snap, settings)
    st.divider()
    _an_render_dividends(df_txn, df_assets, df_snap)

    st.divider()
    if len(df_filtered) >= 2:
        st.caption(
            f"Analyse sur {len(df_filtered)} jours · "
            f"du {df_filtered.iloc[0]['date'].strftime('%d/%m/%Y')} "
            f"au {df_filtered.iloc[-1]['date'].strftime('%d/%m/%Y')}"
        )


def _pc_render_kpis(
    df_snap_one: pd.DataFrame,
    acc_type: str,
    div_acc: dict,
) -> float:
    """KPIs + barre plafond PEA. Retourne total_value pour les onglets."""
    latest           = df_snap_one.iloc[-1]
    total_value      = float(latest["total_value"])
    invested_capital = float(latest["invested_capital"])
    plus_value       = total_value - invested_capital
    perf_pct         = (plus_value / invested_capital * 100) if invested_capital > 0 else 0.0

    total_div        = div_acc["total"] if not div_acc.get("empty") else 0.0
    total_return     = plus_value + total_div
    total_return_pct = (total_return / invested_capital * 100) if invested_capital > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)
    display_kpi_block(col1, "Valeur totale",   fmt_eur(total_value))
    display_kpi_block(col2, "Capital investi", fmt_eur(invested_capital))

    pv_subline = (
        f"Total return (÷ dividendes) : {fmt_eur(total_return)} · {total_return_pct:+.2f} %"
        if total_div > 0 else None
    )
    display_kpi_block(col3, "Plus-value latente", fmt_eur(plus_value),
                      perf_pct, is_percent=True, subline=pv_subline)

    cagr_acc = compute_cagr(df_snap_one)
    display_kpi_block(col4, "CAGR (depuis le début)",
                      fmt_pct(cagr_acc) if cagr_acc is not None else "—")

    if acc_type == "PEA" and invested_capital > 0:
        pea_pct = min(invested_capital / PEA_PLAFOND * 100, 100.0)
        color   = "🟢" if pea_pct < 75 else ("🟡" if pea_pct < 95 else "🔴")
        st.progress(
            pea_pct / 100,
            text=(
                f"{color} Plafond PEA : {fmt_eur(invested_capital)} versés "
                f"/ {fmt_eur(PEA_PLAFOND)} ({pea_pct:.1f} %)"
            ),
        )

    return total_value


def _pc_render_evolution(df_snap_one: pd.DataFrame) -> None:
    """Sélecteur de période + graphique d'évolution valeur/capital."""
    st.subheader("📈 Évolution")

    col_period, _ = st.columns([2, 5])
    with col_period:
        periode = st.selectbox(
            "Période",
            options=PERIODE_OPTIONS,
            index=PERIODE_OPTIONS.index(PERIODE_DEFAULT),
            label_visibility="collapsed",
            key="compte_periode",
        )

    df_filtered = filter_by_period(df_snap_one, periode)

    if len(df_filtered) >= 2:
        idx         = _build_perf_index(df_filtered)
        perf_period = (idx.iloc[-1] - 1) * 100
        col_p1, col_p2, _ = st.columns([1, 1, 4])
        display_kpi_block(col_p1, f"Perf ({periode})", fmt_pct(perf_period))
        display_kpi_block(col_p2, "Nb snapshots", str(len(df_filtered)))

    st.plotly_chart(compute_perf_chart(df_filtered), use_container_width=True)


def _pc_render_details(
    df_txn_acc: pd.DataFrame,
    df_assets: pd.DataFrame,
    div_acc: dict,
    total_value: float,
) -> None:
    """Onglets Positions / Allocation / Dividendes. compute_positions_with_pru appelé une fois."""
    st.subheader("📋 Détails")
    tab_pos, tab_alloc, tab_div = st.tabs(["📋 Positions", "📊 Allocation", "💰 Dividendes"])

    df_pos     = compute_positions_with_pru(df_txn_acc, df_assets)
    by_ttm_acc = div_acc.get("by_asset_ttm", {}) if not div_acc.get("empty") else {}

    with tab_pos:
        render_positions_table(df_pos, by_asset_ttm=by_ttm_acc, label_capital="Capital investi")

    with tab_alloc:
        if not df_pos.empty:
            col_a, col_b = st.columns(2)
            render_allocation_charts(df_pos, col_a, col_b)
        else:
            st.info("Aucune position détectée.")

    with tab_div:
        if div_acc.get("empty"):
            st.info("Aucun dividende enregistré pour ce compte.")
        else:
            yield_acc = div_acc["ttm"] / total_value * 100 if total_value > 0 else 0.0
            c1, c2, c3, c4 = st.columns(4)
            display_kpi_block(c1, "Total reçu",           fmt_eur(div_acc["total"]))
            display_kpi_block(c2, "Reçu cette année",     fmt_eur(div_acc["ytd"]))
            display_kpi_block(c3, "Rendement TTM",        f"{yield_acc:.2f} %")
            display_kpi_block(c4, "Nombre de versements", str(div_acc["nb"]))

            col_l, col_r = st.columns(2)
            with col_l:
                st.caption("Par source")
                st.plotly_chart(div_acc["fig_asset"], use_container_width=True)
            with col_r:
                st.caption("Par année")
                st.plotly_chart(div_acc["fig_year"],  use_container_width=True)


def page_compte():
    st.title("🏦 Vue par compte")
    _set_page_title("Vue par compte")

    try:
        with st.spinner("Chargement des données..."):
            df_accounts = fetch_accounts()
            df_txn      = fetch_transactions()
            df_assets   = fetch_assets()
            df_snap_acc = fetch_snapshots_by_account()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    if df_accounts.empty:
        st.warning("Aucun compte actif.")
        return

    account_id = st.selectbox(
        "Compte",
        options=df_accounts["id"].tolist(),
        format_func=lambda x: df_accounts.set_index("id").loc[x, "name"],
        label_visibility="collapsed",
    )
    acc_row  = df_accounts.set_index("id").loc[account_id]
    acc_name = acc_row["name"]
    acc_type = acc_row["type"].upper()

    st.caption(f"Enveloppe : **{acc_type}**")

    df_txn_acc  = df_txn[df_txn["account_id"] == account_id]
    df_snap_one = (
        df_snap_acc[df_snap_acc["account_name"] == acc_name]
        .sort_values("date")
        .reset_index(drop=True)
    )

    if df_snap_one.empty:
        st.info("Aucun snapshot pour ce compte — relance un snapshot pour commencer.")
        return

    div_acc     = compute_dividends(df_txn_acc, df_assets)
    total_value = _pc_render_kpis(df_snap_one, acc_type, div_acc)
    st.divider()
    _pc_render_evolution(df_snap_one)
    st.divider()
    _pc_render_details(df_txn_acc, df_assets, div_acc, total_value)

    st.caption(
        f"Dernière donnée : {df_snap_one.iloc[-1]['date'].strftime('%d/%m/%Y')} "
        f"· {len(df_snap_one)} snapshot(s)"
    )


def _rq_render_overview(
    df_positions: pd.DataFrame,
    dca_amount: float,
    capital_pea: float,
) -> None:
    """Graphiques d'allocation + métriques + barre plafond PEA."""
    st.subheader("📊 Répartition du portefeuille")
    total_pea = df_positions["value"].sum()

    col1, col2 = st.columns(2)
    render_allocation_charts(df_positions, col1, col2)

    col_a, col_b = st.columns(2)
    col_a.metric("Valeur totale PEA", fmt_eur(total_pea))
    col_b.metric("DCA mensuel (settings)", fmt_eur(dca_amount))

    if capital_pea > 0:
        pea_pct = min(capital_pea / PEA_PLAFOND * 100, 100.0)
        color   = "🟢" if pea_pct < 75 else ("🟡" if pea_pct < 95 else "🔴")
        st.progress(
            pea_pct / 100,
            text=(
                f"{color} Plafond PEA : {fmt_eur(capital_pea)} investi "
                f"/ {fmt_eur(PEA_PLAFOND)} ({pea_pct:.1f} %)"
            ),
        )


def _rq_render_targets(
    df_positions: pd.DataFrame,
    settings: dict,
    total_pea: float,
) -> tuple[dict, float]:
    """Formulaire des allocations cibles + bouton sauvegarde. Retourne (targets, total_cible)."""
    st.subheader("🎯 Allocations cibles")
    st.caption("Renseigne le pourcentage cible pour chaque ligne. Le total doit faire 100 %.")

    saved_raw = settings.get("pea_targets") or "{}"
    try:
        saved_targets = json.loads(saved_raw)
    except (json.JSONDecodeError, TypeError):
        saved_targets = {}

    targets     = {}
    total_cible = 0.0

    for _, row in df_positions.iterrows():
        aid          = str(int(row["asset_id"]))
        poids_actuel = row["value"] / total_pea * 100
        default_cible = float(saved_targets.get(aid, round(poids_actuel)))

        col_name, col_actuel, col_cible = st.columns([3, 1, 1])
        col_name.markdown(f"**{row['name']}**")
        col_actuel.metric("Actuel", f"{poids_actuel:.1f} %")

        cible = col_cible.number_input(
            "Cible %",
            min_value=0.0,
            max_value=100.0,
            value=default_cible,
            step=1.0,
            key=f"target_{aid}",
            label_visibility="collapsed",
        )
        targets[aid] = cible
        total_cible += cible

    col_total, col_save = st.columns([3, 2])
    with col_total:
        if abs(total_cible - 100) < 0.1:
            st.success(f"✅ Total : {total_cible:.1f} % — prêt à calculer")
        else:
            st.error(f"❌ Total : {total_cible:.1f} % — doit être égal à 100 %")

    with col_save:
        if st.button("💾 Enregistrer les cibles", use_container_width=True,
                     help="Sauvegarde en base — persistant entre les sessions"):
            try:
                supabase.table("settings").upsert({
                    "id":          1,
                    "pea_targets": json.dumps(targets),
                    "updated_at":  pd.Timestamp.now(tz="UTC").isoformat(),
                }).execute()
                fetch_settings.clear()
                st.success("✅ Allocations cibles enregistrées.")
            except Exception as e:
                st.error(f"❌ Erreur lors de la sauvegarde : {e}")

    return targets, total_cible


def _rq_render_orders(
    df_positions: pd.DataFrame,
    targets: dict,
    dca_amount: float,
) -> None:
    """Tableau de situation, warnings et récap des ordres."""
    df_summary, orders, warnings_list = compute_rebalancing_orders(
        df_positions, targets, dca_amount
    )

    st.subheader("📊 Situation actuelle vs cible")

    def color_ecart(val):
        if val > 0.5:
            return "color: #2ECC71"
        elif val < -0.5:
            return "color: #E84C4C"
        return "color: #888888"

    df_display = df_summary[["name", "value", "poids_pct", "cible_pct", "ecart_pct"]].copy()
    df_display.columns = ["Asset", "Valeur (€)", "Actuel %", "Cible %", "Écart %"]
    df_display["Valeur (€)"] = df_display["Valeur (€)"].map(fmt_eur)

    st.dataframe(
        df_display.style.map(color_ecart, subset=["Écart %"]),
        use_container_width=True,
        hide_index=True,
    )

    for w in warnings_list:
        if w.startswith("✅"):
            st.success(w)
        elif w.startswith("⚠️"):
            st.warning(w)
        elif w.startswith("ℹ️"):
            st.info(w)

    if not orders:
        return

    st.subheader("🛒 Ordres à passer sur Trade Republic")
    st.markdown("### 👉 Ce mois-ci, saisis :")

    cols = st.columns(len(orders))
    for i, order in enumerate(orders):
        cols[i].metric(
            order["name"],
            f"{order['a_saisir']} €",
            f"{order['nb_titres']} titre(s) × {order['prix']:.2f} €",
            delta_color="off",
        )

    with st.expander("📋 Détail des ordres"):
        df_orders = pd.DataFrame(orders)[["name", "nb_titres", "prix", "montant_reel", "a_saisir"]]
        df_orders.columns = ["Asset", "Titres", "Prix unitaire", "Montant réel", "À saisir (TR)"]
        df_orders["Prix unitaire"] = df_orders["Prix unitaire"].map(lambda x: f"{x:.2f} €")
        df_orders["Montant réel"]  = df_orders["Montant réel"].map(
            lambda x: f"{x:,.2f} €".replace(",", " ")
        )
        df_orders["À saisir (TR)"] = df_orders["À saisir (TR)"].map(lambda x: f"{x} €")
        st.dataframe(df_orders, use_container_width=True, hide_index=True)

    total_reel   = sum(o["montant_reel"] for o in orders)
    total_saisir = sum(o["a_saisir"] for o in orders)

    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric("DCA disponible", fmt_eur(dca_amount))
    col2.metric("Total réellement investi", f"{total_reel:,.2f} €".replace(",", " "))
    col3.metric(
        "Total à saisir sur TR",
        f"{total_saisir} €",
        f"Marge : +{total_saisir - total_reel:.2f} €",
        delta_color="off",
    )


def page_reequilibrage():
    st.title("⚖️ Rééquilibrage PEA")
    _set_page_title("Rééquilibrage PEA")

    try:
        settings    = fetch_settings()
        df_accounts = fetch_accounts()
        df_assets   = fetch_assets()
        df_txn      = fetch_transactions()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    dca_amount   = float(settings.get("monthly_dca") or 0)
    pea_accounts = df_accounts[df_accounts["type"] == "PEA"]

    if pea_accounts.empty:
        st.warning("Aucun compte de type PEA trouvé dans la base.")
        return

    pea_id       = int(pea_accounts.iloc[0]["id"])
    df_positions = compute_pea_positions(df_txn, df_assets, pea_id)

    if df_positions.empty:
        st.warning("Aucune position trouvée sur le PEA. Vérifie tes transactions.")
        return

    if dca_amount == 0:
        st.info("Définis ton DCA mensuel dans **Saisie manuelle** pour utiliser cette page.")
        return

    df_pru      = compute_positions_with_pru(
        df_txn[df_txn["account_id"] == pea_id].reset_index(drop=True), df_assets
    )
    capital_pea = df_pru["invested"].sum() if not df_pru.empty else 0.0
    total_pea   = df_positions["value"].sum()

    st.divider()
    _rq_render_overview(df_positions, dca_amount, capital_pea)
    st.divider()
    targets, total_cible = _rq_render_targets(df_positions, settings, total_pea)
    st.divider()
    if abs(total_cible - 100) < 0.1:
        _rq_render_orders(df_positions, targets, dca_amount)


def page_synthese_mensuelle():
    st.title("📅 Synthèse mensuelle")
    _set_page_title("Synthèse mensuelle")

    try:
        with st.spinner("Chargement des données..."):
            df_snap   = fetch_snapshots_agg()
            df_txn    = fetch_transactions()
            df_assets = fetch_assets()
            settings  = fetch_settings()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    if df_snap.empty:
        st.info("Aucune donnée disponible — enregistre au moins un snapshot pour commencer.")
        return

    MOIS_FR = {
        1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
        5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
        9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
    }

    today      = pd.Timestamp.today().normalize()
    first_snap = df_snap["date"].min().replace(day=1)
    months     = [
        (today - pd.DateOffset(months=i)).replace(day=1)
        for i in range(12)
        if (today - pd.DateOffset(months=i)).replace(day=1) >= first_snap
    ]

    if not months:
        st.info("Pas encore assez de données pour afficher une synthèse mensuelle.")
        return

    col_sel, _ = st.columns([2, 5])
    with col_sel:
        selected = st.selectbox(
            "Mois",
            options=months,
            format_func=lambda m: f"{MOIS_FR[m.month]} {m.year}",
            label_visibility="collapsed",
        )

    month_start = pd.Timestamp(selected)
    month_end   = (month_start + pd.DateOffset(months=1)) - pd.Timedelta(days=1)

    df_before = df_snap[df_snap["date"] < month_start].sort_values("date")
    df_during = df_snap[
        (df_snap["date"] >= month_start) & (df_snap["date"] <= month_end)
    ].sort_values("date")

    if df_during.empty:
        st.warning("Aucun snapshot enregistré pour ce mois.")
        return

    val_start = float(df_before.iloc[-1]["total_value"]) if not df_before.empty else None
    val_end   = float(df_during.iloc[-1]["total_value"])
    nb_snaps  = len(df_during)
    last_date = df_during.iloc[-1]["date"].strftime("%d/%m/%Y")

    # ── Évolution du portefeuille ──────────────────────────────
    st.divider()
    st.subheader("📈 Évolution du portefeuille")

    variation_eur = (val_end - val_start) if val_start is not None else None
    variation_pct = (variation_eur / val_start * 100) if val_start else None

    col1, col2, col3, col4 = st.columns(4)
    display_kpi_block(col1, "Valeur début de mois", fmt_eur(val_start) if val_start else "—")
    display_kpi_block(col2, "Valeur fin de mois",   fmt_eur(val_end))
    display_kpi_block(
        col3, "Variation €",
        fmt_eur(variation_eur) if variation_eur is not None else "—",
        delta=variation_eur, is_percent=False,
    )
    display_kpi_block(
        col4, "Performance",
        fmt_pct(variation_pct) if variation_pct is not None else "—",
        delta=variation_pct, is_percent=True,
    )

    # ── Transactions du mois ──────────────────────────────────
    st.divider()
    st.subheader("📋 Transactions du mois")

    TYPE_LABELS = {"buy": "Achat", "sell": "Vente", "dividend": "Dividende", "fee": "Frais"}
    asset_map   = df_assets.set_index("id")["name"].to_dict()

    df_txn_month = df_txn[
        (df_txn["date"] >= month_start) & (df_txn["date"] <= month_end)
    ].copy()

    if df_txn_month.empty:
        st.info("Aucune transaction enregistrée ce mois.")
    else:
        df_txn_month["asset_name"] = df_txn_month["asset_id"].map(asset_map).fillna("—")
        df_txn_month["type_label"] = df_txn_month["type"].map(TYPE_LABELS).fillna(df_txn_month["type"])

        df_display = df_txn_month[["date", "type_label", "asset_name", "total_amount"]].copy()
        df_display = df_display.sort_values("date")
        df_display["date"]         = df_display["date"].dt.strftime("%d/%m/%Y")
        df_display["total_amount"] = df_display["total_amount"].map(fmt_eur)
        df_display.columns         = ["Date", "Type", "Asset", "Montant"]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

    # Barre DCA
    dca_target    = float(settings.get("monthly_dca") or 0)
    invested_month = abs(
        df_txn[
            (df_txn["date"] >= month_start) & (df_txn["date"] <= month_end) &
            (df_txn["type"] == "buy")
        ]["total_amount"].sum()
    )
    if dca_target > 0:
        dca_pct = min(invested_month / dca_target, 1.0)
        color   = "🟢" if dca_pct >= 0.95 else ("🟡" if dca_pct >= 0.5 else "🔴")
        st.progress(
            dca_pct,
            text=(
                f"{color} DCA : {fmt_eur(invested_month)} investis "
                f"/ objectif {fmt_eur(dca_target)} ({dca_pct * 100:.0f} %)"
            ),
        )

    # ── Dividendes du mois ────────────────────────────────────
    st.divider()
    st.subheader("💰 Dividendes reçus")

    df_div_month = df_txn[
        (df_txn["date"] >= month_start) & (df_txn["date"] <= month_end) &
        (df_txn["type"] == "dividend")
    ].copy()

    if df_div_month.empty:
        st.info("Aucun dividende reçu ce mois.")
    else:
        df_div_month["asset_name"] = df_div_month["asset_id"].map(asset_map).fillna("—")
        total_div = float(df_div_month["total_amount"].sum())

        col_d1, col_d2, _ = st.columns([1, 1, 3])
        display_kpi_block(col_d1, "Total dividendes", fmt_eur(total_div))
        display_kpi_block(col_d2, "Versements",        str(len(df_div_month)))

        by_asset = (
            df_div_month.groupby("asset_name")["total_amount"]
            .sum()
            .reset_index()
            .sort_values("total_amount", ascending=False)
        )
        by_asset["total_amount"] = by_asset["total_amount"].map(fmt_eur)
        by_asset.columns = ["Asset", "Montant"]
        st.dataframe(by_asset, use_container_width=True, hide_index=True)

    # ── Analyse IA ────────────────────────────────────────────
    st.divider()
    st.subheader("🤖 Analyse IA")

    gemini_key = settings.get("gemini_api_key") or ""

    if not gemini_key:
        st.info(
            "Configure ta clé API Gemini dans **Saisie manuelle → Paramètres** "
            "pour activer l'analyse mensuelle IA. C'est gratuit sur "
            "[aistudio.google.com](https://aistudio.google.com).",
            icon="🔑",
        )
    else:
        cache_key = f"gemini_{selected.strftime('%Y-%m')}"

        if cache_key not in st.session_state:
            st.session_state[cache_key] = None

        if st.session_state[cache_key]:
            st.markdown(st.session_state[cache_key])
            if st.button("🔄 Régénérer l'analyse", key="regen_gemini"):
                st.session_state[cache_key] = None
                st.rerun()
        else:
            if st.button("✨ Générer l'analyse IA", key="gen_gemini", type="primary"):
                mois_label     = f"{MOIS_FR[selected.month]} {selected.year}"
                fire_target_val = float(settings.get("fire_target_amount") or 0)
                dca_target_val  = float(settings.get("monthly_dca") or 0)

                # Actifs détenus (ayant au moins un achat)
                buy_asset_ids = df_txn[df_txn["type"] == "buy"]["asset_id"].dropna().astype(int).unique()
                assets_held   = df_assets[df_assets["id"].isin(buy_asset_ids)][["name", "asset_class", "geography"]].drop_duplicates()
                assets_lines  = "\n".join(
                    f"  - {r['name']} ({r['asset_class']}"
                    + (f", {r['geography']}" if r.get("geography") else "") + ")"
                    for _, r in assets_held.iterrows()
                ) or "  (aucun actif détecté)"

                # Opérations du mois (achats / ventes)
                ops_month = df_txn_month[df_txn_month["type"].isin(["buy", "sell"])].copy()
                if not ops_month.empty:
                    ops_month["asset_name"] = ops_month["asset_id"].map(asset_map).fillna("—")
                    ops_month["label"]      = ops_month["type"].map({"buy": "Achat", "sell": "Vente"})
                    ops_lines = "\n".join(
                        f"  - {r['label']} {r['asset_name']} : {fmt_eur(abs(r['total_amount']))}"
                        for _, r in ops_month.iterrows()
                    )
                else:
                    ops_lines = "  Aucune opération ce mois"

                # DCA
                dca_context = (
                    f"{fmt_eur(invested_month)} investis / objectif {fmt_eur(dca_target_val)} "
                    f"({invested_month / dca_target_val * 100:.0f} %)"
                    if dca_target_val > 0 else "Non configuré"
                )

                # Dividendes
                div_context = (
                    f"{fmt_eur(float(df_div_month['total_amount'].sum()))} "
                    f"({len(df_div_month)} versement(s))"
                    if not df_div_month.empty else "Aucun"
                )

                # FIRE
                fire_line = ""
                if fire_target_val > 0 and val_end:
                    fire_pct  = val_end / fire_target_val * 100
                    fire_line = f"\n- Progression FIRE : {fire_pct:.1f} % de l'objectif {fmt_eur(fire_target_val)}"

                prompt = f"""Tu es un analyste financier personnel pour un investisseur français en stratégie FIRE.

DONNÉES DU PORTEFEUILLE — {mois_label}

Performance :
- Valeur début : {fmt_eur(val_start) if val_start else 'inconnue'} → fin : {fmt_eur(val_end)}
- Variation : {fmt_eur(variation_eur) if variation_eur is not None else '—'} ({f'{variation_pct:+.2f} %' if variation_pct is not None else '—'})

Portefeuille détenu :
{assets_lines}

Opérations du mois :
{ops_lines}

Épargne & DCA : {dca_context}
Dividendes reçus : {div_context}{fire_line}

---
Rédige une analyse en 2-3 paragraphes courts et percutants.
- Utilise ta connaissance des marchés pour expliquer les performances de ces actifs spécifiques sur ce mois (contexte macro, secteurs, zones géographiques).
- Commente la discipline d'épargne et la trajectoire FIRE si disponible.
- Sois direct et factuel, pas de généralités creuses. Pas de bullet points.
- Commence immédiatement par l'analyse, sans salutation."""

                with st.spinner("Analyse en cours..."):
                    try:
                        result = _call_gemini(gemini_key, prompt)
                        st.session_state[cache_key] = result
                        st.rerun()
                    except requests.exceptions.HTTPError as e:
                        code = e.response.status_code
                        if code == 400:
                            st.error("❌ Clé API invalide — vérifie ta clé dans les paramètres.")
                        elif code == 429:
                            st.warning("⏳ Quota Gemini atteint — attends 1 minute et réessaie. (Free tier : 15 requêtes/min)")
                        else:
                            st.error(f"❌ Erreur API Gemini ({code}) — réessaie dans quelques instants.")
                    except requests.exceptions.Timeout:
                        st.error("❌ Timeout — Gemini n'a pas répondu à temps. Réessaie.")
                    except Exception as e:
                        st.error(f"❌ Erreur inattendue : {e}")

    st.caption(f"Données au {last_date} · {nb_snaps} snapshot(s) ce mois")


def page_saisie():
    st.title("✍️ Saisie manuelle")
    _set_page_title("Saisie manuelle")

    try:
        settings    = fetch_settings()
        df_accounts = fetch_accounts()
        df_assets   = fetch_assets()
        df_txn      = fetch_transactions()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    try:
        _nb_days, _is_stale = check_data_freshness(fetch_snapshots_agg())
        if _is_stale:
            st.warning(
                f"⚠️ Dernier snapshot vieux de **{_nb_days} jours ouvrés** — "
                "pensez à enregistrer un snapshot après avoir saisi vos transactions."
            )
    except RuntimeError:
        pass

    tab_settings, tab_prix, tab_transaction, tab_import = st.tabs([
        "⚙️ Paramètres",
        "💲 Prix manuels",
        "➕ Nouvelle transaction",
        "📥 Import TR",
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

        st.divider()
        st.subheader("🤖 Clé API Gemini (Analyse IA)")
        st.caption(
            "Clé Google AI Studio pour l'analyse mensuelle IA. "
            "Gratuit sur [aistudio.google.com](https://aistudio.google.com)."
        )

        gemini_key_saved = settings.get("gemini_api_key") or ""
        col_key, col_btn = st.columns([4, 1])
        with col_key:
            new_gemini_key = st.text_input(
                "Clé API Gemini",
                value="",
                type="password",
                placeholder="AIzaSy...",
                label_visibility="collapsed",
            )
        with col_btn:
            if st.button("💾 Enregistrer", key="save_gemini_key", use_container_width=True):
                if new_gemini_key.strip():
                    try:
                        supabase.table("settings").upsert({
                            "id":         1,
                            "gemini_api_key": new_gemini_key.strip(),
                            "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        }).execute()
                        fetch_settings.clear()
                        st.success("✅ Clé enregistrée.")
                    except Exception as e:
                        st.error(f"❌ Erreur : {e}")
                else:
                    st.warning("Saisis une clé avant d'enregistrer.")

        if gemini_key_saved:
            st.caption(f"✅ Clé configurée — se termine par `...{gemini_key_saved[-4:]}`")
        else:
            st.caption("❌ Aucune clé configurée — l'analyse IA dans la Synthèse mensuelle est désactivée.")

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
                    options=["buy", "sell", "dividend", "fee"],
                    format_func=lambda x: {
                        "buy":      "🟢 Achat",
                        "sell":     "🔴 Vente",
                        "dividend": "🎁 Dividende",
                        "fee":      "💸 Frais",
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

            # ── Validation ────────────────────────────────────────
            errors = []

            # Asset requis pour buy / sell
            if is_trade and asset is None:
                errors.append("Un asset est requis pour un achat ou une vente.")

            if is_trade and unit_price == 0:
                errors.append("Le prix unitaire ne peut pas être 0 pour un achat/vente.")
            if is_trade and quantity == 0:
                errors.append("La quantité ne peut pas être 0 pour un achat/vente.")
            if not is_trade and manual_amount == 0:
                errors.append("Le montant ne peut pas être 0.")

            # Sell : vérifier la position ouverte sur ce compte
            if type_txn == "sell" and asset is not None and quantity > 0:
                trades_acc = df_txn[
                    (df_txn["account_id"] == account) &
                    (df_txn["asset_id"]   == asset) &
                    (df_txn["type"].isin(["buy", "sell"]))
                ].copy()

                if trades_acc.empty:
                    errors.append(
                        "Vous ne détenez pas cet actif sur ce compte — "
                        "aucune transaction d'achat trouvée."
                    )
                else:
                    signed = trades_acc["quantity"].fillna(0).astype(float)
                    signed = signed.where(trades_acc["type"] == "buy", -signed)
                    qty_held = round(signed.sum(), 8)

                    if qty_held <= 0:
                        errors.append(
                            f"Position nulle sur ce compte pour cet actif "
                            f"(solde calculé : {qty_held:.4f} titres)."
                        )
                    elif quantity > qty_held:
                        errors.append(
                            f"Quantité insuffisante — vous détenez {qty_held:.4f} titre(s), "
                            f"vous essayez d'en vendre {quantity:.4f}."
                        )

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

    # ══════════════════════════════════════════════════════════
    # ONGLET 4 — IMPORT TRADE REPUBLIC CSV
    # ══════════════════════════════════════════════════════════
    with tab_import:
        st.subheader("📥 Import CSV Trade Republic")
        st.caption(
            "Importe les achats depuis l'export CSV de Trade Republic. "
            "Seules les lignes `category=TRADING / type=BUY` sont traitées — "
            "les virements, intérêts et paiements carte sont ignorés."
        )

        uploaded = st.file_uploader(
            "Fichier CSV Trade Republic",
            type=["csv"],
            key="tr_csv_upload",
            label_visibility="collapsed",
        )

        if uploaded is not None:
            try:
                df_csv = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
            except Exception as e:
                st.error(f"❌ Impossible de lire le fichier : {e}")
                df_csv = pd.DataFrame()

            if not df_csv.empty:
                # Filter only BUY trading rows
                mask = (
                    df_csv.get("category", pd.Series(dtype=str)).str.upper() == "TRADING"
                ) & (
                    df_csv.get("type", pd.Series(dtype=str)).str.upper() == "BUY"
                )
                df_buys = df_csv[mask].copy()

                if df_buys.empty:
                    st.info("Aucune ligne d'achat (TRADING/BUY) trouvée dans ce fichier.")
                else:
                    # Build ISIN → asset_id lookup
                    isin_to_asset = {}
                    if not df_assets.empty and "isin" in df_assets.columns:
                        for _, arow in df_assets.iterrows():
                            if arow.get("isin"):
                                isin_to_asset[arow["isin"].strip()] = {
                                    "id":   int(arow["id"]),
                                    "name": arow["name"],
                                }

                    # Account mapping selectors
                    tr_account_types = df_buys["account_type"].dropna().str.upper().unique().tolist()
                    acc_options      = df_accounts["id"].tolist() if not df_accounts.empty else []
                    acc_labels       = {row["id"]: row["name"] for _, row in df_accounts.iterrows()} if not df_accounts.empty else {}

                    st.markdown("**Correspondance des comptes TR → BeyondGrid**")
                    mapping_cols = st.columns(len(tr_account_types)) if tr_account_types else []
                    acc_type_map: dict[str, int] = {}

                    # Default guesses: PEA → first PEA account, DEFAULT → first non-PEA account
                    def _guess_account(tr_type: str) -> int | None:
                        for _, arow in df_accounts.iterrows():
                            atype = (arow.get("type") or "").upper()
                            if tr_type == "PEA" and atype == "PEA":
                                return int(arow["id"])
                            if tr_type == "DEFAULT" and atype not in ("PEA",):
                                return int(arow["id"])
                        return acc_options[0] if acc_options else None

                    for col, tr_type in zip(mapping_cols, tr_account_types):
                        guess = _guess_account(tr_type)
                        default_idx = acc_options.index(guess) if guess in acc_options else 0
                        chosen = col.selectbox(
                            f"TR **{tr_type}** →",
                            options=acc_options,
                            index=default_idx,
                            format_func=lambda x: acc_labels.get(x, str(x)),
                            key=f"tr_acc_map_{tr_type}",
                        )
                        acc_type_map[tr_type] = chosen

                    # Build existing transactions key set for duplicate detection
                    # Key: YYYY-MM-DD_asset_id — le montant n'est pas fiable si
                    # la transaction a été saisie manuellement avec une quantité arrondie.
                    existing_keys: set[str] = set()
                    if not df_txn.empty:
                        for _, txrow in df_txn.iterrows():
                            if txrow.get("asset_id") is not None and not pd.isna(txrow.get("asset_id")):
                                date_part = pd.to_datetime(txrow["date"]).strftime("%Y-%m-%d")
                                key = f"{date_part}_{int(txrow['asset_id'])}"
                                existing_keys.add(key)

                    # Parse each BUY row
                    rows_preview = []
                    for _, r in df_buys.iterrows():
                        isin       = (r.get("symbol") or "").strip()
                        acc_type   = (r.get("account_type") or "DEFAULT").upper()
                        date_str   = (r.get("date") or "").strip()
                        shares_str = (r.get("shares") or "0").strip()
                        price_str  = (r.get("price") or "0").strip()
                        amount_str = (r.get("amount") or "0").strip()
                        fee_str    = (r.get("fee") or "0").strip()
                        tr_id      = (r.get("transaction_id") or "").strip()
                        name_tr    = (r.get("name") or "").strip()

                        asset_info = isin_to_asset.get(isin)
                        account_id = acc_type_map.get(acc_type)

                        try:
                            qty        = round(float(shares_str), 8)
                            unit_price = round(float(price_str), 6)
                            total_amt  = round(float(amount_str), 2)
                            fee_amt    = round(float(fee_str), 2) if fee_str else 0.0
                        except (ValueError, TypeError):
                            qty = unit_price = total_amt = fee_amt = 0.0

                        dup_key = f"{date_str}_{asset_info['id'] if asset_info else '?'}"
                        is_dup  = asset_info is not None and dup_key in existing_keys

                        status = (
                            "⚠️ ISIN inconnu"   if asset_info is None else
                            "⚠️ Compte inconnu" if account_id is None else
                            "🔁 Déjà importé"   if is_dup else
                            "✅ Prêt"
                        )

                        rows_preview.append({
                            "status":     status,
                            "date":       date_str,
                            "isin":       isin,
                            "asset":      asset_info["name"] if asset_info else name_tr or isin,
                            "compte":     acc_type,
                            "qté":        qty,
                            "prix (€)":   unit_price,
                            "montant (€)": total_amt,
                            "_asset_id":  asset_info["id"] if asset_info else None,
                            "_account_id": account_id,
                            "_fee":       fee_amt,
                            "_tr_id":     tr_id,
                            "_is_dup":    is_dup,
                            "_ready":     asset_info is not None and account_id is not None and not is_dup,
                        })

                    df_preview = pd.DataFrame(rows_preview)

                    # Summary counts
                    n_ready   = df_preview["_ready"].sum()
                    n_dup     = df_preview["_is_dup"].sum()
                    n_no_isin = (df_preview["status"] == "⚠️ ISIN inconnu").sum()
                    n_total   = len(df_preview)

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                    col_s1.metric("Total achats", n_total)
                    col_s2.metric("✅ Prêts", n_ready)
                    col_s3.metric("🔁 Déjà importés", int(n_dup))
                    col_s4.metric("⚠️ ISIN inconnus", int(n_no_isin))

                    st.divider()

                    # Preview table (display columns only)
                    display_cols = ["status", "date", "asset", "compte", "qté", "prix (€)", "montant (€)"]
                    st.dataframe(
                        df_preview[display_cols],
                        use_container_width=True,
                        hide_index=True,
                    )

                    # Unmatched ISINs expander
                    unmatched = df_preview[df_preview["status"] == "⚠️ ISIN inconnu"][["date", "isin", "asset", "compte"]].drop_duplicates()
                    if not unmatched.empty:
                        with st.expander(f"⚠️ {len(unmatched)} ISIN(s) non reconnu(s) — à créer manuellement dans Assets"):
                            st.dataframe(unmatched, use_container_width=True, hide_index=True)

                    # Import button
                    st.divider()
                    if n_ready == 0:
                        st.info("Aucune transaction à importer (tout est déjà importé ou les assets sont inconnus).")
                    else:
                        if st.button(
                            f"📥 Importer {n_ready} transaction(s)",
                            use_container_width=True,
                            type="primary",
                            key="tr_import_btn",
                        ):
                            rows_to_insert = df_preview[df_preview["_ready"] == True]
                            inserted = 0
                            errors_import = []
                            for _, imp in rows_to_insert.iterrows():
                                try:
                                    comment = f"TR:{imp['_tr_id']}" if imp["_tr_id"] else "Import TR"
                                    supabase.table("transactions").insert({
                                        "date":         imp["date"],
                                        "type":         "buy",
                                        "account_id":   int(imp["_account_id"]),
                                        "asset_id":     int(imp["_asset_id"]),
                                        "quantity":     float(imp["qté"]),
                                        "unit_price":   float(imp["prix (€)"]),
                                        "fees":         float(imp["_fee"]) if imp["_fee"] else 0.0,
                                        "total_amount": float(imp["montant (€)"]),
                                        "comment":      comment,
                                    }).execute()
                                    inserted += 1
                                except Exception as exc:
                                    errors_import.append(f"{imp['date']} {imp['asset']} : {exc}")

                            fetch_transactions.clear()
                            if inserted:
                                st.success(f"✅ {inserted} transaction(s) importée(s) avec succès.")
                            if errors_import:
                                for err in errors_import:
                                    st.error(f"❌ {err}")


def page_transactions():
    st.title("🧾 Historique des transactions")
    _set_page_title("Transactions")

    try:
        df_txn      = fetch_transactions()
        df_accounts = fetch_accounts()
        df_assets   = fetch_assets()
    except RuntimeError as e:
        st.error(f"❌ Base de données inaccessible — {e}")
        st.stop()

    if df_txn.empty:
        st.info("Aucune transaction enregistrée.")
        return

    # ── Résumé des flux ───────────────────────────────────────
    st.subheader("📊 Résumé des flux")

    total_invested   = abs(df_txn[df_txn["type"] == "buy"]["total_amount"].sum())
    total_sold       = df_txn[df_txn["type"] == "sell"]["total_amount"].sum()
    total_dividends  = df_txn[df_txn["type"] == "dividend"]["total_amount"].sum()
    total_fees       = abs(df_txn[df_txn["type"] == "fee"]["total_amount"].sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total investi (achats)",  fmt_eur(total_invested))
    col2.metric("Total cédé (ventes)",     fmt_eur(total_sold))
    col3.metric("Total dividendes",        fmt_eur(total_dividends))
    col4.metric("Total frais",             fmt_eur(total_fees))

    st.divider()

    # ── Filtres ───────────────────────────────────────────────
    st.subheader("Filtres")

    col1, col2, col3, col4 = st.columns(4)

    # Compte
    account_names = df_accounts["name"].dropna().tolist() if not df_accounts.empty else []
    
    account_filter = col1.selectbox(
        "Compte",
        options=["Tous"] + account_names,
    )

    # Type
    type_filter = col2.selectbox(
        "Type",
        options=["Tous"] + sorted(df_txn["type"].unique().tolist()),
    )

    # Asset
    asset_names_list = sorted(df_assets["name"].dropna().tolist()) if not df_assets.empty else []
    asset_filter = col3.selectbox(
        "Asset",
        options=["Tous"] + asset_names_list,
    )

    # Date range
    date_min = df_txn["date"].min().date()
    date_max = df_txn["date"].max().date()

    date_range = col4.date_input(
        "Période",
        value=(date_min, date_max),
    )

    # ── Filtrage ──────────────────────────────────────────────
    df_filtered = df_txn.copy()

    if account_filter != "Tous":
        match = df_accounts[df_accounts["name"] == account_filter]["id"]
        if match.empty:
            st.warning(f"Compte '{account_filter}' introuvable.")
            return
        account_id = match.iloc[0]
        df_filtered = df_filtered[df_filtered["account_id"] == account_id]

    if type_filter != "Tous":
        df_filtered = df_filtered[df_filtered["type"] == type_filter]

    if asset_filter != "Tous":
        asset_match = df_assets[df_assets["name"] == asset_filter]["id"]
        if not asset_match.empty:
            df_filtered = df_filtered[df_filtered["asset_id"] == asset_match.iloc[0]]

    if len(date_range) == 2:
        df_filtered = df_filtered[
            (df_filtered["date"] >= pd.to_datetime(date_range[0])) &
            (df_filtered["date"] <= pd.to_datetime(date_range[1]))
        ]

    # ── Mise en forme ─────────────────────────────────────────
    df_display = df_filtered.copy()

    df_display["date"] = df_display["date"].dt.strftime("%d/%m/%Y")
    df_display["total_amount"] = df_display["total_amount"].map(fmt_eur)

    # mapping comptes
    account_map = df_accounts.set_index("id")["name"].to_dict()
    df_display["account"] = df_display["account_id"].map(account_map)

     # mapping assets
    asset_map = df_assets.set_index("id")["name"].to_dict()
    df_display["asset"] = df_display["asset_id"].map(asset_map)

    df_display = df_display[[
        "date",
        "account",
        "type",
        "asset",
        "quantity",
        "unit_price",
        "fees",
        "total_amount",
        "comment",
    ]]

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    csv = df_filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Exporter en CSV",
        data=csv,
        file_name=f"transactions_{pd.Timestamp.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.divider()

    with st.expander("🗑️ Supprimer une transaction"):
        if df_filtered.empty:
            st.info("Aucune transaction dans la sélection actuelle.")
        else:
            txn_options = {}
            for _, row in df_filtered.iterrows():
                asset_name = asset_map.get(row.get("asset_id"), "—") if pd.notna(row.get("asset_id")) else "—"
                acct_name  = account_map.get(row.get("account_id"), "—")
                label = (
                    f"{row['date'].strftime('%d/%m/%Y')} | {row['type']} | "
                    f"{asset_name} | {fmt_eur(abs(float(row['total_amount'])))} | {acct_name}"
                )
                txn_options[label] = int(row["id"])

            selected_label = st.selectbox(
                "Choisir la transaction à supprimer",
                options=list(txn_options.keys()),
                key="delete_txn_select",
            )
            selected_id = txn_options[selected_label]

            if st.button("🗑️ Supprimer", type="secondary", key="delete_txn_btn"):
                st.session_state["delete_txn_confirm"] = selected_id

            if st.session_state.get("delete_txn_confirm") == selected_id:
                st.warning("⚠️ Cette suppression est **irréversible**. Confirmer ?")
                c1, c2 = st.columns(2)
                if c1.button("✅ Confirmer la suppression", type="primary", key="delete_confirm_yes"):
                    supabase.table("transactions").delete().eq("id", selected_id).execute()
                    fetch_transactions.clear()
                    st.session_state.pop("delete_txn_confirm", None)
                    st.success("Transaction supprimée.")
                    st.rerun()
                if c2.button("Annuler", key="delete_confirm_no"):
                    st.session_state.pop("delete_txn_confirm", None)
                    st.rerun()



# ============================================================
# 5. ROUTING
# ============================================================

st.sidebar.title("BeyondGrid 📈")
st.sidebar.caption("Suivi d'investissement")

# ── Bouton de rafraîchissement manuel ──────────────────────
if st.sidebar.button("🔄 Actualiser les données", use_container_width=True):
    # Invalidation chirurgicale : uniquement les tables Supabase.
    # fetch_benchmark_history (yfinance, TTL 1h) est intentionnellement conservé.
    fetch_snapshots_agg.clear()
    fetch_snapshots_by_account.clear()
    fetch_settings.clear()
    fetch_accounts.clear()
    fetch_assets.clear()
    fetch_transactions.clear()
    st.rerun()

st.sidebar.divider()

# ── Alerte fraîcheur des données (visible sur toutes les pages) ─
try:
    _df_snap_check = fetch_snapshots_agg()
    _nb_days, _is_stale = check_data_freshness(_df_snap_check)
    if _is_stale:
        st.sidebar.warning(
            f"⚠️ Snapshot : **{_nb_days}j ouvrés** sans mise à jour — "
            "vérifie GitHub Actions."
        )
    if len(_df_snap_check) >= 2:
        _, _max_dd = compute_drawdown(_df_snap_check)
        if _max_dd < -20:
            st.sidebar.error(f"📉 Drawdown sévère : **{_max_dd:.1f} %** depuis le plus haut")
except RuntimeError:
    st.sidebar.error("❌ Supabase inaccessible")

menu = st.sidebar.radio(
    "Navigation",
    options=[
        "Vue Globale",
        "Vue par compte",
        "Analyses & Graphiques",
        "Synthèse mensuelle",
        "Rééquilibrage PEA",
        "Saisie manuelle",
        "Transactions",
    ],
    format_func=lambda x: {
        "Vue Globale":           "🏠 Vue Globale",
        "Vue par compte":        "🏦 Vue par compte",
        "Analyses & Graphiques": "📊 Analyses",
        "Synthèse mensuelle":    "📅 Synthèse mensuelle",
        "Rééquilibrage PEA":     "⚖️ Rééquilibrage PEA",
        "Saisie manuelle":       "✍️ Saisie manuelle",
        "Transactions":          "🧾 Transactions",
    }[x],
)

if menu == "Vue Globale":
    page_vue_globale()
elif menu == "Vue par compte":
    page_compte()
elif menu == "Analyses & Graphiques":
    page_analyses()
elif menu == "Synthèse mensuelle":
    page_synthese_mensuelle()
elif menu == "Rééquilibrage PEA":
    page_reequilibrage()
elif menu == "Saisie manuelle":
    page_saisie()
elif menu == "Transactions":
    page_transactions()


# ── Version en bas de sidebar ──────────────────────────────
st.sidebar.divider()
with st.sidebar.expander(f"📋 v{APP_VERSION} — Patch notes"):
    for version, notes in PATCH_NOTES.items():
        st.markdown(f"**v{version}**")
        for note in notes:
            st.markdown(f"- {note}")
st.sidebar.caption(f"BeyondGrid v{APP_VERSION}")
