// Node contract test for the P2 Q&A conversation view (pure functions, no browser).
//
// `ask_core.js` has no DOM/import dependencies, so it is imported directly.
// Run: node tests/ask_view.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const corePath = path.join(here, "..", "graph2note", "webstatic", "js", "ask_core.js");
const core = await import(pathToFileURL(corePath).href);

// ---- 1) request assembly carries session_id on every turn (P1 contract) ----
const sid = "qa-fixture-3turn";
const questions = ["alpha 的含义？", "beta 的含义？", "gamma 的含义？"];
const payloads = questions.map((q) => core.buildAskPayload(q, sid, ""));
assert.deepStrictEqual(payloads.map((p) => p.session_id), [sid, sid, sid]);
assert.deepStrictEqual(payloads.map((p) => p.question), questions);
assert.ok(payloads.every((p) => !("pdf_id" in p)), "empty scope == all PDFs");
// a picked scope is sent as pdf_id (single-PDF scope shape)
assert.strictEqual(core.buildAskPayload("x", sid, "pdf-9").pdf_id, "pdf-9");
assert.strictEqual(core.buildAskPayload("  trimmed  ", sid, "").question, "trimmed");

// ---- 2) citation chips: [PDF name · pN] and jump to the source page ---------
const cite = {
  index: 1, label: "[1]", document_id: "d1", pdf_id: "pdf-1",
  pdf_name: "scan-review.pdf", page_number: 12, page_index: 11,
  source_page_url: "/api/documents/d1/source-page",
  review_url: "/api/documents/d1",
};
assert.strictEqual(core.citationLabel(cite), "[scan-review.pdf · p12]");
const chip = core.citationChipHtml(cite);
assert.ok(chip.includes('class="ask-citation"'), chip);
assert.ok(chip.includes('href="/api/documents/d1/source-page"'), chip);
assert.ok(chip.includes('target="_blank"'), chip);
assert.ok(chip.includes('data-document-id="d1"'), chip);
assert.ok(chip.includes('data-page-index="11"'), chip);
assert.ok(chip.includes("scan-review.pdf · p12"), chip);
assert.ok(chip.includes('href="#doc/d1"'), "editor link kept");
// fallbacks: title for the name, page_index+1 for the page
assert.strictEqual(core.citationLabel({ index: 1, title: "手稿A", page_index: 4 }), "[手稿A · p5]");
assert.strictEqual(core.citationLabel({ index: 1, document_id: "d9", page_index: 0 }), "[d9 · p1]");
// escaping never leaks markup
assert.ok(core.citationChipHtml({ index: 1, title: "<img>", page_index: 0 }).includes("&lt;img&gt;"));

// ---- 3) a P1-shaped 3-turn session restores with per-turn citations --------
const session = {
  session_id: sid,
  scope: { kind: "all", pdf_ids: [] },
  turns: [
    { index: 1, question: questions[0], answer: "答案一 [1]", status: "answered", retrieved: 3,
      citations: [{ index: 1, pdf_name: "a.pdf", page_index: 0, page_number: 1,
                    source_page_url: "/api/documents/da/source-page" }],
      untrusted_citations: [] },
    { index: 2, question: questions[1], answer: "答案二 [1]", status: "answered", retrieved: 2,
      citations: [{ index: 1, pdf_name: "a.pdf", page_index: 1, page_number: 2,
                    source_page_url: "/api/documents/db/source-page" }],
      untrusted_citations: [] },
    { index: 3, question: questions[2], answer: "答案三 [1]", status: "answered", retrieved: 1,
      citations: [{ index: 1, pdf_name: "b.pdf", page_index: 6, page_number: 7,
                    source_page_url: "/api/documents/dc/source-page" }],
      untrusted_citations: [] },
  ],
};
const turns = core.sessionToTurns(session);
assert.strictEqual(turns.length, 3);
const html = core.renderConversationHtml(turns);
const blocks = html.split('<article class="ask-turn ').slice(1);
assert.strictEqual(blocks.length, 6, "3 turns -> 3 user + 3 assistant bubbles");
// each turn shows its own citation only (independence)
assert.ok(blocks[1].includes("[a.pdf · p1]") && blocks[1].includes("/api/documents/da/source-page"));
assert.ok(blocks[3].includes("[a.pdf · p2]") && blocks[3].includes("/api/documents/db/source-page"));
assert.ok(blocks[5].includes("[b.pdf · p7]") && blocks[5].includes("/api/documents/dc/source-page"));
assert.ok(!blocks[1].includes("/api/documents/db/source-page"), "no citation bleed into turn 1");
assert.ok(!blocks[3].includes("/api/documents/da/source-page"), "no citation bleed into turn 2");
// bubbles: user right / assistant left
assert.ok(core.userTurnHtml(turns[0]).includes("ask-bubble-user"));
assert.ok(core.assistantTurnHtml(turns[0]).includes("ask-bubble-assistant"));
assert.ok(html.indexOf("ask-bubble-user") < html.indexOf("ask-bubble-assistant"));

// ---- 4) waiting / error / retry states -------------------------------------
const pending = core.pendingTurnHtml({ index: 2, question: questions[1] });
assert.ok(pending.includes("ask-pending"));
assert.ok(pending.includes("正在检索并生成"));
const error = core.errorTurnHtml({ index: 2, question: questions[1], error: "网络错误" });
assert.ok(error.includes('data-ask-retry="2"'), error);
assert.ok(error.includes("重试本轮"));
assert.ok(error.includes("网络错误"));
// an error turn never renders as an answer bubble with citations
assert.ok(!error.includes("ask-citations"));

// ---- 5) API response -> turn mapping ---------------------------------------
const mapped = core.turnFromResponse({
  status: "answered", question: questions[2], answer: "答案 [1]", turn_index: 3,
  retrieved: 4, model: "stub-model",
  citations: [{ index: 1, pdf_name: "b.pdf", page_index: 6, page_number: 7,
                source_page_url: "/api/documents/dc/source-page" }],
  untrusted_citations: ["[9]"],
});
assert.strictEqual(mapped.index, 3);
assert.strictEqual(mapped.retrieved, 4);
assert.strictEqual(core.assistantTurnHtml(mapped).includes("[b.pdf · p7]"), true);
assert.ok(core.assistantTurnHtml(mapped).includes("已忽略"));

console.log("ask_view: all assertions passed ✓");
