from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_azure_cli_path() -> str:
    candidate = Path(r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")
    if candidate.exists():
        return str(candidate)
    return "az"


DEFAULT_SEARCH_SOURCE_DATA_FIELDS: tuple[str, ...] = (
    "doc_id",
    "chunk_id",
    "clean_text",
    "summary_text",
    "keyword_hints",
    "image_description_text",
    "source_name",
    "source_uri",
    "section_path",
    "page_numbers",
    "tags",
    "image_evidence_json",
)
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = ("*",)


@dataclass(frozen=True, slots=True)
class SearchKnowledgeSourceConfig:
    knowledge_source_name: str
    index_name: str
    description: str = ""
    route_keywords: tuple[str, ...] = ()
    assignment_keywords: tuple[str, ...] = ()
    semantic_configuration_name: str = "default-semantic-config"
    source_data_fields: tuple[str, ...] = DEFAULT_SEARCH_SOURCE_DATA_FIELDS
    search_fields: tuple[str, ...] = DEFAULT_SEARCH_FIELDS


def _normalize_string_list(value: object, *, lower: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        entry = item.strip()
        if not entry:
            continue
        if lower:
            entry = entry.lower()
        if entry in seen:
            continue
        seen.add(entry)
        normalized.append(entry)
    return tuple(normalized)


def _split_csv_string(value: str) -> tuple[str, ...]:
    entries = [item.strip() for item in value.split(",")]
    return tuple(entry for entry in entries if entry)


def _load_extra_search_sources() -> tuple[SearchKnowledgeSourceConfig, ...]:
    raw = os.getenv("AZURE_SEARCH_EXTRA_SOURCES_JSON", "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()

    sources: list[SearchKnowledgeSourceConfig] = []
    seen_names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        knowledge_source_name = str(
            item.get("knowledge_source_name") or item.get("name") or ""
        ).strip()
        index_name = str(item.get("index_name") or item.get("search_index_name") or "").strip()
        if not knowledge_source_name or not index_name or knowledge_source_name in seen_names:
            continue
        seen_names.add(knowledge_source_name)
        semantic_configuration_name = str(
            item.get("semantic_configuration_name") or "default-semantic-config"
        ).strip() or "default-semantic-config"
        source_data_fields = _normalize_string_list(item.get("source_data_fields"))
        search_fields = _normalize_string_list(item.get("search_fields"))
        sources.append(
            SearchKnowledgeSourceConfig(
                knowledge_source_name=knowledge_source_name,
                index_name=index_name,
                description=str(item.get("description") or "").strip(),
                route_keywords=_normalize_string_list(item.get("route_keywords"), lower=True),
                assignment_keywords=_normalize_string_list(
                    item.get("assignment_keywords") or item.get("document_keywords"),
                    lower=True,
                ),
                semantic_configuration_name=semantic_configuration_name,
                source_data_fields=source_data_fields or DEFAULT_SEARCH_SOURCE_DATA_FIELDS,
                search_fields=search_fields or DEFAULT_SEARCH_FIELDS,
            )
        )
    return tuple(sources)


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Search Lab")
    environment: str = os.getenv("APP_ENV", "development")
    base_dir: Path = Path(os.getenv("APP_BASE_DIR", Path.cwd()))
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", Path.cwd() / "data"))
    uploads_dir: Path = Path(os.getenv("APP_UPLOADS_DIR", Path.cwd() / "data" / "uploads"))
    artifacts_dir: Path = Path(os.getenv("APP_ARTIFACTS_DIR", Path.cwd() / "data" / "artifacts"))
    store_path: Path = Path(os.getenv("APP_STORE_PATH", Path.cwd() / "data" / "job_store.json"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    chunk_size_tokens: int = int(os.getenv("CHUNK_SIZE_TOKENS", "420"))
    chunk_overlap_tokens: int = int(os.getenv("CHUNK_OVERLAP_TOKENS", "60"))
    max_pages_per_segment: int = int(os.getenv("MAX_PAGES_PER_SEGMENT", "250"))
    large_document_page_threshold: int = int(os.getenv("LARGE_DOCUMENT_PAGE_THRESHOLD", "250"))
    hard_page_split_threshold: int = int(os.getenv("HARD_PAGE_SPLIT_THRESHOLD", "2000"))
    hard_file_split_threshold_mb: int = int(os.getenv("HARD_FILE_SPLIT_THRESHOLD_MB", "500"))
    use_semantic_chunking: bool = _env_flag("USE_SEMANTIC_CHUNKING", False)
    enable_llm_boundary_stitching: bool = _env_flag("ENABLE_LLM_BOUNDARY_STITCHING", True)
    enable_demo_seed: bool = _env_flag("ENABLE_DEMO_SEED", True)
    workshop_strict_mode: bool = _env_flag("WORKSHOP_STRICT_MODE", True)
    workshop_skill_profile: str = os.getenv("WORKSHOP_SKILL_PROFILE", "baseline_extract")
    default_ingestion_mode: str = os.getenv("DEFAULT_INGESTION_MODE", "hybrid_blob_skillset")
    search_pipeline_mode: str = os.getenv("SEARCH_PIPELINE_MODE", "hybrid_blob_skillset")
    azure_cli_path: str = os.getenv("AZURE_CLI_PATH", _default_azure_cli_path())
    azure_document_intelligence_endpoint: str = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
    azure_document_intelligence_key: str = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")
    azure_document_intelligence_model: str = os.getenv(
        "AZURE_DOCUMENT_INTELLIGENCE_MODEL", "prebuilt-layout"
    )
    azure_content_understanding_endpoint: str = os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT", "")
    azure_content_understanding_key: str = os.getenv("AZURE_CONTENT_UNDERSTANDING_KEY", "")
    azure_content_understanding_analyzer_id: str = os.getenv(
        "AZURE_CONTENT_UNDERSTANDING_ANALYZER_ID", ""
    )
    azure_search_endpoint: str = os.getenv("AZURE_SEARCH_ENDPOINT", "")
    azure_search_key: str = os.getenv("AZURE_SEARCH_KEY", "")
    azure_search_index_name: str = os.getenv("AZURE_SEARCH_INDEX_NAME", "ai-search-lab-index")
    azure_search_knowledge_source_name: str = os.getenv(
        "AZURE_SEARCH_KNOWLEDGE_SOURCE_NAME", "ai-search-lab-source"
    )
    azure_search_knowledge_base_name: str = os.getenv(
        "AZURE_SEARCH_KNOWLEDGE_BASE_NAME", "ai-search-lab-kb"
    )
    azure_search_api_version: str = os.getenv("AZURE_SEARCH_API_VERSION", "2026-05-01-preview")
    azure_search_indexer_api_version: str = os.getenv("AZURE_SEARCH_INDEXER_API_VERSION", "2026-05-01-preview")
    azure_search_extra_sources: tuple[SearchKnowledgeSourceConfig, ...] = _load_extra_search_sources()
    azure_search_auto_broadcast_limit: int = int(os.getenv("AZURE_SEARCH_AUTO_BROADCAST_LIMIT", "4"))
    azure_search_request_timeout_seconds: int = int(
        os.getenv("AZURE_SEARCH_REQUEST_TIMEOUT_SECONDS", "180")
    )
    azure_search_skillset_name: str = os.getenv("AZURE_SEARCH_SKILLSET_NAME", "ai-search-lab-skillset")
    azure_search_blob_data_source_name: str = os.getenv(
        "AZURE_SEARCH_BLOB_DATA_SOURCE_NAME",
        "ai-search-lab-blob-datasource",
    )
    azure_search_blob_indexer_name: str = os.getenv(
        "AZURE_SEARCH_BLOB_INDEXER_NAME",
        "ai-search-lab-blob-indexer",
    )
    azure_search_enrichment_index_name: str = os.getenv(
        "AZURE_SEARCH_ENRICHMENT_INDEX_NAME",
        "ai-search-lab-enrichment-index",
    )
    azure_search_enrichment_knowledge_source_name: str = os.getenv(
        "AZURE_SEARCH_ENRICHMENT_KNOWLEDGE_SOURCE_NAME",
        "ai-search-lab-enrichment-source",
    )
    azure_search_include_enrichment_source_in_chat: bool = _env_flag(
        "AZURE_SEARCH_INCLUDE_ENRICHMENT_SOURCE_IN_CHAT",
        True,
    )
    azure_search_enable_native_multimodal_retrieval: bool = _env_flag(
        "AZURE_SEARCH_ENABLE_NATIVE_MULTIMODAL_RETRIEVAL",
        False,
    )
    azure_search_require_blob_skillset_success: bool = _env_flag(
        "AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS",
        True,
    )
    azure_search_require_native_multimodal_success: bool = _env_flag(
        "AZURE_SEARCH_REQUIRE_NATIVE_MULTIMODAL_SUCCESS",
        False,
    )
    azure_search_native_api_version: str = os.getenv(
        "AZURE_SEARCH_NATIVE_API_VERSION",
        "2026-05-01-preview",
    )
    azure_search_native_knowledge_base_name: str = os.getenv(
        "AZURE_SEARCH_NATIVE_KNOWLEDGE_BASE_NAME",
        "ai-search-lab-native-kb",
    )
    azure_search_native_knowledge_source_prefix: str = os.getenv(
        "AZURE_SEARCH_NATIVE_KNOWLEDGE_SOURCE_PREFIX",
        "ai-search-lab-native-source-",
    )
    azure_search_native_auto_query_terms: tuple[str, ...] = _split_csv_string(
        os.getenv(
            "AZURE_SEARCH_NATIVE_AUTO_QUERY_TERMS",
            "diagram,figure,image,visual,blueprint,chart,schematic,drawing,show me,look at",
        )
    )
    azure_search_native_content_extraction_mode: str = os.getenv(
        "AZURE_SEARCH_NATIVE_CONTENT_EXTRACTION_MODE",
        "standard",
    ).strip().lower()
    azure_search_native_chat_completion_deployment: str = os.getenv(
        "AZURE_SEARCH_NATIVE_CHAT_COMPLETION_DEPLOYMENT",
        "gpt-5-4-mini-native",
    )
    azure_search_native_chat_completion_model_name: str = os.getenv(
        "AZURE_SEARCH_NATIVE_CHAT_COMPLETION_MODEL_NAME",
        "gpt-5.4-mini",
    )
    azure_search_native_retrieve_retry_attempts: int = int(
        os.getenv("AZURE_SEARCH_NATIVE_RETRIEVE_RETRY_ATTEMPTS", "3")
    )
    azure_search_native_retrieve_retry_base_delay_seconds: int = int(
        os.getenv("AZURE_SEARCH_NATIVE_RETRIEVE_RETRY_BASE_DELAY_SECONDS", "10")
    )
    azure_search_retrieve_retry_attempts: int = int(
        os.getenv("AZURE_SEARCH_RETRIEVE_RETRY_ATTEMPTS", "3")
    )
    azure_search_retrieve_retry_base_delay_seconds: int = int(
        os.getenv("AZURE_SEARCH_RETRIEVE_RETRY_BASE_DELAY_SECONDS", "6")
    )
    azure_search_blob_connection_string: str = os.getenv("AZURE_SEARCH_BLOB_CONNECTION_STRING", "")
    azure_search_blob_source_container: str = os.getenv("AZURE_SEARCH_BLOB_SOURCE_CONTAINER", "documents")
    azure_search_blob_source_prefix: str = os.getenv("AZURE_SEARCH_BLOB_SOURCE_PREFIX", "workshop")
    azure_search_skillset_preferred_extractor: str = os.getenv(
        "AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR",
        "document_extraction",
    )
    azure_search_enable_answer_synthesis: bool = _env_flag("AZURE_SEARCH_ENABLE_ANSWER_SYNTHESIS", False)
    azure_search_answer_instructions: str = os.getenv(
        "AZURE_SEARCH_ANSWER_INSTRUCTIONS",
        "Use concise bullets, preserve citations, and separate evidence by source when multiple corpora contribute.",
    )
    azure_search_enable_enrichment_cache: bool = _env_flag("AZURE_SEARCH_ENABLE_ENRICHMENT_CACHE", True)
    azure_search_enrichment_cache_connection_string: str = os.getenv(
        "AZURE_SEARCH_ENRICHMENT_CACHE_CONNECTION_STRING",
        "",
    )
    azure_search_enrichment_cache_container: str = os.getenv(
        "AZURE_SEARCH_ENRICHMENT_CACHE_CONTAINER",
        "search-enrichment-cache",
    )
    azure_search_enable_genai_prompt_skill: bool = _env_flag("AZURE_SEARCH_ENABLE_GENAI_PROMPT_SKILL", True)
    azure_search_enable_integrated_vectorization: bool = _env_flag(
        "AZURE_SEARCH_ENABLE_INTEGRATED_VECTORIZATION",
        True,
    )
    azure_search_prompt_seed_page_length: int = int(
        os.getenv("AZURE_SEARCH_PROMPT_SEED_PAGE_LENGTH", "1200")
    )
    azure_search_prompt_seed_pages_to_take: int = int(
        os.getenv("AZURE_SEARCH_PROMPT_SEED_PAGES_TO_TAKE", "2")
    )
    azure_search_prompt_seed_page_overlap: int = int(
        os.getenv("AZURE_SEARCH_PROMPT_SEED_PAGE_OVERLAP", "0")
    )
    azure_search_indexer_transient_retry_attempts: int = int(
        os.getenv("AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_ATTEMPTS", "3")
    )
    azure_search_indexer_transient_retry_base_delay_seconds: int = int(
        os.getenv("AZURE_SEARCH_INDEXER_TRANSIENT_RETRY_BASE_DELAY_SECONDS", "20")
    )
    azure_search_vector_field_name: str = os.getenv("AZURE_SEARCH_VECTOR_FIELD_NAME", "content_vector")
    azure_search_vector_dimensions: int = int(os.getenv("AZURE_SEARCH_VECTOR_DIMENSIONS", "3072"))
    azure_search_enable_blob_rbac: bool = _env_flag("AZURE_SEARCH_ENABLE_BLOB_RBAC", False)
    azure_search_default_rbac_scope_ids: tuple[str, ...] = _split_csv_string(
        os.getenv("AZURE_SEARCH_DEFAULT_RBAC_SCOPE_IDS", "")
    )
    azure_search_blob_rbac_metadata_field: str = os.getenv(
        "AZURE_SEARCH_BLOB_RBAC_METADATA_FIELD",
        "rbac_scope_ids",
    )
    azure_search_enable_image_serving: bool = _env_flag("AZURE_SEARCH_ENABLE_IMAGE_SERVING", False)
    azure_search_asset_store_connection_string: str = os.getenv(
        "AZURE_SEARCH_ASSET_STORE_CONNECTION_STRING",
        "",
    )
    azure_search_asset_store_container: str = os.getenv(
        "AZURE_SEARCH_ASSET_STORE_CONTAINER",
        "search-image-assets",
    )
    azure_openai_embedding_deployment: str = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    azure_openai_embedding_model_name: str = os.getenv(
        "AZURE_OPENAI_EMBEDDING_MODEL_NAME",
        "text-embedding-3-large",
    )
    azure_foundry_resource_endpoint: str = os.getenv("AZURE_FOUNDRY_RESOURCE_ENDPOINT", "")
    azure_foundry_api_key: str = os.getenv("AZURE_FOUNDRY_API_KEY", "")
    azure_foundry_chat_deployment: str = os.getenv("AZURE_FOUNDRY_CHAT_DEPLOYMENT", "gpt-5-4-mini-chat")
    azure_foundry_chat_model_name: str = os.getenv("AZURE_FOUNDRY_CHAT_MODEL_NAME", "")
    azure_foundry_project_endpoint: str = os.getenv("AZURE_FOUNDRY_PROJECT_ENDPOINT", "")
    azure_foundry_agent_id: str = os.getenv("AZURE_FOUNDRY_AGENT_ID", "")
    foundry_chat_mode: str = os.getenv("FOUNDRY_CHAT_MODE", "search_knowledge_base")
    azure_search_llm_deployment: str = os.getenv("AZURE_SEARCH_LLM_DEPLOYMENT", "gpt-5-4-mini-search")
    azure_search_llm_model_name: str = os.getenv("AZURE_SEARCH_LLM_MODEL_NAME", "gpt-5.4-mini")
    azure_search_llm_reasoning_effort: str = os.getenv("AZURE_SEARCH_LLM_REASONING_EFFORT", "low")
    azure_search_llm_use_managed_identity: bool = _env_flag("AZURE_SEARCH_LLM_USE_MANAGED_IDENTITY", True)
    azure_search_allow_foundry_enrichment_supplement: bool = _env_flag(
        "AZURE_SEARCH_ALLOW_FOUNDRY_ENRICHMENT_SUPPLEMENT",
        False,
    )
    search_query_key: str = os.getenv("AZURE_SEARCH_QUERY_KEY", "")
    azure_storage_account: str = os.getenv("AZURE_STORAGE_ACCOUNT", "")
    azure_storage_account_key: str = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "")
    azure_storage_container: str = os.getenv("AZURE_STORAGE_CONTAINER", "document-figure-artifacts")
    enable_parser_figure_extraction: bool = _env_flag("ENABLE_PARSER_FIGURE_EXTRACTION", False)
    enable_image_understanding: bool = _env_flag("ENABLE_IMAGE_UNDERSTANDING", True)
    parser_figure_max_artifacts: int = int(os.getenv("PARSER_FIGURE_MAX_ARTIFACTS", "80"))
    max_figure_image_pixels: int = int(os.getenv("MAX_FIGURE_IMAGE_PIXELS", "40000000"))
    max_figure_image_dimension: int = int(os.getenv("MAX_FIGURE_IMAGE_DIMENSION", "4096"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def azure_docint_enabled(self) -> bool:
        return bool(self.azure_document_intelligence_endpoint and self.azure_document_intelligence_key)

    @property
    def azure_content_understanding_enabled(self) -> bool:
        return bool(
            self.azure_content_understanding_endpoint
            and self.azure_content_understanding_key
            and self.azure_content_understanding_analyzer_id
        )

    @property
    def azure_search_enabled(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_key)

    @property
    def azure_search_multi_index_enabled(self) -> bool:
        return len(self.azure_search_extra_sources) > 0

    @property
    def azure_search_blob_connection_string_resolved(self) -> str:
        if self.azure_search_blob_connection_string:
            return self.azure_search_blob_connection_string
        if self.azure_storage_connection_string:
            return self.azure_storage_connection_string
        return ""

    @property
    def azure_search_blob_ingestion_enabled(self) -> bool:
        return bool(
            self.azure_search_enabled
            and self.azure_search_blob_source_container
            and self.azure_search_blob_connection_string_resolved
        )

    @property
    def azure_search_native_multimodal_enabled(self) -> bool:
        return bool(
            self.azure_search_enable_native_multimodal_retrieval
            and self.azure_search_enabled
            and self.azure_search_blob_ingestion_enabled
            and self.azure_search_asset_store_container
            and (self.azure_search_asset_store_connection_string or self.azure_search_blob_connection_string_resolved)
            and self.azure_search_llm_enabled
        )

    @property
    def azure_foundry_chat_enabled(self) -> bool:
        return bool(self.azure_foundry_resource_endpoint and self.azure_foundry_chat_deployment)

    @property
    def parser_figure_extraction_enabled(self) -> bool:
        if self.enable_parser_figure_extraction:
            return True
        return self.workshop_skill_profile in {"visual_nlp", "content_understanding"}

    @property
    def parser_image_understanding_enabled(self) -> bool:
        return bool(
            self.parser_figure_extraction_enabled
            and self.enable_image_understanding
            and self.azure_foundry_chat_enabled
        )

    @property
    def azure_search_llm_enabled(self) -> bool:
        return bool(
            self.azure_search_llm_deployment
            and self.azure_foundry_openai_base_url
            and (self.azure_search_llm_use_managed_identity or self.azure_foundry_api_key)
        )

    @property
    def azure_foundry_openai_base_url(self) -> str:
        if not self.azure_foundry_resource_endpoint:
            return ""
        parsed = urlparse(self.azure_foundry_resource_endpoint)
        hostname = parsed.netloc
        if hostname.endswith(".cognitiveservices.azure.com"):
            hostname = hostname.replace(".cognitiveservices.azure.com", ".openai.azure.com")
        if not hostname:
            return ""
        scheme = parsed.scheme or "https"
        return f"{scheme}://{hostname}"

    @property
    def azure_foundry_services_base_url(self) -> str:
        if not self.azure_foundry_resource_endpoint:
            return ""
        parsed = urlparse(self.azure_foundry_resource_endpoint)
        hostname = parsed.netloc
        if hostname.endswith(".cognitiveservices.azure.com"):
            hostname = hostname.replace(".cognitiveservices.azure.com", ".services.ai.azure.com")
        if not hostname:
            return ""
        scheme = parsed.scheme or "https"
        return f"{scheme}://{hostname}"

    @property
    def azure_blob_storage_enabled(self) -> bool:
        return bool(self.azure_storage_account and self.azure_storage_container)

    @property
    def azure_blob_account_url(self) -> str:
        if not self.azure_storage_account:
            return ""
        return f"https://{self.azure_storage_account}.blob.core.windows.net"

    @property
    def azure_storage_connection_string(self) -> str:
        raw = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        if raw:
            return raw
        if self.azure_storage_account and self.azure_storage_account_key:
            return (
                "DefaultEndpointsProtocol=https;"
                f"AccountName={self.azure_storage_account};"
                f"AccountKey={self.azure_storage_account_key};"
                "EndpointSuffix=core.windows.net"
            )
        return ""

    @property
    def hard_file_split_threshold_bytes(self) -> int:
        return self.hard_file_split_threshold_mb * 1024 * 1024


settings = Settings()
settings.ensure_directories()
