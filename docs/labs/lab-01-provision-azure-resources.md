# Lab 01 - Provision Azure Resources

## Goal

Provision the Azure services required by the core workshop:

- Azure AI Search
- Azure Blob Storage
- Azure AI Document Intelligence
- Azure AI Foundry model resource or reused existing Foundry resource

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

## Step 3 - Confirm the Blob containers

The core workshop expects these containers:

- `documents`
- `document-figure-artifacts`
- `search-enrichment-cache-v2`

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

## What To Inspect In This Repo

```text
Focus for this lab:
- understand how the repo expects Azure resources to be named
- understand which services are required by the workshop

Primary files:
- scripts/provision-azure.ps1
- .env.example
- backend/core/config.py
- docs/environment-reference.md
```

- [`scripts/provision-azure.ps1`](../../scripts/provision-azure.ps1)
  Provisions the resource group, Search service, Blob containers, Document Intelligence resource, and Foundry wiring expected by the workshop.
- [`.env.example`](../../.env.example)
  Shows which outputs from the provisioning step must be copied into environment variables.
- [`backend/core/config.py`](../../backend/core/config.py)
  Defines the runtime settings that decide whether Search, Blob ingestion, Document Intelligence, and the workshop profiles are actually enabled.
- [`docs/environment-reference.md`](../environment-reference.md)
  Explains how the environment variables map to the app behavior.

## Learn References

- [Azure AI Search overview](https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search)
- [Skillset concepts](https://learn.microsoft.com/en-us/azure/search/cognitive-search-working-with-skillsets)
- [Tutorial: skillsets](https://learn.microsoft.com/en-us/azure/search/tutorial-skillset)
