# Lab 08 - Optional Content Understanding Upgrade

## Goal

Run the same workshop comparison with the Azure Content Understanding skill as the Search-managed extractor.

## Questions This Lab Answers

- When should I choose `ContentUnderstandingSkill` instead of `DocumentExtractionSkill`?
- What kinds of documents benefit the most from Search-managed semantic extraction?
- Is Content Understanding replacing the earlier labs or acting as an advanced alternative?
- What extra service dependencies and configuration does it add?

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

## Code Walkthrough

This lab changes the extractor, not the overall workshop structure:

```python
# backend/services/workshop_profiles.py
WorkshopSkillProfile(
    id="content_understanding",
    added_skills=("ContentUnderstandingSkill",),
    cumulative_skills=(
        "ContentUnderstandingSkill",
        "AzureOpenAIEmbeddingSkill",
        "ChatCompletionSkill",
    ),
    recommended_retrieval_modes=("hybrid", "agentic"),
)
```

- It is still the same document and the same comparison method.
- The difference is that the Search-managed extraction phase becomes more semantic and multimodal.

The extractor switch is implemented here:

```python
# backend/services/search_skillset_enrichment.py
def _active_extractor_kind(self, *, profile: WorkshopSkillProfile | None = None) -> str:
    wants_content_understanding = (
        active_profile.id == "content_understanding"
        or settings.azure_search_skillset_preferred_extractor == "content_understanding"
    )
    ...
    return "document_extraction"
```

```python
# backend/services/search_skillset_enrichment.py
if active_extractor == "content_understanding":
    return {
        "@odata.type": "#Microsoft.Skills.Util.ContentUnderstandingSkill",
        "resourceUri": settings.azure_content_understanding_endpoint.rstrip("/"),
        "analyzerName": settings.azure_content_understanding_analyzer_id,
    }
```

- The code does not create a separate ingestion system for this lab.
- It swaps the Search skillset extractor while preserving the rest of the workshop flow.
- In strict mode, missing Content Understanding settings fail fast instead of quietly falling back.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `content_understanding` |
| `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` | Forces the Search skillset extractor. | `content_understanding` |
| `AZURE_CONTENT_UNDERSTANDING_ENDPOINT` | Service endpoint for the extractor. | Required for this lab. |
| `AZURE_CONTENT_UNDERSTANDING_KEY` | Authentication for the extractor. | Required for this lab. |
| `AZURE_CONTENT_UNDERSTANDING_ANALYZER_ID` | Analyzer selected inside Content Understanding. | Use different analyzers to compare extraction behavior. |
| `WORKSHOP_STRICT_MODE` | Whether the lab fails fast when Content Understanding is missing. | Keep `true`. |

## Best-Practice Takeaways

- treat Content Understanding as an advanced extractor comparison, not the starting point for the workshop
- use it when structure, figures, and semantic chunk boundaries matter enough to justify the extra dependency
- keep strict mode on so participants see configuration gaps immediately
- compare chunk quality and retrieval behavior against earlier profiles using the same document

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the advanced profile.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for the extractor switch.
- [`backend/services/parsers.py`](../../backend/services/parsers.py) to compare app-managed versus Search-managed Content Understanding.
- [`backend/core/config.py`](../../backend/core/config.py) for the enabling flags.

## Learn References

- [Document Layout skill for semantic chunking](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking)
- [Chunk and vectorize content with the Azure Content Understanding skill](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking-content-understanding)
- [Integrated vectorization](https://learn.microsoft.com/en-us/azure/search/search-how-to-integrated-vectorization)
