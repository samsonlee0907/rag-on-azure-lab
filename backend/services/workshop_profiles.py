from __future__ import annotations

from dataclasses import asdict, dataclass, field

from backend.core.config import settings


@dataclass(frozen=True, slots=True)
class WorkshopSkillProfile:
    id: str
    order: int
    title: str
    lab_path: str
    target_index_name: str
    target_skillset_name: str
    target_indexer_name: str
    description: str
    added_skills: tuple[str, ...] = ()
    cumulative_skills: tuple[str, ...] = ()
    retrieval_focus: str = ""
    recommended_retrieval_modes: tuple[str, ...] = ()
    recommended_question: str = ""
    requires: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    implementation_status: str = "documented"

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


def _suffix_name(base_name: str, suffix: str) -> str:
    normalized = suffix.strip().replace("_", "-")
    return f"{base_name}-{normalized}"


def build_workshop_skill_profiles() -> list[WorkshopSkillProfile]:
    base_index = settings.azure_search_enrichment_index_name
    base_skillset = settings.azure_search_skillset_name
    base_indexer = settings.azure_search_blob_indexer_name

    profiles = [
        WorkshopSkillProfile(
            id="baseline_extract",
            order=1,
            title="Baseline Extraction",
            lab_path="./docs/labs/lab-03-baseline-extraction.md",
            target_index_name=_suffix_name(base_index, "baseline"),
            target_skillset_name=_suffix_name(base_skillset, "baseline"),
            target_indexer_name=_suffix_name(base_indexer, "baseline"),
            description=(
                "Ingest the same document with DocumentExtractionSkill only to establish the starting retrieval quality."
            ),
            added_skills=("DocumentExtractionSkill",),
            cumulative_skills=("DocumentExtractionSkill",),
            retrieval_focus="Raw extracted text, section coverage, and baseline searchability.",
            recommended_retrieval_modes=("full_text",),
            recommended_question="What major sections and themes are present in this document?",
            notes=(
                "This is the simplest Azure AI Search built-in extraction path.",
                "Use it to show what retrieval looks like before chunking, enrichment, or visual analysis are added.",
            ),
            implementation_status="implemented",
        ),
        WorkshopSkillProfile(
            id="chunk_vector",
            order=2,
            title="Chunking And Vectorization",
            lab_path="./docs/labs/lab-04-chunking-and-vectorization.md",
            target_index_name=_suffix_name(base_index, "chunk-vector"),
            target_skillset_name=_suffix_name(base_skillset, "chunk-vector"),
            target_indexer_name=_suffix_name(base_indexer, "chunk-vector"),
            description=(
                "Re-index the same document with built-in Text Split and Azure OpenAI Embedding skills to show how chunking improves recall and targeting."
            ),
            added_skills=("SplitSkill", "AzureOpenAIEmbeddingSkill"),
            cumulative_skills=(
                "DocumentExtractionSkill",
                "SplitSkill",
                "AzureOpenAIEmbeddingSkill",
            ),
            retrieval_focus="Improved chunk-level recall, better semantic matching, and reduced whole-document noise.",
            recommended_retrieval_modes=("full_text", "vector", "hybrid"),
            recommended_question="Which specific chunk best explains the architecture workflow in this document?",
            requires=("AZURE_OPENAI_EMBEDDING_DEPLOYMENT",),
            notes=(
                "Azure AI Search guidance treats chunking as a first-class design choice for retrieval quality.",
                "This lab should compare retrieval against the baseline extraction index using the same document and prompt.",
            ),
            implementation_status="implemented",
        ),
        WorkshopSkillProfile(
            id="genai_enrichment",
            order=3,
            title="Generative Enrichment",
            lab_path="./docs/labs/lab-05-generative-enrichment.md",
            target_index_name=_suffix_name(base_index, "genai"),
            target_skillset_name=_suffix_name(base_skillset, "genai"),
            target_indexer_name=_suffix_name(base_indexer, "genai"),
            description=(
                "Add Search-side generative enrichment so summaries and retrieval tags are created during indexing."
            ),
            added_skills=("ChatCompletionSkill",),
            cumulative_skills=(
                "DocumentExtractionSkill",
                "SplitSkill",
                "AzureOpenAIEmbeddingSkill",
                "ChatCompletionSkill",
            ),
            retrieval_focus="Higher-level retrieval cues such as summaries, keywords, and agent-friendly abstraction.",
            recommended_retrieval_modes=("hybrid", "agentic"),
            recommended_question="What summary or retrieval cues make this document easier to search accurately?",
            requires=("AZURE_SEARCH_LLM_DEPLOYMENT",),
            notes=(
                "This repo uses ChatCompletionSkill as the implemented generative enrichment surface.",
                "GenAI Prompt skill can be introduced as a follow-on variation, but the base workshop keeps the concrete implementation on ChatCompletionSkill.",
                "Use this lab to contrast chunk-only retrieval versus chunk plus generative retrieval hints.",
            ),
            implementation_status="implemented",
        ),
        WorkshopSkillProfile(
            id="visual_nlp",
            order=4,
            title="Image And NLP Enrichment",
            lab_path="./docs/labs/lab-06-image-and-nlp-enrichment.md",
            target_index_name=_suffix_name(base_index, "visual-nlp"),
            target_skillset_name=_suffix_name(base_skillset, "visual-nlp"),
            target_indexer_name=_suffix_name(base_indexer, "visual-nlp"),
            description=(
                "Add OCR, Image Analysis, Language Detection, Entity Recognition, Text Merge, and Shaper to demonstrate how visual and linguistic enrichments change retrieval."
            ),
            added_skills=(
                "OCRSkill",
                "ImageAnalysisSkill",
                "LanguageDetectionSkill",
            ),
            cumulative_skills=(
                "DocumentExtractionSkill",
                "SplitSkill",
                "AzureOpenAIEmbeddingSkill",
                "ChatCompletionSkill",
                "OCRSkill",
                "ImageAnalysisSkill",
                "LanguageDetectionSkill",
            ),
            retrieval_focus="Image text, captions, detected entities, merged text fields, and better evidence surfacing for diagram-heavy documents.",
            recommended_retrieval_modes=("hybrid", "agentic"),
            recommended_question="What does the diagram say, which entities are important, and how does the merged evidence improve the answer?",
            notes=(
                "Use the same diagram-heavy document so the audience can see the benefit of OCR and image understanding.",
                "This repo implements OCR, Image Analysis, and Language Detection directly in code for this track.",
                "EntityRecognitionSkillV3, MergeSkill, and ShaperSkill remain part of the workshop discussion and can be added as a portal or JSON extension once the base lab succeeds.",
                "This is the strongest lab for comparing purely textual retrieval against visual-plus-NLP enrichment.",
            ),
            implementation_status="implemented_with_extensions",
        ),
        WorkshopSkillProfile(
            id="content_understanding",
            order=5,
            title="Content Understanding Alternative",
            lab_path="./docs/labs/lab-08-optional-content-understanding-skill-upgrade.md",
            target_index_name=_suffix_name(base_index, "content-understanding"),
            target_skillset_name=_suffix_name(base_skillset, "content-understanding"),
            target_indexer_name=_suffix_name(base_indexer, "content-understanding"),
            description=(
                "Switch the Search-managed extractor to the Azure Content Understanding skill to compare newer semantic extraction against the earlier built-in profiles."
            ),
            added_skills=("ContentUnderstandingSkill",),
            cumulative_skills=(
                "ContentUnderstandingSkill",
                "AzureOpenAIEmbeddingSkill",
                "ChatCompletionSkill",
            ),
            retrieval_focus="Semantic chunking, image descriptions, and richer structure-aware extraction inside the Search skillset itself.",
            recommended_retrieval_modes=("hybrid", "agentic"),
            recommended_question="How does the Content Understanding skill change chunk boundaries and diagram-grounded retrieval?",
            requires=(
                "AZURE_FOUNDRY_RESOURCE_ENDPOINT",
            ),
            notes=(
                "Keep this later in the workshop because it exercises the resource-attached Content Understanding skill.",
                "The GA skill binds to the billable Foundry resource via the skillset's managed identity, so no separate Content Understanding endpoint, key, or analyzer is required.",
                "Use it to compare with the earlier DocumentExtractionSkill and classic enrichment profiles.",
            ),
            implementation_status="optional_advanced_lab",
        ),
    ]
    return profiles


def get_workshop_skill_profile(profile_id: str | None = None) -> WorkshopSkillProfile:
    target_profile_id = (profile_id or settings.workshop_skill_profile or "baseline_extract").strip().lower()
    for profile in build_workshop_skill_profiles():
        if profile.id == target_profile_id:
            return profile
    for profile in build_workshop_skill_profiles():
        if profile.id == "baseline_extract":
            return profile
    raise RuntimeError("No workshop skill profiles are available.")


def build_workshop_profile_summary() -> dict[str, object]:
    profiles = build_workshop_skill_profiles()
    active_profile = get_workshop_skill_profile()
    return {
        "same_document_strategy": True,
        "comparison_pattern": "ingest the same document into progressively richer Azure AI Search indexes and compare retrieval behavior",
        "retrieval_tracks": [
            {
                "id": "full_text",
                "title": "Full Text Search",
                "description": "Keyword and lexical matching over chunk text in the canonical Azure AI Search index.",
            },
            {
                "id": "vector",
                "title": "Vector Search",
                "description": "Embedding similarity search over chunk vectors in the canonical Azure AI Search index.",
            },
            {
                "id": "hybrid",
                "title": "Hybrid Search",
                "description": "Combined keyword and vector retrieval over the same chunk corpus.",
            },
            {
                "id": "agentic",
                "title": "Agentic Retrieval",
                "description": "Official Azure AI Search knowledge-base retrieval with query planning, subqueries, and grounded synthesis.",
            },
        ],
        "active_profile_id": active_profile.id,
        "profiles": [profile.to_payload() for profile in profiles],
    }
