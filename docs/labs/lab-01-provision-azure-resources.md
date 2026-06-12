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
