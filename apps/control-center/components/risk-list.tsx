export function RiskList({ risks }: { risks: string[] }) {
  if (risks.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">Risks</p>
      <ul className="mt-1 list-inside list-disc text-sm text-destructive">
        {risks.map((risk) => (
          <li key={risk}>{risk}</li>
        ))}
      </ul>
    </div>
  );
}
