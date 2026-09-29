import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { dashboardApi, type DashboardAlert, type ProjectDashboard } from "../api/dashboard";
import { Alert, Button } from "../components/ui";
import { formatDate, formatFcfa, formatPercent } from "../lib/format";

const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });
const statusLabels: Record<string, string> = {
  PENDING: "À traiter",
  SUBMITTED: "Soumise",
  APPROVED: "Validée",
  REJECTED: "Rejetée",
};

function AlertCard({ alert }: { alert: DashboardAlert }) {
  const tone = alert.severity === "critical" ? "error" : alert.severity === "warning" ? "warning" : "info";
  return <Alert tone={tone}>{alert.message}{alert.days_late ? ` (${alert.days_late} jours)` : ""}</Alert>;
}

export default function ProjectDashboardPage() {
  const { id = "" } = useParams();
  const [dashboard, setDashboard] = useState<ProjectDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDashboard(await dashboardApi.project(id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de charger le tableau du projet.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !dashboard) return <main className="page"><p>Chargement du tableau du projet…</p></main>;
  if (error && !dashboard) {
    return (
      <main className="page">
        <Alert tone="error">{error}</Alert>
        <Link to={`/projets/${id}`}>Retour au projet</Link>
      </main>
    );
  }
  if (!dashboard) return null;

  const { project, milestones, tasks, evidence, budget, expenses, alerts, activity, permissions } = dashboard;

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <Link to={`/projets/${id}`}>← {project.name}</Link>
          <h1>Tableau de bord du projet</h1>
          <p className="subtitle">{project.code} · {project.status_label} · actualisé {dateTime.format(new Date(dashboard.generated_at))}</p>
        </div>
        <Button variant="ghost" onClick={() => void load()} loading={loading}>Actualiser</Button>
      </header>

      {error ? <Alert tone="warning">{error} — les dernières données chargées sont affichées.</Alert> : null}

      <section className="metric-grid" aria-label="Indicateurs du projet">
        <div className="metric metric-featured">
          <div className="metric-label">Avancement global</div>
          <div className="metric-value">{formatPercent(project.progress)}</div>
          <div className="progress-track" role="progressbar" aria-valuenow={project.progress} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${Math.max(0, Math.min(100, project.progress))}%` }} />
          </div>
        </div>
        <div className="metric"><div className="metric-label">Jalons achevés</div><div className="metric-value">{milestones.done} / {milestones.total}</div></div>
        <div className="metric"><div className="metric-label">Tâches achevées</div><div className="metric-value">{tasks.done} / {tasks.total}</div></div>
        <div className="metric"><div className="metric-label">Preuves terrain</div><div className="metric-value">{evidence.total}</div></div>
        <div className="metric"><div className="metric-label">Retards actifs</div><div className="metric-value">{milestones.late + tasks.late}</div></div>
      </section>

      <div className="dashboard-columns">
        <section className="card">
          <div className="section-heading"><h2>Échéances</h2><Link to={`/projets/${id}#planning`}>Voir le planning</Link></div>
          <div className="timeline-grid">
            <div className="timeline-item">
              <span className="eyebrow">Jalon précédent achevé</span>
              {milestones.last ? <><strong>{milestones.last.title}</strong><span>{formatDate(milestones.last.actual_date)}</span></> : <span>Aucun jalon terminé.</span>}
            </div>
            <div className="timeline-item">
              <span className="eyebrow">Prochain jalon</span>
              {milestones.next ? <><strong>{milestones.next.title}</strong><span>{formatDate(milestones.next.planned_date)} · {milestones.next.days_remaining >= 0 ? `${milestones.next.days_remaining} j restants` : `${Math.abs(milestones.next.days_remaining)} j de retard`}</span></> : <span>Aucun jalon à venir.</span>}
            </div>
          </div>
        </section>

        {permissions.view_finance && budget ? (
          <section className="card">
            <div className="section-heading"><h2>Budget</h2><Link to={`/projets/${id}#finances`}>Voir les finances</Link></div>
            <div className="metric-grid metric-grid-compact">
              <div className="metric"><div className="metric-label">Budget prévu</div><div className="metric-value">{formatFcfa(budget.planned)}</div></div>
              <div className="metric"><div className="metric-label">Engagé</div><div className="metric-value">{formatFcfa(budget.committed)}</div></div>
              <div className="metric"><div className="metric-label">Payé</div><div className="metric-value">{formatFcfa(budget.paid)}</div></div>
              <div className="metric"><div className="metric-label">Solde</div><div className="metric-value">{formatFcfa(budget.balance)}</div></div>
            </div>
            <p className="field-hint">Taux d'engagement : {formatPercent(budget.consumption_rate)} · {expenses.pending_review ?? 0} dépense(s) à valider</p>
            {expenses.recent.length ? <ul className="compact-list">{expenses.recent.map((expense) => <li key={expense.id}><span>{expense.title}<small>{formatDate(expense.incurred_on)} · {statusLabels[expense.status] ?? expense.status}</small></span><strong>{formatFcfa(expense.amount)}</strong></li>)}</ul> : <p className="field-hint">Aucune dépense enregistrée.</p>}
          </section>
        ) : null}
      </div>

      <section className="card">
        <div className="section-heading"><h2>Alertes et risques</h2><span className="badge">{alerts.length}</span></div>
        {alerts.length ? alerts.map((alert, index) => <AlertCard key={`${alert.code}-${index}`} alert={alert} />) : <p className="field-hint">Aucun retard ni seuil budgétaire dépassé.</p>}
      </section>

      <section className="card">
        <div className="section-heading"><h2>Preuves terrain récentes</h2><Link to={`/projets/${id}/preuves`}>Ouvrir les preuves</Link></div>
        {evidence.recent.length ? (
          <ul className="evidence-preview-list">
            {evidence.recent.map((item) => (
              <li key={item.id}>
                {item.thumbnail ? <a href={item.thumbnail} target="_blank" rel="noreferrer"><img src={item.thumbnail} alt="Aperçu de la preuve" loading="lazy" /></a> : <div className="image-placeholder">{item.media_ready ? "Document" : "Analyse antivirus en cours"}</div>}
                <div><strong>{item.description || "Preuve sans description"}</strong><small>{formatDate(item.captured_at)} · {statusLabels[item.status] ?? item.status} · {item.author.first_name} {item.author.last_name}</small></div>
              </li>
            ))}
          </ul>
        ) : <p className="field-hint">Aucune preuve n'a encore été déposée.</p>}
      </section>

      {permissions.view_activity ? (
        <section className="card">
          <div className="section-heading"><h2>Activité récente</h2><Link to={`/projets/${id}/activite`}>Journal complet</Link></div>
          {activity.length ? <ul className="activity-list">{activity.slice(0, 5).map((item) => <li key={item.id}><span><strong>{item.action.replaceAll("_", " ").toLocaleLowerCase("fr-FR")}</strong><small>{item.actor ? `${item.actor.first_name} ${item.actor.last_name}` : "Système"} · {dateTime.format(new Date(item.created_at))}</small></span><span className="field-hint">{item.entity_type} #{item.entity_id}</span></li>)}</ul> : <p className="field-hint">Aucune activité enregistrée.</p>}
        </section>
      ) : null}

      <footer className="page-footer"><span>Budget initial : {formatFcfa(project.budget_total)}</span><span>Fin prévue : {formatDate(project.planned_end_date)}</span></footer>
    </main>
  );
}
