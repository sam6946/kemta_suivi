from django.contrib import admin
from django.urls import include, path

from apps.core.dev_views import DevOutboxView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("apps.core.urls")),
    # Outils de développement : renvoient 404 hors environnement de développement.
    path("api/dev/outbox/", DevOutboxView.as_view(), name="dev-outbox"),
    path("api/auth/", include("apps.users.urls")),
    path("api/meta/", include("apps.users.urls_meta")),
]
