# Lab 09 - Troubleshooting And Verification

## Goal

Give facilitators a short operational checklist for the progressive workshop track.

## Quick Checks

### 1. App health

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/health
```

### 2. Config summary

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/config
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8016/api/workshop/profiles
```

Verify:

- Search is enabled
- Blob ingestion is enabled
- strict mode is enabled
- the active workshop profile matches the lab you intend to run
- the available retrieval modes are `full_text`, `vector`, `hybrid`, and `agentic`

### 3. Python tests

```powershell
cd .\v2
python -m unittest discover -s tests
```

## Common Failure Patterns

### Blob + skillset ingestion fails

Check:

- Search endpoint and key
- Blob connection string
- Foundry resource endpoint
- Search service identity access to Foundry
- indexer status in Azure AI Search
- active workshop profile and its target index or skillset names

### Vector or hybrid retrieval fails

Check:

- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- canonical index schema contains the vector field
- the current corpus was uploaded after vector support was enabled
- the selected corpus is the one you think it is

### Agentic retrieval fails

Check:

- knowledge base exists
- knowledge sources exist
- `AZURE_SEARCH_LLM_DEPLOYMENT` is valid
- answer synthesis is enabled if the workshop expects Search-side answer synthesis
- the selected corpus is actually ready

### Chat returns no visible subqueries

Check:

- the question is complex enough to trigger planning
- the debug panel is enabled
- Azure AI Search may still have used agentic reasoning even if only one concrete search step is exposed

## Facilitator Smoke Prompts

Use these before the audience joins:

- `What major sections and themes are present in this document?`
- `Which specific chunk best explains the architecture workflow in this document?`
- `What summary or retrieval cues make this document easier to search accurately?`
- `Explain how the document describes ingestion, indexing, and answer generation. Separate the answer into extraction, indexing, and retrieval stages.`

Together these validate:

- Blob + skillset ingestion
- progressive profile switching
- full text retrieval
- vector retrieval
- hybrid retrieval
- agentic retrieval
- citation rendering
- evidence card rendering
