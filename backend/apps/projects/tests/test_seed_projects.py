"""Le seed de développement couvre le périmètre de la phase 3 (données réalistes en FCFA)."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMember
from apps.users.models import User


@pytest.mark.django_db
def test_seed_creates_organizations_projects_and_members():
    call_command("seed_dev", stdout=StringIO())

    assert Organization.objects.count() == 3
    assert Project.objects.count() == 4
    assert ProjectMember.objects.count() >= 15

    project = Project.objects.get(code="RBS-T1")
    assert project.organization.name == "KEMTA Promotion Douala"
    assert project.currency == "XAF"
    assert int(project.budget_total) == 85_000_000
    assert project.status == "ACTIVE"

    # Chaque projet a au moins un responsable et un agent de terrain.
    roles = set(project.members.values_list("role", flat=True))
    assert {"PROJECT_OWNER", "ENGINEER", "FIELD_AGENT", "VALIDATOR", "INVESTOR"} <= roles

    # Les budgets sont tous des entiers FCFA cohérents avec le contexte camerounais.
    for budget in Project.objects.values_list("budget_total", flat=True):
        assert budget == budget.to_integral_value()
        assert 1_000_000 <= budget <= 1_000_000_000


@pytest.mark.django_db
def test_seed_is_idempotent_for_projects():
    call_command("seed_dev", stdout=StringIO())
    call_command("seed_dev", stdout=StringIO())
    assert Organization.objects.count() == 3
    assert Project.objects.count() == 4


@pytest.mark.django_db
def test_seed_skip_projects_creates_users_only():
    call_command("seed_dev", "--skip-projects", stdout=StringIO())
    assert User.objects.count() == 9
    assert Organization.objects.count() == 0
    assert Project.objects.count() == 0
