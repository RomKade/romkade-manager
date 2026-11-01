import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: "jeton" } } }) } },
  TERMS_URL: "#", PRIVACY_URL: "#",
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ session: { user: { user_metadata: {} } }, signOut: async () => undefined }) }));

import { TopLiked } from "../pages/Dashboard";

const platform = { id: 1, directory: "SFC", code: "SFC", label: "Super Nintendo" };
const mario = { id: 1, title: "Super Mario World", platform, image_url: null, boxart_url: null, present: true };
let calls: { url: string; token: string | null }[] = [];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, token: new Headers(init?.headers).get("X-Romkade-Token") });
    const days = new URL(url, "http://x").searchParams.get("days");
    const games = [
      { key: "SFC/super mario world", title: "Super Mario World", platform_code: "SFC", platform_label: "Super Nintendo",
        platform_dir: "SFC", likes: 12, dislikes: 1, cover: "https://cloud/art/a.webp", game: mario },
      { key: "MD/sonic the hedgehog", title: "Sonic The Hedgehog", platform_code: "MD", platform_label: "Mega Drive",
        platform_dir: "MD", likes: 5, dislikes: 0, cover: "https://cloud/art/b.webp", game: null },
    ];
    return new Response(JSON.stringify(days === "7" ? [] : games), { headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Les plus aimés du moment", () => {
  it("classement de 30 jours par défaut, période au choix ; un jeu de la bibliothèque s'ouvre", async () => {
    const open = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><TopLiked nowId={undefined} onOpen={open} /></MemoryRouter>
      </QueryClientProvider>,
    );
    const section = await screen.findByRole("region", { name: "Les plus aimés du moment" });
    expect(await within(section).findByText("Sonic The Hedgehog")).toBeInTheDocument();
    expect(calls[0]).toEqual({ url: "/api/cloud/likes/top?days=30", token: "jeton" });
    expect(within(section).getByTitle("12 joueurs aiment, 1 n'aiment pas")).toHaveTextContent("12");
    expect(within(section).getByTitle("Ce jeu n'est pas dans ta bibliothèque")).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: /^Super Mario World/ }));
    expect(open).toHaveBeenCalledWith(1);
    // Accord non donné : la ligne explique comment compter dans le classement.
    expect(within(section).getByText(/si tu acceptes les statistiques anonymes/)).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("radio", { name: "7 jours" }));
    expect(await within(section).findByText(/Pas encore assez d'avis/)).toBeInTheDocument();
    await waitFor(() => expect(calls.map((c) => c.url)).toContain("/api/cloud/likes/top?days=7"));
  });
});
