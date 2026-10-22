import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthScreen } from "../auth/AuthScreen";

vi.mock("../auth/supabase", () => ({ supabase: { auth: {} }, TERMS_URL: "#", PRIVACY_URL: "#" }));

describe("code à 6 chiffres", () => {
  it("une case par chiffre : avance seule, accepte un collage, revient en arrière", async () => {
    render(<AuthScreen needsMfa onDone={() => undefined} />);  // l'écran de double authentification demande un code
    const boxes = screen.getAllByRole("textbox").filter((el) => el.id.startsWith("auth-code-"));
    expect(boxes).toHaveLength(6);
    const user = userEvent.setup();
    await user.type(boxes[0]!, "4a2");                       // les lettres sont ignorées
    expect(boxes.map((b) => (b as HTMLInputElement).value).join("")).toBe("42");
    expect(document.activeElement).toBe(boxes[2]!);
    fireEvent.paste(boxes[0]!, { clipboardData: { getData: () => "123 456" } });
    expect(boxes.map((b) => (b as HTMLInputElement).value).join("")).toBe("123456");
    await user.click(boxes[5]!);
    await user.keyboard("{Backspace}{Backspace}");
    expect(boxes.map((b) => (b as HTMLInputElement).value).join("")).toBe("1234");
  });
});
