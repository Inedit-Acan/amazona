import assert from "node:assert/strict";
import { test } from "node:test";
import { audienceBars, campaignPlan, latestCampaign, platformLabel } from "./marketing.ts";

const c = (id: string, market: string, platform: string) => ({ id, market, platform });

test("latestCampaign devuelve la primera (más reciente) de esa plataforma y mercado", () => {
  const list = [c("new", "eu", "meta"), c("old", "eu", "meta"), c("g", "eu", "google"), c("us", "us", "meta")];
  assert.equal(latestCampaign(list, "eu", "meta")?.id, "new");
  assert.equal(latestCampaign(list, "eu", "google")?.id, "g");
  assert.equal(latestCampaign(list, "mx", "meta"), undefined);
});

test("campaignPlan: una por plataforma en el mercado, Meta antes que Google y las desconocidas al final", () => {
  const list = [c("g", "eu", "google"), c("t", "eu", "tiktok"), c("m2", "eu", "meta"), c("m1", "eu", "meta"), c("us", "us", "meta")];
  assert.deepEqual(
    campaignPlan(list, "eu").map((x) => x.id),
    ["m2", "g", "t"],
  );
  assert.deepEqual(campaignPlan(list, "mx"), []);
});

test("audienceBars: el mayor segmento vale 1 y el resto es proporcional; sin segmentos, vacío", () => {
  const bars = audienceBars([
    { name: "A", age_range: "25-44", interests: ["x"], estimated_reach: 250000 },
    { name: "B", age_range: "35-54", interests: ["y"], estimated_reach: 125000 },
  ]);
  assert.deepEqual(
    bars.map((b) => [b.name, b.share]),
    [
      ["A", 1],
      ["B", 0.5],
    ],
  );
  assert.deepEqual(audienceBars(undefined), []);
  assert.equal(audienceBars([{ name: "Z", age_range: "-", interests: [], estimated_reach: 0 }])[0].share, 0);
});

test("platformLabel etiqueta las plataformas conocidas y deja el resto tal cual", () => {
  assert.equal(platformLabel("meta"), "Meta Ads");
  assert.equal(platformLabel("google"), "Google Ads");
  assert.equal(platformLabel("tiktok"), "tiktok");
});
