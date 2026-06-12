param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $false)]
    [string]$Location = "eastus",

    [Parameter(Mandatory = $false)]
    [string]$ResourceGroupName = "rg-ai-search-lab",

    [Parameter(Mandatory = $false)]
    [string]$SearchServiceName = "",

    [Parameter(Mandatory = $false)]
    [string]$DocumentIntelligenceName = "",

    [Parameter(Mandatory = $false)]
    [string]$StorageAccountName = "",

    [Parameter(Mandatory = $false)]
    [string]$FigureArtifactContainerName = "document-figure-artifacts",

    [Parameter(Mandatory = $false)]
    [string]$SearchSourceContainerName = "documents",

    [Parameter(Mandatory = $false)]
    [string]$SearchCacheContainerName = "search-enrichment-cache-v2",

    [Parameter(Mandatory = $false)]
    [string]$SearchAssetStoreContainerName = "search-image-assets-v2",

    [Parameter(Mandatory = $false)]
    [string]$SearchSku = "standard",

    [Parameter(Mandatory = $false)]
    [string]$ExistingFoundryResourceGroup = "",

    [Parameter(Mandatory = $false)]
    [string]$ExistingFoundryResourceName = "",

    [Parameter(Mandatory = $false)]
    [string]$FoundryResourceName = "",

    [Parameter(Mandatory = $false)]
    [string]$FoundryProjectName = "enterprise-knowledge-v2-project",

    [Parameter(Mandatory = $false)]
    [switch]$CreateFoundryProject,

    [Parameter(Mandatory = $false)]
    [switch]$CreateOptionalModelDeployments,

    [Parameter(Mandatory = $false)]
    [string]$ChatModelName = "gpt-5.4",

    [Parameter(Mandatory = $false)]
    [string]$ChatModelVersion = "",

    [Parameter(Mandatory = $false)]
    [string]$ChatDeploymentName = "gpt-5-4",

    [Parameter(Mandatory = $false)]
    [string]$PlanningModelName = "gpt-5-mini",

    [Parameter(Mandatory = $false)]
    [string]$PlanningModelVersion = "",

    [Parameter(Mandatory = $false)]
    [string]$PlanningDeploymentName = "gpt-5-mini",

    [Parameter(Mandatory = $false)]
    [string]$NativeChatModelName = "gpt-5.2",

    [Parameter(Mandatory = $false)]
    [string]$NativeChatModelVersion = "",

    [Parameter(Mandatory = $false)]
    [string]$NativeChatDeploymentName = "gpt-5-2",

    [Parameter(Mandatory = $false)]
    [string]$EmbeddingModelName = "text-embedding-3-large",

    [Parameter(Mandatory = $false)]
    [string]$EmbeddingModelVersion = "",

    [Parameter(Mandatory = $false)]
    [string]$EmbeddingDeploymentName = "text-embedding-3-large"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RandomSuffix {
    -join ((97..122) + (48..57) | Get-Random -Count 6 | ForEach-Object { [char]$_ })
}

function Ensure-Name {
    param(
        [string]$Value,
        [string]$Prefix,
        [int]$MaxLength = 24,
        [switch]$LowercaseOnly
    )

    if ($Value) {
        return $Value
    }

    $suffix = Get-RandomSuffix
    $candidate = "$Prefix$suffix"
    if ($LowercaseOnly) {
        $candidate = $candidate.ToLowerInvariant()
    }
    if ($candidate.Length -gt $MaxLength) {
        return $candidate.Substring(0, $MaxLength)
    }
    return $candidate
}

function Invoke-Az {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host ">> az $($Arguments -join ' ')" -ForegroundColor Cyan
    $raw = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }
    return $raw
}

function Invoke-AzJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $raw = Invoke-Az -Arguments $Arguments
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Ensure-RoleAssignment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AssigneeObjectId,
        [Parameter(Mandatory = $true)]
        [string]$PrincipalType,
        [Parameter(Mandatory = $true)]
        [string]$RoleName,
        [Parameter(Mandatory = $true)]
        [string]$Scope
    )

    try {
        Invoke-Az -Arguments @(
            "role", "assignment", "create",
            "--assignee-object-id", $AssigneeObjectId,
            "--assignee-principal-type", $PrincipalType,
            "--role", $RoleName,
            "--scope", $Scope,
            "--output", "none"
        ) | Out-Null
    }
    catch {
        if ($_.Exception.Message -match "already exists") {
            Write-Host "Role assignment already exists for $RoleName on $Scope" -ForegroundColor DarkYellow
            return
        }
        throw
    }
}

function Ensure-StorageContainer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,
        [Parameter(Mandatory = $true)]
        [string]$AccountName
    )

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Invoke-Az -Arguments @(
                "storage", "container", "create",
                "--name", $ContainerName,
                "--account-name", $AccountName,
                "--auth-mode", "login",
                "--public-access", "off",
                "--output", "none"
            ) | Out-Null
            return
        }
        catch {
            if ($attempt -eq 10) {
                throw
            }
            Write-Host "Waiting for storage RBAC propagation before creating container $ContainerName..." -ForegroundColor DarkYellow
            Start-Sleep -Seconds 15
        }
    }
}

function Enable-FoundryProjectManagement {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetResourceGroup,
        [Parameter(Mandatory = $true)]
        [string]$TargetFoundryName
    )

    $accountPatchBody = @{
        properties = @{
            allowProjectManagement = $true
        }
    } | ConvertTo-Json -Depth 10

    $bodyPath = New-TemporaryFile
    try {
        Set-Content -LiteralPath $bodyPath.FullName -Value $accountPatchBody -Encoding utf8NoBOM
        Invoke-Az -Arguments @(
            "rest",
            "--method", "PATCH",
            "--uri", "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$TargetResourceGroup/providers/Microsoft.CognitiveServices/accounts/${TargetFoundryName}?api-version=2025-06-01",
            "--headers", "Content-Type=application/json",
            "--body", "@$($bodyPath.FullName)",
            "--output", "none"
        ) | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $bodyPath.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-FoundryProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetResourceGroup,
        [Parameter(Mandatory = $true)]
        [string]$TargetFoundryName
    )

    Enable-FoundryProjectManagement -TargetResourceGroup $TargetResourceGroup -TargetFoundryName $TargetFoundryName
    $projectUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$TargetResourceGroup/providers/Microsoft.CognitiveServices/accounts/${TargetFoundryName}/projects/${FoundryProjectName}?api-version=2025-06-01"
    $projectBody = @{
        location = $Location
        identity = @{
            type = "SystemAssigned"
        }
        properties = @{
            displayName = $FoundryProjectName
            description = "Project for the AI Search Lab workshop and native multimodal retrieval."
        }
    } | ConvertTo-Json -Depth 10

    $bodyPath = New-TemporaryFile
    try {
        Set-Content -LiteralPath $bodyPath.FullName -Value $projectBody -Encoding utf8NoBOM
        Invoke-Az -Arguments @(
            "rest",
            "--method", "PUT",
            "--uri", $projectUri,
            "--headers", "Content-Type=application/json",
            "--body", "@$($bodyPath.FullName)",
            "--output", "none"
        ) | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $bodyPath.FullName -Force -ErrorAction SilentlyContinue
    }
}

if (($ExistingFoundryResourceGroup -and -not $ExistingFoundryResourceName) -or ($ExistingFoundryResourceName -and -not $ExistingFoundryResourceGroup)) {
    throw "Provide both ExistingFoundryResourceGroup and ExistingFoundryResourceName when reusing an existing Foundry resource."
}

$SearchServiceName = Ensure-Name -Value $SearchServiceName -Prefix "aisearchlab" -MaxLength 20 -LowercaseOnly
$DocumentIntelligenceName = Ensure-Name -Value $DocumentIntelligenceName -Prefix "aidocintlab" -MaxLength 20 -LowercaseOnly
$StorageAccountName = Ensure-Name -Value $StorageAccountName -Prefix "aislabstore" -MaxLength 20 -LowercaseOnly
if (-not $ExistingFoundryResourceName) {
    $FoundryResourceName = Ensure-Name -Value $FoundryResourceName -Prefix "aifoundrylab" -MaxLength 20 -LowercaseOnly
}

$tenantInfo = Invoke-AzJson -Arguments @("account", "show", "--subscription", $SubscriptionId, "--output", "json")
if (-not $tenantInfo) {
    throw "Unable to resolve the target subscription. Run 'az login' first."
}

Invoke-Az -Arguments @("account", "set", "--subscription", $SubscriptionId) | Out-Null

Write-Host "Registering providers..." -ForegroundColor Yellow
Invoke-Az -Arguments @("provider", "register", "--namespace", "Microsoft.Search", "--wait") | Out-Null
Invoke-Az -Arguments @("provider", "register", "--namespace", "Microsoft.CognitiveServices", "--wait") | Out-Null
Invoke-Az -Arguments @("provider", "register", "--namespace", "Microsoft.Storage", "--wait") | Out-Null

Write-Host "Creating resource group..." -ForegroundColor Yellow
Invoke-Az -Arguments @("group", "create", "--name", $ResourceGroupName, "--location", $Location, "--output", "none") | Out-Null

Write-Host "Creating storage account..." -ForegroundColor Yellow
Invoke-Az -Arguments @(
    "storage", "account", "create",
    "--name", $StorageAccountName,
    "--resource-group", $ResourceGroupName,
    "--location", $Location,
    "--sku", "Standard_LRS",
    "--kind", "StorageV2",
    "--min-tls-version", "TLS1_2",
    "--allow-blob-public-access", "false",
    "--allow-shared-key-access", "true",
    "--output", "none"
) | Out-Null

Invoke-Az -Arguments @(
    "storage", "account", "update",
    "--name", $StorageAccountName,
    "--resource-group", $ResourceGroupName,
    "--allow-shared-key-access", "true",
    "--output", "none"
) | Out-Null

$storageScope = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Storage/storageAccounts/$StorageAccountName"
$managedIdentityStorageConnectionString = "ResourceId=$storageScope;"

try {
    $signedInUserId = (Invoke-Az -Arguments @("ad", "signed-in-user", "show", "--query", "id", "--output", "tsv")).Trim()
    if ($signedInUserId) {
        Write-Host "Granting Storage Blob Data Contributor to the signed-in user..." -ForegroundColor Yellow
        Ensure-RoleAssignment -AssigneeObjectId $signedInUserId -PrincipalType "User" -RoleName "Storage Blob Data Contributor" -Scope $storageScope
    }
}
catch {
    Write-Warning "Unable to assign Storage Blob Data Contributor automatically. You may need to grant blob data access manually."
}

Write-Host "Creating Blob containers..." -ForegroundColor Yellow
Ensure-StorageContainer -ContainerName $FigureArtifactContainerName -AccountName $StorageAccountName
Ensure-StorageContainer -ContainerName $SearchSourceContainerName -AccountName $StorageAccountName
Ensure-StorageContainer -ContainerName $SearchCacheContainerName -AccountName $StorageAccountName
Ensure-StorageContainer -ContainerName $SearchAssetStoreContainerName -AccountName $StorageAccountName

Write-Host "Creating Azure AI Search service..." -ForegroundColor Yellow
Invoke-Az -Arguments @(
    "search", "service", "create",
    "--name", $SearchServiceName,
    "--resource-group", $ResourceGroupName,
    "--location", $Location,
    "--sku", $SearchSku,
    "--partition-count", "1",
    "--replica-count", "1",
    "--semantic-search", "standard",
    "--auth-options", "aadOrApiKey",
    "--aad-auth-failure-mode", "http401WithBearerChallenge",
    "--identity-type", "SystemAssigned",
    "--public-network-access", "enabled",
    "--output", "none"
) | Out-Null

$searchShow = Invoke-AzJson -Arguments @(
    "search", "service", "show",
    "--name", $SearchServiceName,
    "--resource-group", $ResourceGroupName,
    "--output", "json"
)
$searchPrincipalId = $searchShow.identity.principalId

Write-Host "Creating Document Intelligence resource..." -ForegroundColor Yellow
Invoke-Az -Arguments @(
    "cognitiveservices", "account", "create",
    "--name", $DocumentIntelligenceName,
    "--resource-group", $ResourceGroupName,
    "--location", $Location,
    "--kind", "FormRecognizer",
    "--sku", "S0",
    "--custom-domain", $DocumentIntelligenceName,
    "--yes",
    "--output", "none"
) | Out-Null

if ($ExistingFoundryResourceName) {
    $resolvedFoundryResourceGroup = $ExistingFoundryResourceGroup
    $resolvedFoundryResourceName = $ExistingFoundryResourceName
    Write-Host "Reusing existing Foundry resource $resolvedFoundryResourceName in $resolvedFoundryResourceGroup..." -ForegroundColor Yellow
}
else {
    $resolvedFoundryResourceGroup = $ResourceGroupName
    $resolvedFoundryResourceName = $FoundryResourceName
    Write-Host "Creating Foundry resource..." -ForegroundColor Yellow
    Invoke-Az -Arguments @(
        "cognitiveservices", "account", "create",
        "--name", $resolvedFoundryResourceName,
        "--resource-group", $resolvedFoundryResourceGroup,
        "--location", $Location,
        "--kind", "AIServices",
        "--sku", "S0",
        "--custom-domain", $resolvedFoundryResourceName,
        "--assign-identity",
        "--yes",
        "--output", "none"
    ) | Out-Null
}

if ($CreateFoundryProject) {
    Write-Host "Ensuring Foundry project..." -ForegroundColor Yellow
    Ensure-FoundryProject -TargetResourceGroup $resolvedFoundryResourceGroup -TargetFoundryName $resolvedFoundryResourceName
}

if ($CreateOptionalModelDeployments) {
    Write-Host "Creating optional Foundry model deployments..." -ForegroundColor Yellow

    if ($ChatModelVersion) {
        Invoke-Az -Arguments @(
            "cognitiveservices", "account", "deployment", "create",
            "--resource-group", $resolvedFoundryResourceGroup,
            "--name", $resolvedFoundryResourceName,
            "--deployment-name", $ChatDeploymentName,
            "--model-format", "OpenAI",
            "--model-name", $ChatModelName,
            "--model-version", $ChatModelVersion,
            "--sku-name", "Standard",
            "--sku-capacity", "1",
            "--output", "none"
        ) | Out-Null
    }
    else {
        Write-Warning "Skipping chat model deployment because ChatModelVersion was not provided."
    }

    if ($PlanningModelVersion) {
        Invoke-Az -Arguments @(
            "cognitiveservices", "account", "deployment", "create",
            "--resource-group", $resolvedFoundryResourceGroup,
            "--name", $resolvedFoundryResourceName,
            "--deployment-name", $PlanningDeploymentName,
            "--model-format", "OpenAI",
            "--model-name", $PlanningModelName,
            "--model-version", $PlanningModelVersion,
            "--sku-name", "Standard",
            "--sku-capacity", "1",
            "--output", "none"
        ) | Out-Null
    }
    else {
        Write-Warning "Skipping planning model deployment because PlanningModelVersion was not provided."
    }

    if ($EmbeddingModelVersion) {
        Invoke-Az -Arguments @(
            "cognitiveservices", "account", "deployment", "create",
            "--resource-group", $resolvedFoundryResourceGroup,
            "--name", $resolvedFoundryResourceName,
            "--deployment-name", $EmbeddingDeploymentName,
            "--model-format", "OpenAI",
            "--model-name", $EmbeddingModelName,
            "--model-version", $EmbeddingModelVersion,
            "--sku-name", "Standard",
            "--sku-capacity", "1",
            "--output", "none"
        ) | Out-Null
    }
    else {
        Write-Warning "Skipping embedding model deployment because EmbeddingModelVersion was not provided."
    }

    if ($NativeChatModelVersion) {
        Invoke-Az -Arguments @(
            "cognitiveservices", "account", "deployment", "create",
            "--resource-group", $resolvedFoundryResourceGroup,
            "--name", $resolvedFoundryResourceName,
            "--deployment-name", $NativeChatDeploymentName,
            "--model-format", "OpenAI",
            "--model-name", $NativeChatModelName,
            "--model-version", $NativeChatModelVersion,
            "--sku-name", "GlobalStandard",
            "--sku-capacity", "1",
            "--output", "none"
        ) | Out-Null
    }
    else {
        Write-Warning "Skipping native multimodal chat model deployment because NativeChatModelVersion was not provided."
    }
}

$docIntKeys = Invoke-AzJson -Arguments @(
    "cognitiveservices", "account", "keys", "list",
    "--name", $DocumentIntelligenceName,
    "--resource-group", $ResourceGroupName,
    "--output", "json"
)
$docIntShow = Invoke-AzJson -Arguments @(
    "cognitiveservices", "account", "show",
    "--name", $DocumentIntelligenceName,
    "--resource-group", $ResourceGroupName,
    "--output", "json"
)
$foundryShow = Invoke-AzJson -Arguments @(
    "cognitiveservices", "account", "show",
    "--name", $resolvedFoundryResourceName,
    "--resource-group", $resolvedFoundryResourceGroup,
    "--output", "json"
)
$foundryKeys = Invoke-AzJson -Arguments @(
    "cognitiveservices", "account", "keys", "list",
    "--name", $resolvedFoundryResourceName,
    "--resource-group", $resolvedFoundryResourceGroup,
    "--output", "json"
)

if ($searchPrincipalId) {
    Write-Host "Granting Storage roles to the Search managed identity..." -ForegroundColor Yellow
    Ensure-RoleAssignment -AssigneeObjectId $searchPrincipalId -PrincipalType "ServicePrincipal" -RoleName "Storage Blob Data Contributor" -Scope $storageScope
    Ensure-RoleAssignment -AssigneeObjectId $searchPrincipalId -PrincipalType "ServicePrincipal" -RoleName "Storage Table Data Contributor" -Scope $storageScope
    Write-Host "Granting Cognitive Services User to the Search managed identity on the Foundry resource..." -ForegroundColor Yellow
    Ensure-RoleAssignment -AssigneeObjectId $searchPrincipalId -PrincipalType "ServicePrincipal" -RoleName "Cognitive Services User" -Scope $foundryShow.id
}

$searchAdminKeys = Invoke-AzJson -Arguments @(
    "search", "admin-key", "show",
    "--resource-group", $ResourceGroupName,
    "--service-name", $SearchServiceName,
    "--output", "json"
)
$searchQueryKeyName = "app-query-key"
$existingQueryKeys = Invoke-AzJson -Arguments @(
    "search", "query-key", "list",
    "--resource-group", $ResourceGroupName,
    "--service-name", $SearchServiceName,
    "--output", "json"
)
$queryKey = $existingQueryKeys | Where-Object { $_.name -eq $searchQueryKeyName } | Select-Object -First 1
if (-not $queryKey) {
    $queryKey = Invoke-AzJson -Arguments @(
        "search", "query-key", "create",
        "--resource-group", $ResourceGroupName,
        "--service-name", $SearchServiceName,
        "--name", $searchQueryKeyName,
        "--output", "json"
    )
}

$projectEndpoint = ""
if ($CreateFoundryProject) {
    $projectEndpoint = "https://$resolvedFoundryResourceName.services.ai.azure.com/api/projects/$FoundryProjectName"
}

$output = [ordered]@{
    resourceGroup = $ResourceGroupName
    location = $Location
    storageAccount = $StorageAccountName
    storageContainers = [ordered]@{
        figures = $FigureArtifactContainerName
        documents = $SearchSourceContainerName
        enrichmentCache = $SearchCacheContainerName
        imageAssets = $SearchAssetStoreContainerName
    }
    searchService = $SearchServiceName
    searchPrincipalId = $searchPrincipalId
    documentIntelligence = $DocumentIntelligenceName
    foundryResource = $resolvedFoundryResourceName
    foundryResourceGroup = $resolvedFoundryResourceGroup
    foundryProject = $(if ($CreateFoundryProject) { $FoundryProjectName } else { "" })
    env = [ordered]@{
        APP_NAME = "AI Search Lab"
        APP_ENV = "development"
        LOG_LEVEL = "INFO"
        CHUNK_SIZE_TOKENS = "420"
        CHUNK_OVERLAP_TOKENS = "60"
        MAX_PAGES_PER_SEGMENT = "250"
        LARGE_DOCUMENT_PAGE_THRESHOLD = "250"
        HARD_PAGE_SPLIT_THRESHOLD = "2000"
        HARD_FILE_SPLIT_THRESHOLD_MB = "500"
        USE_SEMANTIC_CHUNKING = "false"
        ENABLE_LLM_BOUNDARY_STITCHING = "true"
        WORKSHOP_STRICT_MODE = "true"
        WORKSHOP_SKILL_PROFILE = "genai_enrichment"
        DEFAULT_INGESTION_MODE = "hybrid_blob_skillset"
        SEARCH_PIPELINE_MODE = "hybrid_blob_skillset"
        AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = $docIntShow.properties.endpoint
        AZURE_DOCUMENT_INTELLIGENCE_KEY = $docIntKeys.key1
        AZURE_DOCUMENT_INTELLIGENCE_MODEL = "prebuilt-layout"
        AZURE_CONTENT_UNDERSTANDING_ENDPOINT = ""
        AZURE_CONTENT_UNDERSTANDING_KEY = ""
        AZURE_CONTENT_UNDERSTANDING_ANALYZER_ID = ""
        AZURE_SEARCH_ENDPOINT = "https://$SearchServiceName.search.windows.net"
        AZURE_SEARCH_KEY = $searchAdminKeys.primaryKey
        AZURE_SEARCH_QUERY_KEY = $queryKey.key
        AZURE_SEARCH_INDEX_NAME = "enterprise-knowledge-index-v2"
        AZURE_SEARCH_KNOWLEDGE_SOURCE_NAME = "enterprise-knowledge-source-v2"
        AZURE_SEARCH_KNOWLEDGE_BASE_NAME = "enterprise-knowledge-base-v2"
        AZURE_SEARCH_API_VERSION = "2026-05-01-preview"
        AZURE_SEARCH_INDEXER_API_VERSION = "2026-05-01-preview"
        AZURE_SEARCH_EXTRA_SOURCES_JSON = ""
        AZURE_SEARCH_AUTO_BROADCAST_LIMIT = "4"
        AZURE_SEARCH_SKILLSET_NAME = "enterprise-knowledge-skillset-v2"
        AZURE_SEARCH_BLOB_DATA_SOURCE_NAME = "enterprise-knowledge-blob-datasource-v2"
        AZURE_SEARCH_BLOB_INDEXER_NAME = "enterprise-knowledge-blob-indexer-v2"
        AZURE_SEARCH_ENRICHMENT_INDEX_NAME = "enterprise-knowledge-enrichment-index-v2"
        AZURE_SEARCH_ENRICHMENT_KNOWLEDGE_SOURCE_NAME = "enterprise-knowledge-enrichment-source-v2"
        AZURE_SEARCH_INCLUDE_ENRICHMENT_SOURCE_IN_CHAT = "true"
        AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL = "true"
        AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS = "true"
        AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS = "true"
        AZURE_SEARCH_NATIVE_API_VERSION = "2026-05-01-preview"
        AZURE_SEARCH_NATIVE_KNOWLEDGE_BASE_NAME = "enterprise-knowledge-native-kb-v2"
        AZURE_SEARCH_NATIVE_KNOWLEDGE_SOURCE_PREFIX = "enterprise-native-blob-source-v2-"
        AZURE_SEARCH_NATIVE_AUTO_QUERY_TERMS = "diagram,figure,image,visual,blueprint,chart,schematic,drawing,show me,look at"
        AZURE_SEARCH_NATIVE_CONTENT_EXTRACTION_MODE = "standard"
        AZURE_SEARCH_NATIVE_CHAT_COMPLETION_DEPLOYMENT = $NativeChatDeploymentName
        AZURE_SEARCH_NATIVE_CHAT_COMPLETION_MODEL_NAME = $NativeChatModelName
        AZURE_SEARCH_BLOB_CONNECTION_STRING = $managedIdentityStorageConnectionString
        AZURE_SEARCH_BLOB_SOURCE_CONTAINER = $SearchSourceContainerName
        AZURE_SEARCH_BLOB_SOURCE_PREFIX = "v2"
        AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR = "document_extraction"
        AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS = "true"
        AZURE_SEARCH_ANSWER_INSTRUCTIONS = "Use concise bullets, preserve citations, separate evidence by source when multiple corpora contribute, and answer directly from retrieved text or image evidence without asking the user to re-upload or reconfirm images that were already retrieved."
        AZURE_SEARCH_ENABLE_ENRICHMENT_CACHE = "true"
        AZURE_SEARCH_ENRICHMENT_CACHE_CONNECTION_STRING = $managedIdentityStorageConnectionString
        AZURE_SEARCH_ENRICHMENT_CACHE_CONTAINER = $SearchCacheContainerName
        AZURE_SEARCH_ENABLE_GENAI_PROMPT_SKILL = "true"
        AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION = "true"
        AZURE_SEARCH_ALLOW_FOUNDRY_ENRICHMENT_SUPPLEMENT = "false"
        AZURE_SEARCH_VECTOR_FIELD_NAME = "content_vector"
        AZURE_SEARCH_VECTOR_DIMENSIONS = "3072"
        AZURE_SEARCH_ENABLE_BLOB_RBAC = "false"
        AZURE_SEARCH_DEFAULT_RBAC_SCOPE_IDS = ""
        AZURE_SEARCH_BLOB_RBAC_METADATA_FIELD = "rbac_scope_ids"
        AZURE_SEARCH_ENABLE_IMAGE_SERVING = "true"
        AZURE_SEARCH_ASSET_STORE_CONNECTION_STRING = $managedIdentityStorageConnectionString
        AZURE_SEARCH_ASSET_STORE_CONTAINER = $SearchAssetStoreContainerName
        AZURE_OPENAI_EMBEDDING_DEPLOYMENT = $EmbeddingDeploymentName
        AZURE_FOUNDRY_RESOURCE_ENDPOINT = $foundryShow.properties.endpoint
        AZURE_FOUNDRY_API_KEY = $foundryKeys.key1
        AZURE_FOUNDRY_RESOURCE_ID = $foundryShow.id
        AZURE_FOUNDRY_CHAT_DEPLOYMENT = $ChatDeploymentName
        AZURE_FOUNDRY_CHAT_MODEL_NAME = $ChatModelName
        AZURE_FOUNDRY_PROJECT_ENDPOINT = $projectEndpoint
        AZURE_FOUNDRY_PROJECT_NAME = $(if ($CreateFoundryProject) { $FoundryProjectName } else { "" })
        AZURE_SEARCH_LLM_DEPLOYMENT = $PlanningDeploymentName
        AZURE_SEARCH_LLM_MODEL_NAME = $PlanningModelName
        AZURE_SEARCH_LLM_REASONING_EFFORT = "low"
        AZURE_SEARCH_LLM_USE_MANAGED_IDENTITY = "true"
        FOUNDRY_CHAT_MODE = "search_knowledge_base"
        AZURE_STORAGE_ACCOUNT = $StorageAccountName
        AZURE_STORAGE_ACCOUNT_KEY = ""
        AZURE_STORAGE_CONNECTION_STRING = ""
        AZURE_STORAGE_CONTAINER = $FigureArtifactContainerName
        ENABLE_IMAGE_UNDERSTANDING = "true"
        MAX_FIGURE_IMAGE_PIXELS = "40000000"
        MAX_FIGURE_IMAGE_DIMENSION = "4096"
        REQUEST_TIMEOUT_SECONDS = "120"
    }
}

Write-Host ""
Write-Host "Provisioning complete. Use these values in .env:" -ForegroundColor Green
$output | ConvertTo-Json -Depth 10
