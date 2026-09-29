# État du MVP — KEMTA SUIVI

Dernière mise à jour : **29 septembre 2026**. L'implémentation des phases 0 à 11 est présente
sur la branche de travail ; les validations reproductibles et les éléments qui dépendent d'un
compte fournisseur, d'un navigateur ou d'une infrastructure de production sont distingués ci-dessous.

## Validation exécutée

| Vérification | Résultat |
|---|---|
| Backend — `cd backend && ./.venv/bin/pytest` | **504 réussis, 4 ignorés** ; les tests ignorés portent sur les verrous/concurrences PostgreSQL et sont incompatibles avec SQLite |
| Backend — `ruff check .` + `ruff format --check .` | ✅ propres |
| Django — `manage.py check` | ✅ aucun problème |
| Migrations — `makemigrations --check --dry-run` | ✅ aucune migration manquante |
| Frontend — `npm test` | **102 réussis** sur 11 fichiers Vitest |
| Frontend — `npm run lint` + `npm run build` | ✅ ESLint, TypeScript et build Vite réussis |
| Dépendances — `pip-audit` (runtime et dev) | ✅ aucune vulnérabilité connue |
| Dépendances — `npm ci` / audit npm | ✅ aucune vulnérabilité connue |
| Compose | ✅ `docker-compose.yml` et `docker-compose.prod.yml` parsés en YAML, respectivement 6 et 7 services |
| Démarrage local | ✅ `./dev.sh --local` a appliqué les migrations, créé la seed dev ; `/api/health/` et Vite répondent |
| Playwright | 2 tests E2E sont découverts ; **ils n'ont pas été exécutés**, Chromium n'est pas installé (téléchargement Playwright bloqué par `ECONNRESET`) |
| Compose production / Nginx | non exécutés : Docker et Nginx ne sont pas installés dans l'environnement |

Le démarrage local utilise SQLite et un cache local. Le test `/api/health/` vérifie donc la base et
le cache de ce mode local ; il ne valide pas une stack PostgreSQL/Redis en conteneurs.

## Vue par phase

| Phase | Contenu | État |
|---|---|---|
| 0 — Cadrage | backlog, architecture, RBAC, modèle, contrat API et plan de tests | ✅ |
| 1 — Fondations | Django/DRF, migrations, `./dev.sh`, healthcheck, erreurs structurées, logs | ✅ |
| 2 — Authentification et RBAC | téléphone comme identifiant, email facultatif, OTP, sessions JWT, rôles et reset MVP-017 | ✅ |
| 3 — Organisations et projets | organisations, membres, projets et contrôles de périmètre | ✅ |
| 4 — Planning | jalons, tâches, dépendances, progression serveur, retards | ✅ |
| 5 — Preuves terrain | upload, GPS, validation, historique immuable, fichiers privés | ✅ |
| 6 — Offline-first | file IndexedDB, rejeu idempotent, reprise et conflits visibles | ✅ |
| 7 — Finances | budgets, dépenses, justificatifs, paiements et grand livre append-only | ✅ |
| 8 — Dashboard | synthèse projet, cache serveur court, finances selon permission | ✅ |
| 9 — Journal | journal d'activité paginé et protégé, événements métier étendus | ✅ |
| 10 — Asynchrone et notifications | outbox transactionnelle, Celery, notifications in-app, scans média | ✅ |
| 11 — Performance et observabilité | métriques, pagination, limites d'agrégats, tests anti-N+1 | ✅ |

## MVP fonctionnel

| ID | Fonctionnalité | État | Couverture / précision |
|---|---|---|---|
| MVP-001 | Inscription par téléphone, sans email obligatoire | ✅ | tests API d'inscription ; test Playwright de l'écran écrit, non exécuté faute de Chromium |
| MVP-002 | OTP sécurisé | ✅ | stockage haché, limites, OTP SMS/email console ; tests d'envoi Africa's Talking simulé |
| MVP-003 | Connexion et sessions | ✅ | rotation, révocation, verrouillage et changement de mot de passe testés |
| MVP-004 | RBAC et permissions backend | ✅ | matrice de rôles, tests positifs/négatifs et périmètres 403/404 |
| MVP-005 | Organisations, projets et membres | ✅ | CRUD, permissions, pagination, journalisation et tests anti-N+1 |
| MVP-006 | Jalons, tâches et avancement | ✅ | validations, dépendances sans cycle, retards, permissions et calcul serveur |
| MVP-007 | Capture de preuves | ✅ | compression appareil, GPS explicite, hash, idempotence et validation binaire |
| MVP-008 | Validation et historique des preuves | ✅ | transitions contrôlées, commentaire, séparation des tâches, historique append-only |
| MVP-009 | Synchronisation offline | ✅ | IndexedDB, retry borné, rejouabilité, conflits ; tests backend et Vitest |
| MVP-010 | Finances | ✅ | dépenses, paiements, seuils, concurrence PostgreSQL (tests dédiés ignorés ici), contre-écritures |
| MVP-011 | Dashboard agrégé | ✅ | endpoint projet, compteurs SQL, alertes et cache court ; tests de performance |
| MVP-012 | Journal d'activité | ✅ | immuable, filtrage des métadonnées sensibles, pagination et permissions |
| MVP-013 | Sécurité média | ✅ | ClamAV, quarantaine, quotas, URLs signées, reprise de scans `SCANNING` ; preuves dans les suites média |
| MVP-014 | Notifications | ✅ | outbox Celery idempotente, notifications privées/regroupées et marquage lu |
| MVP-015 | Santé et observabilité | ✅ | healthcheck, métriques admin, états de tâche Celery et logs assainis |
| MVP-016 | Seed et tests E2E | 🟡 | seed de démo complète ; 2 scénarios Playwright écrits/découverts, non exécutés faute de navigateur |
| MVP-017 | Réinitialisation du mot de passe | ✅ | OTP SMS, réponse neutre, révocation des sessions et tests backend/frontend ; E2E écrit mais non exécuté |
| MVP-018 | Réinitialisation par email (P1/P2) | ⏭️ | email facultatif/vérifiable disponible ; récupération par email hors MVP |

## Sécurité médias et notifications

- Les evidences et justificatifs restent indisponibles tant que le scan n'est pas `CLEAN` ; les
  fichiers infectés sont supprimés. Les reprises périodiques récupèrent les scans interrompus et
  les fichiers supprimés ne consomment plus les quotas ni les métriques d'octets.
- Les liens image sont relatifs, signés et à durée courte ; chaque accès revalide l'utilisateur et
  ses permissions. Les réponses sont privées, `no-store` et sans referrer.
- Les événements métier sont inscrits dans une outbox, distribués après commit et dédupliqués ;
  les alertes de retard ont une clé de déduplication par projet et par journée locale.
- Les codes OTP restent disponibles pour les tests locaux via `/api/dev/outbox/`, mais ne sont
  jamais imprimés dans les logs. Cet endpoint renvoie 404 en production.

## Configuration nécessaire avant une mise en production

1. **SMS** : l'adaptateur Africa's Talking est intégré et testé avec réponses HTTP simulées. Il
   faut fournir un compte configuré, KYC/solde, `SMS_USERNAME`, `SMS_API_KEY` et un `SMS_SENDER_ID`
   enregistré pour le Cameroun. Aucun identifiant réel n'est livré dans Git ; aucun SMS réel n'a
   été envoyé pendant la validation.
2. **Médias** : la production exige ClamAV (`CLAMAV_HOST`) et un stockage privé correctement
   dimensionné.
3. **TLS et domaines** : provisionner les certificats Nginx, définir `ALLOWED_HOSTS`, origines
   CSRF/CORS, `SECRET_KEY` et identifiants PostgreSQL/Redis forts. Ne pas exécuter `seed_dev`.
4. **Compose** : le fichier production utilise `!reset` pour retirer les montages/ports hérités du
   Compose de développement ; Docker Compose v2.24+ est requis. Il reste à vérifier le rendu
   (`docker compose config`) et le lancement réel avec Docker dans un environnement qui le possède.
5. **E2E/mobile** : installer Chromium puis lancer `cd frontend && npm run test:e2e`; valider aussi
   sur un appareil mobile réel les permissions caméra/GPS et le retour réseau. La suite navigateur
   actuelle couvre la présence du champ téléphone sans email et le parcours reset → reconnexion →
   dashboard, mais elle n'a pas pu tourner dans ce sandbox.

## Décisions métier encore ouvertes / hors MVP

- Compte Africa's Talking, conformité KYC, sender ID et crédits SMS à fournir par le déploiement.
- Procédure de changement de numéro / perte de SIM (ADR-007) et calendrier ouvré camerounais
  (jours fériés pour les retards, ADR-010) à arbitrer avec le produit.
- Invitations SMS (ADR-008), Gantt graphique (ADR-009) et reset par email (MVP-018) restent hors
  périmètre de ce MVP.

Voir [`BACKLOG_MVP.md`](BACKLOG_MVP.md), [`test-plan.md`](test-plan.md) et
[`api-contract.md`](api-contract.md) pour le détail des règles et des routes.
