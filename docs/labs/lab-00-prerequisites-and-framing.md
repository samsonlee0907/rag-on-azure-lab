# Lab 00 - Prerequisites And Workshop Framing

## Goal

Set the audience context before anyone runs the app:

- why large-document ingestion is hard
- why retrieval quality is a system design problem
- how this workshop separates ingestion improvements from search-mode improvements

## Core Workshop Message

The workshop has two axes of comparison:

1. **Ingestion profile progression**
   - baseline extraction
   - chunking and embeddings
   - generative enrichment
   - visual and NLP enrichment
   - optional Content Understanding

2. **Retrieval mode progression**
   - full text
   - vector
   - hybrid
   - agentic retrieval

The source document stays constant. Only the profile or retrieval mode changes.

## What To Explain

### 1. The file is not the indexed unit

The workshop app does **not** index a whole PDF as one blob of text. It:

1. parses the file
2. repairs extraction seams
3. creates canonical chunks
4. enriches the original file through Azure AI Search
5. publishes the chunk corpus for multiple retrieval methods

### 2. There are two Azure AI Search responsibilities in the workshop

- `Search-managed Blob enrichment lane`
  - Blob upload
  - Search data source
  - Search indexer
  - Search skillset
  - enrichment cache
  - profile-specific enrichment index

- `Retrieval plane`
  - direct full text search
  - direct vector search
  - direct hybrid search
  - official knowledge-base agentic retrieval

### 3. The app runs in strict mode

The core workshop deliberately fails if Blob + skillset enrichment fails. That keeps the lab honest. Participants see the real Azure path instead of a silent local fallback.

### 4. Agentic retrieval comes after the search-mode fundamentals

The audience should first see:

- what lexical search can and cannot do
- what embeddings improve
- why hybrid often becomes the best direct-search baseline

Only then should the workshop move to agentic retrieval as the official Azure AI Search knowledge-base feature.

## What Participants Need

- local clone of `v2`
- Azure subscription access
- Azure CLI signed in
- Python 3.11+

## Suggested Opening Questions

- `Why can't we just upload a PDF and chat over it?`
- `What changes when the same document is chunked before search?`
- `Why does vector search find things that lexical search misses?`
- `Why should agentic retrieval be shown after, not before, the other search modes?`
