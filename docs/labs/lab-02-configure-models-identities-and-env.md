# Lab 02 - Configure Models, Identities, And Environment

## Goal

Prepare the exact workshop configuration so the core Azure-native path is the one being exercised.

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
