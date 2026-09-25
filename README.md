# kemta_suivi

Suivi de chantier (Cameroun) : preuves terrain offline-first, gestion de projets, budget FCFA.

## Documentation

| Document | Contenu |
|---|---|
| [`docs/BACKLOG_MVP.md`](docs/BACKLOG_MVP.md) | Backlog MVP priorisé, phases 0 → 11, fonctionnalités MVP-001 → MVP-018, définition de terminé commune |
| [`docs/flows/authentication.md`](docs/flows/authentication.md) | Flux inscription, OTP, connexion, **réinitialisation du mot de passe (MVP-017)**, journalisation d'authentification |

## Périmètre d'authentification

- Identifiant principal : **numéro de téléphone** (normalisé E.164). L'email est facultatif.
- Preuve de possession du numéro : **OTP SMS** haché, expirable, à usage unique, limité.
- Connexion : téléphone + mot de passe → JWT (access court + refresh rotatif).
- **Mot de passe oublié : réinitialisation par OTP SMS (P0, MVP-017)** — révocation des sessions
  actives, SMS de confirmation, journalisation, aucune énumération de compte.

## État du dépôt

Phase 0 (cadrage) en cours : modèles, matrice des rôles, contrat API et stratégie offline restent
à rédiger. Aucun code applicatif pour le moment.
