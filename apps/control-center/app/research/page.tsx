"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type ResearchCandidate } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default function ResearchPage() {
  const router = useRouter();
  const [category, setCategory] = useState("electronics");
  const [keywords, setKeywords] = useState("");
  const [maxResults, setMaxResults] = useState(5);
  const [candidates, setCandidates] = useState<ResearchCandidate[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const run = await api.createResearchRun({
        category,
        keywords: keywords
          .split(",")
          .map((k) => k.trim())
          .filter(Boolean),
        max_results: maxResults,
      });
      setCandidates(run.candidates);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Research run failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateCandidate(candidate: ResearchCandidate) {
    const params = new URLSearchParams({
      title: `Validate ${candidate.name} opportunity`,
      product_name: candidate.name,
      category: candidate.category,
      demand_signal: String(candidate.data.demand_signal ?? ""),
      competition_level: String(candidate.data.competition_level ?? ""),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function findSuppliers(candidate: ResearchCandidate) {
    const params = new URLSearchParams({
      product_id: candidate.product_id,
      category: candidate.category,
    });
    router.push(`/sourcing?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Research"
        description="Discover and rank candidate products by simulated opportunity — Fase 3, Agente 1. Fixture-driven demand/niche data, no live sources yet."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New research run</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5 sm:col-span-1">
                <label htmlFor="category" className="text-sm font-medium">
                  Category
                </label>
                <select
                  id="category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="electronics">electronics</option>
                  <option value="home">home</option>
                  <option value="accessories">accessories</option>
                </select>
              </div>
              <div className="space-y-1.5 sm:col-span-1">
                <label htmlFor="keywords" className="text-sm font-medium">
                  Keywords (comma-separated)
                </label>
                <input
                  id="keywords"
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  placeholder="earbuds, wireless"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5 sm:col-span-1">
                <label htmlFor="maxResults" className="text-sm font-medium">
                  Max results
                </label>
                <input
                  id="maxResults"
                  type="number"
                  min={1}
                  max={20}
                  value={maxResults}
                  onChange={(e) => setMaxResults(Number(e.target.value))}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Research run failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Researching…" : "Run research"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {candidates ? (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            {candidates.length === 0
              ? "No candidates found for this category/keywords."
              : `${candidates.length} candidate${candidates.length === 1 ? "" : "s"}, ranked by opportunity score`}
          </h2>
          {candidates.map((candidate) => (
            <Card key={candidate.product_id}>
              <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium">{candidate.name}</p>
                  <p className="text-sm text-muted-foreground">{candidate.data.niche_rationale}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Opportunity {candidate.opportunity_score?.toFixed(2)} · Demand{" "}
                    {candidate.data.demand_signal?.toFixed(2)} · Competition {candidate.data.competition_level}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => findSuppliers(candidate)}>
                    Find suppliers
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => validateCandidate(candidate)}>
                    Validate this product
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  );
}
