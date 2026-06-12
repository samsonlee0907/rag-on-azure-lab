# Lab 07 - Agentic Retrieval

## Goal

Switch from direct search modes to the official Azure AI Search knowledge-base retrieval path.

This lab does **not** introduce a new ingestion profile. It uses the best corpus produced in Labs 05 or 06 and changes the retrieval method to `Agentic retrieval`.

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
