# Contrat API — KEMTA SUIVI (Phase 0)

Base : `/api/`. Version implicite v1 (`/api/v1/` réservé pour la suite). Format : JSON.
Auth : `Authorization: Bearer <access>` (JWT). Tous les endpoints renvoient du JSON, y compris en
erreur. Pagination : `?page=&page_size=` (défaut 20, max 100) pour **toute** collection.

## 1. Conventions

### Enveloppe de succès
Les collections paginées : `{ "count": 42, "next": null, "previous": null, "results": [...] }`.
Les objets : l'objet lui-même.

### Enveloppe d'erreur (uniforme)
```json
{ "error": { "code": "otp_invalid", "message": "Code invalide ou expiré.",
             "details": { "field": "code" }, "request_id": "9f2c…" } }
```
`request_id` est repris dans les logs structurés → corrélation frontend/backend.

### Codes HTTP
`200` ok · `201` créé · `204` supprimé/action sans contenu · `400` validation ·
`401` non authentifié/token expiré · `403` authentifié mais interdit · `404` non visible
(hors périmètre d'accès) · `409` conflit métier (doublon, état incompatible) ·
`413` fichier trop volumineux · `415` type de fichier refusé · `422` règle métier non
respectée · `429` rate limit · `500` erreur serveur (jamais de traceback exposé).

### Idempotence
Toute opération créée depuis le terrain accepte l'en-tête **`Idempotency-Key: <uuid>`**
(obligatoire pour `POST /evidences/`, `POST /expenses/`, `POST /sync/`). Une clé déjà traitée
renvoie **la même réponse** stockée (`200`, corps d'origine) au lieu de créer un doublon.

### Rate limiting (par IP + par numéro/utilisateur)
`auth/otp/*` et `auth/password/reset/*` : 5 demandes/h/numéro, 20/h/IP · `auth/login/` :
10/min/IP · reste de l'API : 1000/h/utilisateur. Réponse `429` avec `Retry-After`.

---

## 2. Authentification (Phase 2 — MVP-001, 002, 003, 017)

| # | Méthode | Endpoint | Auth | Description |
|---|---|---|---|---|
| A1 | `POST` | `/api/auth/register/` | — | Inscription par téléphone |
| A2 | `POST` | `/api/auth/otp/verify/` | — | Vérification OTP (activation, reset, email) |
| A3 | `POST` | `/api/auth/otp/resend/` | — | Renvoi contrôlé d'un OTP |
| A4 | `POST` | `/api/auth/login/` | — | Connexion téléphone + mot de passe |
| A5 | `POST` | `/api/auth/token/refresh/` | — | Renouvellement (rotation du refresh) |
| A6 | `POST` | `/api/auth/logout/` | JWT | Révocation du refresh token |
| A7 | `GET`/`PATCH` | `/api/auth/me/` | JWT | Profil courant + ajout de l'email |
| A8 | `POST` | `/api/auth/password/reset/request/` | — | **Demande de réinitialisation (MVP-017)** |
| A9 | `POST` | `/api/auth/password/reset/confirm/` | — | **Validation OTP + nouveau mot de passe** |
| A10 | `POST` | `/api/auth/password/change/` | JWT | Changement de mot de passe connecté |
| A11 | `POST` | `/api/auth/email/request/` | JWT | OTP d'ajout d'email |
| A12 | `POST` | `/api/auth/email/confirm/` | JWT | Confirmation de l'email |

### A1 `POST /api/auth/register/`
```json
{ "phone": "+237690123456", "password": "…", "password_confirm": "…",
  "first_name": "Arnaud", "last_name": "Nkoulou" }
```
`201` → `{ "phone_masked": "+237 6XX XX 34 56", "otp_ttl": 300, "retry_in": 60 }`
Erreurs : `phone_invalid` · `phone_already_used` (409) · `phone_pending_activation` (409) ·
`password_too_weak` (400). Aucun token n'est renvoyé : le compte reste inactif.

### A2 `POST /api/auth/otp/verify/`
```json
{ "phone": "+237690123456", "code": "123456", "purpose": "SIGNUP" }
```
`200` → `{ "access": "…", "refresh": "…", "user": { "id", "phone", "first_name", "last_name",
"role", "is_phone_verified", "email" }, "permissions": ["project.view", …] }`
Erreurs : `otp_invalid` · `otp_max_attempts` (429) · `account_not_confirmed`.

### A4 `POST /api/auth/login/`
`{ "phone", "password" }` → `200` (même corps que A2).
`401` `invalid_credentials` (message identique pour numéro inconnu et mot de passe faux) ·
`403` `account_not_confirmed` · `429` `account_locked` après `N` échecs (`locked_until`).

### A5 `POST /api/auth/token/refresh/`
`{ "refresh" }` → `200 { "access", "refresh" }` (rotation : l'ancien refresh est révoqué).
`401` `token_invalid` → le frontend purge la session (aucune boucle de retry).

### A8 `POST /api/auth/password/reset/request/`
`{ "phone": "+237690123456" }` → **toujours**
```json
{ "detail": "Si ce numéro est associé à un compte, un code vient d'être envoyé par SMS.",
  "retry_in": 60, "otp_ttl": 300 }
```
`200` dans tous les cas (numéro inconnu, compte inactif, compte désactivé) → **pas
d'énumération** ; `429` si quota dépassé. Compte inactif → un OTP `SIGNUP` est renvoyé à la place.

### A9 `POST /api/auth/password/reset/confirm/`
```json
{ "phone": "+237690123456", "code": "123456",
  "new_password": "…", "new_password_confirm": "…" }
```
`200` → `{ "detail": "Mot de passe réinitialisé.", "sessions_revoked": true }`
Effets : OTP consommé, mot de passe changé, **tous les refresh tokens révoqués**, SMS de
confirmation (Celery), `ActivityLog: PASSWORD_RESET_CONFIRMED`.
Erreurs : `otp_invalid` · `otp_max_attempts` · `password_too_weak` · `password_reused` ·
`account_not_confirmed`.

### A10 `POST /api/auth/password/change/`
`{ "current_password", "new_password", "new_password_confirm" }` → `200 { "sessions_revoked": true }`
(les autres sessions sont révoquées, la session courante est renouvelée).

---

## 3. Métadonnées

| Méthode | Endpoint | Description |
|---|---|---|
| `GET` | `/api/meta/roles/` | Les 9 rôles + libellés + capacités (source unique partagée avec le frontend) |
| `GET` | `/api/meta/status/` | Tous les `TextChoices` (statuts projet/jalon/tâche/preuve/dépense) — phase 4 |
| `GET` | `/api/health/` | Santé application + PostgreSQL + Redis (détail en §8) |

---

## 4. Organisations et projets (Phase 3 — MVP-005)

| Méthode | Endpoint | Permission |
|---|---|---|
| `GET`/`POST` | `/api/organizations/` | voir/créer une organisation |
| `GET`/`PATCH`/`DELETE` | `/api/organizations/{id}/` | membre / `ORG_OWNER` |
| `GET`/`POST` | `/api/organizations/{id}/members/` | membre / `ORG_OWNER`+ |
| `PATCH`/`DELETE` | `/api/organizations/{id}/members/{user_id}/` | `ORG_OWNER`+ |
| `GET`/`POST` | `/api/projects/` | membre des projets visibles / `ORG_OWNER` |
| `GET`/`PATCH`/`DELETE` | `/api/projects/{id}/` | membre du projet / `PROJECT_OWNER`+ |
| `GET`/`POST` | `/api/projects/{id}/members/` | membre / `PROJECT_OWNER`+ |
| `PATCH`/`DELETE` | `/api/projects/{id}/members/{user_id}/` | `PROJECT_OWNER`+ |

**Filtres** projets : `?status=DRAFT,ACTIVE&organization=&search=&ordering=&page=&page_size=`
(tri supporté : `created_at`, `name`, `status`, `budget_total`, avec `-` pour décroissant).
Recherche sur `name`, `code`, `city`, `location_label`.

**Ajout d'un membre** (`POST .../members/`) : le compte doit exister.

```json
{ "phone": "+2376XXXXXXXX", "role": "ENGINEER",
  "can_validate_evidence": false, "can_manage_finance": false }
```
`404 user_not_found` (numéro inconnu) · `409 user_not_activated` · `409 member_already_exists` ·
`403 permission_denied` (rôle sans `manage_members`).

**Champ `permissions`** renvoyé par les endpoints projet — calculé par le backend, jamais déduit
côté client :

```json
{ "edit_project": true, "archive_project": true, "manage_members": true,
  "capture_evidence": true, "validate_evidence": false,
  "view_finance": true, "manage_finance": false }
```

**Sémantique d'accès** : projet hors périmètre → `404` (l'objet n'existe pas pour l'utilisateur) ;
projet visible mais action interdite → `403`. Voir `docs/flows/project.md` §3.

**Performance** : compteurs annotés (`Count`, distinct) et relations chargées via
`select_related` ; les permissions d'une page entière sont résolues en une passe
(`build_capabilities_map`). Les seuils de requêtes sont verrouillés par
`test_project_list_has_no_n_plus_one` et `test_organization_list_has_no_n_plus_one`.

## 5. Jalons et tâches (Phase 4 — MVP-006)

| Méthode | Endpoint | Notes |
|---|---|---|
| `GET`/`POST` | `/api/projects/{id}/milestones/` | liste ordonnée (`order`, `planned_date`) ; création → `201` |
| `GET`/`PATCH`/`DELETE` | `/api/milestones/{id}/` | `DELETE` = suppression logique → `204` |
| `GET`/`POST` | `/api/projects/{id}/tasks/` | filtres `?status=&milestone=&assignee=&late=1`, tri `?ordering=` (liste blanche) |
| `GET`/`PATCH`/`DELETE` | `/api/tasks/{id}/` | `PATCH` partiel ; un responsable désigné peut modifier l'exécution |
| `GET` | `/api/projects/{id}/schedule/` | vue planning agrégée : projet, jalons, tâches sans jalon, résumé, alertes |
| `GET` | `/api/projects/{id}/delays/` | retards déterministes (`reference_date` incluse) |

**Écriture d'un jalon**

```json
{ "title": "Fondations terminées", "description": "…", "status": "DONE",
  "planned_date": "2026-04-30", "actual_date": "2026-05-02", "order": 2, "weight": "2" }
```

**Écriture d'une tâche**

```json
{ "title": "Coulage des semelles", "milestone": 12, "status": "IN_PROGRESS",
  "planned_start_date": "2026-03-01", "planned_end_date": "2026-03-20",
  "actual_start_date": "2026-03-02", "progress": 40, "weight": 3,
  "assignee_id": 7, "depends_on": [9, 10] }
```

**Réponse `GET /api/projects/{id}/schedule/`**

```json
{ "project": { "id", "name", "status", "progress", "planned_start_date", "planned_end_date" },
  "milestones": [ { "id", "title", "status", "status_label", "planned_date", "actual_date",
                    "order", "weight", "is_late", "days_late", "progress",
                    "task_total", "task_done" } ],
  "orphan_tasks": [ { "id", "title", "status", "progress", "is_late", "days_late" } ],
  "summary": { "milestones_total": 4, "milestones_done": 1, "tasks_total": 12, "tasks_done": 5,
               "tasks_late": 2, "milestones_late": 1, "names_late": ["…"] },
  "alerts": [ { "type": "task_late|milestone_late", "id", "title", "days_late", "…_date" } ] }
```

**Erreurs spécifiques** : `dependent_not_in_project` et `dependency_not_in_project` → `400`
(champ `depends_on`) · `dependency_cycle` → `409` · `invalid_status`, `invalid_ordering` → `400` ·
dates incohérentes et avancement hors bornes → `400` avec le champ concerné ·
`permission_denied` → `403` (projet visible) · projet hors périmètre → `404`.

**Avancement** : calculé côté serveur à chaque écriture (voir `docs/flows/planning.md` §3) ;
`progress` du projet est en lecture seule. Chaque écriture de jalon ou de tâche renvoie le champ
`project_progress` (nouvel avancement du projet) et les suppressions `204` l'exposent dans
l'en-tête `X-Project-Progress` — le client n'a donc jamais à recalculer quoi que ce soit. Performance : `/schedule/` reste à nombre constant de
requêtes (`test_schedule_has_no_n_plus_one`).

## 6. Preuves terrain (Phase 5 — MVP-007, 008 ; Phase 6 — MVP-009)

| Méthode | Endpoint | Notes |
|---|---|---|
| `POST` | `/api/evidences/` | `multipart` : `file`, `project`, `captured_at`, `gps_status`, `latitude?`, `longitude?`, `gps_accuracy?`, `device_model?`, `device_platform?`, `app_version?`, `description?`, `task?` ; en-tête `Idempotency-Key` **obligatoire** |
| `GET` | `/api/projects/{id}/evidences/` | galerie paginée + `counts` par statut ; `?status=` (CSV), `?sync_status=`, `?author=`, `?task=`, `?pending=true` |
| `GET` | `/api/evidences/{id}/` | détail + `permissions` par preuve + `last_validation` |
| `GET` | `/api/evidences/{id}/history/` | historique paginé des décisions (append-only) |
| `POST` | `/api/evidences/{id}/transition/` | `{ "action": "VALIDATE"\|"REJECT"\|"FLAG"\|"REOPEN", "comment": "…" }` |
| `GET` | `/api/evidences/{id}/file/` | fichier d'origine, accès contrôlé par appartenance au projet |
| `GET` | `/api/evidences/{id}/thumbnail/` | miniature (WebP, JPEG de repli) — retombe sur l'original tant qu'elle n'est pas prête |
| `GET` | `/api/evidences/pending/` | file d'attente du validateur, tous projets confondus ; `?older_than_hours=` |
| `POST` | `/api/sync/batch/` | **Phase 6 (MVP-009)** : reprise de synchronisation par lot, mêmes clés d'idempotence (voir §6.1) |

**Création** : `201` avec `status=PENDING`, `sync_status=SYNCED`, `hash_sha256` (empreinte du
fichier **reçu**, recalculée côté serveur) et `distance_from_site_m` / `inside_geofence` quand le
projet a des coordonnées. Le nom du fichier envoyé est ignoré : le chemin est régénéré
(`evidences/{project_id}/{yyyy}/{mm}/{uuid}.ext`).

**Rejeu** : même `Idempotency-Key` + même auteur → `200` (et non `201`) avec l'en-tête
`Idempotency-Replayed: true` et **la même preuve** : un envoi réessayé après une coupure réseau
n'est jamais dupliqué.

**URLs de fichiers** : `file_url` et `thumbnail_url` sont des **chemins relatifs**
(`/api/evidences/{id}/file/`) ; le client les résout sur son propre hôte, ce qui reste valable
derrière un proxy. Les réponses sont `Cache-Control: private` (jamais de cache partagé) et, si
`MEDIA_X_ACCEL_REDIRECT` est actif, le corps est délégué à Nginx (`X-Accel-Redirect`).

| Code | HTTP | Sens |
|---|---|---|
| `idempotency_key_required` | 400 | en-tête `Idempotency-Key` absent |
| `duplicate_evidence` | 409 | même `hash_sha256` déjà déposé sur ce projet ; `details.evidence` porte l'existante |
| `file_too_large` | 413 | au-delà de `MAX_UPLOAD_SIZE_MB` (10 Mo) |
| `unsupported_media_type` | 415 | contenu réel non JPEG/PNG/WebP (`details.allowed`) |
| `file_empty` · `image_dimensions_too_large` | 400 | fichier vide ; image > 4000 px sur un côté |
| `captured_at_in_future` | 400 | horloge de l'appareil en avance (`details.server_time`) |
| `evidence_out_of_geofence` | 422 | photo prise hors du périmètre (`details.distance_m`, `radius_m`) |
| `comment_required` | 400 | rejet ou signalement sans commentaire |
| `invalid_transition` | 409 | action incompatible avec le statut courant (`details.allowed_actions`) |
| `cannot_validate_own_evidence` | 403 | un acteur ne valide pas sa propre preuve (sauf administrateur plateforme) |
| `invalid_status` | 400 | filtre `status` inconnu |

### 6.1 Synchronisation hors ligne (Phase 6 — MVP-009)

| Méthode | Endpoint | Notes |
|---|---|---|
| `POST` | `/api/sync/batch/` | rejeu d'un lot d'opérations **sans fichier** (50 maximum), chacune avec sa clé d'idempotence |
| `GET` | `/api/sync/status/` | ce que le serveur sait de la synchronisation : types acceptés, opérations appliquées, verrous en cours |
| `POST` | `/api/sync/operations/{key}/forget/` | libère une clé restée `IN_PROGRESS` (appareil disparu en plein envoi) |

Requête :
```json
{ "operations": [
  { "op_id": "uuid client", "type": "TASK_UPDATE", "idempotency_key": "uuid client",
    "payload": { "task": 12, "progress": "60.00" } }
] }
```

Réponse `200` : un résultat **par opération**, jamais un échec global — un lot partiel est normal
et attendu au retour du réseau.

| `status` | Sens | Ce que fait le client |
|---|---|---|
| `SYNCED` | appliquée (ou **rejouée** : `replayed: true`) | retire l'opération de la file |
| `CONFLICT` | l'état serveur ne permet pas l'opération telle quelle (`permission_denied`, `invalid_transition`, `comment_required`, `cannot_validate_own_evidence`, `not_found`, `op_in_progress`, `idempotency_key_conflict`) | garde l'opération, montre le motif, laisse l'utilisateur décider |
| `FAILED` | opération mal formée ou définitivement refusée (`invalid_operation_payload`, `validation_error`, `unsupported_operation`, `operation_requires_file`) | idem, avec relance manuelle possible |

`payload` attendu par type d'opération :

| `type` | `payload` |
|---|---|
| `TASK_UPDATE` | `{ "task": id, …champs de la tâche (dont `status`, `progress`, dates réelles) }` |
| `TASK_CREATE` | `{ "project": id, …champs de la tâche }` |
| `MILESTONE_UPDATE` | `{ "milestone": id, …champs du jalon }` |
| `MILESTONE_CREATE` | `{ "project": id, …champs du jalon }` |
| `EVIDENCE_TRANSITION` | `{ "evidence": id, "action": "VALIDATE"\|"REJECT"\|"FLAG"\|"REOPEN", "comment": "…" }` |

Règles :
- une clé déjà appliquée est **rejouée** (même réponse, aucun second effet) ; une clé en cours de
  traitement renvoie `op_in_progress` ; une clé réutilisée pour un autre type renvoie
  `idempotency_key_conflict` ;
- les opérations sont **isolées** : le refus de l'une n'annule pas les autres ;
- les **fichiers ne passent pas par le lot** : une photo part sur `POST /api/evidences/` avec sa
  clé (une opération `EVIDENCE_UPLOAD` dans un lot est refusée avec `operation_requires_file`) ;
- au-delà de 50 opérations ou en présence de deux clés identiques, le lot entier est refusé
  (`400`), car son résultat serait ambigu.

**Machine à états** : `PENDING → {VALIDATED, REJECTED, FLAGGED}` ·
`VALIDATED → {FLAGGED, REJECTED, REOPEN}` · `REJECTED → {REOPEN, VALIDATE}` ·
`FLAGGED → {REOPEN, VALIDATE, REJECT}` (`REOPEN` ramène à `PENDING`). Chaque décision écrit une
ligne `EvidenceValidation` (acteur, date, action, commentaire) et un `ActivityLog`
(`evidence_captured`, `evidence_validated`, `evidence_rejected`, `evidence_flagged`,
`evidence_reopened`). Champ `permissions` renvoyé par preuve :
`{ validate_evidence, cannot_validate_own, can_see_location }` — l'UI n'invente aucune règle.

## 7. Finances et dashboard (Phase 7/8 — MVP-010, 011)

`GET`/`POST` `/api/projects/{id}/budget-lines/` · `GET`/`POST` `/api/projects/{id}/expenses/` ·
`GET`/`PATCH` `/api/expenses/{id}/` · `POST` `/api/expenses/{id}/transition/` ·
`POST` `/api/expenses/{id}/payments/` · `GET` `/api/projects/{id}/transactions/` ·
`GET` **`/api/projects/{id}/dashboard/`** (endpoint agrégé, une seule requête) ·
`GET` `/api/projects/{id}/activity/` (journal paginé).

### `GET /api/projects/{id}/dashboard/` — réponse
```json
{
  "project": { "id", "name", "status", "currency": "XAF", "progress": 62 },
  "budget": { "planned": 50000000, "consumed": 31250000, "balance": 18750000,
              "consumption_rate": 62.5, "threshold_reached": false },
  "milestones": { "last": { "title", "status", "planned_date", "actual_date" },
                  "next": { "title", "status", "planned_date", "days_remaining": 12 },
                  "late_count": 1 },
  "tasks": { "total": 48, "done": 30, "late": 3 },
  "evidence": { "total": 120, "pending": 4, "validated": 108, "rejected": 6, "flagged": 2,
                "recent": [ { "id", "thumbnail", "status", "captured_at", "author" } ] },
  "expenses": { "recent": [ { "id", "title", "amount", "status", "incurred_on" } ] },
  "alerts": [ { "code": "PROJECT_DELAYED", "severity": "warning", "message": "…", "since": "…" } ],
  "activity": [ { "id", "action", "actor", "created_at", "entity" } ],
  "permissions": { "can_validate_evidence": true, "can_manage_finance": false,
                   "can_edit_schedule": true },
  "generated_at": "2026-01-15T09:12:03Z"
}
```
Contrats : les montants sont calculés côté serveur (**les totaux envoyés par le client sont
ignorés**) ; chaque sous-collection est **limitée** (5-10 éléments) avec un lien « voir tout » ;
les alertes sont **déterministes** ; `permissions` reflète exactement le backend.

## 8. Santé et exploitation (Phase 1/11)

`GET /api/health/` → `200` si tout va bien, `503` sinon :
```json
{ "status": "ok", "app": "ok", "database": "ok", "redis": "ok",
  "version": "1.0.0", "environment": "production", "checks_ms": { "database": 3, "redis": 1 } }
```
Aucun secret, aucune donnée métier. `/api/health/` n'est **pas** authentifié mais n'expose rien
de sensible (pas de version de librairies, pas de DEBUG).

## 9. Outils de développement (jamais en production)

| Méthode | Endpoint | Disponibilité | Description |
|---|---|---|---|
| `GET` | `/api/dev/outbox/` | **développement uniquement** | Derniers messages SMS/email émis par l'adaptateur console (test du parcours OTP/réinitialisation sans téléphone) |

Désactivé dès que `DEBUG=false` ou `DJANGO_ENV=production` : la route renvoie alors **404**
(l'existence de l'endpoint n'est pas révélée). La réponse ne contient que les messages destinés
à l'utilisateur, aucun secret technique.

## 10. Règles transverses

- Toute action sensible produit un `ActivityLog` (liste fermée, cf. `data-model.md` §7).
- Toute collection est paginée ; les curseurs/alternatives sont interdits sans ADR.
- Les listes utilisent `select_related`/`prefetch_related` documentés ; les tests assertions
  comptent les requêtes (`django_assert_num_queries`).
- Aucune boucle de polling < 30 s côté frontend (exigence MVP-011) : rafraîchissement manuel,
  revalidation au focus, ou SSE/Push ultérieurement.
