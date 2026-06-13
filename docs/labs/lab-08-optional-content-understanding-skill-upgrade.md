# Lab 08 - Optional Content Understanding Upgrade

## Goal

Run the same workshop comparison with the Azure Content Understanding skill as the Search-managed extractor.

## Questions This Lab Answers

- When should I choose `ContentUnderstandingSkill` instead of `DocumentExtractionSkill`?
- What kinds of documents benefit the most from Search-managed semantic extraction?
- Is Content Understanding replacing the earlier labs or acting as an advanced alternative?
- What extra service dependencies and configuration does it add?

Select the **Content Understanding Alternative** profile in the upload **Skill Profile** picker for this lab. Keep the extractor preference on Content Understanding:

```dotenv
# Default extractor implementation for the Content Understanding profile
AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=content_understanding
```

## When To Use This Lab

Use this only after Labs 03 through 07 are working. It is the advanced comparison lab for:

- Search-managed semantic extraction
- Search-managed chunk boundary quality
- richer structure handling for mixed-layout or figure-heavy documents

> `#Microsoft.Skills.Util.ContentUnderstandingSkill` is **generally available** (Azure AI Search `2026-04-01` REST API; semantic chunking and AI image descriptions arrived in `2026-05-01-preview`). It is **resource-attached**: it binds to the billable Microsoft Foundry resource declared in the skillset's `cognitiveServices` block and needs **no standalone Content Understanding endpoint, key, or analyzer**. Treat it as an advanced extractor comparison, not the workshop starting point.

## Step 1 - Confirm the attached Foundry resource

The skill reuses the same Foundry resource you already attached for embeddings and the GenAI Prompt skill. No separate Content Understanding resource is required. Confirm the resource is set so the skillset attaches it with the search service's managed identity:

```dotenv
# Already present from Lab 02 - the CU skill reuses it via managed identity
AZURE_FOUNDRY_RESOURCE_ENDPOINT=https://<your-foundry>.cognitiveservices.azure.com/
```

The search service's system-assigned managed identity must hold **Cognitive Services User** on that Foundry resource (granted in Lab 02). The Foundry resource must be in a [Content Understanding-supported region](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/language-region-support).

> The legacy `AZURE_CONTENT_UNDERSTANDING_ENDPOINT` / `_KEY` / `_ANALYZER_ID` variables only drive the app-managed direct parser in [`backend/services/parsers.py`](../../backend/services/parsers.py). They are **not** required for this Search-managed skill and can stay blank.

Leave strict mode on:

```dotenv
WORKSHOP_STRICT_MODE=true
AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS=true
```

## Step 2 - Start the app

Always launch through the helper script so `.env` is loaded into the process environment (a raw `uvicorn` invocation leaves the Azure feature flags unset):

```powershell
.\scripts\run-local-app.ps1 -Port 8016
```

## Step 3 - Upload the same document again

Use the same source file when possible. On the upload screen, set the **Skill Profile** picker to **Content Understanding Alternative** before submitting.

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
- Blob + skillset enrichment completes (`status: ready`, no errors)
- the enrichment index recorded in the job ends with `-content-understanding`
- the enrichment index is populated with Content Understanding's **semantic chunks** in `split_chunks` (layout-aware Markdown that preserves headings, tables, and `![](figures/...)` references), plus generated `summary_text` and `keyword_hints_raw`

> Reference run (146-page PDF): Content Understanding's semantic chunking produced **217 chunks** versus 414 from the default Document Intelligence fixed-size chunking - fewer, larger, structure-respecting chunks.

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

The extractor switch is implemented here. The gate checks that a billable Foundry resource is attachable (managed identity preferred), **not** the legacy parser key:

```python
# backend/services/search_skillset_enrichment.py
def _active_extractor_kind(self, *, profile: WorkshopSkillProfile | None = None) -> str:
    wants_content_understanding = (
        active_profile.id == "content_understanding"
        or settings.azure_search_skillset_preferred_extractor == "content_understanding"
    )
    if wants_content_understanding:
        if settings.azure_content_understanding_skill_available:  # Foundry resource attached
            return "content_understanding"
        ...
    return "document_extraction"
```

The GA skill is resource-attached (no `resourceUri` / `apiKey` / `analyzerName`) and chunks internally, so it returns `text_sections` instead of a single content string:

```python
# backend/services/search_skillset_enrichment.py
if active_extractor == "content_understanding":
    return {
        "@odata.type": "#Microsoft.Skills.Util.ContentUnderstandingSkill",
        "context": "/document",
        "extractionOptions": ["locationMetadata"],
        "chunkingProperties": {"method": "semantic", "unit": "tokens", "maximumLength": 500},
        "inputs": [{"name": "file_data", "source": "/document/file_data"}],
        "outputs": [{"name": "text_sections", "targetName": "cu_text_sections"}],
    }
```

Because the skill emits chunked `text_sections`, a `MergeSkill` rebuilds `/document/content_markdown` to feed the downstream prompt-seed, summary, keyword, and embedding skills, while the indexer projects each chunk's `content` into the `split_chunks` collection (one small term per chunk - projecting the merged full-document string would exceed the 32,766-byte single-term limit).

- The code does not create a separate ingestion system for this lab.
- It swaps the Search skillset extractor while preserving the rest of the workshop flow.
- In strict mode, the absence of an attachable billable Foundry resource fails fast instead of quietly falling back to `DocumentExtractionSkill`.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `content_understanding` |
| `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` | Forces the Search skillset extractor. | `content_understanding` |
| `AZURE_FOUNDRY_RESOURCE_ENDPOINT` | Billable Foundry resource the skill attaches to via managed identity. | Required (reused from Lab 02). |
| `AZURE_CONTENT_UNDERSTANDING_*` | Endpoint/key/analyzer for the **app-managed direct parser only** ([`parsers.py`](../../backend/services/parsers.py)). | Not needed for the Search-managed skill; leave blank. |
| `WORKSHOP_STRICT_MODE` | Whether the lab fails fast when no billable resource is attachable. | Keep `true`. |

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

- [Azure Content Understanding skill in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-content-understanding)
- [Attach a billable Azure AI resource to a skillset](https://learn.microsoft.com/en-us/azure/search/cognitive-search-attach-cognitive-services)
- [Chunk and vectorize content with the Azure Content Understanding skill](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking-content-understanding)
- [Document Layout skill for semantic chunking](https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking) (a separate, alternative semantic-chunking option)
- [Integrated vectorization](https://learn.microsoft.com/en-us/azure/search/search-how-to-integrated-vectorization)
