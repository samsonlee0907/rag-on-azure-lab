# Lab 03 - Baseline Extraction And Full Text Search

## Goal

Establish the simplest Azure AI Search baseline:

- `DocumentExtractionSkill`
- Blob data source
- Search indexer
- one profile-specific enrichment index
- full text retrieval over the canonical chunk index

Set:

```dotenv
WORKSHOP_SKILL_PROFILE=baseline_extract
```

## Step 1 - Start or restart the app

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8016
```

## Step 2 - Verify the active profile

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `active_profile_id` is `baseline_extract`
- the target enrichment index name ends with `-baseline`

## Step 3 - Upload the workshop document

Use one representative document and keep it for the rest of the workshop.

Recommended document traits:

- 50+ pages if possible
- headings and section changes
- at least one diagram or structured figure

## Step 4 - Wait for the corpus to reach `ready`

Use the portal:

- `Ingestion`
- `Knowledge Base`

Confirm:

- document status is `ready`
- Blob + skillset enrichment completed

## Step 5 - Set the chat retrieval mode to `Full text`

In the chat UI:

1. use `Custom Selection`
2. pick only the newly uploaded corpus
3. choose `Full text`

## Step 6 - Ask the baseline prompts

- `What major sections and themes are present in this document?`
- `Which exact phrases from the document best describe the main architecture or workflow?`
- `What part of the document best matches the phrase "indexing and retrieval"?`

## Step 7 - Explain what the audience should notice

Call out:

- exact-term sensitivity
- lexical matching strength
- lexical miss behavior when the wording changes
- broader or noisier evidence when chunking and semantic signals are still minimal

## Success Criteria

- the document reaches `ready`
- Blob + skillset enrichment completes
- the enrichment index recorded in the job ends with `-baseline`
- full text search returns grounded citations over the selected corpus

## What To Inspect In This Repo

```text
Profile: baseline_extract
Built-in skill focus: DocumentExtractionSkill
Retrieval focus: full_text

Primary files:
- backend/services/workshop_profiles.py
- backend/services/search_skillset_enrichment.py
- backend/services/indexing.py
- backend/app.py
```

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py)
  The `baseline_extract` profile declares the lab title, the target enrichment index names, and the fact that this lab adds only `DocumentExtractionSkill`.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Inspect `AzureSearchSkillsetEnrichmentService._build_skillset_body()` and `_build_extractor_skill()`. This is where the Blob skillset lane is assembled for the baseline lab.
- [`backend/services/indexing.py`](../../backend/services/indexing.py)
  Inspect `AzureSearchKnowledgeBaseAdapter.direct_search()` and `_run_direct_search()`. This is where `full_text` is translated into a direct `docs/search` request over the canonical chunk index.
- [`backend/app.py`](../../backend/app.py)
  Inspect `config_summary()`, `workshop_profiles()`, and `chat()`. These show how the UI discovers the active profile and how the chat request selects the `full_text` path.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Document Extraction skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-document-extraction)
- [Create a full-text query](https://learn.microsoft.com/en-us/azure/search/search-query-create)
- [BM25 relevance scoring](https://learn.microsoft.com/en-us/azure/search/index-similarity-and-scoring)
