import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { dashboardApi, type CeleryTaskLog, type OperationsSummary } from "../api/dashboard";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button } from "../components/ui";

const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "medium" });

export default function OperationsPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [tasks, setTasks] = useState<CeleryTaskLog[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (pageNumber = 1) => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, taskPage] = await Promise.all([
        dashboardApi.operationsSummary(),
        dashboardApi.operationsTasks(pageNumber),
      ]);
      setSummary(summaryData);
      setTasks(taskPage.results);
      setCount(taskPage.count);
      setPage(pageNumber);
      setHasNext(Boolean(taskPage.next));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de charger les outils d'exploitation.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!user?.capabilities.includes("view_operations")) {
    return <main className="page"><Link to="/tableau-de-bord">← Tableau de bord</Link><Alert tone="error">Cette page est réservée aux administrateurs de la plateforme.</Alert></main>;
  }

  const api = summary?.api;
  const taskCounts = summary?.tasks ?? {};

  return (
    <main className="page">
      <header className="page-header">
        <div><Link to="/tableau-de-bord">← Tableau de bord</Link><h1>Outils d'exploitation</h1><p className="subtitle">Métriques d'API et exécutions asynchrones. Accès administrateur uniquement.</p></div>
        <Button variant="ghost" onClick={() => void load(page)} loading={loading}>Actualiser</Button>
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}
      <section className="metric-grid" aria-label="Santé de l'API">
        <div className="metric"><div className="metric-label">Requêtes API</div><div className="metric-value">{api?.requests_total ?? "…"}</div></div>
        <div className="metric"><div className="metric-label">Erreurs HTTP</div><div className="metric-value">{api?.errors_total ?? "…"}</div></div>
        <div className="metric"><div className="metric-label">Erreurs serveur</div><div className="metric-value">{api?.server_errors_total ?? "…"}</div></div>
        <div className="metric"><div className="metric-label">Événements en attente</div><div className="metric-value">{summary?.pending_events ?? "…"}</div></div>
        <div className="metric"><div className="metric-label">Tâches Celery</div><div className="metric-value">{count}</div></div>
      </section>

      <section className="card">
        <div className="section-heading"><h2>État des tâches</h2><a href="/api/metrics/" target="_blank" rel="noreferrer">Snapshot JSON des métriques</a></div>
        <div className="grid">
          {Object.entries(taskCounts).map(([state, value]) => <div className="metric" key={state}><div className="metric-label">{state}</div><div className="metric-value">{value}</div></div>)}
          {!Object.keys(taskCounts).length ? <p className="field-hint">Aucune tâche journalisée.</p> : null}
        </div>
        {summary?.pending_events ? <Alert tone="warning">{summary.pending_events} événement(s) métier attendent leur distribution.</Alert> : null}
      </section>

      <section className="card">
        <h2>Temps de réponse par route</h2>
        {api?.routes.length ? (
          <div className="table-scroll"><table><thead><tr><th>Route</th><th>Requêtes</th><th>Erreurs</th><th>Moyenne</th><th>P95</th></tr></thead><tbody>
            {api.routes.slice(0, 20).map((route) => <tr key={`${route.method}:${route.route}`}><td><code>{route.method} {route.route}</code></td><td>{route.requests}</td><td>{route.errors}</td><td>{route.avg_duration_ms.toFixed(1)} ms</td><td>{route.p95_duration_ms === null ? "—" : `${route.p95_duration_ms} ms`}</td></tr>)}
          </tbody></table></div>
        ) : <p className="field-hint">Les métriques apparaîtront à mesure que les requêtes API seront observées.</p>}
      </section>

      <section className="card">
        <h2>Journal Celery <span className="badge">{count}</span></h2>
        {loading && !tasks.length ? <p className="field-hint">Chargement…</p> : null}
        {!tasks.length && !loading ? <p className="field-hint">Aucune tâche Celery exécutée.</p> : null}
        <ul className="task-log-list">
          {tasks.map((task) => <li key={task.task_id}>
            <div className="task-log-heading"><strong>{task.name}</strong><span className={`evidence-status status-${task.state.toLowerCase()}`}>{task.state}</span></div>
            <small>{task.task_id} · {task.finished_at ? dateTime.format(new Date(task.finished_at)) : task.started_at ? `Démarrée ${dateTime.format(new Date(task.started_at))}` : `En file ${task.queued_at ? dateTime.format(new Date(task.queued_at)) : ""}`}</small>
            {task.retries ? <small>Relances : {task.retries}</small> : null}
            {task.error ? <pre className="task-error">{task.error}</pre> : null}
          </li>)}
        </ul>
        <nav className="pagination-controls" aria-label="Pagination des tâches">
          <Button variant="ghost" disabled={page <= 1 || loading} onClick={() => void load(page - 1)}>Précédent</Button>
          <span>Page {page}</span>
          <Button variant="ghost" disabled={!hasNext || loading} onClick={() => void load(page + 1)}>Suivant</Button>
        </nav>
      </section>
    </main>
  );
}
