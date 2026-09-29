import { request } from "./client";
import type { Paginated } from "./organizations";

export type DashboardAlert = {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  days_late?: number;
};

export type ProjectDashboard = {
  project: {
    id: number;
    name: string;
    code: string;
    status: string;
    status_label: string;
    currency: "XAF";
    progress: number;
    budget_total: number;
    planned_start_date: string | null;
    planned_end_date: string | null;
  };
  milestones: {
    total: number;
    done: number;
    late: number;
    last: { id: number; title: string; status: string; actual_date: string } | null;
    next: { id: number; title: string; status: string; planned_date: string; days_remaining: number } | null;
  };
  tasks: { total: number; done: number; late: number };
  evidence: {
    total: number;
    counts: Record<string, number>;
    recent: {
      id: number;
      status: string;
      description: string;
      captured_at: string;
      author: { id: number; first_name: string; last_name: string };
      media_ready: boolean;
      has_thumbnail: boolean;
      thumbnail: string | null;
    }[];
  };
  budget: {
    planned: number;
    allocated: number;
    unallocated: number;
    committed: number;
    paid: number;
    outstanding: number;
    balance: number;
    consumption_rate: number;
    threshold: "OK" | "WARNING" | "EXCEEDED";
    currency: "XAF";
    alerts: DashboardAlert[];
  } | null;
  expenses: {
    count: number | null;
    pending_review: number | null;
    recent: { id: number; title: string; amount: number; status: string; incurred_on: string }[];
  };
  alerts: DashboardAlert[];
  activity: ActivityEntry[];
  permissions: {
    view_finance: boolean;
    view_activity: boolean;
    capture_evidence: boolean;
    validate_evidence: boolean;
  };
  generated_at: string;
};

export type ActivityEntry = {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string;
  organization: number | null;
  project: number | null;
  actor: { id: number; first_name: string; last_name: string; role: string } | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type OperationsSummary = {
  tasks: Record<string, number>;
  pending_events: number;
  api: {
    requests_total: number;
    errors_total: number;
    server_errors_total: number;
    routes: {
      method: string;
      route: string;
      requests: number;
      errors: number;
      server_errors: number;
      avg_duration_ms: number;
      p95_duration_ms: number | null;
    }[];
    counters: Record<string, number>;
  };
};

export type CeleryTaskLog = {
  task_id: string;
  name: string;
  state: string;
  retries: number;
  error: string;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export const dashboardApi = {
  project: (projectId: string | number) =>
    request<ProjectDashboard>(`/projects/${projectId}/dashboard/`, { auth: true }),
  activity: (projectId: string | number, page = 1, action = "") => {
    const query = new URLSearchParams({ page: String(page) });
    if (action) query.set("action", action);
    return request<Paginated<ActivityEntry>>(
      `/projects/${projectId}/activity/?${query.toString()}`,
      { auth: true },
    );
  },
  operationsSummary: () => request<OperationsSummary>("/operations/", { auth: true }),
  operationsTasks: (page = 1) =>
    request<Paginated<CeleryTaskLog>>(`/operations/tasks/?page=${page}`, { auth: true }),
};
