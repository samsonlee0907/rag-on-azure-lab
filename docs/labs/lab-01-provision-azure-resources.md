# Lab 01 - Provision Azure Resources

## Goal

Provision the Azure services required by the core workshop:

- Azure AI Search
- Azure Blob Storage
- Azure AI Document Intelligence
- Azure AI Foundry model resource or reused existing Foundry resource

## Questions This Lab Answers

- Which Azure resources are required for this workshop?
- Why do I need both Azure AI Search and Blob Storage?
- Why are multiple model deployments used instead of one?
- Which permissions matter before upload, indexing, and retrieval can work?

## Step 1 - Sign in to Azure

```powershell
az login
az account show
```

Make sure the correct subscription is active.

## Step 2 - Run the provisioning script

From the repository root:

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\provision-azure.ps1 `
  -SubscriptionId "<subscription-id>" `
  -Location "eastus" `
  -ResourceGroupName "rg-ai-search-lab" `
  -ExistingFoundryResourceGroup "<foundry-resource-group>" `
  -ExistingFoundryResourceName "<foundry-resource-name>"
```

If you also want the script to create the workshop model deployments, use the built-in default versions and capacities:

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\provision-azure.ps1 `
  -SubscriptionId "<subscription-id>" `
  -Location "eastus" `
  -ResourceGroupName "rg-ai-search-lab" `
  -ExistingFoundryResourceGroup "<foundry-resource-group>" `
  -ExistingFoundryResourceName "<foundry-resource-name>" `
  -CreateOptionalModelDeployments `
  -ChatDeploymentCapacity 100 `
  -PlanningDeploymentCapacity 100 `
  -NativeChatDeploymentCapacity 100 `
  -EmbeddingDeploymentCapacity 100
```

## Step 3 - Confirm the Blob containers

The core workshop expects these containers:

- `documents`
- `document-figure-artifacts`
- `search-enrichment-cache`

Validate them:

```powershell
az storage container list `
  --account-name "<storage-account-name>" `
  --auth-mode login `
  --output table
```

## Step 4 - Confirm the Search service identity wiring

The Search service managed identity must be able to:

- call the Foundry model resource
- read the Blob source used by the Search indexer

Validate the Search service identity exists:

```powershell
az resource show `
  --ids "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Search/searchServices/<search-name>" `
  --query identity
```

## Step 5 - Record the outputs

Capture these values for `.env`:

- Search endpoint
- Search admin key
- Storage account name
- Blob connection string or resource ID style connection string
- Document Intelligence endpoint
- Foundry resource endpoint

## Success Criteria

- Azure AI Search is provisioned
- Blob containers exist
- Document Intelligence exists
- Foundry resource is available

## Code Walkthrough

The provisioning script is not just creating random Azure services. It is creating the exact resources this lab code expects to exist.

```powershell
# scripts/provision-azure.ps1
[string]$ResourceGroupName = "rg-ai-search-lab"
[string]$SearchSourceContainerName = "documents"
[string]$SearchCacheContainerName = "search-enrichment-cache"
[string]$SearchAssetStoreContainerName = "search-image-assets"
[string]$PlanningModelName = "gpt-5.4-mini"
[string]$NativeChatModelName = "gpt-5.4-mini"
[string]$EmbeddingModelName = "text-embedding-3-large"
```

- `documents` is the Blob container the Search indexer reads from.
- `search-enrichment-cache` is for Search enrichment caching so re-runs are cheaper and faster.
- `search-image-assets` is the asset-store container used by the native image-serving path.
- The workshop now uses the same supported GPT family for all LLM roles, but keeps separate deployment names for Search planning, native multimodal synthesis, and app-side synthesis.

The runtime later consumes those names directly:

```python
# backend/services/search_skillset_enrichment.py
body = {
    "dataSourceName": data_source_name or settings.azure_search_blob_data_source_name,
    "targetIndexName": self._target_index_name(active_profile),
    "skillsetName": self._target_skillset_name(active_profile),
}
```

- If the resource names in Azure do not line up with `.env`, the lab fails at the Search indexer or knowledge-base step.
- This is why the provisioning lab matters: it establishes the naming contract for the rest of the workshop.

## Configuration Knobs

| Parameter or variable | What it controls | When to change it |
| --- | --- | --- |
| `ResourceGroupName` | The workshop’s isolated Azure landing zone. | Change per audience or workshop run. |
| `SearchSku` | Azure AI Search capacity tier. | Increase for larger workshops or heavier indexing. |
| `SearchSourceContainerName` | Blob container that stores uploaded source documents. | Change if you want a dedicated container per lab. |
| `SearchCacheContainerName` | Blob container for enrichment cache. | Keep stable across reruns to demonstrate cache behavior. |
| `SearchAssetStoreContainerName` | Blob container for native image assets. | Required only if you enable the native image-serving path. |
| `ChatDeploymentCapacity`, `PlanningDeploymentCapacity`, `NativeChatDeploymentCapacity`, `EmbeddingDeploymentCapacity` | Starting throughput allocation for workshop deployments. | Default to `100` so each deployment starts at roughly 100,000 TPM when your quota supports it. |
| `CreateOptionalModelDeployments` | Whether the script also deploys LLMs and embeddings. | Turn on when you want the full workshop stack provisioned in one pass. |

## Best-Practice Takeaways

- isolate workshop infrastructure in a dedicated resource group
- separate source documents, enrichment cache, and asset storage
- separate planning, answer, and embedding model roles even when the underlying GPT model family is the same
- verify RBAC early so you do not misdiagnose infrastructure issues as app issues

## Files To Inspect

- [`scripts/provision-azure.ps1`](../../scripts/provision-azure.ps1) for the resource contract.
- [`.env.example`](../../.env.example) for the values that must come back from provisioning.
- [`backend/core/config.py`](../../backend/core/config.py) for the runtime feature flags.
- [`docs/environment-reference.md`](../environment-reference.md) for the full variable reference.

## Learn References

- [Azure AI Search overview](https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search)
- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Tutorial: skillsets](https://learn.microsoft.com/en-us/azure/search/tutorial-skillset)
