export type SystemState = "loading" | "online" | "offline";

const LABEL: Record<SystemState, string> = {
  loading: "Verificando sistema…",
  online: "Sistema online",
  offline: "Sistema indisponível",
};

// ball (bolinha de tenis) = so para "online"; clay (saibro) = so para
// "offline"/erro. Nenhuma outra cor decora este indicador.
const DOT_CLASS: Record<SystemState, string> = {
  loading: "bg-mist animate-pulse",
  online: "bg-ball",
  offline: "bg-clay",
};

export default function StatusIndicator({ status }: { status: SystemState }) {
  return (
    <div className="flex items-center gap-3" role="status">
      <span
        className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_CLASS[status]}`}
        aria-hidden="true"
      />
      <span className="font-display text-base font-medium">{LABEL[status]}</span>
    </div>
  );
}
