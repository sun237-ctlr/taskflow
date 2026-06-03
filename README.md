# TaskFlow Pro 🚀

Gestionnaire de tâches collaboratif — Application web Flask + SQLite/PostgreSQL.

## Fonctionnalités
- ✅ Tâches avec priorité, catégorie, échéance, tags
- ✅ Sous-tâches & journal de bord
- ✅ Projets collaboratifs + gestion des membres
- ✅ Timer Pomodoro
- ✅ Statistiques en temps réel
- ✅ Export CSV
- ✅ Authentification sécurisée
- ✅ Multi-utilisateurs

---

## 🖥️ Lancer en local

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Lancer
python app.py

# 3. Ouvrir dans le navigateur
# http://localhost:5000
```

---

## 🌐 Déployer en ligne

### Option 1 — Railway (recommandé, gratuit)

1. Crée un compte sur https://railway.app
2. Clique **New Project → Deploy from GitHub**
3. Connecte ton dépôt GitHub
4. Railway détecte automatiquement le `Procfile`
5. Va dans **Variables** et ajoute :
   - `SECRET_KEY` = une longue chaîne aléatoire (ex: `mon-super-secret-2024-xyz`)
   - `DATABASE_URL` = laisse vide (Railway crée SQLite auto) ou ajoute une PostgreSQL
6. Clique **Deploy** — ton app est en ligne en 2 minutes !

URL de ton app : `https://ton-projet.railway.app`

---

### Option 2 — Render (gratuit)

1. Crée un compte sur https://render.com
2. Clique **New → Web Service**
3. Connecte ton dépôt GitHub
4. Configuration :
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Variables d'environnement :
   - `SECRET_KEY` = ta clé secrète
6. Clique **Create Web Service**

---

### Option 3 — Heroku

```bash
# Installe Heroku CLI, puis :
heroku create mon-taskflow
heroku config:set SECRET_KEY="ma-cle-secrete"
git push heroku main
heroku open
```

---

### Option 4 — Docker (VPS/serveur)

```bash
# Build
docker build -t taskflow .

# Lancer
docker run -p 8000:8000 \
  -e SECRET_KEY="ma-cle-secrete" \
  -v ./data:/app/instance \
  taskflow
```

---

## 🔒 Variables d'environnement

| Variable | Description | Exemple |
|---|---|---|
| `SECRET_KEY` | Clé secrète Flask (**obligatoire**) | `abc123xyz...` |
| `DATABASE_URL` | URL base de données | `sqlite:///taskflow.db` ou `postgresql://...` |

---

## 📦 Mettre sur GitHub (étape obligatoire pour déployer)

```bash
git init
git add .
git commit -m "TaskFlow Pro - initial"
git remote add origin https://github.com/TON-NOM/taskflow.git
git push -u origin main
```

---

## 🏗️ Structure du projet

```
taskflow/
├── app.py              ← Backend Flask (API + routes)
├── requirements.txt    ← Dépendances Python
├── Procfile            ← Pour Railway/Heroku
├── railway.toml        ← Config Railway
├── render.yaml         ← Config Render
├── Dockerfile          ← Pour déploiement Docker/VPS
├── README.md           ← Ce fichier
└── templates/
    ├── auth.html       ← Page connexion/inscription
    └── dashboard.html  ← Application principale
```
