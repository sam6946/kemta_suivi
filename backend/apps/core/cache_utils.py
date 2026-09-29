"""Invalidation ciblée des fragments agrégés mis en cache."""

import logging

from django.core.cache import cache

logger = logging.getLogger("kemta.cache")


def invalidate_project_dashboard(project_id: int | None) -> None:
    if project_id is not None:
        key = f"kemta:dashboard:project:v1:{project_id}"
        try:
            cache.delete_many([key, f"{key}:finance"])
        except Exception:
            # Une panne du cache ne doit jamais annuler ni masquer une écriture métier validée.
            logger.warning("Invalidation du dashboard projet %s différée", project_id)
