# Stratégie offline-first, synchronisation et cache (Phase 0 — implémentée en phase 6)

> **État au terme de la phase 5** : le socle serveur de la synchronisation est en place et testé —
> `Idempotency-Key` **obligatoire** sur `POST /api/evidences/` (rejeu → même preuve, en-tête
> `Idempotency-Replayed: true`), dédoublonnage par `hash_sha256` par projet (`409
> duplicate_evidence` avec la preuve existante), empreinte calculée **sur l'appareil** avant envoi et
> `sync_status` exposé par l'API. La file locale (IndexedDB) et `POST /api/sync/batch/` restent à
> construire en phase 6 ; aucun changement de contrat n'est requis. Voir `docs/flows/evidences.md` §7.

Contexte : réseau 3G intermittent, chantiers hors zone de couverture, téléphones Android
d'entrée/milieu de gamme. **Aucune action terrain critique ne doit dépendre d'une requête
immédiate.**

## 1. Ce qui est disponible hors ligne / en ligne

| Action | Hors ligne | Mécanisme |
|---|---|---|
| Capturer une preuve (photo + GPS + métadonnées) | ✅ | écriture IndexedDB + fichier dans OPFS/IndexedDB Blob |
| Consulter ses projets, jalons, tâches, preuves | ✅ | cache de lecture (IndexedDB) |
| Créer/modifier une tâche ou un jalon | ✅ | file d'opérations |
| Voir un dashboard | ⚠️ lecture seule | dernier snapshot mis en cache, bandeau « données du … » |
| S'inscrire, se connecter, valider un OTP | ❌ | erreur explicite réessayable |
| **Réinitialiser son mot de passe** | ❌ | nécessite un SMS + validation serveur immédiate (MVP-017) |
| Valider/rejeter une preuve d'un tiers | ⚠️ mise en file | appliquée au retour réseau, conflit possible |

Règle produit : une action non réalisable hors ligne n'est **jamais** silencieusement mise en
file : l'UI affiche « Connexion requise » + bouton Réessayer.

## 2. Stockage local (IndexedDB, via `idb`)

| Store | Contenu | Clé |
|---|---|---|
| `outbox` | opérations à synchroniser | `opId` (UUID) |
| `evidence_drafts` | métadonnées + blob de la preuve locale | `localId` |
| `projects`, `milestones`, `tasks`, `evidences` | cache de lecture (SWR) | `id` |
| `dashboards` | dernier snapshot par projet | `projectId` |
| `meta` | rôles, statuts, version du schéma, `lastSyncAt` | `key` |

Versionnement du schéma (`meta.schemaVersion`) avec migration explicite au démarrage ; en cas de
schéma inconnu, purge et resynchronisation (jamais de perte de `outbox` : on la conserve
séparément).

## 3. File de synchronisation

### Statuts locaux
`PENDING` → `UPLOADING` → `SYNCED` ; échec → `FAILED` (relançable) ; divergence détectée →
`CONFLICT`.

### Format d'une opération
```json
{ "opId": "uuid", "type": "EVIDENCE_CREATE", "entity": "evidence",
  "localId": "uuid", "projectId": "uuid", "idempotencyKey": "uuid",
  "method": "POST", "path": "/api/evidences/", "body": { … },
  "attachments": [{ "field": "file", "blobKey": "…", "hash": "sha256…" }],
  "attempts": 0, "nextAttemptAt": 0, "lastError": null, "status": "PENDING" }
```

### Cycle de vie
1. **Écriture locale immédiate** → l'UI affiche la preuve avec son statut local
   (`En attente de synchronisation`).
2. **Déclenchement** : événement `online`, retour de visibilité de l'onglet/app, fin d'une
   opération précédente, ou action manuelle « Synchroniser ». Aucune action utilisateur
   obligatoire.
3. **Upload** en `multipart`, une opération à la fois pour les pièces jointes (reprise possible),
   en lot (`POST /api/sync/batch/`) pour les opérations sans fichier.
4. **Backoff exponentiel** : `min(30s, 1s × 2^attempts)` avec gigue ±20 %, `max_attempts = 8`
   (configurable). Après la limite : `FAILED`, visible et relançable à la main.
5. **Reprise après interruption** : si la connexion coupe en plein `UPLOADING`, l'opération
   repasse `PENDING` (l'`Idempotency-Key` identique garantit qu'aucun doublon ne sera créé côté
   serveur). Un rechargement de l'application recharge la file telle quelle.

### Idempotence et déduplication
- `idempotencyKey` UUID v4 généré **côté client à la création de l'opération locale**, conservé
  après rechargement (persisté dans `outbox`).
- Le serveur stocke `(user, endpoint, key)` : une clé déjà `DONE` renvoie la réponse d'origine ;
  une clé `IN_PROGRESS` renvoie `409 op_in_progress` (le client réessaie plus tard, sans créer de
  doublon).
- `hash_sha256` du fichier calculé **côté client** (Web Crypto, `SubtleCrypto.digest`) et
  recalculé côté serveur : `(project, hash)` unique → doublon détecté même sans clé d'idempotence.

### Conflits
| Cas | Règle documentée |
|---|---|
| Preuve déjà supprimée / projet archivé côté serveur | `409` → opération `CONFLICT`, l'utilisateur choisit : abandonner ou conserver une copie locale |
| Statut de preuve changé par un validateur pendant l'upload | **le serveur gagne** ; l'UI affiche le nouveau statut et l'historique |
| Champs de tâche modifiés des deux côtés | last-write-wins sur `updated_at`, avec `ActivityLog` des deux versions ; les champs financiers ne sont **jamais** modifiables offline |
| Montant de dépense modifié offline | **interdit** : les écritures financières nécessitent le réseau (intégrité d'abord) |
| Doublon de fichier | `409 duplicate_evidence` → l'existante est affichée, l'opération passe `SYNCED` (sans doublon) |

Toute règle de conflit est testée ; aucun conflit n'est résolu silencieusement sans historique.

## 4. Interface de suivi

Écran « Synchronisation » + badge global : nombre d'éléments `PENDING`/`FAILED`/`CONFLICT`,
dernière synchro, bouton « Tout relancer », détail par élément (type, projet, erreur, tentative).
Les preuves non synchronisées sont marquées dans la galerie. Les erreurs sont comptabilisées
(métrique `sync_failed_total`) et journalisées côté client (niveau `warn`, sans données
personnelles).

## 5. Stratégie de cache

### Serveur (Redis)
| Donnée | Clé | TTL | Invalidation |
|---|---|---|---|
| Dashboard projet | `dash:{project_id}:{role}` | 60 s | signal `post_save` sur `Task`/`Milestone`/`Expense`/`Evidence` |
| Compteurs projet (tâches, preuves) | `counts:{project_id}` | 30 s | idem |
| Rôles / statuts (`/api/meta/`) | `meta:roles`, `meta:status` | 1 h | redéploiement |
| Compteurs de rate limiting | `rl:{scope}:{key}` | fenêtre | — |
| Verrou de tâche | `lock:{task}` | court | — |

Pas de cache sur les données financières brutes (source de vérité = SQL) ; le cache ne concerne
que des agrégats reconstruisibles. En cas d'indisponibilité Redis, l'application **dégrade en
mode sans cache** (jamais d'erreur 500 pour une panne de cache).

### Client
- SWR : affichage immédiat du cache + revalidation en arrière-plan au focus/retour en ligne.
- Pas de polling automatique inférieur à 30 s ; pas de WebSocket dans le MVP.
- Code splitting par route, images servies en `thumbnail` dans les listes, `loading="lazy"`.

## 6. Performance cible (réseau 3G simulé, environnement de référence)

| Parcours | Cible |
|---|---|
| Premier rendu dashboard (cache froid) | < 3 s, **≤ 3 requêtes réseau** |
| Dashboard en cache | < 500 ms |
| Capture + mise en file d'une preuve (hors ligne) | < 2 s |
| Upload d'une preuve compressée (≈ 300 Ko, 3G) | < 10 s |
| Nombre de requêtes SQL du dashboard | ≤ 12 (asserté en test) |

Mesures reproductibles via `docs/test-plan.md` ; résultats consignés dans
`docs/performance.md` (à créer en Phase 11).
