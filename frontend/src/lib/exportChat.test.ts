import { chatToMarkdown, exportFileName } from "./exportChat";

describe("exportChat", () => {
  it("exportiert Rollen und Text, leere Nachrichten ausgenommen", () => {
    const md = chatToMarkdown(
      [
        { id: "1", role: "user", text: "Hallo", ts: 0, streaming: false },
        { id: "2", role: "assistant", text: "", ts: 0, streaming: false },
        { id: "3", role: "assistant", text: "Hi!", ts: 0, streaming: false },
      ],
      new Date(2026, 0, 2, 3, 4),
    );
    expect(md).toContain("**Du**");
    expect(md).toContain("Hallo");
    expect(md.match(/\*\*Cat\*\*/g)).toHaveLength(1);
  });

  it("baut einen Dateinamen mit Datum", () => {
    expect(exportFileName(new Date(2026, 0, 2))).toBe("cat-chat-2026-01-02.md");
  });
});
