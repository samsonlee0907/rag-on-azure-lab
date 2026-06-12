# Lab 07 - Agentic Retrieval

## Goal

Switch from direct search modes to the official Azure AI Search knowledge-base retrieval path.

This lab does **not** introduce a new ingestion profile. It uses the best corpus produced in Labs 05 or 06 and changes the retrieval method to `Agentic retrieval`.

## Questions This Lab Answers

- What makes retrieval “agentic” instead of just “hybrid plus an LLM”?
- What are a knowledge source and a knowledge base in practical terms?
- When should I use `agentic` instead of `hybrid`?
- What does answer synthesis add beyond extractive retrieval?

Recommended active profile:

- `genai_enrichment` for text-heavy documents
- `visual_nlp` for diagram-heavy documents

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

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `AZURE_SEARCH_LLM_DEPLOYMENT` | Model used by the knowledge base for planning and answer synthesis. | Point to your supported planning model. |
| `AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS` | Synthesized answer versus raw extractive retrieval. | Toggle on and off to contrast the output styles. |
| `AZURE_SEARCH_LLM_REASONING_EFFORT` | How much effort the retrieve path spends on planning. | Compare `low` versus `medium`. |
| `AZURE_SEARCH_EXTRA_SOURCES_JSON` | Additional knowledge sources for cross-index routing. | Use when you want a multi-corpus lab run. |
| `AZURE_SEARCH_AUTO_BROADCAST_LIMIT` | How aggressively the app fans out across configured knowledge sources. | Raise it if you want broader agentic routing demos. |

## Best-Practice Takeaways

- do not introduce agentic retrieval before participants understand direct search behavior
- use agentic retrieval for decomposition, source routing, and multi-part questions
- keep retrieval activity visible so planning stays inspectable
- compare agentic and hybrid on the same prompt to show what planning actually changes

## Files To Inspect

- [`backend/app.py`](../../backend/app.py) for the retrieval-mode switch.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for the knowledge-base request body and routing.
- [`backend/services/chat.py`](../../backend/services/chat.py) for how citations and retrieval activity are normalized for the UI.

## Learn References

- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Query a knowledge base via APIs](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve)
- [Enable answer synthesis](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-answer-synthesis)
- [Quickstart: agentic retrieval in the Azure portal](https://learn.microsoft.com/en-us/azure/search/get-started-portal-agentic-retrieval)
