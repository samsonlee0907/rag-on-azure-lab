# Lab 04 - Chunking, Embeddings, And Vector Search

## Goal

Re-index the same document with built-in chunk-aware enrichment and embeddings:

- `SplitSkill`
- `AzureOpenAIEmbeddingSkill`

Then compare:

- full text search
- vector search
- hybrid search

## Questions This Lab Answers

- Why does chunking matter so much for RAG quality?
- What is the difference between a good chunk and a bad chunk?
- When should `vector` beat `full_text`, and when should `full_text` still win?
- Why is `hybrid` often the safest direct-search default?

This lab uses the **Chunking And Vectorization** skill profile, selected per upload from the UI.

## Step 1 - Start the app

Launch through the helper script if it is not already running:

```powershell
.\scripts\run-local-app.ps1 -Port 8016
```

## Step 2 - Confirm the profile is available

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `chunk_vector` appears in the `profiles` list
- its target enrichment index name ends with `-chunk-vector`

## Step 3 - Upload the same document again

Do not change the source file. The point is to isolate the effect of chunking and embeddings. On the upload screen, set the **Skill Profile** picker to **Chunking And Vectorization** before submitting.

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

## Code Walkthrough

This profile adds chunk-aware enrichment and embeddings on top of the baseline extractor:

```python
# backend/services/workshop_profiles.py
WorkshopSkillProfile(
    id="chunk_vector",
    added_skills=("SplitSkill", "AzureOpenAIEmbeddingSkill"),
    cumulative_skills=(
        "DocumentExtractionSkill",
        "SplitSkill",
        "AzureOpenAIEmbeddingSkill",
    ),
    recommended_retrieval_modes=("full_text", "vector", "hybrid"),
)
```

- The document stays the same.
- The index gets richer because Search now stores chunk-oriented text slices and embeddings.

This is how the Search skillset adds chunking and vectorization:

```python
# backend/services/search_skillset_enrichment.py
def _build_split_skill(self) -> dict[str, Any]:
    return {
        "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
        "textSplitMode": "pages",
        "maximumPageLength": 1500,
        "pageOverlapLength": 150,
        "inputs": [{"name": "text", "source": "/document/content_markdown"}],
    }

def _build_embedding_skill(self, *, text_source: str = "/document/summary_text") -> dict[str, Any]:
    return {
        "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
        "deploymentId": settings.azure_openai_embedding_deployment,
        "dimensions": settings.azure_search_vector_dimensions,
    }
```

- `SplitSkill` makes the enrichment lane more retrieval-friendly.
- `AzureOpenAIEmbeddingSkill` enables semantic similarity search over those enriched fields.

> Two embedding paths, on purpose. The Search-side `AzureOpenAIEmbeddingSkill` (integrated vectorization) only populates the **enrichment index**. The `vector` and `hybrid` chat modes query the **canonical chunk index**, whose vectors are produced app-side in `_embed_chunks_for_index`, and the query itself is embedded app-side too. Using the same embedding model for both index and query is what keeps vector similarity meaningful. The canonical index defines an HNSW profile but no `vectorizer`, so it expects pre-computed query vectors rather than `text`-kind vector queries.

This is the direct-search switch in the app:

```python
# backend/services/indexing.py
if retrieval_mode == "full_text":
    body["search"] = question          # pure BM25, no reranking
    return body

if retrieval_mode == "vector":
    body["search"] = "*"
    body["vectorQueries"] = [{"kind": "vector", "vector": query_vector, ...}]
    return body

# hybrid: BM25 + vector fused by RRF, then reranked by the semantic ranker
body["search"] = question
body["queryType"] = "semantic"
body["semanticConfiguration"] = "default-semantic-config"
body["captions"] = "extractive|highlight-false"
body["vectorQueries"] = [{"kind": "vector", "vector": query_vector, ...}]
```

- `full_text` is lexical only (BM25).
- `vector` is embedding similarity only (HNSW).
- `hybrid` runs both, fuses the two ranked lists with [Reciprocal Rank Fusion (RRF)](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking), and then applies the [semantic ranker](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview) to rerank the fused top results and return extractive captions.

### How hybrid ranking actually works

This is the most important concept in the lab, so make it explicit:

1. **BM25** scores the lexical query and produces `@search.score`.
2. **HNSW vector search** scores the embedding query and produces its own `@search.score`.
3. **RRF** fuses both ranked lists into one combined `@search.score`. Documents that rank highly in either list rise to the top.
4. **Semantic ranker (L2)** takes the fused top results and reranks them with a Bing-derived model, producing `@search.rerankerScore` on a 0 to 4 scale plus extractive captions.

The app sorts direct results by `@search.rerankerScore` first and `@search.score` second, which is why `hybrid` results can reorder relative to a pure BM25 or pure vector run:

```python
# backend/services/indexing.py
def _direct_result_rank(item):
    return (
        float(item.get("@search.rerankerScore") or 0),
        float(item.get("@search.score") or 0),
    )
```

Because `full_text` is pure BM25 it has no `@search.rerankerScore`, so it falls back to the BM25 score. The semantic ranker is a separately billed premium feature with [regional limits](https://learn.microsoft.com/en-us/azure/search/search-region-support); if `hybrid` queries fail, confirm semantic ranker is enabled on the search service before debugging anything else.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `chunk_vector` |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding deployment used by the Search skill. | Point to your embedding deployment alias, such as `text-embedding-3-large-vector`. |
| `AZURE_OPENAI_EMBEDDING_MODEL_NAME` | Embedding model family used by the Search vectorizer. | Keep this on `text-embedding-3-large` unless you intentionally switch model families. |
| `AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION` | Whether the Search skillset writes vector fields into the **enrichment index** during indexing via `AzureOpenAIEmbeddingSkill`. | Keep `true` for this lab. |
| `CHUNK_SIZE_TOKENS` | App-owned canonical chunk size. | Lower it to show more granular retrieval. |
| `CHUNK_OVERLAP_TOKENS` | App-owned chunk overlap. | Increase it to show better continuity at boundaries. |
| `USE_SEMANTIC_CHUNKING` | App chunker behavior, separate from Search `SplitSkill`. | Toggle only if you want to contrast app chunking with Search chunking. |

## Best-Practice Takeaways

- chunking is a first-class retrieval design choice, not a preprocessing afterthought
- embeddings are only as useful as the chunk boundaries they represent
- hybrid search is usually the best direct-search comparison mode because it blends lexical and semantic signals
- compare Search-managed chunking and app-managed chunking deliberately instead of assuming they solve the same problem

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the lab declaration.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for `SplitSkill` and `AzureOpenAIEmbeddingSkill`.
- [`backend/services/chunking.py`](../../backend/services/chunking.py) for the app-owned canonical chunker.
- [`backend/services/indexing.py`](../../backend/services/indexing.py) for the direct search request bodies.

## Learn References

- [Chunk documents for vector search and agentic retrieval](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents)
- [Text Split skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-textsplit)
- [Azure OpenAI Embedding skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-azure-openai-embedding)
- [Vector search overview](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- [Hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
- [Relevance scoring in hybrid search using RRF](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
- [Semantic ranking in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview)
