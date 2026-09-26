"""Jeu de données de **développement** : un compte de démonstration par rôle.

- Refuse de s'exécuter si `DJANGO_ENV=production` (sauf `--force`).
- Aucune donnée n'est simulée côté produit : ces comptes servent aux démos et aux tests.
- Organisations, projets, membres, jalons et tâches de démonstration.
- Les preuves terrain et les lignes budgétaires seront ajoutées aux phases 5 et 7.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
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


# Planning de démonstration : offsets en jours par rapport à aujourd'hui (dates cohérentes et
# retards reproductibles), poids de pondération, responsables désignés par rôle.
PLANNING = {
    "RBS-T1": [
        {
            "title": "Installation de chantier",
            "status": "DONE",
            "planned_offset": -120,
            "actual_offset": -118,
            "weight": 1,
            "tasks": [
                {
                    "title": "Clôture et base vie",
                    "status": "DONE",
                    "weight": 1,
                    "start_offset": -120,
                    "end_offset": -114,
                    "actual_offset": -113,
                    "role": "FIELD_AGENT",
                },
                {
                    "title": "Raccordement eau et électricité",
                    "status": "DONE",
                    "weight": 1,
                    "start_offset": -115,
                    "end_offset": -108,
                    "actual_offset": -107,
                    "role": "CONTRACTOR",
                },
            ],
        },
        {
            "title": "Fondations et soubassement",
            "status": "DONE",
            "planned_offset": -60,
            "actual_offset": -52,
            "weight": 2,
            "tasks": [
                {
                    "title": "Terrassement",
                    "status": "DONE",
                    "weight": 2,
                    "start_offset": -100,
                    "end_offset": -75,
                    "actual_offset": -74,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Semelles et longrines",
                    "status": "DONE",
                    "weight": 3,
                    "start_offset": -74,
                    "end_offset": -58,
                    "actual_offset": -52,
                    "role": "CONTRACTOR",
                },
            ],
        },
        {
            "title": "Élévation des niveaux",
            "status": "IN_PROGRESS",
            "planned_offset": 45,
            "weight": 3,
            "tasks": [
                {
                    "title": "Poteaux niveau 1",
                    "status": "DONE",
                    "weight": 2,
                    "start_offset": -50,
                    "end_offset": -30,
                    "actual_offset": -29,
                    "role": "CONTRACTOR",
                },
                # Tâche en retard : fin prévue dépassée, statut non terminal.
                {
                    "title": "Dalle niveau 2",
                    "status": "IN_PROGRESS",
                    "progress": 60,
                    "weight": 3,
                    "start_offset": -28,
                    "end_offset": -5,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Maçonnerie niveau 2",
                    "status": "IN_PROGRESS",
                    "progress": 20,
                    "weight": 2,
                    "start_offset": -10,
                    "end_offset": 20,
                    "role": "CONTRACTOR",
                },
            ],
        },
        {
            "title": "Second œuvre et réception",
            "status": "PLANNED",
            "planned_offset": 150,
            "weight": 2,
            "tasks": [
                {
                    "title": "Électricité et plomberie",
                    "status": "TODO",
                    "weight": 2,
                    "start_offset": 30,
                    "end_offset": 90,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Visite de réception",
                    "status": "TODO",
                    "weight": 1,
                    "start_offset": 130,
                    "end_offset": 150,
                    "role": "VALIDATOR",
                },
            ],
        },
    ],
    "AKW-T2": [
        {
            "title": "Études d'exécution",
            "status": "DONE",
            "planned_offset": -90,
            "actual_offset": -85,
            "weight": 1,
            "tasks": [
                {
                    "title": "Plans béton armé",
                    "status": "DONE",
                    "weight": 2,
                    "start_offset": -90,
                    "end_offset": -70,
                    "actual_offset": -68,
                    "role": "ENGINEER",
                },
            ],
        },
        {
            "title": "Gros œuvre",
            "status": "IN_PROGRESS",
            "planned_offset": 60,
            "weight": 4,
            "tasks": [
                {
                    "title": "Fondations spéciales",
                    "status": "DONE",
                    "weight": 3,
                    "start_offset": -65,
                    "end_offset": -35,
                    "actual_offset": -33,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Structure niveau 1",
                    "status": "IN_PROGRESS",
                    "progress": 45,
                    "weight": 3,
                    "start_offset": -30,
                    "end_offset": 25,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Essais béton 28 jours",
                    "status": "TODO",
                    "weight": 1,
                    "start_offset": 5,
                    "end_offset": 40,
                    "role": "ENGINEER",
                    "depends_on": ["Structure niveau 1"],
                },
            ],
        },
        {
            "title": "Clos et couvert",
            "status": "PLANNED",
            "planned_offset": 210,
            "weight": 2,
            "tasks": [
                {
                    "title": "Charpente et couverture",
                    "status": "TODO",
                    "weight": 2,
                    "start_offset": 80,
                    "end_offset": 140,
                    "role": "CONTRACTOR",
                },
            ],
        },
    ],
    "VCK-01": [
        {
            "title": "Ouverture de la plateforme",
            "status": "DONE",
            "planned_offset": -150,
            "actual_offset": -140,
            "weight": 2,
            "tasks": [
                {
                    "title": "Débroussaillage",
                    "status": "DONE",
                    "weight": 2,
                    "start_offset": -150,
                    "end_offset": -120,
                    "actual_offset": -118,
                    "role": "CONTRACTOR",
                },
            ],
        },
        {
            # Jalon en retard : date prévue dépassée, statut non terminal.
            "title": "Terrassement général",
            "status": "IN_PROGRESS",
            "planned_offset": -12,
            "weight": 3,
            "tasks": [
                {
                    "title": "Décapage PK0 à PK2",
                    "status": "DONE",
                    "weight": 2,
                    "start_offset": -110,
                    "end_offset": -80,
                    "actual_offset": -78,
                    "role": "CONTRACTOR",
                },
                {
                    "title": "Remblais PK2 à PK5",
                    "status": "IN_PROGRESS",
                    "progress": 35,
                    "weight": 3,
                    "start_offset": -70,
                    "end_offset": 30,
                    "role": "CONTRACTOR",
                },
            ],
        },
        {
            "title": "Couche de fondation",
            "status": "PLANNED",
            "planned_offset": 120,
            "weight": 2,
            "tasks": [
                {
                    "title": "Grave non traitée",
                    "status": "TODO",
                    "weight": 2,
                    "start_offset": 35,
                    "end_offset": 100,
                    "role": "CONTRACTOR",
                },
            ],
        },
    ],
    "REC-NKB": [
        {
            "title": "Réception du chantier",
            "status": "PLANNED",
            "planned_offset": 25,
            "weight": 1,
            "tasks": [
                {
                    "title": "Relevé de l'état des lieux",
                    "status": "TODO",
                    "weight": 1,
                    "start_offset": 5,
                    "end_offset": 15,
                    "role": "ENGINEER",
                },
            ],
        },
    ],
}


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
            organizations, projects, memberships, milestones, tasks = self._seed_projects()
            self.stdout.write(
                f"{organizations} organisation(s), {projects} projet(s), "
                f"{memberships} appartenance(s), {milestones} jalon(s), {tasks} tâche(s) créés."
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
    @staticmethod
    def _day(offset):
        """Date relative à aujourd'hui : les retards de démonstration restent stables."""
        if offset is None:
            return None
        return timezone.localdate() + timedelta(days=offset)

    @transaction.atomic
    def _seed_planning(self, projects_by_code: dict) -> tuple[int, int]:
        """Jalons et tâches de démonstration, idempotents (clé : projet + titre)."""
        from decimal import Decimal

        from apps.projects.models import Milestone, ProjectMember, Task
        from apps.projects.progress import recalculate_project_progress

        users_by_role = {user.role: user for user in User.objects.all()}
        created_milestones = 0
        created_tasks = 0

        for code, milestones in PLANNING.items():
            project = projects_by_code.get(code)
            if project is None:
                continue
            tasks_by_title: dict[str, object] = {}
            for index, spec in enumerate(milestones):
                milestone, created = Milestone.objects.get_or_create(
                    project=project,
                    title=spec["title"],
                    defaults={
                        "status": spec["status"],
                        "planned_date": self._day(spec.get("planned_offset")),
                        "actual_date": self._day(spec.get("actual_offset")),
                        "order": index,
                        "weight": Decimal(str(spec.get("weight", 1))),
                        "created_by": project.created_by,
                    },
                )
                created_milestones += int(created)

                for task_spec in spec["tasks"]:
                    assignee = users_by_role.get(task_spec.get("role", ""))
                    # Seuls les membres actifs du projet peuvent être responsables.
                    if (
                        assignee is not None
                        and not ProjectMember.objects.filter(
                            project=project, user=assignee, is_active=True
                        ).exists()
                    ):
                        assignee = None
                    task, task_created = Task.objects.get_or_create(
                        project=project,
                        title=task_spec["title"],
                        defaults={
                            "milestone": milestone,
                            "status": task_spec["status"],
                            "planned_start_date": self._day(task_spec.get("start_offset")),
                            "planned_end_date": self._day(task_spec.get("end_offset")),
                            "actual_end_date": self._day(task_spec.get("actual_offset")),
                            "progress": Decimal(str(task_spec.get("progress", 0))),
                            "weight": Decimal(str(task_spec.get("weight", 1))),
                            "assignee": assignee,
                            "created_by": project.created_by,
                        },
                    )
                    created_tasks += int(task_created)
                    tasks_by_title[task_spec["title"]] = task

            # Dépendances posées après création (M2M), sans cycle.
            for spec in milestones:
                for task_spec in spec["tasks"]:
                    task = tasks_by_title.get(task_spec["title"])
                    for dependency_title in task_spec.get("depends_on", []):
                        dependency = tasks_by_title.get(dependency_title)
                        if task is not None and dependency is not None:
                            task.depends_on.add(dependency)

            recalculate_project_progress(project)

        return created_milestones, created_tasks

    def _seed_projects(self) -> tuple[int, int, int, int, int]:
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
        projects_by_code: dict = {}
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
            projects_by_code[spec["code"]] = project

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

        created_milestones, created_tasks = self._seed_planning(projects_by_code)

        return (
            created_organizations,
            created_projects,
            created_memberships,
            created_milestones,
            created_tasks,
        )
