import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { dashboardApi, type ActivityEntry } from "../api/dashboard";
import { Alert, Button } from "../components/ui";

const ACTIONS = [
  ["", "Toutes les actions"],
  ["PROJECT_CREATED", "Projet créé"],
  ["PROJECT_UPDATED", "Projet modifié"],
  ["MEMBER_ADDED", "Membre ajouté"],
  ["MEMBER_ROLE_CHANGED", "Rôle modifié"],
  ["MILESTONE_CREATED", "Jalon créé"],
  ["MILESTONE_UPDATED", "Jalon modifié"],
  ["TASK_CREATED", "Tâche créée"],
  ["TASK_STATUS_CHANGED", "Tâche mise à jour"],
  ["EVIDENCE_CAPTURED", "Preuve déposée"],
  ["EVIDENCE_VALIDATED", "Preuve validée"],
  ["EVIDENCE_REJECTED", "Preuve rejetée"],
  ["EXPENSE_SUBMITTED", "Dépense soumise"],
  ["EXPENSE_APPROVED", "Dépense approuvée"],
  ["EXPENSE_REJECTED", "Dépense rejetée"],
  ["PAYMENT_RECORDED", "Paiement enregistré"],
  ["BUDGET_THRESHOLD_REACHED", "Seuil budgétaire atteint"],
  ["BUDGET_EXCEEDED", "Budget dépassé"],
];
const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });

function labelFor(action: string) {
  return ACTIONS.find(([code]) => code === action)?.[1] ?? action.replaceAll("_", " ").toLocaleLowerCase("fr-FR");
}

export default function ProjectActivityPage() {
  const { id = "" } = useParams();
  const [results, setResults] = useState<ActivityEntry[]>([]);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrevious, setHasPrevious] = useState(false);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (pageNumber: number, selectedAction: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await dashboardApi.activity(id, pageNumber, selectedAction);
      setResults(response.results);
      setPage(pageNumber);
      setCount(response.count);
      setHasNext(Boolean(response.next));
      setHasPrevious(Boolean(response.previous));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de charger le journal d'activité.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load(1, action);
  }, [load, action]);

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <Link to={`/projets/${id}/tableau-de-bord`}>← Tableau du projet</Link>
          <h1>Journal d'activité</h1>
          <p className="subtitle">Événements métier horodatés, filtrables et en lecture seule.</p>
        </div>
        <label className="filter-control">
          <span>Action</span>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            {ACTIONS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
          </select>
        </label>
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {loading ? <p className="field-hint">Chargement…</p> : null}
      {!loading && !error && results.length === 0 ? <section className="card"><p>Aucun événement pour ce filtre.</p></section> : null}
      <section className="card">
        <p className="field-hint">{count} événement(s)</p>
        <ol className="activity-list activity-full-list">
          {results.map((item) => <li key={item.id}>
            <span className="activity-marker" aria-hidden="true" />
            <div className="activity-copy">
              <strong>{labelFor(item.action)}</strong>
              <small>{item.actor ? `${item.actor.first_name} ${item.actor.last_name}` : "Système"} · {dateTime.format(new Date(item.created_at))}</small>
              <small>{item.entity_type}{item.entity_id ? ` #${item.entity_id}` : ""}</small>
            </div>
          </li>)}
        </ol>
      </section>
      <nav className="pagination-controls" aria-label="Pagination du journal">
        <Button variant="ghost" disabled={!hasPrevious || loading} onClick={() => void load(page - 1, action)}>Précédent</Button>
        <span>Page {page}</span>
        <Button variant="ghost" disabled={!hasNext || loading} onClick={() => void load(page + 1, action)}>Suivant</Button>
      </nav>
    </main>
  );
}
