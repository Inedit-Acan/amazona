import assert from "node:assert/strict";
import { test } from "node:test";
import {
  channelKindOf,
  channelLabel,
  isTransactional,
  measuredChannelsLabel,
  scoredForLabel,
  wrongChannelNote,
} from "./channel-view.ts";

test("channelKindOf: el tipo sale del prefijo, que es autodescriptivo", () => {
  assert.equal(channelKindOf("own_web"), "own_web");
  assert.equal(channelKindOf("marketplace:amazon"), "marketplace");
  assert.equal(channelKindOf("search:google"), "search");
  assert.equal(channelKindOf("social:tiktok"), "social");
});

test("channelKindOf: lo que no se reconoce no se adivina", () => {
  assert.equal(channelKindOf("lo-que-sea"), null);
  assert.equal(channelKindOf("inventado:cosa"), null);
});

test("channelLabel: una plataforma nueva se lee aunque no tenga nombre propio", () => {
  assert.equal(channelLabel("marketplace:amazon"), "Amazon (marketplace)");
  assert.equal(channelLabel("marketplace:allegro"), "allegro (marketplace)");
});

test("channelLabel: sin canal se dice agnóstico, no «todos»", () => {
  assert.equal(channelLabel(null), "Agnóstico del canal");
  assert.equal(channelLabel(undefined), "Agnóstico del canal");
});

test("channelLabel: la web propia no lleva sufijo de tipo", () => {
  assert.equal(channelLabel("own_web"), "Web propia");
});

test("TikTok no es TikTok Shop, y se ve", () => {
  assert.equal(channelLabel("social:tiktok"), "TikTok (social)");
  assert.equal(channelLabel("marketplace:tiktok_shop"), "TikTok Shop (marketplace)");
  assert.equal(isTransactional("social:tiktok"), false);
  assert.equal(isTransactional("marketplace:tiktok_shop"), true);
});

test("isTransactional: donde se cobra y donde no", () => {
  assert.equal(isTransactional("own_web"), true);
  assert.equal(isTransactional("marketplace:amazon"), true);
  assert.equal(isTransactional("search:google"), false);
  assert.equal(isTransactional(null), false);
});

test("scoredForLabel: un nulo no se lee como un fallo", () => {
  assert.equal(scoredForLabel("own_web"), "Puntuado para Web propia");
  assert.equal(scoredForLabel(null), "Puntuado sin canal (agnóstico)");
});

test("wrongChannelNote: sin nada retenido no hay nota", () => {
  assert.equal(wrongChannelNote([], "own_web"), null);
});

test("wrongChannelNote: dice qué se midió y para qué no sirve", () => {
  assert.equal(
    wrongChannelNote(["marketplace:ebay"], "own_web"),
    "Sin score: lo medido es de eBay (marketplace) y no sirve para Web propia",
  );
});

test("wrongChannelNote: una señal sin canal se nombra tal cual", () => {
  assert.match(wrongChannelNote(["sin canal"], "own_web")!, /sin canal/);
});

test("wrongChannelNote: y también cuando la decisión es la agnóstica", () => {
  assert.match(
    wrongChannelNote(["marketplace:ebay"], null)!,
    /no sirve para una decisión sin canal/,
  );
});

test("measuredChannelsLabel: agnóstico es correcto para el interés y sospechoso para la competencia", () => {
  assert.equal(measuredChannelsLabel([]), "Agnóstico del canal");
  assert.equal(measuredChannelsLabel(undefined), "Agnóstico del canal");
  assert.equal(
    measuredChannelsLabel(["marketplace:ebay", "own_web"]),
    "eBay (marketplace) · Web propia",
  );
});
