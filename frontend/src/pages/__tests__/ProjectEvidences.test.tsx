/**
 * Preuves terrain : capture (compression + GPS), galerie avec statuts, validation et historique.
 * Les décisions autorisées viennent du backend (`permissions`) : l'écran ne les recalcule pas.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectEvidences from "../ProjectEvidences";

const PROJECT = {
  id: 12,
  organization: 3,
  organization_name: "KEMTA Promotion Douala",
  name: "Résidence Bonamoussadi — tranche 1",
  code: "RBS-T1",
  description: "",
  location_label: "Bonamoussadi",
  city: "Douala",
  region: "Littoral",
  latitude: "4.089100",
  longitude: "9.740600",
  geofence_radius_m: 500,
  currency: "XAF" as const,
  budget_total: 85000000,
  status: "ACTIVE" as const,
  status_label: "En cours",
  progress: "60.00",
  planned_start_date: "2026-01-12",
  planned_end_date: "2026-12-18",
  actual_start_date: null,
  actual_end_date: null,
  created_by: { id: 7, first_name: "Arnaud", last_name: "Nkoulou" } as never,
  member_count: 6,
  permissions: {
    edit_project: true,
    archive_project: true,
    manage_members: true,
    manage_schedule: true,
    update_task: true,
    capture_evidence: true,
    validate_evidence: true,
    view_finance: true,
    manage_finance: true,
    view_activity: true,
  },
  created_at: "2026-01-01T08:00:00Z",
  updated_at: "2026-01-01T08:00:00Z",
};

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    id: 41,
    project: 12,
    task: null,
    task_title: null,
    author: {
      id: 6,
      first_name: "Didier",
      last_name: "Ngassa",
      phone_masked: "+23769100 •• 06",
      role_label: "Agent terrain / chef de chantier",
    },
    status: "PENDING",
    status_label: "En attente de validation",
    sync_status: "SYNCED",
    sync_status_label: "Reçue",
    captured_at: "2026-09-24T10:12:00Z",
    received_at: "2026-09-24T10:13:10Z",
    latitude: "4.089200",
    longitude: "9.740700",
    gps_accuracy: 9,
    gps_status: "AVAILABLE",
    gps_status_label: "Disponible",
    device_model: "Tecno Spark 10",
    device_platform: "Android",
    app_version: "0.5.0",
    description: "Ferraillage avant coulage",
    hash_sha256: "a".repeat(64),
    size_bytes: 348_000,
    content_type: "image/jpeg",
    file_url: "/api/evidences/41/file/",
    thumbnail_url: "/api/evidences/41/thumbnail/",
    distance_from_site_m: 12.4,
    inside_geofence: true,
    validation_count: 0,
    permissions: { validate_evidence: true, cannot_validate_own: false, can_see_location: true },
    created_at: "2026-09-24T10:13:10Z",
    ...overrides,
  };
}

/**
 * jsdom n'implémente ni le décodage d'image ni le canvas : on fournit des doublures minimales
 * pour que la vraie chaîne `preparePhoto` (compression + empreinte) s'exécute dans les tests.
 */
function stubBrowserImageApis() {
  class FakeImage {
    width = 1280;
    height = 960;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(_value: string) {
      setTimeout(() => this.onload?.(), 0);
    }
    get src() {
      return "blob:mock";
    }
  }
  vi.stubGlobal("Image", FakeImage as unknown as typeof Image);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback: BlobCallback) =>
    callback(new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" })),
  );
  // jsdom déclare ces méthodes sans les implémenter : on les remplace pour de bon.
  Object.defineProperty(URL, "createObjectURL", { value: () => "blob:mock", configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => undefined, configurable: true });
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi({
  items = [evidence()],
  canCapture = true,
  ownEvidence = false,
  duplicate = false,
  outOfGeofence = false,
  history = [] as unknown[],
}: {
  items?: unknown[];
  canCapture?: boolean;
  ownEvidence?: boolean;
  duplicate?: boolean;
  outOfGeofence?: boolean;
  history?: unknown[];
} = {}) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const project = {
    ...PROJECT,
    permissions: { ...PROJECT.permissions, capture_evidence: canCapture },
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });

    if (url.startsWith("/api/projects/12/evidences/")) {
      return jsonResponse({
        count: items.length,
        next: null,
        previous: null,
        results: items,
        counts: { pending: 1, validated: 1, rejected: 0, flagged: 0 },
      });
    }
    if (url.startsWith("/api/evidences/pending/")) {
      return jsonResponse({ count: 0, results: [] });
    }
    if (url.startsWith("/api/evidences/") && url.endsWith("/history/")) {
      return jsonResponse({ count: history.length, results: history });
    }
    if (url.startsWith("/api/evidences/") && url.endsWith("/transition/")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (ownEvidence) {
        return jsonResponse(
          {
            error: {
              code: "cannot_validate_own_evidence",
              message: "Vous ne pouvez pas valider votre propre preuve.",
              details: {},
              request_id: "t",
            },
          },
          403,
        );
      }
      return jsonResponse({
        ...evidence({
          status: body.action === "VALIDATE" ? "VALIDATED" : "REJECTED",
          status_label: body.action === "VALIDATE" ? "Validée" : "Rejetée",
          validation_count: 1,
        }),
        last_validation: {
          id: 1,
          actor: { id: 9, first_name: "Estelle", last_name: "Mvondo", role_label: "Contrôleur" },
          action: body.action,
          action_label: body.action === "VALIDATE" ? "Validation" : "Rejet",
          from_status: "PENDING",
          to_status: body.action === "VALIDATE" ? "VALIDATED" : "REJECTED",
          comment: body.comment ?? "",
          created_at: "2026-09-26T08:00:00Z",
        },
      });
    }
    if (url === "/api/evidences/" && init?.method === "POST") {
      if (duplicate) {
        return jsonResponse(
          {
            error: {
              code: "duplicate_evidence",
              message: "Cette photo a déjà été déposée.",
              details: { evidence: { id: 90 } },
              request_id: "t",
            },
          },
          409,
        );
      }
      if (outOfGeofence) {
        return jsonResponse(
          {
            error: {
              code: "evidence_out_of_geofence",
              message: "Hors périmètre",
              details: { distance_m: 28_000, radius_m: 500 },
              request_id: "t",
            },
          },
          422,
        );
      }
      return jsonResponse(evidence({ id: 77, description: "Nouvelle preuve" }), 201);
    }
    throw new Error(`Requête inattendue : ${url} ${init?.method ?? "GET"}`);
  });

  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return { calls, project };
}

/** Ouvre le détail de la première preuve de la galerie (bouton de la vignette). */
function openFirstCard(section: HTMLElement): HTMLElement {
  const card = within(section).getAllByTestId("evidence-card")[0];
  return within(card).getByRole("button");
}

function renderPage(project: typeof PROJECT) {
  return render(<ProjectEvidences project={project} />);
}

beforeEach(() => {
  stubBrowserImageApis();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("ProjectEvidences", () => {
  it("affiche la galerie avec les statuts et l'état d'attente", async () => {
    const { project } = mockApi({
      items: [
        evidence(),
        evidence({
          id: 42,
          status: "VALIDATED",
          status_label: "Validée",
          description: "Semelles coulées",
          gps_status: "UNAVAILABLE",
          gps_status_label: "Indisponible",
          latitude: null,
          longitude: null,
          distance_from_site_m: null,
          inside_geofence: null,
        }),
      ],
    });
    renderPage(project);

    const section = await screen.findByTestId("evidences");
    expect(within(section).getByText("En attente de validation")).toBeInTheDocument();
    expect(within(section).getByText("Validée")).toBeInTheDocument();
    // Deux preuves en attente/validée : les compteurs viennent du backend.
    expect(within(section).getByText(/À valider : 1/)).toBeInTheDocument();
    // Une preuve sans GPS est explicitement signalée, jamais silencieusement ignorée.
    expect(within(section).getByText("Indisponible")).toBeInTheDocument();
    expect(within(section).getAllByTestId("evidence-card")).toHaveLength(2);
  });

  it("affiche un état vide explicite quand il n'y a aucune preuve", async () => {
    const { project } = mockApi({ items: [] });
    renderPage(project);

    expect(await screen.findByTestId("empty-gallery")).toHaveTextContent(/Aucune preuve/i);
  });

  it("compresse la photo et l'envoie avec GPS, description et clé d'idempotence", async () => {
    const user = userEvent.setup();
    const { calls, project } = mockApi({ items: [] });
    renderPage(project);

    await screen.findByTestId("empty-gallery");
    const file = new File([new Uint8Array([1, 2, 3, 4])], "chantier.jpg", { type: "image/jpeg" });
    await user.upload(screen.getByLabelText(/photo du chantier/i), file);

    const preview = await screen.findByTestId("capture-preview");
    expect(within(preview).getByText(/Empreinte :/)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/description/i), "Ferraillage avant coulage");
    await user.click(screen.getByRole("button", { name: /envoyer la preuve/i }));

    await waitFor(() => {
      const upload = calls.find((call) => call.url === "/api/evidences/" && call.init?.method === "POST");
      expect(upload).toBeDefined();
      expect(upload!.init!.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
      const body = upload!.init!.body as FormData;
      expect(body.get("project")).toBe("12");
      expect(body.get("description")).toBe("Ferraillage avant coulage");
      // Le GPS n'a pas été demandé : la preuve part avec un statut explicite, sans coordonnées.
      expect(body.get("gps_status")).toBe("UNAVAILABLE");
      expect(body.get("latitude")).toBeNull();
    });
  });

  it("envoie la position obtenue et l'affiche à l'utilisateur", async () => {
    const user = userEvent.setup();
    const { calls, project } = mockApi({ items: [] });
    const getCurrentPosition = vi.fn((success: PositionCallback) =>
      success({
        coords: { latitude: 4.0892, longitude: 9.7407, accuracy: 9 },
      } as GeolocationPosition),
    );
    Object.defineProperty(globalThis.navigator, "geolocation", {
      value: { getCurrentPosition },
      configurable: true,
    });

    renderPage(project);
    await screen.findByTestId("empty-gallery");
    await user.upload(
      screen.getByLabelText(/photo du chantier/i),
      new File([new Uint8Array([9, 9, 9])], "photo.jpg", { type: "image/jpeg" }),
    );
    await screen.findByTestId("capture-preview");
    await user.click(screen.getByRole("button", { name: /obtenir ma position/i }));

    // Le message est affiché à la fois par l'aide GPS et par l'état de la capture.
    expect((await screen.findAllByText(/Position obtenue/i)).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /envoyer la preuve/i }));

    await waitFor(() => {
      const upload = calls.find((call) => call.url === "/api/evidences/" && call.init?.method === "POST");
      const body = upload!.init!.body as FormData;
      expect(body.get("gps_status")).toBe("AVAILABLE");
      expect(Number(body.get("latitude"))).toBeCloseTo(4.0892);
      expect(Number(body.get("longitude"))).toBeCloseTo(9.7407);
      expect(Number(body.get("gps_accuracy"))).toBe(9);
    });
  });

  it("explique un refus de localisation sans bloquer l'envoi", async () => {
    const user = userEvent.setup();
    const { project } = mockApi({ items: [] });
    Object.defineProperty(globalThis.navigator, "geolocation", {
      value: {
        getCurrentPosition: (_s: PositionCallback, error?: PositionErrorCallback) =>
          error?.({ code: 1 } as GeolocationPositionError),
      },
      configurable: true,
    });

    renderPage(project);
    await screen.findByTestId("empty-gallery");
    await user.upload(
      screen.getByLabelText(/photo du chantier/i),
      new File([new Uint8Array([7, 7, 7])], "photo.jpg", { type: "image/jpeg" }),
    );
    await screen.findByTestId("capture-preview");
    await user.click(screen.getByRole("button", { name: /obtenir ma position/i }));

    expect((await screen.findAllByText(/refusée/i)).length).toBeGreaterThan(0);
    // La photo reste envoyable : le refus GPS n'empêche pas le travail de terrain.
    expect(screen.getByRole("button", { name: /envoyer la preuve/i })).toBeEnabled();
  });

  it("avertit d'un doublon sans laisser croire à un échec technique", async () => {
    const user = userEvent.setup();
    const { project } = mockApi({ items: [], duplicate: true });
    renderPage(project);

    await screen.findByTestId("empty-gallery");
    await user.upload(
      screen.getByLabelText(/photo du chantier/i),
      new File([new Uint8Array([5, 5, 5])], "photo.jpg", { type: "image/jpeg" }),
    );
    await screen.findByTestId("capture-preview");
    await user.click(screen.getByRole("button", { name: /envoyer la preuve/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/déjà été déposée/i);
  });

  it("explique un refus pour cause de périmètre géographique", async () => {
    const user = userEvent.setup();
    const { project } = mockApi({ items: [], outOfGeofence: true });
    renderPage(project);

    await screen.findByTestId("empty-gallery");
    await user.upload(
      screen.getByLabelText(/photo du chantier/i),
      new File([new Uint8Array([6, 6, 6])], "photo.jpg", { type: "image/jpeg" }),
    );
    await screen.findByTestId("capture-preview");
    await user.click(screen.getByRole("button", { name: /envoyer la preuve/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/trop éloignée du chantier/i);
  });

  it("valide une preuve et enregistre la décision dans l'historique", async () => {
    const user = userEvent.setup();
    const { calls, project } = mockApi({
      history: [
        {
          id: 1,
          actor: { id: 9, first_name: "Estelle", last_name: "Mvondo", role_label: "Contrôleur" },
          action: "VALIDATE",
          action_label: "Validation",
          from_status: "PENDING",
          to_status: "VALIDATED",
          comment: "Conforme",
          created_at: "2026-09-26T08:00:00Z",
        },
      ],
    });
    renderPage(project);

    const section = await screen.findByTestId("evidences");
    await user.click(openFirstCard(section));

    const detail = await screen.findByTestId("evidence-detail");
    expect(within(detail).getByText(/Historique des décisions/i)).toBeInTheDocument();
    await user.click(within(detail).getByRole("button", { name: /^valider$/i }));

    await waitFor(() => {
      const transition = calls.find(
        (call) => call.url === "/api/evidences/41/transition/" && call.init?.method === "POST",
      );
      expect(transition).toBeDefined();
      expect(JSON.parse(String(transition!.init!.body))).toMatchObject({ action: "VALIDATE" });
    });
    expect(await screen.findByTestId("history-entry")).toHaveTextContent(/Validation/);
  });

  it("exige un commentaire pour rejeter", async () => {
    const user = userEvent.setup();
    const { calls, project } = mockApi();
    renderPage(project);

    const section = await screen.findByTestId("evidences");
    await user.click(openFirstCard(section));
    const detail = await screen.findByTestId("evidence-detail");
    await user.click(within(detail).getByRole("button", { name: /^rejeter$/i }));

    expect(await screen.findByText(/commentaire est obligatoire/i)).toBeInTheDocument();
    expect(
      calls.find((call) => call.url === "/api/evidences/41/transition/"),
      "aucune requête ne doit partir sans motif",
    ).toBeUndefined();

    await user.type(within(detail).getByLabelText(/commentaire/i), "Photo floue");
    await user.click(within(detail).getByRole("button", { name: /^rejeter$/i }));

    await waitFor(() => {
      const transition = calls.find((call) => call.url === "/api/evidences/41/transition/");
      expect(JSON.parse(String(transition!.init!.body))).toMatchObject({
        action: "REJECT",
        comment: "Photo floue",
      });
    });
  });

  it("affiche « consultation seule » quand la validation n'est pas permise", async () => {
    const user = userEvent.setup();
    const { project } = mockApi({
      items: [
        evidence({
          permissions: {
            validate_evidence: false,
            cannot_validate_own: false,
            can_see_location: true,
          },
        }),
      ],
    });
    renderPage(project);

    const section = await screen.findByTestId("evidences");
    await user.click(openFirstCard(section));
    const detail = await screen.findByTestId("evidence-detail");

    expect(within(detail).getByText(/Consultation seule/i)).toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: /^valider$/i })).not.toBeInTheDocument();
    expect(within(detail).getAllByText(/Aucune décision enregistrée/i).length).toBeGreaterThan(0);
  });

  it("explique qu'un auteur ne peut pas valider sa propre preuve", async () => {
    const user = userEvent.setup();
    const { project } = mockApi({
      items: [
        evidence({
          permissions: {
            validate_evidence: false,
            cannot_validate_own: true,
            can_see_location: true,
          },
        }),
      ],
    });
    renderPage(project);

    const section = await screen.findByTestId("evidences");
    await user.click(openFirstCard(section));

    expect(await screen.findByText(/un autre validateur doit statuer/i)).toBeInTheDocument();
  });

  it("masque le formulaire de capture sans la capacité correspondante", async () => {
    const { project } = mockApi({ canCapture: false });
    renderPage(project);

    await screen.findByTestId("evidences");
    expect(screen.queryByLabelText(/photo du chantier/i)).not.toBeInTheDocument();
    expect(screen.getByText(/ne permet pas de déposer une preuve/i)).toBeInTheDocument();
  });

  it("filtre la galerie par statut", async () => {
    const user = userEvent.setup();
    const { calls, project } = mockApi({ items: [] });
    renderPage(project);

    await screen.findByTestId("empty-gallery");
    await user.selectOptions(screen.getByLabelText(/filtrer par statut/i), "PENDING");

    await waitFor(() => {
      expect(
        calls.some((call) => call.url === "/api/projects/12/evidences/?status=PENDING"),
      ).toBe(true);
    });
  });
});
