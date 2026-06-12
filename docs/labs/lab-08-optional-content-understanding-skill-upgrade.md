# Lab 08 - Optional Content Understanding Upgrade

## Goal

Run the same workshop comparison with the Azure Content Understanding skill as the Search-managed extractor.

Set:

```dotenv
WORKSHOP_SKILL_PROFILE=content_understanding
AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=content_understanding
```

## When To Use This Lab

Use this only after Labs 03 through 07 are working. It is the advanced comparison lab for:

- Search-managed semantic extraction
- Search-managed chunk boundary quality
- richer structure handling for mixed-layout or figure-heavy documents

## Step 1 - Configure Azure Content Understanding

Add:

```dotenv
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=
AZURE_CONTENT_UNDERSTANDING_KEY=
AZURE_CONTENT_UNDERSTANDING_ANALYZER_ID=
```

Leave strict mode on:

```dotenv
WORKSHOP_STRICT_MODE=true
AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS=true
```

## Step 2 - Restart the app

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8016
```

## Step 3 - Upload the same document again

Use the same source file when possible.

## Step 4 - Compare against earlier profiles

Use:

- `Hybrid` for direct chunk-quality comparison
- `Agentic retrieval` for the official knowledge-base comparison

Discuss:

- chunk boundary quality
- section continuity
- table and figure handling
- retrieval behavior for structure-heavy questions

## Success Criteria

- the app starts without strict-mode extractor errors
- Blob + skillset enrichment completes
- the enrichment index recorded in the job ends with `-content-understanding`

## What To Inspect In This Repo

```text
Profile: content_understanding
Built-in skill focus:
- ContentUnderstandingSkill

Retrieval focus:
- hybrid
- agentic
```

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py)
  The `content_understanding` profile declares the advanced extractor comparison track.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Inspect `_active_extractor_kind()`, `_build_extractor_skill()`, and `_build_skillset_body()`. This is where the Search-managed extractor flips from `document_extraction` to `content_understanding`.
- [`backend/services/parsers.py`](../../backend/services/parsers.py)
  Compare the app-managed Azure Content Understanding parser path with the Search-managed Content Understanding skill path so the audience sees that these are different integration layers.
- [`backend/core/config.py`](../../backend/core/config.py)
  Inspect the Content Understanding environment variables and the `azure_content_understanding_enabled` flag.

## Learn References

- [Document Layout skill for semantic chunking](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking)
- [Chunk and vectorize content with the Azure Content Understanding skill](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking-content-understanding)
- [Integrated vectorization](https://learn.microsoft.com/en-us/azure/search/search-how-to-integrated-vectorization)
