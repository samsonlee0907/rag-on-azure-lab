# Lab 07 - Agentic Retrieval

## Goal

Switch from direct search modes to the official Azure AI Search knowledge-base retrieval path.

This lab does **not** introduce a new ingestion profile. It uses the best corpus produced in Labs 05 or 06 and changes the retrieval method to `Agentic retrieval`.

> GA, with a preview surface in this workshop. The core agentic retrieval flow - knowledge bases, indexed knowledge sources, and the `retrieve` action - is **generally available in the `2026-04-01` REST API** for programmatic access. This app pins `2026-05-01-preview` (see `AZURE_SEARCH_API_VERSION`) to exercise the newest capabilities (multi-source routing, semantic chunking, AI image descriptions); those preview-only features have no SLA and are not recommended for production. The Azure portal and Microsoft Foundry portal also expose agentic retrieval as preview-only. Internally, agentic retrieval runs each subquery as a hybrid query and reranks it with the semantic ranker, so the same semantic-ranker availability and billing caveats from Lab 04 apply. Azure AI Search bills agentic retrieval by retrieval tokens; the planning and answer-synthesis LLM calls are billed separately on Azure OpenAI.

## Questions This Lab Answers

- What makes retrieval “agentic” instead of just “hybrid plus an LLM”?
- What are a knowledge source and a knowledge base in practical terms?
- When should I use `agentic` instead of `hybrid`?
- What does answer synthesis add beyond extractive retrieval?

Recommended active profile:

- `genai_enrichment` for text-heavy documents
- `visual_nlp` for diagram-heavy documents

> The `visual_nlp` corpus is now built with the **Document Layout** extractor (Lab 06), so its
> figure crops are figure-aware and carry page / bounding-polygon metadata. Agentic retrieval over
> that corpus draws on the same `-visual-nlp` enrichment index (richer OCR + captions), so questions
> that reference "supporting figures" have cleaner visual evidence to reason over.

## Step 1 - Keep one corpus selected

Use `Custom Selection` and pick exactly one ready corpus first. That makes the retrieval activity easier to explain.

## Step 2 - Set the retrieval mode to `Agentic retrieval`

The chat UI now routes the question through the Azure AI Search knowledge base instead of the direct `docs/search` path.

## Step 3 - Ask a complex question

Use questions that benefit from decomposition or multi-step reasoning:

- `Explain how the document describes ingestion, indexing, and answer generation. Separate the answer into extraction, indexing, and retrieval stages.`
- `Compare the document's view of retrieval quality, chunking, and evidence grounding. What should a team implement first and why?`
- `Use the workflow sections and any supporting figures to explain the end-to-end architecture.`

## Step 4 - Inspect the retrieval activity

Use the right-hand activity panel to show:

- routing summary
- the retrieval method
- visible search steps
- decomposed search intents when Azure AI Search returns them

## Step 5 - Compare against `Hybrid`

Run the same question once in `Hybrid` mode and once in `Agentic retrieval`.

Explain the difference:

- `Hybrid` is still a direct search request over the canonical chunk index.
- `Agentic retrieval` uses the knowledge base and can decompose the question into subqueries before grounding the answer.

## Step 6 - Explain what counts as success

The point of this lab is not that agentic retrieval always returns more steps. The point is that it is the official Azure AI Search retrieval mode for query planning, subqueries, source selection, and grounded synthesis.

## Success Criteria

- the answer returns in `Agentic retrieval` mode
- the debug panel shows `retrieval_mode = agentic`
- the activity panel shows retrieval routing and any exposed subqueries
- the answer remains grounded with citations
- on the `visual_nlp` corpus, citations that land on a figure page also show figure cards - the same
  query-time crop join that `Hybrid` uses applies to agentic citations

## Code Walkthrough

The chat endpoint cleanly separates direct search from agentic retrieval:

```python
# backend/app.py
elif requested_retrieval_mode in {"full_text", "vector", "hybrid"}:
    payload = adapter.direct_search(
        question_text,
        retrieval_mode=requested_retrieval_mode,
        doc_ids=selected_doc_ids or None,
        doc_source_assignments=doc_source_assignments,
    )
else:
    payload = adapter.chat(
        question_text,
        doc_ids=selected_doc_ids or None,
        doc_source_assignments=doc_source_assignments,
    )
```

- `full_text`, `vector`, and `hybrid` all stay on the direct `docs/search` path.
- `agentic` switches to the knowledge-base `retrieve` action.
- This is the cleanest place in the repo to explain the difference between search modes and the official agentic feature.

The actual knowledge-base retrieve payload is built here:

```python
# backend/services/indexing.py
payload = {
    "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
    "includeActivity": True,
    "outputMode": "answerSynthesis" if settings.azure_search_enable_answer_synthesis else "extractiveData",
    "retrievalReasoningEffort": {"kind": settings.azure_search_llm_reasoning_effort},
    "knowledgeSourceParams": knowledge_source_params,
}
```

- `knowledgeSourceParams` is how the app scopes the retrieve call to the selected corpus or corpora.
- `includeActivity` is why the portal can show the routing summary and the visible search steps.
- `retrievalReasoningEffort` is one of the easiest configuration knobs to demonstrate live.

### Figure evidence works in agentic mode too

Agentic retrieval returns its own citations from the knowledge base, but it does **not** need a
separate image path. After the knowledge base returns, the same query-time figure join from Lab 06
(`_hydrate_citations` + `_build_native_figure_page_map` in
[backend/services/chat.py](../../backend/services/chat.py)) runs over the agentic citations and
attaches figure crops by `doc_id` + page number - exactly as it does for `Hybrid`, `Vector`, and
`Full text`:

```python
# backend/services/chat.py - one chokepoint runs for every retrieval mode, agentic included
citations = _hydrate_citations(citations)   # joins native figure crops onto citations by page
```

- This is why an agentic answer over the `visual_nlp` corpus shows the same figure cards as a hybrid
  answer: the join keys on the citation's document and pages, not on which retrieval mode produced it.
- If you ask a "use any supporting figures" question in `Agentic retrieval` and see figure cards
  under the citations, that join is doing its work. (If figures appear in `Hybrid` but not `Agentic`,
  it is almost always a stale browser cache - hard-refresh with Ctrl+F5.)

### Figure *text* now reaches the direct lanes too

Agentic retrieval has always had an edge on chart-heavy questions because its in-Search enrichment
index already carries the figure OCR (`ocr_text_chunks`) and captions, so the in-Search synthesizer
can reason over chart numbers directly. The direct lanes (`Full text`, `Vector`, `Hybrid`) historically
could not - they only saw the chunk's prose snippet and the crop *image*, which the answer model can't
read. Lab 06's per-figure text projection (`search-image-assets-text`) plus the snippet injection in
`_hydrate_citations` closes that gap: the figure's OCR/caption text is spliced onto the citation
snippet by page, so the direct lanes now reflect chart content too. Net effect after the next
ingestion: every retrieval mode - agentic and direct - can answer "what does the chart on page 4 show"
with the figure's actual numbers.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `AZURE_SEARCH_LLM_DEPLOYMENT` | Model used by the knowledge base for planning and answer synthesis. | Point to your supported planning model. |
| `AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS` | Synthesized answer versus raw extractive retrieval. | Toggle on and off to contrast the output styles. |
| `AZURE_SEARCH_LLM_REASONING_EFFORT` | How much effort the retrieve path spends on planning. | `low` (the default) and `medium` send the query to the LLM for subquery planning and knowledge-source selection; `minimal` skips planning and issues the query directly. Compare `minimal` vs `low` vs `medium`. |
| `AZURE_SEARCH_EXTRA_SOURCES_JSON` | Additional knowledge sources for cross-index routing. | Use when you want a multi-corpus lab run. |
| `AZURE_SEARCH_AUTO_BROADCAST_LIMIT` | How aggressively the app fans out across configured knowledge sources. | Raise it if you want broader agentic routing demos. |

## Best-Practice Takeaways

- do not introduce agentic retrieval before participants understand direct search behavior
- use agentic retrieval for decomposition, source routing, and multi-part questions
- keep retrieval activity visible so planning stays inspectable
- compare agentic and hybrid on the same prompt to show what planning actually changes
- remember that lower `retrievalReasoningEffort` and fewer knowledge sources reduce both latency and token cost

## Files To Inspect

- [`backend/app.py`](../../backend/app.py) for the retrieval-mode switch.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for the knowledge-base request body and routing.
- [`backend/services/chat.py`](../../backend/services/chat.py) for how citations and retrieval activity are normalized for the UI.

## Learn References

- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Query a knowledge base via APIs](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve)
- [Enable answer synthesis](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-answer-synthesis)
- [Quickstart: agentic retrieval in the Azure portal](https://learn.microsoft.com/en-us/azure/search/get-started-portal-agentic-retrieval)
