import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "../App";
import { AssistantShots } from "../components/AssistantShots";

const game = { id: 7, title: "Wonder Boy", platform: "Sega Master System" };
const shot = { name: "20261019-205245.png", taken_at: "2026-10-19T20:52:45Z", size: 1024, url: "/api/screenshots/7/20261019-205245.png" };
let calls: { url: string; body?: string }[] = [];

function show(kind: string, shots: typeof shot[]) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter><AssistantShots kind={kind} game={game} shots={shots} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? String(init.body) : undefined });
    if (url.endsWith("/analyze")) {
      return new Response(JSON.stringify({ text: "Écran des commandes : bouton 1 lance la hache, bouton 2 saute.", model: "gemma" }),
        { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(new Blob(["png"], { type: "image/png" }), { status: 200 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Duke et les captures d'écran", () => {
  it("sans capture : le dit, et explique comment en prendre une", () => {
    show("show_screenshots", []);
    expect(screen.getByText("Tu n'as pas encore pris de capture de Wonder Boy.")).toBeInTheDocument();
    expect(screen.getByText(/dis-moi « prends une capture »/)).toBeInTheDocument();
  });

  it("montre les captures, les fait lire par le modèle, et mène à la page des captures", async () => {
    show("show_screenshots", [shot]);
    expect(screen.getByText("Tes captures de Wonder Boy (1)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Capture de Wonder Boy/ })).toHaveAttribute("src", shot.url);
    expect(screen.getByRole("link", { name: /Toutes les captures/ })).toHaveAttribute("href", "/captures?game=7");
    await userEvent.click(screen.getByRole("button", { name: "Analyser" }));
    expect(await screen.findByText(/bouton 1 lance la hache/)).toBeInTheDocument();
    const call = calls.find((c) => c.url.endsWith("/analyze"))!;
    expect(call.url).toBe("/api/games/7/screenshots/20261019-205245.png/analyze");
    expect(JSON.parse(call.body!)).toEqual({ lang: "fr" });
  });
});
