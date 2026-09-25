# kemta_suivi

Suivi de chantier (Cameroun) : preuves terrain **offline-first**, jalons et planning, budget en
**FCFA**, journal d'activité. Backend Django/DRF + PostgreSQL/Redis/Celery, frontend
React/TypeScript/Vite.

**Avancement actuel : Phases 0 (cadrage) et 1 (fondations) livrées, Phase 2 (authentification,
RBAC et **réinitialisation du mot de passe**) implémentée et testée.** Les chapitres suivants
(projets, jalons, preuves, finances, dashboard) sont spécifiés et planifiés dans le backlog.

## 1. Démarrage rapide avec Docker (chemin nominal)

```bash
cp .env.example .env          # puis remplacez SECRET_KEY
docker compose up -d --build  # db + redis + web + worker + beat + frontend
docker compose exec web python manage.py seed_dev   # comptes de démonstration (dev)
```

- Frontend : <http://localhost:5173>
- API : <http://localhost:8000/api/>
- Santé : <http://localhost:8000/api/health/> (vérifie application, PostgreSQL et Redis)
- Admin : <http://localhost:8000/admin/>

Comptes de démonstration (un par rôle) — création par `seed_dev`, **développement uniquement** :

| Rôle | Téléphone | Mot de passe |
|---|---|---|
| Project owner | `+237 690 000 003` | `Kemta#2026Demo` |
| Ingénieur | `+237 690 000 004` | `Kemta#2026Demo` |
| Agent terrain | `+237 690 000 006` | `Kemta#2026Demo` |
| Financier | `+237 690 000 008` | `Kemta#2026Demo` |

**Tester le parcours OTP sans téléphone** : en développement, le fournisseur SMS est un
adaptateur console et l'écran d'activation comme l'écran de réinitialisation affichent un bouton
« Afficher les codes de test » qui lit `GET /api/dev/outbox/` (endpoint désactivé — HTTP 404 —
dès que `DEBUG=false` ou `DJANGO_ENV=production`). Aucun code OTP n'est écrit dans les logs.

## 2. Démarrage sans Docker

```bash
# Backend (SQLite en local, aucun service externe requis)
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
USE_SQLITE=true USE_LOCAL_CACHE=true CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py migrate && python manage.py seed_dev
USE_SQLITE=true USE_LOCAL_CACHE=true CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py runserver 0.0.0.0:8000

# Frontend (proxy /api → http://127.0.0.1:8000)
cd frontend && npm install && npm run dev
```

## 3. Tests

```bash
cd backend && pytest                       # 143 tests, sans infrastructure externe
cd backend && pytest --cov=apps --cov-report=term-missing
cd frontend && npm test                    # 15 tests : politique de mot de passe + écrans « mot de passe oublié »
cd frontend && npm run build               # vérification TypeScript + build
```

Les tests backend tournent sur SQLite, cache mémoire, Celery en mode eager et SMS/email en
adaptateur console : **aucun service externe n'est nécessaire**.

## 4. Périmètre d'authentification livré (Phase 2)

- Identifiant principal : **numéro de téléphone** normalisé E.164 (Cameroun), l'email est facultatif.
- Inscription → **OTP SMS haché, expirable, à usage unique**, tentatives et renvois limités,
  compte inactif jusqu'à validation.
- Connexion téléphone + mot de passe, JWT (access 15 min, refresh rotatif + blacklist),
  verrouillage temporaire après échecs répétés.
- **Mot de passe oublié (MVP-017)** : `/mot-de-passe-oublie` → OTP SMS → nouveau mot de passe →
  **révocation de toutes les sessions**, SMS de confirmation, journalisation, réponse neutre
  (aucune énumération de compte).
- Changement de mot de passe pour un utilisateur connecté (ancien mot de passe requis).
- 9 rôles et matrice de capacités testée en positif **et** en négatif.
- Journal d'activité **immuable** (auth, OTP, rôles, mots de passe) — suppression interdite.
- Rate limiting par numéro/IP, enveloppe d'erreur uniforme avec `request_id`, logs structurés
  sans secret.

## 5. Documentation

| Document | Contenu |
|---|---|
| [`docs/BACKLOG_MVP.md`](docs/BACKLOG_MVP.md) | Backlog priorisé, phases 0 → 11, MVP-001 → MVP-018, définition de terminé commune |
| [`docs/architecture.md`](docs/architecture.md) | Architecture, Docker, stockage médias, observabilité, sécurité, ADR |
| [`docs/data-model.md`](docs/data-model.md) | Modèle de données cible (identité → finances → exploitation) |
| [`docs/rbac-matrix.md`](docs/rbac-matrix.md) | 9 rôles, capacités, matrices détaillées, implémentation |
| [`docs/api-contract.md`](docs/api-contract.md) | Contrat API : endpoints, erreurs, idempotence, rate limiting |
| [`docs/offline-sync.md`](docs/offline-sync.md) | Stratégie offline-first, file de synchronisation, conflits, cache |
| [`docs/test-plan.md`](docs/test-plan.md) | Plan de tests, matrice fonctionnalité → tests, seed, E2E |
| [`docs/flows/authentication.md`](docs/flows/authentication.md) | Flux inscription / OTP / connexion / **réinitialisation du mot de passe** |

## 6. Structure du dépôt

```
backend/     config/ (settings, urls, celery) · apps/core (journal, santé, erreurs) ·
             apps/users (identité, OTP, sessions, rôles) · tests
frontend/    src/ (api, auth, components, pages) · tests unitaires (vitest)
docs/        cadrage Phase 0 et spécifications
docker-compose.yml · docker-compose.prod.yml · .env.example
```

## 7. Règles non négociables du projet

1. Aucun secret dans le dépôt : uniquement des variables d'environnement (`.env.example` documenté).
2. Aucun OTP, mot de passe ou jeton en clair — ni en base, ni dans les logs, ni dans les réponses.
3. Le backend est l'autorité : le frontend masque, il ne décide pas.
4. Aucune donnée mockée ni bouton fictif dans le parcours produit.
5. Les montants sont en **entiers FCFA** et toujours calculés côté serveur.
6. Une fonctionnalité n'est « terminée » qu'avec ses tests, sa documentation et sa DoD
   (`docs/BACKLOG_MVP.md` §5).
