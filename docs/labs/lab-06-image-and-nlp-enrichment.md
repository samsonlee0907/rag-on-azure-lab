# Lab 06 - Visual And NLP Enrichment

## Goal

Add visual and language-oriented skills to the same document:

- `OcrSkill`
- `ImageAnalysisSkill`
- `LanguageDetectionSkill`

Then compare how `Hybrid` retrieval changes for diagram-heavy or image-heavy questions.

## Questions This Lab Answers

- What is the difference between OCR, image analysis, and parser-side figure extraction?
- Which skills matter most for diagrams, screenshots, or scanned pages?
- How does visual evidence become searchable and then answerable?
- When should I add these skills in production, and when might they add noise or cost?

This lab uses the **Image And NLP Enrichment** skill profile, selected per upload from the UI.

## Step 1 - Start the app

Launch through the helper script if it is not already running:

```powershell
.\scripts\run-local-app.ps1 -Port 8016
```

## Step 2 - Confirm the profile is available

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `visual_nlp` appears in the `profiles` list
- its target enrichment index name ends with `-visual-nlp`

## Step 3 - Upload the same document again

Use the same diagram-heavy file. On the upload screen, set the **Skill Profile** picker to **Image And NLP Enrichment** before submitting.

## Step 4 - Use `Hybrid` retrieval mode

This lab keeps the retrieval mode fixed on `Hybrid` first, then compares with `Agentic`, so the audience can isolate the effect of the new skills.

> **Where each visual/NLP signal lands.** The three skills run inside the Blob skillset. `OcrSkill` and `ImageAnalysisSkill` run at the per-image context (`/document/normalized_images/*`), so their outputs land *under that path* - the indexer output field mappings read `/document/normalized_images/*/...`, and because `description` is a complex `{tags, captions}` object the mapping drills into `captions/*/text` for the human-readable caption sentences. These populate the **Search-managed enrichment index** (`...-visual-nlp`), which **Agentic** retrieval can draw on. The app then merges a **document-level `image_description_text`** (the first several captions) back onto every **canonical chunk**, so `Full text` / `Vector` / `Hybrid` also gain a visual signal. The parser additionally attaches **figure thumbnails** (`image_evidence`) to the chunks on a figure's page so the UI shows grounded visuals. Those thumbnails come from **rendering each page and cropping the figure region** rather than pulling the raw embedded image: engineering PDFs often draw figures as 1-bit image masks / soft-masked (SMask) stencils whose paint colour lives in the page content stream, so the raw bitmap is solid black - rendering composites them faithfully, and the same path also captures **vector-drawn charts** (analyst decks) that carry no embedded image at all. **Caption quality is document-dependent:** Image Analysis 3.2 returns descriptive but generic captions ("a construction site with cranes and buildings", "engineering drawing") and OCR on vector-drawn diagrams yields fragmentary text ("17 07 2017"). The lesson is to *verify what actually landed* (the chunk metrics and enrichment fields) rather than assume.

## Step 5 - Ask image-aware comparison prompts

- `What does the diagram say, and what extra evidence became searchable after OCR and image analysis were added?`
- `Which visual signals help the answer now that the visual profile is active?`
- `Which entity, label, or caption from the figure is most important to the workflow described here?`

## Step 6 - Explain what changed

Compared with Lab 05, this profile now adds:

- OCR output from normalized images
- image descriptions from the image analysis skill
- detected language metadata

This is the lab where you show why purely textual extraction misses important visual evidence.

## Step 7 - Extension discussion

Once this lab works, discuss these next extensions:

- `EntityRecognitionSkillV3`
- `MergeSkill`
- `ShaperSkill`

Keep them out of the base workshop until the audience has seen the core visual/NLP improvement clearly.

## Success Criteria

- the document reaches `ready`
- the enrichment index recorded in the job ends with `-visual-nlp`
- `LanguageDetectionSkill` records a detected language (e.g. `en`) and the parser attaches figure thumbnails (`image_evidence`) to figure-bearing chunks
- `OcrSkill` and `ImageAnalysisSkill` produce real text: the `-visual-nlp` enrichment index holds the per-image caption and OCR collections, and `chunks_with_image_description` is **non-zero** because the merged document-level `image_description_text` lands on every canonical chunk
- you can explain the result honestly: captions are descriptive but generic and OCR on vector diagrams is fragmentary, so judge the *quality* of the signal, not just its presence

## Code Walkthrough

This profile adds the visual and language-oriented Search skills:

```python
# backend/services/workshop_profiles.py
WorkshopSkillProfile(
    id="visual_nlp",
    added_skills=(
        "OCRSkill",
        "ImageAnalysisSkill",
        "LanguageDetectionSkill",
    ),
    recommended_retrieval_modes=("hybrid", "agentic"),
)
```

- This is the best lab for documents with diagrams, scanned pages, screenshots, or mixed-language content.
- The value is easiest to see on the same document used in earlier labs.

These are the actual built-in skills added by the Search skillset, with the output mappings that make their results retrievable:

```python
# backend/services/search_skillset_enrichment.py
def _build_ocr_skill(self) -> dict[str, Any]:
    return {
        "@odata.type": "#Microsoft.Skills.Vision.OcrSkill",
        "context": "/document/normalized_images/*",
        "outputs": [{"name": "text", "targetName": "ocr_text_chunks"}],
    }

def _build_image_analysis_skill(self) -> dict[str, Any]:
    return {
        "@odata.type": "#Microsoft.Skills.Vision.ImageAnalysisSkill",
        "context": "/document/normalized_images/*",
        "visualFeatures": ["tags", "description"],
        # description is a complex {tags, captions} object
        "outputs": [{"name": "description", "targetName": "image_analysis"}],
    }

# Indexer output field mappings read the per-image nodes and drill into caption text:
#   /document/normalized_images/*/ocr_text_chunks                -> ocr_text_chunks
#   /document/normalized_images/*/image_analysis/captions/*/text -> image_description_chunks
```

- `OcrSkill` extracts raster text from normalized images into `ocr_text_chunks`.
- `ImageAnalysisSkill` emits a complex `description` object; the mapping drills into `captions/*/text` so the caption sentences become `image_description_chunks`.
- `LanguageDetectionSkill` runs at `/document` context and records the detected language.
- Getting the **mapping paths** right is the whole game: a skill at `/document/normalized_images/*` context writes its output *under that path*, so a mapping that reads `/document/<output>` silently captures nothing.

One useful comparison in this lab is parser-side figure handling versus Search-side visual enrichment:

```python
# backend/services/pipeline.py
figure_artifacts = intermediate.metadata.get("figure_artifacts") or []
scoped_pages = sorted({page for page in chunk.page_numbers if isinstance(page, int) and page > 0})
if scoped_pages and len(scoped_pages) <= MAX_DIRECT_CHUNK_IMAGE_PAGE_SPAN:
    ...
    chunk.image_evidence = related_figures[:4]
```

- The parser extracts figure artifacts from the source document.
- The Search skillset separately adds OCR and image-description signals.
- This lab is about showing that those are complementary, not duplicate, stages.

> **How the parser captures faithful figures.** Figure thumbnails are produced by **rendering each PDF page and cropping the figure region** (`_extract_pdf_figures_rendered` in [backend/services/parsers.py](../../backend/services/parsers.py)), not by pulling the raw embedded image. Engineering PDFs frequently draw figures as 1-bit image masks or soft-masked (SMask) stencils whose paint colour lives in the page content stream, so the raw XObject is a solid-black bitmap; rendering composites the page faithfully. The same render path has a vector fallback that clusters native chart geometry, so **vector-drawn charts** in analyst decks (which carry no embedded image at all) are still captured as thumbnails.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `visual_nlp` |
| `ENABLE_PARSER_FIGURE_EXTRACTION` | Turns on parser-side figure extraction for a side-by-side comparison with Search-side visual skills. | Set `true` if you want chunk-linked figure artifacts in the portal. |
| `ENABLE_IMAGE_UNDERSTANDING` | Optional per-figure Foundry vision captions for citation thumbnails. Image descriptions for retrieval already come from the Search `ImageAnalysisSkill` (mapped via `captions/*/text`), so this is a separate, richer lane that is off by default to avoid Prompt-Shields throttling during burst ingestion. | Leave `false`; set `true` only if you want per-figure Foundry caption metadata on top of the built-in signal, and accept occasional content-filter retries. |
| `PARSER_FIGURE_MAX_ARTIFACTS` | Caps how many figure artifacts the parser will process from one PDF. | Lower it for very large handbooks so the lab finishes faster. |
| `MAX_FIGURE_IMAGE_PIXELS` | Guards oversized extracted images. | Lower it if you want to demonstrate safety limits. |
| `MAX_FIGURE_IMAGE_DIMENSION` | Caps large figure dimensions. | Lower it if image-heavy PDFs are causing trouble. |
| `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS` | Makes OCR and image-analysis failures visible. | Keep `true` in workshops. |

## Best-Practice Takeaways

- do not assume text extraction alone is enough for figure-heavy documents
- OCR, image analysis, and parser-side figure extraction solve different but complementary problems
- keep image evidence page-scoped and grounded so the UI does not show irrelevant visuals
- add visual skills when the document type justifies them, not by default for every corpus

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the `visual_nlp` profile.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for OCR, image analysis, and language detection.
- [`backend/services/parsers.py`](../../backend/services/parsers.py) for parser-side figure extraction.
- [`backend/services/chat.py`](../../backend/services/chat.py) for how image evidence is surfaced to the UI.

## Learn References

- [OCR skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-ocr)
- [Image Analysis skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-image-analysis)
- [Language Detection skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-language-detection)
- [Extract text from images with AI enrichment](https://learn.microsoft.com/en-us/azure/search/cognitive-search-concept-image-scenarios)
