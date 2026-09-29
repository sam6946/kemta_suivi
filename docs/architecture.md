# Architecture — KEMTA SUIVI (MVP, phases 0–11)

## 1. Vue d'ensemble

```
┌────────────────────────┐        HTTPS         ┌──────────────────────────┐
│  Mobile / Web (PWA)    │ ───────────────────► │  Nginx (TLS, gzip,       │
│  React + TS + Vite     │                      │  static frontend, /api)  │
│  IndexedDB + file sync │ ◄─────────────────── │                          │
└────────────────────────┘                      └───────────┬──────────────┘
                                                            │
                          ┌─────────────────────────────────┴────────────────┐
                          │  Django 5 + DRF (Gunicorn, workers sync/threads) │
                          │  apps: users · projects · evidence · finance ·   │
                          │        core (activity, health, meta)             │
                          └───┬──────────────┬──────────────┬────────────────┘
                              │              │              │
                     ┌────────▼───┐   ┌──────▼──────┐  ┌───▼──────────────┐
                     │ PostgreSQL │   │ Redis       │  │ Celery worker    │
                     │ 16 (données│   │ (cache,     │  │ + beat (médias,  │
                     │ + fichiers │   │  broker, RL)│  │  notifications,  │
                     │  de ledger)│   │             │  │  purge OTP)      │
                     └────────────┘   └─────────────┘  └──────────────────┘
                                                            │
                                              ┌─────────────▼──────────────┐
                                              │ Stockage média (volume     │
                                              │ chiffré / S3-compatible)   │
                                              └────────────────────────────┘
```

**Choix structurants**

| Sujet | Décision | Raison |
|---|---|---|
| Backend | Django 5 + DRF, apps par domaine | admin gratuit, ORM solide, `transaction.atomic()`, écosystème auth |
| Base | PostgreSQL 16 | contraintes d'unicité partielle, `select_for_update`, JSONB |
| Cache / broker | Redis 7 | un seul composant pour cache, rate limiting et Celery |
| Async | Celery (worker + beat) | médias, SMS, notifications, purge OTP |
| Frontend | React 18 + TypeScript + Vite, PWA | offline-first (`idb` : file IndexedDB + binaire des photos), code splitting |
| API | REST JSON (pas de GraphQL) | simplicité, cache HTTP, contrôle fin des permissions |
| Auth | JWT (access 15 min + refresh 7 j rotatif) + OTP SMS | conforme aux flux du backlog |

## 2. Docker Compose

Développement : `db` (PostgreSQL 16), `redis` (Redis 7), `web` (Django), `worker`, `beat` et
`frontend` (Vite/HMR). La commande `./dev.sh` choisit Docker si le daemon est disponible, sinon
elle démarre le backend SQLite et Vite localement. La seed `seed_dev` n'est destinée qu'au local.

Production : superposer `docker-compose.prod.yml` à la base avec
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. Docker Compose
v2.24+ est requis pour `!reset`, qui retire les bind mounts et ports de développement hérités.
Le frontend sert Nginx/TLS, tandis que l'API, PostgreSQL, Redis et ClamAV restent privés. Les
certificats TLS sont provisionnés avant le démarrage. Les secrets ne sont **jamais** dans l'image ;
`SECRET_KEY`, les identifiants DB/SMS et les domaines viennent de `.env` ou d'un gestionnaire de
secrets. L'absence de configuration de production requise fait échouer le démarrage (fail-fast).

## 3. Configuration

`config/settings.py` est piloté par variables d'environnement (django-environ) :
`DJANGO_ENV` (`local`|`test`|`production`) · `DEBUG` · `ALLOWED_HOSTS` · `DATABASE_URL` ·
`REDIS_URL` · `CELERY_BROKER_URL` · `SECRET_KEY` · `SMS_PROVIDER` (`console` en dev/test,
`africastalking` en production), `SMS_USERNAME`, `SMS_API_KEY`, `SMS_SENDER_ID` · `OTP_*` ·
`CORS_ALLOWED_ORIGINS` · `MEDIA_STORAGE` · `MAX_MEDIA_*_QUOTA_MB` · `CLAMAV_*`.
En production, la clé, le fournisseur SMS HTTPS et ClamAV sont obligatoires.

En test/CI : base SQLite en mémoire, cache `LocMem`, Celery eager et SMS/email console ; aucune
infrastructure externe n'est nécessaire. `settings_test.py` force les adaptateurs locaux même si
un `.env` de développeur est présent.

## 4. Stratégie de stockage et sécurité des médias

- **Upload** : `multipart` direct vers Django (`/api/evidences/`) avec `Idempotency-Key` ; le
  serveur vérifie signature binaire, taille (10 Mo), dimensions et empreinte SHA-256.
- **Quarantaine** : evidences et justificatifs passent en statut de scan `SCANNING`. ClamAV est
  obligatoire en production ; seul un média `CLEAN` peut être téléchargé ou dérivé. Les fichiers
  infectés sont supprimés et leurs quotas/métriques sont libérés. Une tâche périodique reprend les
  scans `PENDING` ou restés `SCANNING` après la perte d'un worker.
- **Quotas** : plafonds configurables par utilisateur et projet ; les fichiers supprimés ne sont
  pas comptabilisés. Les dérivées (miniature WebP 320 px, aperçu JPEG 1080 px) sont générées hors
  requête HTTP par Celery.
- **Accès** : aucune URL publique permanente. L'API JWT vérifie l'accès au projet ; les images
  utilisées par `<img>` portent un jeton signé lié à l'utilisateur et à la preuve, expirant après
  `SIGNED_MEDIA_TOKEN_TTL_SECONDS` (300 s par défaut). Toutes les réponses sont `private, no-store`
  et `no-referrer`. Avec `MEDIA_X_ACCEL_REDIRECT=true`, Nginx ne sert que le chemin privé transmis
  par Django après le contrôle d'autorisation.
- **Déduplication/nettoyage** : `Evidence.hash_sha256` empêche les dépôts identiques par projet ;
  une tâche hebdomadaire nettoie les fichiers orphelins.

## 5. Observabilité

- **Logs structurés** : JSON sur une ligne (`timestamp`, `level`, `logger`, `request_id`, `user_id`,
  `path`, `status`, `duration_ms`, `message`) en production ; format lisible en dev.
  Interdiction absolue de journaliser : mot de passe, code OTP, hash, token, fichier. Un test
  (`test_no_secrets_in_logs`) grepe les logs de chaque parcours d'auth.
- **Healthcheck** : `GET /api/health/` vérifie app + base (`SELECT 1`) + Redis (`PING`), avec
  `checks_ms` ; `503` si une dépendance critique échoue. Utilisé par Docker `healthcheck` et
  par le supervisseur de production.
- **Métriques** : `GET /api/metrics/` est réservé à l'administrateur plateforme. Il expose le
  volume/erreurs/latence p95 par route Django (templates de routes, sans query strings), compteurs
  de synchronisation, octets et état de scan des médias, dépendances DB/Redis et états Celery.
  Redis conserve les compteurs avec cardinalité bornée ; en cas d'indisponibilité l'observabilité
  retombe en mémoire et ne bloque pas les requêtes métier.
- **Exploitation** : `/api/operations/` et `/api/operations/tasks/` exposent les événements métier
  en attente et l'historique filtrable Celery aux administrateurs plateforme seulement. Les
  arguments des tâches ne sont pas enregistrés ; les erreurs sont filtrées avant persistance.
- **Erreurs** : handler DRF unique → enveloppe d'erreur + `request_id` ; exception non gérée →
  `500` générique + log `ERROR` avec `request_id` (aucune donnée sensible dans la réponse).

## 6. Hors ligne (phase 6)

- La file d'opérations et les photos en attente vivent dans **IndexedDB** (`idb`), avec un repli
  mémoire si le navigateur refuse le stockage persistant — l'écran de suivi l'annonce alors
  explicitement au lieu de laisser croire à une sauvegarde.
- Le binaire des photos est stocké en `ArrayBuffer` (et non en `Blob`) : c'est la forme la plus
  universellement clonable par IndexedDB ; il est reconstruit en `Blob` à l'envoi.
- Les données métier du serveur ne sont pas mises en cache durablement dans le navigateur. Le
  dashboard utilise un cache serveur court (30 s par défaut) ; les mutations et preuves hors ligne
  conservent uniquement ce qui doit être rejoué.
- Toute écriture rejouable porte une clé d'idempotence ; le serveur tient le registre
  (`SyncOperation`) et rejoue la réponse d'origine plutôt que de réappliquer l'opération.

## 7. Sécurité (exigences transverses)

- Secrets uniquement par variables d'environnement ; `.env.example` documenté, `.env` ignoré.
- Cookies de refresh : `HttpOnly`, `Secure`, `SameSite=Strict` en production ; access token en
  mémoire côté client.
- Rate limiting sur auth/OTP/reset (voir `api-contract.md` §1).
- Mot de passe : validateurs Django (longueur, similitude, mots de passe courants) + refus de la
  réutilisation du mot de passe courant ; OTP haché, expiré, à usage unique.
- `SECURE_*`, `HSTS`, `X_FRAME_OPTIONS`, `CSRF_TRUSTED_ORIGINS`, `ALLOWED_HOSTS` activés en
  production ; `DEBUG=False` obligatoire en production (assertion au démarrage).
- Dépendances : `pip-audit`/`npm audit` en CI, blocage sur vulnérabilité haute.

## 8. Décisions d'architecture (ADR)

| # | Décision | Statut |
|---|---|---|
| ADR-001 | Téléphone = identifiant unique ; email facultatif | ✅ Acceptée |
| ADR-002 | Réinitialisation du mot de passe par OTP SMS (MVP-017) | ✅ Acceptée |
| ADR-003 | Montants en entiers FCFA, jamais de centimes | ✅ Acceptée |
| ADR-004 | Upload direct Django avec idempotence ; presigned URL S3 si l'échelle l'exige | ✅ Acceptée |
| ADR-005 | Africa's Talking pour SMS, via API HTTPS ; secrets et sender ID par environnement | ✅ Intégrée ; compte, KYC, sender ID et coûts à configurer |
| ADR-006 | Volume média privé en local/prod, accès autorisé par Django puis `X-Accel-Redirect` ; S3 ultérieur | ✅ Acceptée |
| ADR-007 | Procédure « numéro perdu / changement de SIM » | 🟡 À décider avant déploiement public |
| ADR-008 | Invitations par SMS (`ProjectInvitation`) | ⏭️ Hors MVP |
| ADR-009 | Gantt graphique vs planning listé | 🟡 Retour produit souhaité |
| ADR-010 | Calendrier ouvré / jours fériés camerounais pour les retards | 🟡 À décider avant exploitation métier |
| ADR-011 | Dépassement budgétaire motivé, refusé sans motif | ✅ Acceptée |
| ADR-012 | `can_manage_finance` ne donne pas le droit d'approuver/payer | ✅ Acceptée |

## 9. Arborescence du dépôt

```
backend/     config/ · apps/core, users, organizations, projects, evidences, sync, finance,
             notifications · migrations · tests · requirements*.txt · manage.py
frontend/    src/api, auth, components, pages, lib, sync · e2e/ · Vitest · Playwright
             Dockerfile · nginx.conf · vite.config.ts
Docker       docker-compose.yml · docker-compose.prod.yml · dev.sh

docs/        BACKLOG_MVP.md · architecture.md · data-model.md · rbac-matrix.md ·
             api-contract.md · offline-sync.md · test-plan.md · STATUS.md · flows/
```
