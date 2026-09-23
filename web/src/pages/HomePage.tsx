import { useEffect, useState } from "react";
import { getHealth, getInfo } from "../services/api";
import type { InfoResponse } from "../types/api";
import StatusIndicator, { type SystemState } from "../components/StatusIndicator";
import InfoRow from "../components/InfoRow";

function formatCutoff(value: string | null): string {
  if (!value) return "não disponível";
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

export default function HomePage() {
  const [state, setState] = useState<SystemState>("loading");
  const [info, setInfo] = useState<InfoResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkSystem() {
      try {
        await getHealth();
        const infoData = await getInfo();
        if (!cancelled) {
          setInfo(infoData);
          setState("online");
        }
      } catch {
        // Nunca inventar dados: se a API falhar, so mostramos o estado
        // indisponivel, nunca um placeholder que pareca um valor real.
        if (!cancelled) {
          setState("offline");
        }
      }
    }

    checkSystem();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <p className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Tennis Radar</p>
      <p className="mt-2 text-sm text-mist">Radar estatístico de tênis</p>

      <div className="mt-10">
        <StatusIndicator status={state} />
      </div>

      {state === "online" && info && (
        <div className="mt-6">
          <InfoRow label="Fuso horário" value={info.timezone} />
          <InfoRow label="Casa de apostas padrão" value={info.default_bookmaker} />
          <InfoRow label="Dados históricos até" value={formatCutoff(info.historical_data_cutoff)} />
          <InfoRow label="Versão do forward test" value={info.forward_version_id} />
        </div>
      )}

      {state === "offline" && (
        <p className="mt-6 text-sm text-clay">
          Não foi possível conectar ao servidor local. Verifique se a API está em execução.
        </p>
      )}
    </div>
  );
}
