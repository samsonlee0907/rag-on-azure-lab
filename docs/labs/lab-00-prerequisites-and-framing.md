# Lab 00 - Prerequisites And Workshop Framing

## Goal

Set the audience context before anyone runs the app:

- why large-document ingestion is hard
- why retrieval quality is a system design problem
- how this workshop separates ingestion improvements from search-mode improvements

## Questions This Lab Answers

- What is Azure AI Search in a RAG architecture?
- Why is retrieval quality mostly a systems problem, not only an LLM problem?
- Why does this workshop separate ingestion improvements from retrieval-mode improvements?
- Why does the workshop keep the same source document across multiple labs?
- Why is agentic retrieval introduced after the direct search modes?

## Core Workshop Message

The workshop has two axes of comparison:

1. **Ingestion profile progression**
   - baseline extraction
   - chunking and embeddings
   - generative enrichment
   - visual and NLP enrichment
   - optional Content Understanding

2. **Retrieval mode progression**
   - full text
   - vector
   - hybrid
   - agentic retrieval

The source document stays constant. Only the profile or retrieval mode changes.

## What To Explain

### 1. The file is not the indexed unit

The workshop app does **not** index a whole PDF as one blob of text. It:

1. parses the file
2. repairs extraction seams
3. creates canonical chunks
4. enriches the original file through Azure AI Search
5. publishes the chunk corpus for multiple retrieval methods

### 2. There are two Azure AI Search responsibilities in the workshop

- `Search-managed Blob enrichment lane`
  - Blob upload
  - Search data source
  - Search indexer
  - Search skillset
  - enrichment cache
  - profile-specific enrichment index

- `Retrieval plane`
  - direct full text search
  - direct vector search
  - direct hybrid search
  - official knowledge-base agentic retrieval

### 3. The app runs in strict mode

The core workshop deliberately fails if Blob + skillset enrichment fails. That keeps the lab honest. Participants see the real Azure path instead of a silent local fallback.

### 4. Agentic retrieval comes after the search-mode fundamentals

The audience should first see:

- what lexical search can and cannot do
- what embeddings improve
- why hybrid often becomes the best direct-search baseline

Only then should the workshop move to agentic retrieval as the official Azure AI Search knowledge-base feature.

## What Participants Need

- local clone of this repository
- Azure subscription access
- Azure CLI signed in
- Python 3.11+

## Code Walkthrough

This is the core workshop contract: keep the same document, change the enrichment profile, and compare retrieval behavior.

```python
# backend/services/workshop_profiles.py
return {
    "comparison_pattern": (
        "ingest the same document into progressively richer Azure AI Search indexes "
        "and compare retrieval behavior"
    ),
    "retrieval_tracks": [
        {"id": "full_text", "title": "Full Text Search"},
        {"id": "vector", "title": "Vector Search"},
        {"id": "hybrid", "title": "Hybrid Search"},
        {"id": "agentic", "title": "Agentic Retrieval"},
    ],
    "active_profile_id": active_profile.id,
}
```

- The workshop is intentionally comparative.
- Participants should change one dimension at a time: either the enrichment profile or the retrieval mode.
- The API surface already exposes this model through `/api/workshop/profiles` and `/api/config`.

This is the ingestion-side sequence the rest of the labs keep reusing:

```python
# backend/services/pipeline.py
profile = parser_registry.detect(path)
intermediate = parser_registry.parse(path, doc_id, profile)
intermediate = normalize_document(intermediate)
chunks = self.chunker.chunk(intermediate)
publish_status = adapter.publish(
    enriched_chunks,
    source_name=intermediate.source_name,
    route_text=" ".join(section_headings),
)
```

- Everything before `publish()` is about document preparation.
- Everything after `publish()` is about how Azure AI Search stores and retrieves the prepared content.
- This distinction is the backbone of the workshop: ingestion quality first, retrieval quality second.

## Configuration Knobs

| Variable | What it controls | Good workshop default |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Which enrichment lab is active. | Start with `baseline_extract`. |
| `DEFAULT_INGESTION_MODE` | Whether uploads go through the Blob + skillset path. | Keep `hybrid_blob_skillset`. |
| `WORKSHOP_STRICT_MODE` | Whether broken Azure steps fail fast instead of silently downgrading. | Keep `true` for workshops. |

## Best-Practice Takeaways

- teach RAG as an indexing-and-retrieval system, not only as a chat interface
- hold the document constant when comparing search behavior
- establish a baseline before introducing more advanced retrieval methods
- keep Azure-dependent paths explicit so participants can see what is really happening

## Files To Inspect

- [`README.md`](../../README.md) for the overall lab sequence.
- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the progression model.
- [`backend/services/pipeline.py`](../../backend/services/pipeline.py) for the ingestion contract.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for the retrieval tracks.

## Learn References

- [Azure AI Search overview](https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search)
- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Skills reference](https://learn.microsoft.com/en-us/azure/search/cognitive-search-predefined-skills)
- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)

## Suggested Opening Questions

- `Why can't we just upload a PDF and chat over it?`
- `What changes when the same document is chunked before search?`
- `Why does vector search find things that lexical search misses?`
- `Why should agentic retrieval be shown after, not before, the other search modes?`
