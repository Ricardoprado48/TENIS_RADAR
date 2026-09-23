// Linha de metadado no estilo "ficha de partida" (rotulo + valor separados
// por um filete), nunca um card -- pedido explicito de evitar excesso de
// cards/visual de painel administrativo.
export default function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border-t border-rule py-4 first:border-t-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6">
      <span className="text-sm text-mist">{label}</span>
      <span className="font-display text-sm text-chalk sm:text-right">{value}</span>
    </div>
  );
}
