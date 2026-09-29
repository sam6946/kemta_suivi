from django.urls import path

from apps.notifications.views import (
    NotificationListView,
    NotificationReadView,
    NotificationUnreadCountView,
    OperationsSummaryView,
    OperationsTaskListView,
)

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/read-all/",
        NotificationListView.as_view(),
        name="notifications-read-all",
    ),
    path(
        "notifications/unread-count/",
        NotificationUnreadCountView.as_view(),
        name="notification-unread-count",
    ),
    path("notifications/<int:pk>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("operations/", OperationsSummaryView.as_view(), name="operations-summary"),
    path("operations/tasks/", OperationsTaskListView.as_view(), name="operations-task-list"),
]
