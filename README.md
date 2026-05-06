# 📊 BeyondGrid — v3.1

> Dashboard de suivi de portefeuille financier multi-comptes, avec performances ajustées des apports et suivi FIRE.

---

## 🚀 Vue d'ensemble

**BeyondGrid** est une application personnelle de suivi d'investissements, conçue pour être simple, fiable et évolutive.

- 📈 Suivi multi-comptes (PEA, CTO, AV, PER, crypto…)
- 📉 Performances **nettes des apports** (méthode TWR-like — un DCA ne gonfle pas artificiellement les chiffres)
- 🎯 Suivi de l'objectif FIRE avec règle des 4 %
- ⚖️ Rééquilibrage PEA assisté avec calcul des ordres Trade Republic
- 🔄 Snapshots journaliers automatisés via GitHub Actions

**Stack :**

| Couche | Techno |
|---|---|
| Frontend | Streamlit |
| Base de données | Supabase (PostgreSQL) |
| Automatisation | GitHub Actions |
| Données de marché | yfinance |

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
| `settings` | Configuration globale (FIRE, DCA, rendement estimé, inflation) |

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

### Vue Globale
- Situation du jour : valeur totale, capital investi, plus-value latente, variation journalière
- Performances récentes 1M / 3M / 1A avec sparklines (nettes des apports)
- Évolution du patrimoine global et par compte (graphiques interactifs)
- Objectif FIRE : progression, revenu passif (règle des 4 %), jours de liberté financière
- Positions ouvertes avec PRU, plus-value latente par ligne
- Répartition par classe d'actifs et géographie

### Analyses & Graphiques
- Performances par année calendaire (YTD inclus)
- Ratio de Sharpe et volatilité annualisée (ajustés des apports)
- Drawdown depuis le plus haut historique
- Comparaison portefeuille vs Livret A
- Comparaison portefeuille vs benchmark (MSCI World, S&P 500…)
- Projection DCA sur horizon configurable avec valeur réelle (inflation déduite)

### Rééquilibrage PEA
- Visualisation de l'allocation actuelle vs cible
- Calcul automatique des ordres à passer (algorithme greedy)
- Format adapté Trade Republic (arrondi au multiple de 5 €)

### Saisie manuelle
- Paramètres globaux (FIRE, DCA, rendement estimé, inflation, Livret A)
- Mise à jour des prix manuels avec liens vers les pages de cours
- Saisie de nouvelles transactions avec aperçu du montant en temps réel

### Transactions
- Historique filtrable par compte, type et période
- Résumé des flux (achats, ventes, dividendes, frais)
- Export CSV

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

## 🎯 Roadmap

- [ ] Correction fiscale (plus-values réalisées, abattements PEA)
- [ ] Vue détaillée par compte
- [ ] Alertes (objectif FIRE atteint, rebalancement nécessaire…)
- [ ] Support multi-devises

---

## 📄 Licence

MIT

---

## 👤 Auteur

**Nathan Ramboz**  
GitHub : [agxas](https://github.com/agxas)
