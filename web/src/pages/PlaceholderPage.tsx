// Tela provisoria para as areas ainda nao implementadas (Calendario, Radar,
// Forward Test, Configuracoes) -- so a estrutura de navegacao, sem dado
// ficticio nenhum (LOTE C em diante decide o conteudo real de cada uma).
export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <div>
      <p className="font-display text-2xl font-semibold tracking-tight">{title}</p>
      <p className="mt-4 text-sm text-mist">Em desenvolvimento.</p>
    </div>
  );
}
