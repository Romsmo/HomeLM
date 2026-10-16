import type { VoiceStateName } from "../protocol";
import Orb from "./Orb";

export default function Stage({ voice }: { voice: VoiceStateName }) {
  return (
    <section
      aria-label="Stage"
      className="relative flex min-h-[18rem] items-center justify-center overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40 backdrop-blur"
    >
      <Orb state={voice} />
    </section>
  );
}
