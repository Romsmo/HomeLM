import type { ChatItem } from "../state/store";

const ROLE_LABEL: Record<ChatItem["role"], string> = {
  user: "Du",
  assistant: "Cat",
  system: "System",
};

export function chatToMarkdown(messages: ChatItem[], now = new Date()): string {
  const header = `# Chat mit Cat, ${now.toLocaleString("de-DE")}\n`;
  const body = messages
    .filter((m) => m.text.trim() !== "")
    .map((m) => {
      const time = new Date(m.ts * 1000).toLocaleTimeString("de-DE", {
        hour: "2-digit",
        minute: "2-digit",
      });
      return `**${ROLE_LABEL[m.role]}** (${time})\n\n${m.text}\n`;
    });
  return [header, ...body].join("\n");
}

export function exportFileName(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `cat-chat-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}.md`;
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
