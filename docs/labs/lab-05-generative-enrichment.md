# Lab 05 - Hybrid Search With Generative Enrichment

## Goal

Add Search-managed generative enrichment to the same document:

- `ChatCompletionSkill`
- retrieval summaries
- keyword hints

Then use `Hybrid` search as the main comparison mode.

## Questions This Lab Answers

- Why add summaries and keyword hints if embeddings already exist?
- What does Search-managed generative enrichment improve for retrieval?
- How do I keep generated metadata from replacing or distorting source text?
- Which kinds of questions benefit most from generated retrieval cues?

Set:

```dotenv
WORKSHOP_SKILL_PROFILE=genai_enrichment
```

## Step 1 - Restart the app

Restart after changing `.env`.

## Step 2 - Verify the active profile

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `active_profile_id` is `genai_enrichment`
- the target enrichment index name ends with `-genai`

## Step 3 - Upload the same document again

Keep the source constant.

## Step 4 - Use `Hybrid` retrieval mode

In the chat UI:

1. use `Custom Selection`
2. pick the newly uploaded `genai_enrichment` corpus
3. set retrieval mode to `Hybrid`

## Step 5 - Ask the comparison prompts

- `What summary or retrieval cues make this document easier to search accurately?`
- `Which tags or summaries changed the answer quality compared with the previous lab?`
- `What part of the document should a retrieval system search first if the user asks for the main workflow?`

## Step 6 - Explain what changed

Compared with Lab 04, this profile adds:

- Search-generated summary text
- Search-generated keyword hints

Make the point that this does not replace canonical document text. It gives the search system better retrieval cues on top of the same source content.

## Step 7 - Compare with the earlier run

Show the audience:

- whether hybrid answers rank the right chunk higher
- whether evidence cards become easier to interpret
- whether broad questions improve more than exact-phrase questions

## Success Criteria

- the document reaches `ready`
- enrichment metadata contains summary or keyword outputs
- the enrichment index recorded in the job ends with `-genai`
- hybrid search returns stronger evidence than the chunk-only run for broad conceptual questions

## Code Walkthrough

This profile adds Search-side generative hints on top of chunking and embeddings:

```python
# backend/services/workshop_profiles.py
WorkshopSkillProfile(
    id="genai_enrichment",
    added_skills=("ChatCompletionSkill",),
    cumulative_skills=(
        "DocumentExtractionSkill",
        "SplitSkill",
        "AzureOpenAIEmbeddingSkill",
        "ChatCompletionSkill",
    ),
    recommended_retrieval_modes=("hybrid", "agentic"),
)
```

- This lab is where the Search enrichment lane starts producing abstractions, not just extracted text.
- The audience should compare this against the previous chunk-only lab using the same document and same question.

The generative prompt skills are defined here:

```python
# backend/services/search_skillset_enrichment.py
skills.extend(
    [
        self._build_summary_prompt_skill(
            prompt_skill_kind=prompt_skill_kind,
            text_source="/document/prompt_seed_text",
        ),
        self._build_keywords_prompt_skill(
            prompt_skill_kind=prompt_skill_kind,
            text_source="/document/summary_text",
        ),
    ]
)
```

- The first prompt produces `summary_text`.
- The second prompt turns that summary into retrieval tags and keyword hints.
- This keeps prompt costs and prompt size smaller than sending the entire document into every prompt skill.

Those Search-generated fields are then merged into the canonical chunks instead of replacing the original chunk text:

```python
# backend/services/search_skillset_enrichment.py
for chunk in chunks:
    chunk.summary_text = summary_text
    chunk.image_description_text = image_description_text
    if keyword_hints:
        chunk.keyword_hints = sorted(set([*chunk.keyword_hints, *keyword_hints]))
        chunk.tags = sorted(set([*chunk.tags, *keyword_hints]))
```

- The lab can now show how summaries and tags help retrieval.
- The canonical `clean_text` remains the authoritative source text for citations and evidence.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `genai_enrichment` |
| `AZURE_SEARCH_LLM_DEPLOYMENT` | Model used by the Search prompt skills and knowledge-base planning. | Point to your planning model deployment. |
| `AZURE_SEARCH_PROMPT_SEED_PAGE_LENGTH` | How much text is sampled before summary generation. | Reduce it to show cheaper but less complete summaries. |
| `AZURE_SEARCH_PROMPT_SEED_PAGES_TO_TAKE` | How many split pages feed the summary prompt. | Increase it for longer documents with diffuse context. |
| `AZURE_SEARCH_PROMPT_SEED_PAGE_OVERLAP` | Overlap between prompt seed chunks. | Raise it if summary context feels too discontinuous. |
| `AZURE_SEARCH_ALLOW_FOUNDRY_ENRICHMENT_SUPPLEMENT` | Allows app-side supplementation when Search enrichment is incomplete. | Keep `false` for a cleaner workshop story. |

## Best-Practice Takeaways

- use generative enrichment to add retrieval cues, not to overwrite canonical content
- keep prompt inputs bounded so indexing stays reliable on large documents
- broad conceptual questions usually benefit more from summaries and tags than exact-phrase questions
- treat generated fields as ranking and interpretation aids, not as source truth

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the profile progression.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for the prompt skills and enrichment merge.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for how enriched fields are uploaded.
- [`backend/app.py`](../../backend/app.py) for how those fields appear in the portal.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [ChatCompletionSkill API reference for Azure AI Search](https://learn.microsoft.com/en-us/python/api/azure-search-documents/azure.search.documents.indexes.models.chatcompletionskill?view=azure-python)
- [AI enrichment overview](https://learn.microsoft.com/en-us/azure/search/cognitive-search-concept-intro)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
