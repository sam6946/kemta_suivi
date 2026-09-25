/**
 * Détail projet : lecture des membres, ajout contrôlé par les permissions backend,
 * et absence de toute action non autorisée (le frontend masque, le backend décide).
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../auth/AuthContext";
import ProjectDetailPage from "../ProjectDetailPage";

const OWNER = {
  id: 7,
  phone: "+237691000003",
  phone_masked: "+23769100 •• 03",
  email: null,
  first_name: "Arnaud",
  last_name: "Nkoulou",
  role: "PROJECT_OWNER",
  role_label: "Maître d'ouvrage",
  is_phone_verified: true,
  capabilities: ["edit_project", "manage_members", "view_finance"],
};

const ENGINEER = {
  id: 9,
  phone: "+237691000004",
  phone_masked: "+23769100 •• 04",
  email: null,
  first_name: "Bertrand",
  last_name: "Fotso",
  role: "ENGINEER",
  role_label: "Ingénieur / bureau d'études",
  is_phone_verified: true,
  capabilities: ["manage_schedule", "capture_evidence"],
};

function project(manageMembers: boolean) {
  return {
    id: 12,
    organization: 3,
    organization_name: "KEMTA Promotion Douala",
    name: "Résidence Bonamoussadi — tranche 1",
    code: "RBS-T1",
    description: "",
    location_label: "Bonamoussadi",
    city: "Douala",
    region: "Littoral",
    latitude: null,
    longitude: null,
    geofence_radius_m: 500,
    currency: "XAF",
    budget_total: 85000000,
    status: "ACTIVE",
    status_label: "En cours",
    progress: "0.00",
    planned_start_date: "2026-01-12",
    planned_end_date: "2026-12-18",
    actual_start_date: null,
    actual_end_date: null,
    created_by: OWNER,
    member_count: 2,
    permissions: {
      edit_project: manageMembers,
      archive_project: manageMembers,
      manage_members: manageMembers,
      capture_evidence: true,
      validate_evidence: false,
      view_finance: true,
      manage_finance: manageMembers,
    },
    created_at: "2026-01-01T08:00:00Z",
    updated_at: "2026-01-01T08:00:00Z",
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi({
  manager = true,
  addStatus = 201,
}: { manager?: boolean; addStatus?: number } = {}) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const currentUser = manager ? OWNER : ENGINEER;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });

    if (url.startsWith("/api/auth/me/")) return jsonResponse(currentUser);
    if (url.match(/\/api\/projects\/\d+\/members\/$/) && init?.method === "POST") {
      if (addStatus !== 201) {
        return jsonResponse(
          {
            error: {
              code: "user_not_found",
              message: "Aucun compte KEMTA ne correspond à ce numéro.",
              details: {},
              request_id: "abc",
            },
          },
          addStatus,
        );
      }
      return jsonResponse({ id: 4, user: ENGINEER, role: "ENGINEER", role_label: "Ingénieur", can_validate_evidence: false, can_manage_finance: false, is_active: true, created_at: "" }, 201);
    }
    if (url.match(/\/api\/projects\/\d+\/members\/$/)) {
      return jsonResponse({
        count: 2,
        next: null,
        previous: null,
        results: [
          {
            id: 1,
            user: OWNER,
            role: "PROJECT_OWNER",
            role_label: "Maître d'ouvrage",
            can_validate_evidence: true,
            can_manage_finance: true,
            is_active: true,
            created_at: "",
          },
          {
            id: 2,
            user: ENGINEER,
            role: "ENGINEER",
            role_label: "Ingénieur / bureau d'études",
            can_validate_evidence: false,
            can_manage_finance: false,
            is_active: true,
            created_at: "",
          },
        ],
      });
    }
    if (url.match(/\/api\/projects\/\d+\/$/)) return jsonResponse(project(manager));
    if (url.startsWith("/api/meta/roles/")) {
      return jsonResponse({
        results: [
          { code: "PROJECT_OWNER", label: "Maître d'ouvrage", capabilities: [] },
          { code: "ENGINEER", label: "Ingénieur / bureau d'études", capabilities: [] },
          { code: "FIELD_AGENT", label: "Agent terrain / chef de chantier", capabilities: [] },
        ],
      });
    }
    throw new Error(`Requête inattendue : ${url}`);
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projets/12"]}>
      <AuthProvider>
        <Routes>
          <Route path="/projets/:id" element={<ProjectDetailPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("ProjectDetailPage", () => {
  it("affiche les informations du projet et ses membres", async () => {
    mockApi();
    sessionStorage.setItem("kemta.access", "token");
    renderPage();

    expect(await screen.findByText("Résidence Bonamoussadi — tranche 1")).toBeInTheDocument();
    expect(screen.getByText(/85 000 000 FCFA/)).toBeInTheDocument();
    expect(screen.getAllByTestId("member-row")).toHaveLength(2);
    expect(screen.getByText("Bertrand Fotso")).toBeInTheDocument();
  });

  it("ajoute un membre avec le rôle choisi", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi();
    sessionStorage.setItem("kemta.access", "token");
    renderPage();

    await screen.findByText("Résidence Bonamoussadi — tranche 1");
    await user.type(screen.getByLabelText(/numéro de téléphone/i), "+237 6 91 00 00 04");
    await user.selectOptions(screen.getByLabelText(/rôle sur ce projet/i), "FIELD_AGENT");
    await user.click(screen.getByRole("button", { name: /ajouter au projet/i }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === "POST");
      expect(post).toBeDefined();
    });
    const payload = JSON.parse(String(calls.find((call) => call.init?.method === "POST")!.init?.body));
    expect(payload).toMatchObject({ phone: "+237 6 91 00 00 04", role: "FIELD_AGENT" });
  });

  it("explique clairement qu'un numéro inconnu n'a pas de compte", async () => {
    const user = userEvent.setup();
    mockApi({ addStatus: 404 });
    sessionStorage.setItem("kemta.access", "token");
    renderPage();

    await screen.findByText("Résidence Bonamoussadi — tranche 1");
    await user.type(screen.getByLabelText(/numéro de téléphone/i), "+237699000777");
    await user.click(screen.getByRole("button", { name: /ajouter au projet/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/erreur/i);
  });

  it("masque les actions de gestion pour un rôle non autorisé", async () => {
    mockApi({ manager: false });
    sessionStorage.setItem("kemta.access", "token");
    renderPage();

    await screen.findByText("Résidence Bonamoussadi — tranche 1");
    expect(screen.queryByRole("button", { name: /ajouter au projet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retirer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /archiver le projet/i })).not.toBeInTheDocument();
    expect(screen.getByText(/lecture seule/i)).toBeInTheDocument();
  });
});
