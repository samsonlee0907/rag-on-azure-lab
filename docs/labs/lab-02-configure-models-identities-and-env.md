# Lab 02 - Configure Models, Identities, And Environment

## Goal

Prepare the exact workshop configuration so the core Azure-native path is the one being exercised.

## Questions This Lab Answers

- Which model does what in this workshop?
- What is the difference between app-side synthesis and Search-side planning?
- Which environment variables are mandatory for the first successful run?
- How do I verify the app is using the configuration I expect?

## Step 1 - Deploy or confirm the models

The core workshop uses these model roles:

- `AZURE_FOUNDRY_CHAT_DEPLOYMENT`
  - app-owned grounded synthesis
- `AZURE_SEARCH_LLM_DEPLOYMENT`
  - Search knowledge-base planning
  - Search answer synthesis for agentic retrieval
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
  - Search vectorization
  - canonical chunk vectors

Recommended deployment names used in the workshop:

- `gpt-5-4`
- `gpt-5-mini`
- `text-embedding-3-large`

## Step 2 - Copy the environment template

```powershell
Copy-Item .env.example .env
```

## Step 3 - Keep the workshop-safe defaults

These values should stay on for the core workshop:

```dotenv
WORKSHOP_STRICT_MODE=true
WORKSHOP_SKILL_PROFILE=baseline_extract
DEFAULT_INGESTION_MODE=hybrid_blob_skillset
SEARCH_PIPELINE_MODE=hybrid_blob_skillset
AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS=true
AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS=true
AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL=false
AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS=false
AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_extraction
```

## Step 4 - Fill the Azure values

At minimum:

```dotenv
AZURE_SEARCH_ENDPOINT=
AZURE_SEARCH_KEY=
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=
AZURE_SEARCH_BLOB_CONNECTION_STRING=
AZURE_SEARCH_ENRICHMENT_CACHE_CONNECTION_STRING=
AZURE_FOUNDRY_RESOURCE_ENDPOINT=
AZURE_FOUNDRY_CHAT_DEPLOYMENT=
AZURE_SEARCH_LLM_DEPLOYMENT=
AZURE_SEARCH_LLM_MODEL_NAME=
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=
AZURE_STORAGE_ACCOUNT=
```

## Step 5 - Validate the app configuration contract

After the app is running, `GET /api/config` should report:

- `azure_search_enabled = true`
- `azure_search_blob_ingestion_enabled = true`
- `workshop_strict_mode = true`
- `workshop_skill_profile = baseline_extract`
- `available_retrieval_modes = ["full_text", "vector", "hybrid", "agentic"]`
- `default_retrieval_mode = agentic`
- `azure_search_enable_answer_synthesis = true`

## Success Criteria

- `.env` is complete
- model names are resolved
- strict mode is enabled
- the four core retrieval modes are available

## Code Walkthrough

The workshop is largely controlled by environment variables. Participants should see that the lab behavior is not hardcoded in the UI.

```dotenv
# .env.example
WORKSHOP_SKILL_PROFILE=baseline_extract
DEFAULT_INGESTION_MODE=hybrid_blob_skillset
AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS=true
AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION=true
AZURE_SEARCH_LLM_DEPLOYMENT=
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=
```

- `WORKSHOP_SKILL_PROFILE` decides which skillset profile the Search indexer will build.
- `AZURE_SEARCH_LLM_DEPLOYMENT` is the planning and answer-synthesis model used by Azure AI Search.
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` is the embedding model used for vector search.

The app exposes the interpreted configuration so the audience can verify it without reading logs:

```python
# backend/app.py
return {
    "azure_agentic_planning_model": settings.azure_search_llm_deployment,
    "azure_search_enable_answer_synthesis": settings.azure_search_enable_answer_synthesis,
    "azure_search_enable_integrated_vectorization": settings.azure_search_enable_integrated_vectorization,
    "azure_search_skillset_preferred_extractor": settings.azure_search_skillset_preferred_extractor,
    "workshop_skill_profile": settings.workshop_skill_profile,
}
```

- `/api/config` is the quickest proof that the environment has been parsed correctly.
- If a participant changes `.env` and `/api/config` does not reflect the change, the issue is almost always environment loading or restart behavior.

## Configuration Knobs

| Variable | What it controls | Typical workshop use |
| --- | --- | --- |
| `AZURE_SEARCH_LLM_DEPLOYMENT` | Search-side model for planning and answer synthesis. | Required for `agentic` retrieval. |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model for vector and hybrid search. | Required from Lab 04 onward. |
| `AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS` | Whether Azure AI Search returns a synthesized answer or extractive data. | Keep `true` for agentic demos. |
| `AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION` | Whether the Search-managed enrichment lane writes vectors. | Keep `true` from Lab 04 onward. |
| `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` | Switches between `document_extraction` and `content_understanding`. | Leave at `document_extraction` until Lab 08. |
| `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS` | Makes broken Search enrichment fail visibly. | Keep `true` in a workshop. |

## Best-Practice Takeaways

- keep the first working configuration minimal and explicit
- validate runtime interpretation through `/api/config` before debugging deeper
- treat planning models and embedding models as separate dependencies
- keep optional modes off until the core workshop path is stable

## Files To Inspect

- [`.env.example`](../../.env.example) for the environment contract.
- [`backend/core/config.py`](../../backend/core/config.py) for how those variables become runtime settings.
- [`backend/app.py`](../../backend/app.py) for `/api/config`.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for where the LLM and embedding deployments are used.

## Learn References

- [Vector search overview](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Enable answer synthesis](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-answer-synthesis)
- [Azure OpenAI Embedding skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-azure-openai-embedding)
