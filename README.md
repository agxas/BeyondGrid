# 📊 BeyondGrid

> Dashboard de gestion de portefeuille financier multi-comptes avec suivi FIRE (Financial Independence / Early Retirement)

---

## 🚀 Overview

**BeyondGrid** est une application permettant de suivre et analyser ses investissements de manière centralisée.

Elle permet de :

- 📈 Suivre plusieurs portefeuilles (PEA, CTO, crypto…)
- 🧾 Reconstituer un portefeuille à partir des transactions
- 📊 Visualiser l’évolution du capital
- 🎯 Suivre un objectif d’indépendance financière (FIRE)
- 🔄 Automatiser des snapshots journaliers

Stack technique :

- **Frontend / App** : Streamlit  
- **Backend / Base de données** : Supabase (PostgreSQL)  
- **CI / Automatisation** : GitHub Actions  

---

## 🧱 Architecture

```
BeyondGrid/
├── app.py                     # Application principale Streamlit
├── requirements.txt          # Dépendances Python
├── schema_summary.md         # Documentation de la base
└── .github/workflows/        # Automatisation des snapshots
```

---

## 🗄️ Base de données (Supabase)

Le projet repose sur une logique **transaction-driven + snapshots**.

### Tables principales

- **accounts**
  - Contient les comptes (PEA, CTO, crypto…)

- **assets**
  - Liste des actifs (actions, ETF, crypto, cash…)

- **transactions**
  - Source de vérité :
    - buy / sell  
    - deposit / withdrawal  
    - dividend / fees  

- **snapshots**
  - Valeurs agrégées journalières du portefeuille

- **settings**
  - Configuration globale :
    - objectif FIRE
    - rendement estimé
    - inflation
    - DCA

### 📌 Concepts clés

- Reconstruction du portefeuille via les transactions
- Snapshots pour la performance historique
- Gestion multi-comptes
- Possibilité d’ajouter des benchmarks

---

## ⚙️ Installation

### 1. Cloner le projet

```bash
git clone https://github.com/agxas/BeyondGrid.git
cd BeyondGrid
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

---

## 🔑 Configuration

Configurer les variables d’environnement (par exemple via `.env` ou Streamlit secrets) :

```
SUPABASE_URL=your_url
SUPABASE_KEY=your_key
```

---

## ▶️ Lancement

```bash
streamlit run app.py
```

---

## 🔄 Automatisation

Un workflow GitHub Actions permet de :

- 📅 Générer des snapshots automatiquement
- 🕐 Exécution en semaine (marchés ouverts)
- 📊 Maintenir les historiques à jour

---

## 📊 Fonctionnalités

### ✅ Gestion de portefeuille
- Multi-comptes
- Suivi des actifs
- Historique complet des transactions

### ✅ Analyse financière
- Valeur totale du portefeuille
- Capital investi
- Suivi du cash

### ✅ Suivi FIRE
- Objectif financier
- Rendement attendu
- Inflation
- DCA (Dollar Cost Averaging)

### ✅ Automatisation
- Snapshots journaliers
- Préparation pour mise à jour automatique des prix

---

## 🛠️ Stack technique

- Python
- Streamlit
- Supabase (PostgreSQL)
- GitHub Actions

---

## 🎯 Roadmap

- [ ] Intégration API broker
- [ ] Graphiques avancés
- [ ] Comparaison avec benchmarks
- [ ] Authentification multi-utilisateur
- [ ] Interface UI améliorée

---

## 🤝 Contribution

1. Fork du repo
2. Création d’une branche (`feature/xxx`)
3. Commit
4. Pull Request

---

## 📄 Licence

MIT

---

## 👤 Auteur

**Nathan Ramboz**  
Chargé du support systèmes, réseaux et télécoms  

GitHub : https://github.com/agxas

---

## ⭐ Objectif du projet

BeyondGrid vise à fournir une solution :

- libre
- automatisée
- extensible

pour suivre ses finances sans dépendre d’outils propriétaires.

---
