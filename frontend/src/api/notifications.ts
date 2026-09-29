import { request } from "./client";
import type { Paginated } from "./organizations";

export type Notification = {
  id: number;
  event_type: string;
  project: number | null;
  project_name: string | null;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  count: number;
  is_read: boolean;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
  read_at: string | null;
  link: string | null;
};

export type NotificationPage = Paginated<Notification> & { unread_count: number };

export const notificationsApi = {
  list: (page = 1) =>
    request<NotificationPage>(`/notifications/?page=${page}`, { auth: true }),
  unreadCount: () =>
    request<{ unread_count: number }>("/notifications/unread-count/", { auth: true }),
  markRead: (id: number) =>
    request<Notification>(`/notifications/${id}/read/`, { method: "POST", auth: true }),
  markAllRead: () =>
    request<{ updated: number }>("/notifications/read-all/", { method: "POST", auth: true }),
};
