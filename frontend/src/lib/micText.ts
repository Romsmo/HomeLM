import type { MicControl } from "../hooks/useVoice";

function titleCase(text: string): string {
  return text.replace(/(^|\s)(\p{L})/gu, (_all, space: string, letter: string) => space + letter.toUpperCase());
}

/** Was das Mikrofon gerade tut, in einem Satz (Arbeitsraum und Handy zeigen denselben Text). */
export function micStatusText(mic: MicControl): string {
  if (mic.error) return mic.error;
  switch (mic.state) {
    case "connecting":
      return "Mikrofon verbindet …";
    case "ready":
      if (mic.windowOpen) return "Ich höre weiter zu, sprich einfach";
      return mic.wakeHint ? `Sag „${titleCase(mic.wakeHint)}“ und deine Anfrage` : "Ich höre zu, sprich einfach";
    case "listening":
      return "Ich höre …";
    case "thinking":
      return "Ich denke nach …";
    case "speaking":
      return "Cat spricht …";
    default:
      return mic.unavailable ?? "Mikrofon aus";
  }
}
