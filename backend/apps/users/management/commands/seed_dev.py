"""Jeu de données de **développement** : un compte de démonstration par rôle.

- Refuse de s'exécuter si `DJANGO_ENV=production` (sauf `--force`).
- Aucune donnée n'est simulée côté produit : ces comptes servent aux démos et aux tests.
- Les jalons, preuves et lignes budgétaires seront ajoutés ici aux phases 4 et suivantes.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify as _slugify

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


ORGANIZATIONS = [
    {
        "key": "promoteur",
        "name": "KEMTA Promotion Douala",
        "type": "PROMOTER",
        "city": "Douala",
        "owner_role": "ORG_OWNER",
    },
    {
        "key": "pme",
        "name": "BTP Kribi SARL",
        "type": "PME",
        "city": "Kribi",
        "owner_role": "CONTRACTOR",
    },
    {
        "key": "be",
        "name": "Ingénierie Littoral",
        "type": "ENGINEERING_FIRM",
        "city": "Douala",
        "owner_role": "ENGINEER",
    },
]

# Projets réalistes (contexte camerounais) — montants entiers en FCFA.
PROJECTS = [
    {
        "organization": "promoteur",
        "name": "Résidence Bonamoussadi — tranche 1",
        "code": "RBS-T1",
        "city": "Douala",
        "region": "Littoral",
        "location_label": "Bonamoussadi, avenue principale",
        "latitude": "4.089100",
        "longitude": "9.740600",
        "budget_total": 85_000_000,
        "status": "ACTIVE",
        "planned_start_date": "2026-01-12",
        "planned_end_date": "2026-12-18",
        "members": {
            "PROJECT_OWNER": {},
            "ENGINEER": {},
            "CONTRACTOR": {},
            "FIELD_AGENT": {},
            "VALIDATOR": {"can_validate_evidence": True},
            "FINANCE": {"can_manage_finance": True},
            "INVESTOR": {},
        },
    },
    {
        "organization": "promoteur",
        "name": "Immeuble Akwa — tranche 2",
        "code": "AKW-T2",
        "city": "Douala",
        "region": "Littoral",
        "location_label": "Akwa, rue Castelnau",
        "latitude": "4.051100",
        "longitude": "9.767900",
        "budget_total": 145_000_000,
        "status": "ACTIVE",
        "planned_start_date": "2026-03-02",
        "planned_end_date": "2027-06-30",
        "members": {"PROJECT_OWNER": {}, "ENGINEER": {}, "FINANCE": {"can_manage_finance": True}},
    },
    {
        "organization": "pme",
        "name": "Voie de contournement Kribi",
        "code": "VCK-01",
        "city": "Kribi",
        "region": "Sud",
        "location_label": "Entrée nord de Kribi",
        "latitude": "2.937300",
        "longitude": "9.910000",
        "budget_total": 320_000_000,
        "status": "ACTIVE",
        "planned_start_date": "2025-11-03",
        "planned_end_date": "2026-11-30",
        "members": {"PROJECT_OWNER": {}, "CONTRACTOR": {}, "FIELD_AGENT": {}},
    },
    {
        "organization": "be",
        "name": "Réhabilitation école de Nkolbisson",
        "code": "REC-NKB",
        "city": "Yaoundé",
        "region": "Centre",
        "location_label": "Nkolbisson, quartier Marché",
        "latitude": "3.872000",
        "longitude": "11.450000",
        "budget_total": 22_500_000,
        "status": "DRAFT",
        "planned_start_date": "2026-02-16",
        "planned_end_date": "2026-08-28",
        "members": {"ENGINEER": {}, "VALIDATOR": {"can_validate_evidence": True}},
    },
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
        parser.add_argument(
            "--skip-projects",
            action="store_true",
            help="Ne créer que les comptes (sans organisations, projets ni membres).",
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
        if not options["skip_projects"]:
            organizations, projects, memberships = self._seed_projects()
            self.stdout.write(
                f"{organizations} organisation(s), {projects} projet(s), "
                f"{memberships} appartenance(s) créés."
            )

        if ALL_ROLES:
            self.stdout.write("Rôles disponibles : " + ", ".join(ROLE_LABELS[r] for r in ALL_ROLES))
        self.stdout.write(
            self.style.WARNING(
                "Données de DÉVELOPPEMENT : ne pas exécuter sur une base de production."
            )
        )

    # ------------------------------------------------------------------
    # Organisations, projets et membres de démonstration (phase 3)
    # ------------------------------------------------------------------
    def _seed_projects(self) -> tuple[int, int, int]:
        from apps.organizations.models import Organization, OrganizationMember
        from apps.projects.models import Project, ProjectMember

        users_by_role = {user.role: user for user in User.objects.all()}

        def user_for(role: str):
            return users_by_role.get(role) or User.objects.filter(role=role).first()

        organizations: dict[str, Organization] = {}
        created_organizations = 0
        for spec in ORGANIZATIONS:
            owner = user_for(spec["owner_role"]) or next(iter(users_by_role.values()))
            organization, created = Organization.objects.get_or_create(
                slug=_slugify(spec["name"]),
                defaults={
                    "name": spec["name"],
                    "type": spec["type"],
                    "city": spec["city"],
                    "owner": owner,
                },
            )
            created_organizations += int(created)
            OrganizationMember.objects.get_or_create(
                organization=organization,
                user=owner,
                defaults={"role": "ORG_OWNER"},
            )
            organizations[spec["key"]] = organization

        created_projects = 0
        created_memberships = 0
        for spec in PROJECTS:
            organization = organizations[spec["organization"]]
            creator = user_for("PROJECT_OWNER") or organization.owner
            project, created = Project.objects.get_or_create(
                organization=organization,
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "city": spec["city"],
                    "region": spec["region"],
                    "location_label": spec["location_label"],
                    "latitude": spec["latitude"],
                    "longitude": spec["longitude"],
                    "budget_total": spec["budget_total"],
                    "status": spec["status"],
                    "planned_start_date": spec["planned_start_date"],
                    "planned_end_date": spec["planned_end_date"],
                    "created_by": creator,
                },
            )
            created_projects += int(created)

            for role, flags in spec["members"].items():
                member_user = user_for(role)
                if member_user is None:
                    continue
                _, membership_created = ProjectMember.objects.get_or_create(
                    project=project,
                    user=member_user,
                    defaults={"role": role, **flags},
                )
                created_memberships += int(membership_created)

        return created_organizations, created_projects, created_memberships
