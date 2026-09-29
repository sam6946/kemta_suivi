from rest_framework import serializers

from apps.notifications.models import CeleryTaskLog, Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    link = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event_type",
            "project",
            "project_name",
            "title",
            "body",
            "payload",
            "count",
            "is_read",
            "created_at",
            "updated_at",
            "last_seen_at",
            "read_at",
            "link",
        ]
        read_only_fields = fields

    def get_link(self, obj) -> str | None:
        project_id = (obj.payload or {}).get("project_id") or obj.project_id
        return f"/projets/{project_id}/tableau-de-bord" if project_id else None


class CeleryTaskLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeleryTaskLog
        fields = [
            "task_id",
            "name",
            "state",
            "retries",
            "error",
            "queued_at",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
