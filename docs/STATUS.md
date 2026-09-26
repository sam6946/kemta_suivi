# État d'avancement — MVP KEMTA SUIVI

Dernière mise à jour : phases 0, 1, 2, 3 et 4 livrées.
Preuves d'exécution : `cd backend && pytest` → **300 tests**, couverture **94 %** ;
`cd frontend && npm test` → **38 tests** ; `npm run build` → OK ;
`ruff check` + `ruff format --check` → propres ; `npm run lint` → propre.

## Vue par phase

| Phase | Contenu | État |
|---|---|---|
| 0 — Cadrage | backlog, architecture + ADR, modèle de données, matrice RBAC, contrat API, offline/sync, plan de tests, flux auth et projet | ✅ livrée |
| 1 — Fondations | Docker Compose, PostgreSQL/Redis/Celery, `/api/health/`, logs JSON, `.env.example`, migrations, tests, README | ✅ livrée |
| 2 — Authentification et RBAC | téléphone + OTP, connexion JWT, refresh, RBAC 9 rôles, **réinitialisation du mot de passe**, rate limiting, journalisation | ✅ livrée |
| 3 — Organisations, projets, membres | organisations, projets, membres, rôles par projet, permissions backend, écrans responsive, tests de permissions | ✅ livrée |
| 4 — Jalons, tâches, planning | jalons, tâches, planning listé, avancement serveur, alertes de retard | ✅ livrée |
| 5 — Preuves terrain | capture, compression, GPS, hash, statuts, validations | ⏳ à venir |
| 6 — Offline-first | IndexedDB, file de synchronisation, idempotence, conflits | ⏳ à venir |
| 7 — Budget, dépenses | budget, postes, dépenses, paiements, transactions atomiques | ⏳ à venir |
| 8 — Dashboard agrégé | endpoint `/api/projects/{id}/dashboard/`, alertes, cache | ⏳ à venir |
| 9 — Journalisation étendue | suppression logique, écran d'activité, journaux protégés | 🟡 partielle (modèle + événements phase 2/3) |
| 10 — Asynchrone et notifications | Celery, événements métier, notifications in-app | 🟡 partielle (Celery + SMS/email async) |
| 11 — Performance et observabilité | pagination, N+1, cache, métriques, tests de charge | 🟡 partielle (pagination, N+1 verrouillés par tests) |

## Vue par fonctionnalité (P0)

| ID | Fonctionnalité | État | Preuves |
|---|---|---|---|
| MVP-001 | Inscription par téléphone | ✅ | `apps/users/tests/test_registration.py` |
| MVP-002 | OTP SMS sécurisé | ✅ | `test_otp.py` (hash, expiration, tentatives, renvois, `purpose`) |
| MVP-003 | Connexion et sessions | ✅ | `test_login.py` (rotation, révocation, verrouillage) |
| MVP-004 | RBAC et permissions backend | ✅ | `test_role_matrix.py`, `apps/projects/tests/test_access_matrix.py` |
| MVP-005 | Organisations, projets, membres | ✅ | `test_organizations.py`, `test_projects.py`, `test_members.py` |
| MVP-006 | Jalons, tâches, avancement | ✅ | `test_milestones.py` (14) · `test_tasks.py` (17) · `test_progress.py` (18) |
| MVP-007 | Capture de preuve terrain | ⏳ phase 5 | — |
| MVP-008 | Validation et historique des preuves | ⏳ phase 5 | — |
| MVP-009 | File offline et synchronisation | ⏳ phase 6 | — |
| MVP-010 | Budget et dépenses | ⏳ phase 7 | montants FCFA entiers déjà appliqués (projet) |
| MVP-011 | Dashboard projet agrégé | ⏳ phase 8 | compteurs réels déjà affichés (pas de mock) |
| MVP-012 | Journal d'activité | 🟡 | modèle immuable + événements auth/org/projet/membres ; écran d'activité en phase 9 |
| MVP-013 | Médias | ⏳ phase 5/10 | — |
| MVP-014 | Notifications et événements | ⏳ phase 10 | SMS/email déjà traités par Celery |
| MVP-015 | Observabilité et healthchecks | 🟡 | `/api/health/`, logs JSON, `request_id`, métriques à compléter en phase 11 |
| MVP-016 | Tests E2E et seed | 🟡 | seed dev complet (9 comptes, 3 organisations, 4 projets FCFA, membres) ; E2E Playwright en phase 11 |
| MVP-017 | **Réinitialisation du mot de passe** | ✅ | `test_password_reset.py` (20 cas), `test_security.py` |
| MVP-018 | Réinitialisation par email (P1/P2) | ⏳ | email vérifié par OTP déjà disponible |

## Événements journalisés (immuables)

`USER_REGISTERED`, `OTP_SENT/VERIFIED/FAILED/RESEND`, `LOGIN_SUCCESS/FAILED`, `ACCOUNT_LOCKED`,
`LOGOUT`, `PASSWORD_RESET_REQUESTED/FAILED/CONFIRMED/DENIED`, `PASSWORD_CHANGED`,
`EMAIL_ADDED/VERIFIED`, `ORG_CREATED/UPDATED`, `PROJECT_CREATED/UPDATED/ARCHIVED`,
`MEMBER_ADDED/ROLE_CHANGED/REMOVED`, `MILESTONE_CREATED/UPDATED/DELETED`,
`TASK_CREATED/UPDATED/STATUS_CHANGED/DELETED`.

## Points ouverts (ADR)

| # | Décision | Échéance |
|---|---|---|
| ADR-004 | Upload direct Django vs presigned URL S3 | avant phase 5 |
| ADR-005 | Fournisseur SMS (coût par OTP, couverture réseau) | avant phase 5 (preuves terrain) |
| ADR-006 | Stockage média : volume chiffré vs S3-compatible | avant phase 5 |
| ADR-007 | Procédure « numéro perdu / changement de SIM » | avant mise en production |
| ADR-008 | Invitations par SMS (`ProjectInvitation`) | phase ultérieure |
| ADR-009 | Gantt graphique (barres temporelles) vs planning listé | retour utilisateur avant phase 8 |
| ADR-010 | Calendrier ouvré pour le calcul des retards (jours fériés camerounais) | avant mise en production |
