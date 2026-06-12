# Lab 05 - Hybrid Search With Generative Enrichment

## Goal

Add Search-managed generative enrichment to the same document:

- `ChatCompletionSkill`
- retrieval summaries
- keyword hints

Then use `Hybrid` search as the main comparison mode.

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

## What To Inspect In This Repo

```text
Profile: genai_enrichment
Built-in skill focus:
- ChatCompletionSkill

Retrieval focus:
- hybrid
- optional comparison with agentic retrieval
```

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py)
  The `genai_enrichment` profile declares that this lab adds `ChatCompletionSkill` on top of chunking and embeddings.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Inspect `_profile_uses_prompt_enrichment()`, `_build_summary_prompt_skill()`, `_build_keywords_prompt_skill()`, and `_apply_enrichment_to_document()`. These methods are where Search-generated summaries and keyword hints are created and then merged back into the app’s canonical chunk records.
- [`backend/services/indexing.py`](../../backend/services/indexing.py)
  Inspect `_ensure_index()` and `_upload_chunks()`. This shows that the app still preserves canonical text and page-grounded chunks while adding generative hints as additional fields, not replacements.
- [`backend/app.py`](../../backend/app.py)
  Inspect `/api/documents/{doc_id}` and `/api/chat` so participants can connect the enriched metadata with what appears in the portal and response evidence.

## Learn References

- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [ChatCompletionSkill API reference for Azure AI Search](https://learn.microsoft.com/en-us/python/api/azure-search-documents/azure.search.documents.indexes.models.chatcompletionskill?view=azure-python)
- [AI enrichment overview](https://learn.microsoft.com/en-us/azure/search/cognitive-search-concept-intro)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
