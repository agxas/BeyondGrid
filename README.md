# 📊 BeyondGrid — v5.6

> Dashboard de suivi de portefeuille financier multi-comptes, avec performances ajustées des apports, suivi FIRE et analyse IA mensuelle.

---

## 🚀 Vue d'ensemble

**BeyondGrid** est une application personnelle de suivi d'investissements, conçue pour être simple, fiable et évolutive.

- 📈 Suivi multi-comptes (PEA, CTO, AV, PER, crypto…)
- 📉 Performances **nettes des apports** (méthode TWR-like — un DCA ne gonfle pas artificiellement les chiffres)
- 🎯 Suivi de l'objectif FIRE avec règle des 4 %
- ⚖️ Rééquilibrage PEA assisté avec calcul des ordres Trade Republic
- 📅 Synthèse mensuelle avec analyse IA personnalisée (Gemini 2.5 Flash — gratuit)
- 🔄 Snapshots journaliers automatisés via GitHub Actions

**Stack :**

| Couche | Techno |
|---|---|
| Frontend | Streamlit |
| Base de données | Supabase (PostgreSQL) |
| Automatisation | GitHub Actions |
| Données de marché | yfinance |
| Analyse IA | Google Gemini 2.5 Flash (API gratuite) |

---

## 🧱 Architecture

```
BeyondGrid/
├── app.py                        # Dashboard Streamlit (fichier unique)
├── scripts/
│   └── snapshot.py               # Script de snapshot journalier
├── schema.sql                    # Définition de la base de données
├── schema_summary.md             # Documentation du schéma
├── requirements.txt
└── .github/
    └── workflows/
        └── daily_snapshot.yml    # Workflow GitHub Actions
```

---

## 🗄️ Base de données

Le projet repose sur une logique **transaction-driven + snapshots journaliers**.

### Tables

| Table | Rôle |
|---|---|
| `accounts` | Comptes d'investissement (PEA, CTO, AV…) |
| `assets` | Actifs financiers (ETF, actions, fonds, crypto…) |
| `transactions` | Source de vérité — buy, sell, dividend, fee |
| `snapshots` | Valeurs journalières par compte (total_value, invested_capital) |
| `settings` | Configuration globale (FIRE, DCA, rendement estimé, inflation, clé API Gemini) |

### Modèle de données clé

**`invested_capital`** = coûts d'achat cumulés − produits de vente  
→ représente le capital réellement sorti de poche, calculé depuis les transactions `buy`/`sell` uniquement.

**`total_value`** = valorisation au prix actuel des positions ouvertes  
→ pas de cash idle : tout versement est supposé immédiatement investi.

### Types de transactions

| Type | Description |
|---|---|
| `buy` | Achat d'un actif |
| `sell` | Vente d'un actif |
| `dividend` | Dividende reçu |
| `fee` | Frais de courtage / de gestion |

---

## ⚙️ Installation

```bash
git clone https://github.com/agxas/BeyondGrid.git
cd BeyondGrid
pip install -r requirements.txt
```

---

## 🔑 Configuration

Variables d'environnement requises (Streamlit secrets ou `.env`) :

```
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

---

## ▶️ Lancement

```bash
streamlit run app.py
```

---

## 🔄 Automatisation

`scripts/snapshot.py` tourne chaque soir de semaine via GitHub Actions :

1. Met à jour les prix via yfinance (assets avec `auto_price = TRUE`)
2. Calcule `total_value` et `invested_capital` pour chaque compte actif
3. Écrit le snapshot du jour dans la table `snapshots` (upsert)

Les assets avec `auto_price = FALSE` ont leur prix mis à jour manuellement depuis l'onglet **Saisie manuelle** du dashboard.

---

## 📊 Fonctionnalités

### 🏠 Vue Globale
- Situation du jour : valeur totale, capital investi, plus-value latente, variation journalière
- Performances récentes 1M / 3M / 1A / CAGR (nettes des apports)
- Évolution du patrimoine global et par compte (graphiques interactifs)
- Objectif FIRE : progression, date estimée, revenu passif (règle des 4 %), jours de liberté financière
- Positions ouvertes avec PRU, plus-value latente et rendement dividendes par ligne
- Répartition par classe d'actifs et géographie
- Alerte drawdown sévère (sidebar, visible sur toutes les pages)

### 📊 Analyses & Graphiques
- Performances par année calendaire (YTD inclus)
- Ratio de Sharpe et volatilité annualisée (ajustés des apports, taux sans risque = Livret A)
- Drawdown depuis le plus haut historique
- Comparaison portefeuille vs Livret A
- Comparaison portefeuille vs benchmark (MSCI World, S&P 500…)
- Projection DCA multi-scénarios (pessimiste / neutre / optimiste) avec valeur réelle (inflation déduite)
- Analyse des dividendes par asset et par année

### 📅 Synthèse mensuelle
- Sélecteur de mois (12 derniers mois disponibles)
- Évolution de la valeur : début/fin de mois, variation € et %
- Tableau des transactions du mois + barre de progression DCA vs objectif
- Dividendes reçus dans le mois (total + détail par asset)
- **Défis mensuels** : 4 défis auto-générés (compléter le DCA, ne pas vendre, recevoir un dividende, battre le Livret A) avec barre de progression
- **Analyse IA** : analyse personnalisée en français via Gemini 2.5 Flash (gratuit) — performance, discipline DCA, dividendes, trajectoire FIRE

### 🏦 Vue par compte
- KPIs par enveloppe : valeur, capital investi, plus-value, CAGR
- Barre de progression du plafond PEA (150 k€)
- Graphique d'évolution avec sélecteur de période
- Onglets : Positions / Allocation / Dividendes

### ⚖️ Rééquilibrage PEA
- Visualisation de l'allocation actuelle vs cible
- Formulaire de saisie des cibles (persisté en base)
- Calcul automatique des ordres à passer (algorithme greedy)
- Format adapté Trade Republic (arrondi au multiple de 5 €)

### 📰 Actualités
- Flux RSS des actifs en position ouverte — Yahoo Finance pour les actifs avec ticker, Google News en fallback
- Fil chronologique global (20 articles max) avec tag de l'actif, résumé et lien
- Vue par actif : accordéons dépliables, 5 articles max par position
- Résumé RSS affiché sous chaque titre (masqué automatiquement s'il est identique ou redondant avec le titre)
- Cache 30 min — bouton 🔄 Rafraîchir sur la page + invalidation depuis le bouton sidebar

### 🎮 Progression
- **Score de santé** : score sur 100 pts calculé sur 5 critères (Diversification, Régularité DCA, Performance CAGR, Risque maîtrisé, Trajectoire FIRE) — jauge Plotly + détail coloré par critère
- **Niveaux FIRE** : 6 paliers (Épargnant → FIRE atteint) avec barre de progression vers le prochain niveau
- **Streak DCA** : compteur de mois consécutifs à objectif atteint, record personnel, mini-calendrier visuel des 12 derniers mois
- **Heatmap GitHub-style** : 52 semaines de performance journalière (vert/rouge), survol pour le détail
- **25 badges** répartis en 6 catégories (Patrimoine, Dividendes, Discipline, Portefeuille, Ancienneté, FIRE) — verrouillés/déverrouillés dynamiquement, barre de complétion globale

### ✍️ Saisie manuelle
- Paramètres globaux : FIRE, DCA, rendement estimé, inflation, Livret A
- Clé API Gemini pour l'analyse IA mensuelle (champ sécurisé)
- Mise à jour des prix manuels avec liens vers les pages de cours
- Saisie de nouvelles transactions avec aperçu du montant en temps réel
- Import CSV Trade Republic : achats, ventes et dividendes — correspondance ISIN → asset, aperçu avant import, sélection ligne par ligne, détection des doublons

### 🧾 Transactions
- Historique filtrable par compte, type, asset et période
- Résumé des flux (achats, ventes, dividendes, frais)
- Suppression de transaction avec confirmation

---

## 📐 Calcul des performances

Toutes les métriques de performance sont calculées via un **indice de performance ajusté** (`_build_perf_index`) qui neutralise l'effet des apports en capital :

```
r_t = (V_t − ΔI_t) / V_{t-1} − 1
indice = ∏(1 + r_t)
```

où `ΔI_t` est la variation d'`invested_capital` au jour `t`.

Cela garantit qu'un DCA de 500 € un lundi n'apparaît pas comme un gain de 500 € dans les performances.

---

## 🤖 Analyse IA mensuelle

La page **Synthèse mensuelle** intègre une analyse générée par **Gemini 2.5 Flash** (Google).

Le prompt envoie à Gemini :
- Performance du mois (valeur début/fin, variation €/%)
- Liste complète des actifs détenus (nom, classe, géographie)
- Opérations du mois (achats/ventes avec montants)
- DCA, dividendes et trajectoire FIRE

Gemini utilise sa connaissance des marchés pour contextualiser les perfs des actifs spécifiques (macro, secteurs, zones géo) et rédige une analyse en 2-3 paragraphes.

**Activation :**
1. Créer une clé gratuite sur [aistudio.google.com](https://aistudio.google.com) (sans CB) — utiliser **Gemini 2.5 Flash**
2. La coller dans **Saisie manuelle → ⚙️ Paramètres → Clé API Gemini**
3. Cliquer "✨ Générer l'analyse" dans la Synthèse mensuelle

L'analyse est générée **à la demande** (pas d'appel automatique) et mise en cache pour la session.

---

## 📄 Licence

MIT

---

## 👤 Auteur

**Nathan Ramboz**  
GitHub : [agxas](https://github.com/agxas)
