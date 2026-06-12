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
cd .\v2
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
