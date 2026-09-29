from django.contrib import admin

from apps.notifications.models import BusinessEvent, CeleryTaskLog, Notification


@admin.register(BusinessEvent)
class BusinessEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_type",
        "project",
        "entity_type",
        "entity_id",
        "created_at",
        "dispatched_at",
    )
    list_filter = ("event_type", "dispatched_at")
    search_fields = ("entity_id", "dedupe_key")
    readonly_fields = [field.name for field in BusinessEvent._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "event_type", "project", "count", "read_at", "last_seen_at")
    list_filter = ("event_type", "read_at")
    search_fields = ("recipient__phone", "title", "group_key")
    readonly_fields = [field.name for field in Notification._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CeleryTaskLog)
class CeleryTaskLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "state", "retries", "task_id")
    list_filter = ("state", "name")
    search_fields = ("task_id", "name", "error")
    readonly_fields = [field.name for field in CeleryTaskLog._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
