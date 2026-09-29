import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { notificationsApi, type Notification } from "../api/notifications";
import { Alert, Button } from "../components/ui";

const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });

export default function NotificationsPage() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrevious, setHasPrevious] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = useCallback(async (pageNumber: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await notificationsApi.list(pageNumber);
      setItems(result.results);
      setUnread(result.unread_count);
      setCount(result.count);
      setHasNext(Boolean(result.next));
      setHasPrevious(Boolean(result.previous));
      setPage(pageNumber);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de charger les notifications.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(page);
    // Le changement de page est aussi déclenché par la navigation ci-dessous.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function markRead(item: Notification) {
    if (item.is_read) return;
    setBusy(true);
    setError(null);
    try {
      await notificationsApi.markRead(item.id);
      setFeedback("Notification marquée comme lue.");
      await load(page);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de modifier la notification.");
    } finally {
      setBusy(false);
    }
  }

  async function markAllRead() {
    if (unread === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await notificationsApi.markAllRead();
      setFeedback(`${result.updated} notification(s) marquée(s) comme lue(s).`);
      await load(page);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Impossible de modifier les notifications.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <Link to="/tableau-de-bord">← Tableau de bord</Link>
          <h1>Notifications</h1>
          <p className="subtitle">{unread} non lue(s) · {count} au total</p>
        </div>
        <Button variant="ghost" onClick={() => void markAllRead()} disabled={busy || unread === 0}>
          Tout marquer comme lu
        </Button>
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {feedback ? <Alert tone="success">{feedback}</Alert> : null}
      {loading ? <p className="field-hint">Chargement…</p> : null}
      {!loading && !error && items.length === 0 ? (
        <section className="card"><p>Aucune notification pour le moment.</p></section>
      ) : null}

      <ul className="notification-list">
        {items.map((item) => (
          <li className={`notification-item ${item.is_read ? "is-read" : "is-unread"}`} key={item.id}>
            <div className="notification-copy">
              <div className="notification-title-row">
                <h2>{item.title}</h2>
                {!item.is_read ? <span className="unread-dot" aria-label="Non lue" /> : null}
              </div>
              <p>{item.body}</p>
              <small>
                {item.project_name ? `${item.project_name} · ` : ""}
                {dateTime.format(new Date(item.last_seen_at || item.created_at))}
                {item.count > 1 ? ` · ${item.count} événements` : ""}
              </small>
            </div>
            <div className="notification-actions">
              {item.link ? <Link to={item.link}>Ouvrir le projet</Link> : null}
              {!item.is_read ? (
                <button type="button" className="link-button" disabled={busy} onClick={() => void markRead(item)}>
                  Marquer comme lu
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      <nav className="pagination-controls" aria-label="Pagination des notifications">
        <Button variant="ghost" disabled={!hasPrevious || loading} onClick={() => void load(page - 1)}>
          Précédent
        </Button>
        <span>Page {page}</span>
        <Button variant="ghost" disabled={!hasNext || loading} onClick={() => void load(page + 1)}>
          Suivant
        </Button>
      </nav>
    </main>
  );
}
