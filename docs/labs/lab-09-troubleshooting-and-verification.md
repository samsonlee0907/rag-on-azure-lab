# Lab 09 - Troubleshooting And Verification

## Goal

Give facilitators a short operational checklist for the progressive workshop track.

## Quick Checks

### 1. App health

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/health
```

### 2. Config summary

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/config
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/workshop/profiles
```

Verify:

- Search is enabled
- Blob ingestion is enabled
- strict mode is enabled
- the active workshop profile matches the lab you intend to run
- the available retrieval modes are `full_text`, `vector`, `hybrid`, and `agentic`

### 3. Python tests

```powershell
python -m unittest discover -s tests
```

## Common Failure Patterns

### Blob + skillset ingestion fails

Check:

- Search endpoint and key
- Blob connection string
- Foundry resource endpoint
- Search service identity access to Foundry
- indexer status in Azure AI Search
- active workshop profile and its target index or skillset names

### Vector or hybrid retrieval fails

Check:

- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- canonical index schema contains the vector field
- the current corpus was uploaded after vector support was enabled
- the selected corpus is the one you think it is

### Agentic retrieval fails

Check:

- knowledge base exists
- knowledge sources exist
- `AZURE_SEARCH_LLM_DEPLOYMENT` is valid
- answer synthesis is enabled if the workshop expects Search-side answer synthesis
- the selected corpus is actually ready

### Chat returns no visible subqueries

Check:

- the question is complex enough to trigger planning
- the debug panel is enabled
- Azure AI Search may still have used agentic reasoning even if only one concrete search step is exposed

## Facilitator Smoke Prompts

Use these before the audience joins:

- `What major sections and themes are present in this document?`
- `Which specific chunk best explains the architecture workflow in this document?`
- `What summary or retrieval cues make this document easier to search accurately?`
- `Explain how the document describes ingestion, indexing, and answer generation. Separate the answer into extraction, indexing, and retrieval stages.`

Together these validate:

- Blob + skillset ingestion
- progressive profile switching
- full text retrieval
- vector retrieval
- hybrid retrieval
- agentic retrieval
- citation rendering
- evidence card rendering

## What To Inspect In This Repo

```text
Focus for this lab:
- connect a failed workshop step to the exact code and config involved

Primary files:
- backend/app.py
- backend/core/config.py
- backend/services/search_skillset_enrichment.py
- backend/services/indexing.py
- backend/services/pipeline.py
```

- [`backend/app.py`](../../backend/app.py)
  Start here when a portal action or API route behaves differently than expected.
- [`backend/core/config.py`](../../backend/core/config.py)
  Use this to verify which environment flag controls the behavior you are troubleshooting.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Use this for Blob data source, skillset, indexer, enrichment cache, and prompt-skill failures.
- [`backend/services/indexing.py`](../../backend/services/indexing.py)
  Use this for direct full-text, vector, hybrid, or agentic retrieval failures.
- [`backend/services/pipeline.py`](../../backend/services/pipeline.py)
  Use this for stage-by-stage ingestion errors, retries, and artifact handling.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Reset and rerun indexers](https://learn.microsoft.com/en-us/azure/search/search-howto-run-reset-indexers)
- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
