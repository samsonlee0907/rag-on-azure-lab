# Lab 10 - Troubleshooting And Verification

## Goal

Give facilitators a short operational checklist for the progressive workshop track.

## Questions This Lab Answers

- If an upload fails, where should I inspect first?
- How do I tell whether the failure is in parsing, Search enrichment, or retrieval?
- Which environment variables are most likely to explain unexpected behavior?
- How do I debug Azure AI Search behavior without guessing?

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
- `/api/workshop/profiles` lists every Skill Profile the upload picker can offer (profiles are now chosen per document, so there is no single "active" profile to match against a lab)
- the available retrieval modes include `full_text`, `vector`, `hybrid`, and `agentic`

### 3. Python tests

```powershell
python -m pytest
```

The suite uses `pytest` (with `pytest-asyncio` for the async retrieval tests), so run it through `pytest` rather than `unittest`, which would skip the async cases.

## Common Failure Patterns

### Blob + skillset ingestion fails

Check:

- Search endpoint and key
- Blob connection string
- Foundry resource endpoint
- Search service identity access to Foundry
- indexer status in Azure AI Search
- the Skill Profile selected for that upload and its target index or skillset names

### Vector or hybrid retrieval fails

Check:

- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDING_MODEL_NAME`
- canonical index schema contains the vector field
- the current corpus was uploaded after vector support was enabled
- the selected corpus is the one you think it is
- the semantic ranker is enabled and available in your search service region, since `hybrid` (and agentic) requests use `queryType=semantic` against `default-semantic-config`

### Hybrid returns an error about semantic configuration or ranking

Check:

- the search service tier and region support the [semantic ranker](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview)
- semantic ranker billing is enabled (it is a separately billed premium feature)
- the index actually has the `default-semantic-config` semantic configuration
- `full_text` still works, which isolates the failure to the semantic ranking layer rather than BM25 or filters

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

## Code Walkthrough

The pipeline is intentionally strict about the Azure-dependent steps:

```python
# backend/services/pipeline.py
if (
    settings.azure_search_require_blob_skillset_success
    and enrichment_snapshot.status != "completed"
):
    raise RuntimeError(
        "Azure AI Search Blob + skillset enrichment did not complete successfully."
    )

if (
    settings.azure_search_require_native_multimodal_success
    and native_snapshot.status != "completed"
):
    raise RuntimeError(
        "Azure AI Search native Blob multimodal provisioning did not complete successfully."
    )
```

- This is why workshop failures are visible instead of silently degrading.
- When an upload fails after the parser phase, this is one of the first places to inspect.

The app also gives you a quick runtime summary of what is enabled:

```python
# backend/app.py
return {
    "azure_search_enabled": settings.azure_search_enabled,
    "azure_search_enable_answer_synthesis": settings.azure_search_enable_answer_synthesis,
    "azure_search_enable_integrated_vectorization": settings.azure_search_enable_integrated_vectorization,
    "workshop_skill_profile": settings.workshop_skill_profile,
    "available_retrieval_modes": ["full_text", "vector", "hybrid", "agentic"],
}
```

- `/api/config` is the fastest way to confirm whether the workshop is actually running the mode you think it is.
- If the UI looks wrong, start there before debugging the deeper Azure calls.

## Configuration Knobs

| Variable | What it controls | When to inspect it |
| --- | --- | --- |
| `WORKSHOP_STRICT_MODE` | Whether failures are surfaced immediately. | First check when a step unexpectedly succeeds or silently degrades. |
| `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS` | Whether Blob + skillset enrichment is mandatory. | Check when uploads fail after extraction. |
| `AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS` | Whether native multimodal provisioning is mandatory. | Check when native paths are enabled. |
| `REQUEST_TIMEOUT_SECONDS` | App-side request timeout. | Check when chat feels stuck or prematurely fails. |
| `AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_ATTEMPTS` | Search indexer retry behavior. | Check when indexers intermittently fail. |
| `AZURE_SEARCH_LLM_REASONING_EFFORT` | Planning effort for agentic retrieval. | Check when agentic responses are too slow or too shallow. |

## Best-Practice Takeaways

- debug from the outside in: config, stage, service call, then implementation details
- use `/api/config` to verify mode and feature flags before deeper troubleshooting
- fail-fast workshop settings are useful because they make the true failing Azure step visible
- keep one known-good document around as a control case while debugging
- for production, prefer Microsoft Entra ID with role-based access over the `api-key` header that the workshop uses for Search index and query calls

## Files To Inspect

- [`backend/app.py`](../../backend/app.py) for API routes and `/api/config`.
- [`backend/core/config.py`](../../backend/core/config.py) for the controlling flags.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for Blob ingestion, skillset, and indexer failures.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for full-text, vector, hybrid, and agentic retrieval issues.
- [`backend/services/pipeline.py`](../../backend/services/pipeline.py) for stage-by-stage ingestion behavior.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Reset and rerun indexers](https://learn.microsoft.com/en-us/azure/search/search-howto-run-reset-indexers)
- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
