# Environment Reference

## Core App

- `APP_NAME`: UI and API display name.
- `APP_ENV`: environment label.
- `LOG_LEVEL`: structured log verbosity.
- `REQUEST_TIMEOUT_SECONDS`: backend request timeout used by the frontend as the chat baseline.
- `WORKSHOP_STRICT_MODE`: enables fail-fast workshop behavior. When `true`, the app rejects parser downgrades and fails the job if the required Blob + skillset lane does not complete. Optional extensions such as native multimodal retrieval fail the job only if you explicitly require them.
- `WORKSHOP_SKILL_PROFILE`: sets the default selection of the in-app **Skill Profile** picker. Each upload chooses its own Search-managed enrichment profile from the UI, so this value only seeds the default and is not required to switch profiles between labs.

Supported workshop profile values:

- `baseline_extract`
- `chunk_vector`
- `genai_enrichment`
- `visual_nlp`
- `content_understanding`

Recommended core workshop sequence:

1. `baseline_extract`
2. `chunk_vector`
3. `genai_enrichment`
4. `visual_nlp`
5. `content_understanding` only as the optional advanced lab

## Ingestion Mode

- `DEFAULT_INGESTION_MODE`: default UI and API ingestion mode. The workshop defaults to `hybrid_blob_skillset`.
- `SEARCH_PIPELINE_MODE`: label used for the Search-managed enrichment lane.

Supported values:

- `app_managed`
- `hybrid_blob_skillset`

## Retrieval Modes In The Chat UI

These are UI or API request values, not environment variables:

- `full_text`
- `vector`
- `hybrid`
- `agentic`

How the app uses them:

- `full_text`: direct lexical search over the canonical chunk index
- `vector`: direct embedding similarity search over the canonical chunk index
- `hybrid`: direct lexical + vector query over the canonical chunk index
- `agentic`: Azure AI Search knowledge-base retrieve path with planning and subqueries

## Large-Document Controls

- `CHUNK_SIZE_TOKENS`: target chunk size for the structure-aware chunker.
- `CHUNK_OVERLAP_TOKENS`: chunk overlap.
- `MAX_PAGES_PER_SEGMENT`: target parser segment size when a PDF is split for extraction.
- `LARGE_DOCUMENT_PAGE_THRESHOLD`: marks a document as large for warnings and UX.
- `HARD_PAGE_SPLIT_THRESHOLD`: forces split-by-pages behavior when exceeded.
- `HARD_FILE_SPLIT_THRESHOLD_MB`: forces split-by-size behavior when exceeded.
- `USE_SEMANTIC_CHUNKING`: enables the alternate semantic chunking mode.
- `ENABLE_LLM_BOUNDARY_STITCHING`: enables GPT-assisted seam repair for ambiguous cross-segment boundaries.

## Parser Adapters

- `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`
- `AZURE_DOCUMENT_INTELLIGENCE_KEY`
- `AZURE_DOCUMENT_INTELLIGENCE_MODEL`
- `AZURE_CONTENT_UNDERSTANDING_ENDPOINT`
- `AZURE_CONTENT_UNDERSTANDING_KEY`
- `AZURE_CONTENT_UNDERSTANDING_ANALYZER_ID`

Workshop parser contract:

- PDFs require Azure Document Intelligence in workshop strict mode.
- Office documents require Azure Content Understanding or Azure Document Intelligence in workshop strict mode.
- Simple text formats (`txt`, `md`, `csv`, `json`) can use the local parser.
- Unsupported formats are rejected in workshop strict mode.

The app-managed parser path and the Search-managed Blob skillset lane are separate concerns. The Search-managed Blob lane can use `DocumentExtractionSkill` without Azure Content Understanding being configured.

## Azure AI Search Retrieval Plane

- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_KEY`
- `AZURE_SEARCH_QUERY_KEY`
- `AZURE_SEARCH_INDEX_NAME`
- `AZURE_SEARCH_KNOWLEDGE_SOURCE_NAME`
- `AZURE_SEARCH_KNOWLEDGE_BASE_NAME`
- `AZURE_SEARCH_API_VERSION`
- `AZURE_SEARCH_INDEXER_API_VERSION`
- `AZURE_SEARCH_REQUEST_TIMEOUT_SECONDS`
- `AZURE_SEARCH_EXTRA_SOURCES_JSON`
- `AZURE_SEARCH_AUTO_BROADCAST_LIMIT`

`AZURE_SEARCH_EXTRA_SOURCES_JSON` is a JSON array of extra index-backed knowledge sources. Each object can include:

- `knowledge_source_name`
- `index_name`
- `description`
- `route_keywords`
- `assignment_keywords`
- `semantic_configuration_name`
- `source_data_fields`
- `search_fields`

## Blob + Skillset Enrichment Lane

- `AZURE_SEARCH_BLOB_CONNECTION_STRING`
- `AZURE_SEARCH_BLOB_SOURCE_CONTAINER`
- `AZURE_SEARCH_BLOB_SOURCE_PREFIX`
- `AZURE_SEARCH_SKILLSET_NAME`
- `AZURE_SEARCH_BLOB_DATA_SOURCE_NAME`
- `AZURE_SEARCH_BLOB_INDEXER_NAME`
- `AZURE_SEARCH_ENRICHMENT_INDEX_NAME`
- `AZURE_SEARCH_ENRICHMENT_KNOWLEDGE_SOURCE_NAME`
- `AZURE_SEARCH_INCLUDE_ENRICHMENT_SOURCE_IN_CHAT`
- `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR`
- `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS`
- `AZURE_SEARCH_ALLOW_FOUNDRY_ENRICHMENT_SUPPLEMENT`
- `AZURE_SEARCH_PROMPT_SEED_PAGE_LENGTH`
- `AZURE_SEARCH_PROMPT_SEED_PAGES_TO_TAKE`
- `AZURE_SEARCH_PROMPT_SEED_PAGE_OVERLAP`
- `AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_ATTEMPTS`
- `AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_BASE_DELAY_SECONDS`

The workshop flow uploads the original file to Blob, runs Azure AI Search pull-based enrichment, then merges selected enrichment fields back into the canonical app-managed chunk set.

`AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` selects how each document is cracked before enrichment:

- `document_extraction` (default) - Search-managed extraction; the indexer emits whole-page normalized images.
- `content_understanding` - resource-attached Content Understanding skill with semantic chunking (lab 08 / full-managed lane).
- `document_layout` - resource-attached `DocumentIntelligenceLayoutSkill`; it performs figure-aware image cropping server-side and emits each crop with its page number and bounding polygons. The crops are persisted to the asset store via knowledge-store projections (binary crop -> `AZURE_SEARCH_ASSET_STORE_CONTAINER`, per-figure location metadata -> `AZURE_SEARCH_ASSET_STORE_METADATA_CONTAINER`) and feed the same OCR / Image Analysis enrichment as the visual profile (labs 06/07/09 / Option 1). Requires a billable Foundry / AI Services resource (`AZURE_FOUNDRY_RESOURCE_ENDPOINT` or `AZURE_FOUNDRY_API_KEY`). When this extractor is active the indexer's built-in image cracking (`imageAction`) is disabled so the layout skill is the sole source of normalized images.

Recommended core workshop defaults:

- `WORKSHOP_SKILL_PROFILE=baseline_extract`
- `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_extraction`
- `AZURE_SEARCH_ALLOW_FOUNDRY_ENRICHMENT_SUPPLEMENT=false`
- `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS=true`

The skill profile selected for an upload changes the target Search-managed enrichment index, skillset, and indexer names. Use `GET /api/workshop/profiles` to view the profile catalog and the exact target object names for each lab.

Prompt-enrichment guardrails:

- `AZURE_SEARCH_PROMPT_SEED_PAGE_LENGTH`, `AZURE_SEARCH_PROMPT_SEED_PAGES_TO_TAKE`, and `AZURE_SEARCH_PROMPT_SEED_PAGE_OVERLAP` control the smaller built-in Text Split window used for summary and tag generation.
- `AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_ATTEMPTS` and `AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_BASE_DELAY_SECONDS` control retry and backoff when Search-managed prompt skills hit transient Azure OpenAI throttling.

Supported extractor values:

- `document_extraction`
- `content_understanding`

If you explicitly set `content_understanding`, you must also configure the Azure Content Understanding endpoint, key, and analyzer ID. In workshop strict mode, the app fails instead of silently switching extractors.

## Skillset Features

- `AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS`: enables Search-side answer synthesis for agentic retrieval.
- `AZURE_SEARCH_ANSWER_INSTRUCTIONS`: instructions passed to Search answer synthesis when enabled.
- `AZURE_SEARCH_ENABLE_ENRICHMENT_CACHE`
- `AZURE_SEARCH_ENRICHMENT_CACHE_CONNECTION_STRING`
- `AZURE_SEARCH_ENRICHMENT_CACHE_CONTAINER`
- `AZURE_SEARCH_ENABLE_GENAI_PROMPT_SKILL`
- `AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION`
- `AZURE_SEARCH_VECTOR_FIELD_NAME`
- `AZURE_SEARCH_VECTOR_DIMENSIONS`

Notes:

- The core workshop uses integrated vectorization in the Search-managed enrichment lane and canonical chunk vectors in the direct-search lane.
- `AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS=true` is recommended for Lab 07 so the official agentic retrieval path is fully demonstrated.

## Search Planning, Synthesis, And Embeddings

- `AZURE_SEARCH_LLM_DEPLOYMENT`
- `AZURE_SEARCH_LLM_MODEL_NAME`
- `AZURE_SEARCH_LLM_REASONING_EFFORT`
- `AZURE_SEARCH_LLM_USE_MANAGED_IDENTITY`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDING_MODEL_NAME`

These settings control:

- the LLM attached to the Azure AI Search knowledge base for planning and answer synthesis
- embeddings used for vector and hybrid search

Recommended workshop pattern:

- use the same supported LLM family for the generative roles when that simplifies the workshop
- keep separate deployment names for Search planning, native multimodal synthesis, and app-side synthesis
- keep embeddings on a separate embedding deployment

## Foundry / App-side Model Path

- `AZURE_FOUNDRY_RESOURCE_ENDPOINT`
- `AZURE_FOUNDRY_API_KEY`
- `AZURE_FOUNDRY_CHAT_DEPLOYMENT`
- `AZURE_FOUNDRY_PROJECT_ENDPOINT`
- `AZURE_FOUNDRY_AGENT_ID`
- `FOUNDRY_CHAT_MODE`

The app uses the Foundry chat deployment to synthesize grounded answers for the direct `full_text`, `vector`, and `hybrid` modes after Azure AI Search returns the matching chunk set.

## Native Multimodal Indexing (Default Path)

- `AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL`
- `AZURE_SEARCH_NATIVE_API_VERSION`
- `AZURE_SEARCH_NATIVE_KNOWLEDGE_BASE_NAME`
- `AZURE_SEARCH_NATIVE_KNOWLEDGE_SOURCE_PREFIX`
- `AZURE_SEARCH_NATIVE_AUTO_QUERY_TERMS`
- `AZURE_SEARCH_NATIVE_CONTENT_EXTRACTION_MODE`
- `AZURE_SEARCH_NATIVE_CHAT_COMPLETION_DEPLOYMENT`
- `AZURE_SEARCH_NATIVE_CHAT_COMPLETION_MODEL_NAME`
- `AZURE_SEARCH_NATIVE_RETRIEVE_RETRY_ATTEMPTS`
- `AZURE_SEARCH_NATIVE_RETRIEVE_RETRY_BASE_DELAY_SECONDS`
- `AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS`
- `AZURE_SEARCH_ENABLE_IMAGE_SERVING`
- `AZURE_SEARCH_ASSET_STORE_CONNECTION_STRING`
- `AZURE_SEARCH_ASSET_STORE_CONTAINER`
- `AZURE_SEARCH_ASSET_STORE_METADATA_CONTAINER`

This is now the **default indexing and retrieval path**. The Blob upload is registered as an `azureBlob` Azure AI Search knowledge source whose managed `contentExtractionMode` runs the Document Layout pipeline server-side: it crops figures, persists them to the asset store, verbalizes/embeds them, and serves them through image-serving URLs. This replaces the offline render-then-crop figure parser for the default run; that parser remains available as an explicit opt-in (see Figure Artifacts).

Recommended core workshop defaults:

- `AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL=true`
- `AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS=false`
- `AZURE_SEARCH_ENABLE_IMAGE_SERVING=true`

To fall back to the offline figure parser lane, set `AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL=false` and `ENABLE_PARSER_FIGURE_EXTRACTION=true`.

## Blob Storage

- `AZURE_STORAGE_ACCOUNT`
- `AZURE_STORAGE_ACCOUNT_KEY`
- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_CONTAINER`

The artifact store uses these settings for extracted figure images. The Blob skillset lane can reuse the same storage account or use a separate Blob connection string through `AZURE_SEARCH_BLOB_CONNECTION_STRING`.

For the core workshop path, leave `AZURE_STORAGE_ACCOUNT_KEY` blank and rely on the signed-in Azure identity plus RBAC for Blob access.

## RBAC Scaffolding

- `AZURE_SEARCH_ENABLE_BLOB_RBAC`
- `AZURE_SEARCH_DEFAULT_RBAC_SCOPE_IDS`
- `AZURE_SEARCH_BLOB_RBAC_METADATA_FIELD`

If enabled, the app can stamp default RBAC scopes into uploaded Blob metadata and carry those values into the Search-managed enrichment index and canonical chunks.

## Figure Artifacts (Offline Parser — Opt-In)

- `ENABLE_PARSER_FIGURE_EXTRACTION`
- `ENABLE_IMAGE_UNDERSTANDING`
- `PARSER_FIGURE_MAX_ARTIFACTS`
- `MAX_FIGURE_IMAGE_PIXELS`
- `MAX_FIGURE_IMAGE_DIMENSION`

The offline render-then-crop figure parser is skipped automatically when the native multimodal lane is enabled (the default), since the managed Document Layout pipeline supplies cropped figures instead. Set `ENABLE_PARSER_FIGURE_EXTRACTION=true` to force the offline parser back on (for example when running with `AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL=false`).

The workshop keeps parser-side figure extraction off in the earlier labs and enables it in the visual or Content Understanding tracks. Large embedded PDF figures are normalized to PNG artifacts. Oversized images are downscaled before GPT-based image understanding so a single large TIFF doesn't fail the whole ingestion job. `PARSER_FIGURE_MAX_ARTIFACTS` puts a practical ceiling on parser-side figure work for very large PDFs.
