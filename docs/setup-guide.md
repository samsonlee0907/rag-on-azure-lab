# Setup Guide

Use the workshop README and labs as the primary setup path:

- [README](../README.md)
- [Lab 01 - Provision Azure Resources](./labs/lab-01-provision-azure-resources.md)
- [Lab 02 - Configure Models, Identities, And Environment](./labs/lab-02-configure-models-identities-and-env.md)
- [Lab 03 - Baseline Extraction And Full Text Search](./labs/lab-03-baseline-extraction.md)

## Local Run

1. Create a Python environment.
2. Install dependencies from `requirements.txt`.
3. Copy `.env.example` to `.env`.
4. Start the API and static UI with the helper script (it loads `.env` into the process environment before launching uvicorn):

```powershell
.\scripts\run-local-app.ps1 -Port 8016
```

> Launching `uvicorn` directly does not read `.env`, so the Azure feature flags stay unset and the app runs in offline/disabled mode. Use the script (or export the variables yourself) for any Azure-backed run.

5. Open `http://127.0.0.1:8016`, or pass a different `-Port` to the script to use any free local port.

## Recommended Azure Resources

- Azure AI Search with semantic ranker enabled.
- Azure Blob Storage.
- Azure Document Intelligence resource.
- Azure AI Foundry resource with the workshop model deployments.
- Optional Azure Content Understanding resource plus analyzer if you want to run Lab 08.

## Demo Flow

1. Pick one representative PDF and keep it for the full workshop.
2. Run Labs 03 through 06 by choosing each lab's profile in the in-app **Skill Profile** picker at upload time.
3. Re-upload the same document per lab so each Search-managed enrichment profile gets its own comparison index.
4. Compare `full_text`, `vector`, and `hybrid` exactly where the lab tells you to do so.
5. Run Lab 07 last in the core sequence to show official agentic retrieval over the best corpus.
6. Keep `WORKSHOP_STRICT_MODE=true` so the Azure-native ingestion path fails loudly if any required service-side stage is broken.
