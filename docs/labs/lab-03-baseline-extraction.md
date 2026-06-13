# Lab 03 - Baseline Extraction And Full Text Search

## Goal

Establish the simplest Azure AI Search baseline:

- `DocumentExtractionSkill`
- Blob data source
- Search indexer
- one profile-specific enrichment index
- full text retrieval over the canonical chunk index

## Questions This Lab Answers

- What does `DocumentExtractionSkill` actually do to a file?
- Why is full-text search still important in a RAG workshop?
- What does a lexical baseline tell me before I add chunking and embeddings?
- Why can the baseline return broader or noisier evidence?

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

## Code Walkthrough

The baseline profile deliberately adds only one built-in skill:

```python
# backend/services/workshop_profiles.py
WorkshopSkillProfile(
    id="baseline_extract",
    added_skills=("DocumentExtractionSkill",),
    cumulative_skills=("DocumentExtractionSkill",),
    recommended_retrieval_modes=("full_text",),
)
```

- This is the control group for the rest of the workshop.
- The goal is to show what Azure AI Search can do with only extracted text and lexical matching.

This is the actual skill definition the Search skillset uses:

```python
# backend/services/search_skillset_enrichment.py
skills = [self._build_extractor_skill(extractor_kind=extractor_kind)]

return {
    "@odata.type": "#Microsoft.Skills.Util.DocumentExtractionSkill",
    "name": "#documentExtraction",
    "configuration": {"imageAction": "generateNormalizedImages"},
    "inputs": [{"name": "file_data", "source": "/document/file_data"}],
    "outputs": [{"name": "content", "targetName": "content_markdown"}],
}
```

- `DocumentExtractionSkill` turns the Blob file into `content_markdown`.
- `imageAction=generateNormalizedImages` is important because it prepares image derivatives even before OCR and image analysis are turned on in later labs.

Baseline retrieval is intentionally simple:

```python
# backend/services/indexing.py
if retrieval_mode == "full_text":
    body["search"] = question
    return body
```

- This is plain lexical search over the canonical chunk index.
- It is the right baseline for demonstrating term sensitivity and lexical misses.

## Configuration Knobs

| Variable | What it controls | Good value for this lab |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Chooses the active skillset profile. | `baseline_extract` |
| `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` | Chooses the extractor implementation. | `document_extraction` |
| `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS` | Stops the workshop on broken skillset runs. | `true` |
| `DEFAULT_INGESTION_MODE` | Keeps uploads on the Blob + skillset pipeline. | `hybrid_blob_skillset` |

## Best-Practice Takeaways

- establish a lexical baseline before claiming semantic improvement
- treat extracted text as a starting point, not the final retrieval unit
- keep parser-side figure work out of the baseline so you can attribute later improvements to the visual lab
- compare the same prompts across labs so improvements remain measurable

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the baseline profile declaration.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for the Search skillset body.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for the direct full-text request.
- [`backend/app.py`](../../backend/app.py) for how the portal selects `full_text`.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Document Extraction skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-document-extraction)
- [Create a full-text query](https://learn.microsoft.com/en-us/azure/search/search-query-create)
- [BM25 relevance scoring](https://learn.microsoft.com/en-us/azure/search/index-similarity-and-scoring)
