# Lab 04 - Chunking, Embeddings, And Vector Search

## Goal

Re-index the same document with built-in chunk-aware enrichment and embeddings:

- `SplitSkill`
- `AzureOpenAIEmbeddingSkill`

Then compare:

- full text search
- vector search
- hybrid search

Set:

```dotenv
WORKSHOP_SKILL_PROFILE=chunk_vector
```

## Step 1 - Restart the app

Restart after changing `.env`.

## Step 2 - Verify the active profile

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `active_profile_id` is `chunk_vector`
- the target enrichment index name ends with `-chunk-vector`

## Step 3 - Upload the same document again

Do not change the source file. The point is to isolate the effect of chunking and embeddings.

## Step 4 - Compare the same question across three retrieval modes

Use `Custom Selection` and the newly uploaded corpus.

Ask the same question three times:

1. `Full text`
2. `Vector`
3. `Hybrid`

Recommended prompts:

- `Which specific chunk best explains the architecture workflow in this document?`
- `Find the part that discusses indexing, grounding, and answer generation even if those exact words are not written together.`
- `Which passage best explains how the system moves from document ingestion to retrieval quality?`

## Step 5 - Explain what changed

Compared with Lab 03, this profile adds:

- chunk-oriented enrichment output
- embeddings for semantic matching
- hybrid search over the same chunk corpus

Call out:

- why vector search can recover paraphrases
- why hybrid often becomes the most stable direct-search mode
- how chunking reduces whole-document noise

## Step 6 - Capture observations

Have the audience record:

- which mode found the most relevant chunk
- which mode produced the cleanest evidence list
- where lexical search still won

## Success Criteria

- the document reaches `ready`
- Blob + skillset enrichment completes
- the enrichment index recorded in the job ends with `-chunk-vector`
- vector and hybrid search both return grounded results

## What To Inspect In This Repo

```text
Profile: chunk_vector
Built-in skill focus:
- DocumentExtractionSkill
- SplitSkill
- AzureOpenAIEmbeddingSkill

Retrieval focus:
- full_text
- vector
- hybrid
```

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py)
  The `chunk_vector` profile is where the workshop declares that this lab adds `SplitSkill` and `AzureOpenAIEmbeddingSkill`.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Inspect `_profile_uses_split()`, `_profile_uses_embedding()`, `_build_split_skill()`, `_build_embedding_skill()`, and `_build_enrichment_index_body()`. Those methods wire chunk-aware indexing and integrated vectorization into the Search-managed enrichment lane.
- [`backend/services/chunking.py`](../../backend/services/chunking.py)
  This is the app-owned chunker. Compare it with the Search-managed `SplitSkill` lane so the audience understands the difference between canonical chunks owned by the app and enrichment chunks or vectors owned by Search.
- [`backend/services/indexing.py`](../../backend/services/indexing.py)
  Inspect `direct_search()` and `_run_direct_search()`. This is where the code chooses between lexical search, vector queries, and hybrid requests.

## Learn References

- [Chunk documents for vector search and agentic retrieval](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents)
- [Text Split skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-textsplit)
- [Azure OpenAI Embedding skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-azure-openai-embedding)
- [Vector search overview](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
