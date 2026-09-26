# Modèle de données — KEMTA SUIVI (Phase 0)

Statut : proposition à valider. Devise par défaut : **XAF (FCFA)**. Fuseau : `Africa/Douala`.
Toutes les dates sont en `UTC` en base, affichées en heure locale.

## Conventions transverses

| Sujet | Décision |
|---|---|
| Clé primaire | `UUID` (`uuid4`) exposé publiquement ; pas d'ID séquentiel dans les URLs |
| Suppression | **suppression logique** : champ `deleted_at` + manager `objects = SoftDeleteManager()` ; les journaux (`ActivityLog`) ne sont jamais supprimés |
| Horodatage | `created_at`, `updated_at` automatiques |
| Traçabilité | `created_by` / `updated_by` (FK `User`, `on_delete=PROTECT`) sur les entités métier |
| Argent | `DecimalField(max_digits=15, decimal_places=0)` — **montants entiers en FCFA** ; tout montant avec centimes est **refusé** (`400 amount_invalid`), pas arrondi silencieusement. Le jour où des centimes sont nécessaires, migration explicite + ADR. |
| Devise | `currency` = `XAF` par défaut, champ conservé pour évolutivité |
| GPS | `DecimalField(max_digits=9, decimal_places=6)` + `gps_accuracy` (mètres) + `gps_status` (`AVAILABLE` / `DENIED` / `UNAVAILABLE`) : le refus est un état explicite, pas une valeur nulle |
| Statuts | `TextChoices` côté serveur, jamais libre côté client ; les transitions sont validées par le backend |
| Contraintes | unicité partielle sur `deleted_at IS NULL` (ex. un numéro de téléphone libéré après suppression logique peut être réutilisé) |

---

## 1. Identité, authentification, journalisation

### `User`

| Champ | Type | Contraintes |
|---|---|---|
| `id` | UUID PK | |
| `phone` | `CharField(20)` | **unique** (si non supprimé), format E.164 (`+2376XXXXXXXX`) |
| `email` | `EmailField` | **nullable**, unique si renseigné, non requis à l'inscription |
| `email_verified_at` | `DateTime` | nullable |
| `password` | hash PBKDF2/Argon2 | jamais exposé |
| `first_name`, `last_name` | `CharField` | obligatoires |
| `role` | `CharField` | rôle global, voir `docs/rbac-matrix.md` (9 rôles) |
| `is_active` | bool | `False` tant que l'OTP d'activation n'est pas validé |
| `is_phone_verified` | bool | |
| `language` | `CharField(5)` | `fr` par défaut |
| `last_login_ip`, `last_login_at` | | |
| `password_changed_at` | `DateTime` | permet d'invalider les JWT émis avant un reset |
| `failed_login_count`, `locked_until` | | verrouillage temporaire anti brute-force |
| `deleted_at` | `DateTime` | nullable |

### `OTPCode` — **aucun OTP en clair**

| Champ | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `phone` | `CharField(20)` | indexé |
| `code_hash` | `CharField(128)` | `sha256(sel + code)` — le code en clair n'est jamais persisté |
| `salt` | `CharField(64)` | |
| `purpose` | `SIGNUP` / `PASSWORD_RESET` / `EMAIL_VERIFY` | un code n'est valable que pour son usage |
| `expires_at` | `DateTime` | `OTP_TTL_SECONDS` (défaut 300 s) |
| `attempts` | int | max `OTP_MAX_ATTEMPTS` (5) |
| `consumed_at` | `DateTime` | usage unique |
| `ip_address`, `user_agent` (tronqué) | | anti-abus + journalisation |
| `created_at` | | |
| `user` | FK nullable | renseigné si le compte existe |

Index : `(phone, purpose, consumed_at, expires_at)`. Purge par tâche Celery quotidienne.

### `ActivityLog` — **immuable**

`id` · `actor` (FK nullable, `PROTECT`) · `action` (choix fermé, voir §6) · `entity_type` ·
`entity_id` · `project` (FK nullable) · `organization` (FK nullable) · `metadata` (JSON :
ancienne/nouvelle valeur pour le financier) · `ip_address` · `user_agent` · `created_at`.

Règles : **aucune suppression ni modification** au niveau application (`ActivityLog.objects.delete()`
désactivé, queryset de lecture seule) ; lecture réservée aux rôles autorisés ; pagination
obligatoire.

### `IdempotencyKey`

`key` (UUID client) · `user` · `endpoint` · `request_hash` · `response_status` ·
`response_body` · `state` (`IN_PROGRESS` / `DONE`) · `created_at` (TTL 24 h).
Contrainte : `unique(user, endpoint, key)` → garantit « une même opération répétée ne crée pas de
doublon » (MVP-009).

---

## 2. Organisations, projets, membres (Phase 3)

### `Organization`
`id` · `name` · `slug` (unique) · `type` (`PROMOTER` / `PME` / `ENGINEERING_FIRM` /
`INVESTOR` / `PUBLIC`) · `country` (`CM`) · `city` · `owner` (FK `User`) · `is_active` ·
`deleted_at`.

### `OrganizationMember`
`organization` · `user` · `role` · `is_active` · `created_at`.
Contrainte : `unique(organization, user)`.

### `Project`
`id` · `organization` (FK, **obligatoire**) · `name` · `code` (unique par organisation) ·
`description` · `location_label` · `city` · `region` · `latitude` · `longitude` ·
`geofence_radius_m` (détection « preuve hors périmètre ») · `currency` (`XAF`) ·
`budget_total` · `status` (`DRAFT` / `ACTIVE` / `ON_HOLD` / `COMPLETED` / `ARCHIVED`) ·
`progress` (calculé serveur, mis en cache) · `planned_start_date` · `planned_end_date` ·
`actual_start_date` · `actual_end_date` · `cover` · `created_by` · `deleted_at`.

### `ProjectMember`
`project` · `user` · `role` (rôle *par projet*) · `can_validate_evidence` ·
`can_manage_finance` · `is_active` · `created_at`.
Contrainte : `unique(project, user)`.

---

## 3. Jalons et tâches (Phase 4)

### `Milestone`
`project` · `title` · `description` · `status` (`PLANNED` / `IN_PROGRESS` / `DONE` / `BLOCKED` /
`CANCELLED`) · `planned_date` · `actual_date` · `order` · `weight` (pondération de l'avancement) ·
`created_by` · suppression logique (`deleted_at`).

### `Task`
`project` · `milestone` (FK nullable) · `title` · `description` · `status` (`TODO` / `IN_PROGRESS` /
`DONE` / `BLOCKED` / `CANCELLED`) · `planned_start_date` · `planned_end_date` · `actual_start_date` ·
`actual_end_date` · `progress` (0-100) · `weight` · `assignee` (FK `User` nullable) ·
`depends_on` (M2M vers `Task`, sans cycle) · `created_by` · suppression logique (`deleted_at`).

Implémentation : `apps/projects/models.py`, calcul dans `apps/projects/progress.py`.

**Règles serveur** (détaillées dans `docs/flows/planning.md`)
- `planned_start_date <= planned_end_date`, sinon `400` avec le champ `planned_end_date`.
- `actual_date` / `actual_end_date` interdites si le statut n'est pas terminal, et obligatoires
  pour `DONE`.
- `progress` borné 0-100 (deux décimales), `weight` strictement positif.
- Avancement du projet = moyenne pondérée des jalons non annulés (poids `weight`) + un groupe
  « tâches sans jalon » ; recalculé après chaque écriture de jalon ou de tâche et persisté,
  jamais accepté depuis le client.
- Tâche en retard = `planned_end_date < aujourd'hui` **et** `status != DONE/CANCELLED`.
- Les dépendances (`depends_on`) sont un graphe acyclique interne au projet (`409` sinon).

---

## 4. Preuves terrain (Phase 5/6)

### `Evidence`
`id` · `project` · `author` (`User`) · `file` · `thumbnail` · `hash_sha256` (indexé) ·
`captured_at` (horodatage appareil) · `received_at` (serveur) · `latitude` · `longitude` ·
`gps_accuracy` · `gps_status` · `device_model` · `device_platform` · `app_version` ·
`description` · `sync_status` (`PENDING` / `UPLOADING` / `SYNCED` / `FAILED` / `CONFLICT`) ·
`status` (`PENDING` / `VALIDATED` / `REJECTED` / `FLAGGED`) · `idempotency_key` · `deleted_at`.

Contraintes : `unique(project, hash_sha256)` → dédoublonnage serveur (doublon → `409
duplicate_evidence`, on renvoie l'existante). `unique(author, idempotency_key)`.

### `EvidenceValidation`
`evidence` · `actor` · `from_status` · `to_status` · `action` (`VALIDATE` / `REJECT` / `FLAG` /
`REOPEN`) · `comment` (obligatoire pour `REJECT` et `FLAG`) · `created_at`. Historique en
append-only, affiché dans l'UI.

---

## 5. Finances (Phase 7)

### `BudgetLine`
`project` · `label` · `category` · `planned_amount` · `order`.

### `Expense`
`project` · `budget_line` (nullable) · `title` · `description` · `amount` · `currency` ·
`incurred_on` · `status` (`DRAFT` / `SUBMITTED` / `APPROVED` / `REJECTED` / `PAID` / `CANCELLED`) ·
`receipt` (fichier) · `created_by` · `validated_by` · `deleted_at`.

### `Payment`
`expense` · `amount` · `paid_on` · `method` (`CASH` / `BANK_TRANSFER` / `MOBILE_MONEY` / `CHEQUE`) ·
`reference` · `created_by`.

### `FinancialTransaction` (grand livre, append-only)
`project` · `type` (`EXPENSE` / `PAYMENT` / `ADJUSTMENT` / `CANCELLATION`) · `amount` ·
`direction` (`DEBIT` / `CREDIT`) · `expense`/`payment` (FK nullable) · `balance_after` ·
`created_by` · `created_at`.

**Règles serveur**
- Toute écriture financière passe par un **service** utilisant `transaction.atomic()` +
  `select_for_update()` sur le projet/ligne budgétaire (concurrence).
- `consumed = SUM(transactions DEBIT) - SUM(CANCELLATION)`, `balance = budget - consumed` :
  calculés en SQL (`aggregate`), jamais à partir de valeurs envoyées par le client
  (tout champ de total reçu est **ignoré**).
- `consumed > budget` → alerte déterministe `BUDGET_THRESHOLD_REACHED` (seuils 80 % / 100 %).
- Annulation = contre-écriture (pas de suppression physique).

---

## 6. Notifications et exploitation (Phase 10/11)

`Notification` : `user` · `type` (`MILESTONE_VALIDATED` / `EXPENSE_SUBMITTED` /
`EVIDENCE_REJECTED` / `BUDGET_THRESHOLD_REACHED` / `PROJECT_DELAYED`) · `title` · `body` ·
`payload` (JSON) · `group_key` (regroupement) · `count` · `is_read` · `created_at`.

`CeleryTaskLog` (suivi) : `task_id` · `name` · `state` · `retries` · `error` · `created_at` ·
`updated_at`.

## 7. Événements journalisés (`ActivityLog.action`)

`USER_REGISTERED` · `OTP_SENT` · `OTP_VERIFIED` · `OTP_FAILED` · `OTP_RESEND` · `LOGIN_SUCCESS` ·
`LOGIN_FAILED` · `LOGOUT` · `TOKEN_REFRESHED` · `TOKEN_REFRESH_REJECTED` ·
`PASSWORD_RESET_REQUESTED` · `PASSWORD_RESET_FAILED` · `PASSWORD_RESET_CONFIRMED` ·
`PASSWORD_RESET_DENIED` · `PASSWORD_CHANGED` · `EMAIL_ADDED` · `EMAIL_VERIFIED` ·
`ORG_CREATED` · `ORG_UPDATED` · `PROJECT_CREATED` · `PROJECT_UPDATED` · `PROJECT_ARCHIVED` ·
`MEMBER_ADDED` · `MEMBER_ROLE_CHANGED` · `MEMBER_REMOVED` · `MILESTONE_CREATED` ·
`MILESTONE_UPDATED` · `MILESTONE_CLOSED` · `TASK_CREATED` · `TASK_UPDATED` · `TASK_CLOSED` ·
`EVIDENCE_UPLOADED` · `EVIDENCE_VALIDATED` · `EVIDENCE_REJECTED` · `EVIDENCE_FLAGGED` ·
`EXPENSE_CREATED` · `EXPENSE_UPDATED` · `EXPENSE_APPROVED` · `EXPENSE_REJECTED` ·
`PAYMENT_RECORDED` · `BUDGET_UPDATED` · `EXPORT_GENERATED`.

## 8. Diagramme relationnel (texte)

```
Organization ──< OrganizationMember >── User
     │
     └──< Project ──< ProjectMember >── User
              ├──< Milestone ──< Task ──< Task (depends_on)
              ├──< BudgetLine ──< Expense ──< Payment
              ├──< FinancialTransaction
              └──< Evidence ──< EvidenceValidation
User ──< OTPCode        User ──< ActivityLog (actor)      Project ──< ActivityLog
User ──< IdempotencyKey User ──< Notification
```
