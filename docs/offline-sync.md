# File terrain hors ligne et synchronisation — MVP-009

## État livré

Le mode offline protège d'abord l'action terrain la plus critique : **conserver une preuve photo
prise sans réseau, puis l'envoyer automatiquement au retour de la connexion**. Les lectures serveur
ne sont pas répliquées dans IndexedDB : le projet, le planning, les finances et le dashboard
nécessitent une connexion. L'API de synchronisation accepte aussi des opérations de planning, mais
l'interface actuelle ne les met pas en file ; les écrans de planning et de finances restent en ligne.

Le parcours E2E offline/online est spécifié dans le backlog mais n'a pas été exécuté dans cet
environnement faute de Chromium. Les règles de file/reprise sont couvertes par Vitest et les tests
API/backend.

## 1. Actions hors ligne

| Action | Disponibilité | Comportement |
|---|---|---|
| Capturer et décrire une preuve | ✅ | photo compressée, GPS explicite s'il est disponible, écriture locale de la preuve + métadonnées |
| Afficher les preuves locales en attente | ✅ | galerie du projet, distincte des preuves confirmées par le serveur |
| Synchroniser une preuve | ✅ | reprise automatique au lancement, au retour `online`, à la visibilité de l'onglet ou manuellement |
| Consulter projets, planning, finances, dashboard | ❌ | pas de cache métier local ; message de connexion requis |
| Créer/modifier planning ou finance depuis l'interface | ❌ | les formulaires nécessitent le réseau ; les écritures financières ne sont jamais mises en file silencieusement |
| Authentification, OTP et reset MVP-017 | ❌ | opérations serveur/SMS immédiates ; bouton de nouvelle tentative |

## 2. Stockage local

`frontend/src/lib/db.ts` ouvre une base IndexedDB `kemta-suivi`, versionnée, avec un seul store
`outbox`. Chaque opération garde un identifiant local, son projet, son statut, son nombre d'essais,
sa prochaine échéance et sa clé d'idempotence. Pour une photo, le binaire est conservé sous forme
d'`ArrayBuffer` et reconstruit en `Blob` à l'envoi ; aucune copie des données métier du serveur
n'est stockée.

Si IndexedDB n'est pas disponible, un repli mémoire permet de continuer la session courante, mais
l'interface indique que les données ne survivront pas au rechargement.

## 3. Envoi et idempotence

- Une capture hors ligne crée une opération locale `EVIDENCE_UPLOAD`. Elle garde la même
  `idempotencyKey` à chaque tentative et le hash SHA-256 du fichier compressé.
- À l'envoi, le client utilise `POST /api/evidences/` en multipart avec `Idempotency-Key`. Le
  serveur vérifie le fichier et son hash ; un rejeu renvoie la preuve existante plutôt que d'en
  créer une autre.
- `POST /api/sync/batch/` traite les opérations **sans fichier**, chacune isolément et de façon
  idempotente. Types pris en charge par l'API : `TASK_UPDATE`, `TASK_CREATE`, `MILESTONE_UPDATE`,
  `MILESTONE_CREATE`, `EVIDENCE_TRANSITION`. Leur mise en file depuis le frontend n'est pas encore
  activée ; les captures de preuves restent la seule opération actuellement ajoutée offline par
  l'interface.
- Le registre backend `SyncOperation` garantit une seule application par utilisateur/clé. Une
  réponse déjà appliquée est rejouée ; une clé bloquée `IN_PROGRESS` peut être libérée
  explicitement depuis l'écran de synchronisation.

## 4. Reprise, conflits et suivi

États locaux : `PENDING` → `UPLOADING` → `SYNCED`, `FAILED` (relançable) ou `CONFLICT` (décision
utilisateur). Les erreurs réseau/5xx déclenchent un backoff exponentiel plafonné à 30 secondes,
avec gigue et un maximum de 8 tentatives. Une seule reprise est programmée par opération ; aucun
polling réseau permanent n'est utilisé.

Les conflits métier (permission, transition impossible, preuve supprimée ou doublon de contenu)
ne sont pas rejoués en boucle : le motif est affiché et l'utilisateur peut relancer après correction
ou abandonner l'opération. Les fichiers sont envoyés un par un ; ils ne transitent pas dans le lot
`/api/sync/batch/`.

L'écran `/synchronisation` et le badge global affichent hors-ligne/en attente/échecs/conflits,
permettent la relance ou l'abandon et signalent si le stockage n'est pas persistant. La galerie
présente les preuves locales en attente séparément des preuves serveur.

## 5. Cache et limites

Le navigateur ne met pas en cache les projets, tâches, finances ou dashboard. Le dashboard utilise
un cache **serveur** court et invalidé après les écritures métier ; ce cache n'est pas une copie
offline accessible au téléphone. La reprise réelle doit être vérifiée avec un navigateur Chromium
et, avant validation terrain, sur appareil mobile pour les permissions caméra/GPS et les coupures
réseau.

Tests unitaires/API associés : `frontend/src/lib/__tests__/outbox.test.ts`,
`frontend/src/sync/__tests__/SyncProvider.test.tsx`, `frontend/src/pages/__tests__/SyncPage.test.tsx`,
`frontend/src/pages/__tests__/ProjectEvidences.test.tsx`, `backend/apps/sync/tests/test_batch.py`.
