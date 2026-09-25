"""Jeu de données de **développement** : un compte de démonstration par rôle.

- Refuse de s'exécuter si `DJANGO_ENV=production` (sauf `--force`).
- Aucune donnée n'est simulée côté produit : ces comptes servent aux démos et aux tests.
- Les projets, jalons, preuves et lignes budgétaires seront ajoutés ici en phase 3 et suivantes,
  avec des montants réalistes en FCFA (voir `docs/test-plan.md` §4).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.users.models import User
from apps.users.roles import ALL_ROLES, ROLE_LABELS
from apps.users.services.phone import normalize_phone

# Mot de passe de démonstration : documenté, jamais utilisé hors développement.
DEMO_PASSWORD = "Kemta#2026Demo"

DEMO_PEOPLE = [
    ("PLATFORM_ADMIN", "+237690000001", "Awa", "Mbarga"),
    ("ORG_OWNER", "+237690000002", "Serge", "Kamdem"),
    ("PROJECT_OWNER", "+237690000003", "Arnaud", "Nkoulou"),
    ("ENGINEER", "+237690000004", "Bertrand", "Fotso"),
    ("CONTRACTOR", "+237690000005", "Chantal", "Ekwalla"),
    ("FIELD_AGENT", "+237690000006", "Didier", "Ngassa"),
    ("VALIDATOR", "+237690000007", "Estelle", "Mvondo"),
    ("FINANCE", "+237690000008", "Franck", "Biya"),
    ("INVESTOR", "+237690000009", "Georgette", "Tchoumi"),
]


class Command(BaseCommand):
    help = "Crée les comptes de démonstration (données de développement uniquement)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Autorise l'exécution même si DJANGO_ENV=production (déconseillé).",
        )
        parser.add_argument(
            "--password",
            default=DEMO_PASSWORD,
            help="Mot de passe des comptes de démonstration (développement uniquement).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if getattr(settings, "ENV", "local") == "production" and not options["force"]:
            raise CommandError(
                "Refusé : DJANGO_ENV=production. Utilisez --force en connaissance de cause."
            )

        created = 0
        for role, raw_phone, first_name, last_name in DEMO_PEOPLE:
            phone, error = normalize_phone(raw_phone)
            if error:
                raise CommandError(f"Numéro de démonstration invalide : {raw_phone} ({error})")

            user, is_new = User.objects.get_or_create(
                phone=phone,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "is_active": True,
                    "is_phone_verified": True,
                },
            )
            if is_new:
                user.set_password(options["password"])
                user.save(update_fields=["password"])
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{created} compte(s) créé(s) sur {len(DEMO_PEOPLE)}. "
                f"Mot de passe : {options['password']} (développement uniquement)."
            )
        )
        if ALL_ROLES:
            self.stdout.write("Rôles disponibles : " + ", ".join(ROLE_LABELS[r] for r in ALL_ROLES))
        self.stdout.write(
            self.style.WARNING(
                "Données de DÉVELOPPEMENT : ne pas exécuter sur une base de production."
            )
        )
