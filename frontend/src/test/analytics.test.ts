import { describe, expect, it } from "vitest";

import { sanitize } from "../lib/analytics";

describe("statistiques anonymes", () => {
  it("réduit les adresses au chemin et retire hôtes et provenance", () => {
    const event = {
      uuid: "1", event: "$pageview",
      properties: {
        $current_url: "https://abc.ngrok.app/bibliotheque?q=zelda#x",
        $host: "192.168.1.20:8765", $referrer: "http://192.168.1.20:8765/sauvegardes", $referring_domain: "192.168.1.20",
        $pathname: "/bibliotheque",
      },
      $set_once: { $initial_current_url: "http://localhost:8765/parametres/ia?x=1", $initial_host: "localhost" },
    };
    const out = sanitize(event as never)!;
    expect(out.properties).toEqual({ $current_url: "/bibliotheque", $referrer: "/sauvegardes", $pathname: "/bibliotheque" });
    expect(out.$set_once).toEqual({ $initial_current_url: "/parametres/ia" });
  });
});
