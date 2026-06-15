# Lab 06 - Visual And NLP Enrichment

## Goal

Add visual and language-oriented skills to the same document, and switch the
Search-managed extractor to the **Document Layout** skill so figure cropping and
OCR happen *server-side and figure-aware*:

- `DocumentIntelligenceLayoutSkill` (figure-aware crops + page / bounding-polygon location metadata)
- `OcrSkill`
- `ImageAnalysisSkill`
- `LanguageDetectionSkill`

Then compare how `Hybrid` retrieval changes for diagram-heavy or image-heavy questions,
and contrast the **server-side** figure pipeline with the **offline parser** figure pipeline.

## Questions This Lab Answers

- What is the difference between OCR, image analysis, and figure extraction?
- How does the **Document Layout** skill differ from the default **Document Extraction** skill, and why does that change OCR quality?
- Where do the figure crops and their page / bounding-polygon coordinates land?
- How do the server-side (knowledge-store) and offline (parser) figure paths complement each other?
- When should I add these skills in production, and when might they add noise or cost?

This lab uses the **Image And NLP Enrichment** skill profile, selected per upload from the UI,
with `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_layout`.

## Two Ways To Crop A Figure

This lab runs two figure pipelines side by side. They are **complementary**, not duplicate:

| | **Document Layout skill** (server-side) | **Offline parser** (local) |
| --- | --- | --- |
| Where it runs | Inside the Azure AI Search skillset, on the billable Foundry resource | In the app process, while parsing the upload |
| How it finds figures | Document Intelligence layout model detects figure regions | Renders each PDF page and crops figure regions; vector fallback clusters chart geometry |
| What it emits | Figure **crops** under `/document/normalized_images/*` + per-figure `pageNumber` & `boundingPolygons` | Page-rendered figure **thumbnails** attached to the chunks on a figure's page |
| Where it lands | Knowledge-store projections: crops -> `search-image-assets`, metadata -> `search-image-assets-meta` | `image_evidence` on canonical chunks, served to the citation UI |
| OCR / captions run on | The **figure crops** (dense, figure-scoped text) | n/a (thumbnails are display-only) |

The big change versus the default extractor: with **Document Extraction** the indexer's built-in
image cracker emits **whole-page** normalized images, so OCR and Image Analysis run on entire pages
and mostly capture page noise. With **Document Layout** the skill emits **figure-scoped** crops, so the
same OCR and Image Analysis skills now describe and read *the figure itself*.

## Step 1 - Start the app

Launch through the helper script if it is not already running:

```powershell
.\scripts\run-local-app.ps1 -Port 8016
```

## Step 2 - Confirm the extractor and profile

1. Confirm `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_layout` is set (see `.env`).
2. Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:
   - `visual_nlp` appears in the `profiles` list
   - its target enrichment index name ends with `-visual-nlp`

> The Document Layout skill is **resource-attached**: it binds to the billable Foundry / AI Services
> resource declared in the skillset's `cognitiveServices` block (managed identity, no key in the skill
> body). If no Foundry resource is attached, strict mode raises rather than silently falling back.

## Step 3 - Upload the same document again

Use the same diagram-heavy file. On the upload screen, set the **Skill Profile** picker to
**Image And NLP Enrichment** before submitting.

## Step 4 - Use `Hybrid` retrieval mode

This lab keeps the retrieval mode fixed on `Hybrid` first, then compares with `Agentic`, so the
audience can isolate the effect of the new skills.

> **Where each visual/NLP signal lands.** The Document Layout skill runs at `/document` context and
> emits two outputs: chunked `dl_text_sections` (merged into `/document/content_markdown` by a
> `MergeSkill` so the rest of the graph is identical for every profile) and `normalized_images` -
> the **figure crops**. Because the crops are published under `/document/normalized_images/*`,
> `OcrSkill` and `ImageAnalysisSkill` (both at the per-image context `/document/normalized_images/*`)
> now run on *the figure crops* instead of whole pages. Their outputs feed the indexer output field
> mappings (`ocr_text_chunks`, and `image_analysis/captions/*/text` -> `image_description_chunks`),
> which populate the **Search-managed enrichment index** (`...-visual-nlp`) that **Agentic** retrieval
> can draw on. The app still merges a **document-level `image_description_text`** back onto every
> **canonical chunk**, so `Full text` / `Vector` / `Hybrid` also gain a visual signal. Separately, the
> skillset's **knowledge-store projections** persist each crop to `search-image-assets` and its
> `pageNumber` + `boundingPolygons` location metadata to `search-image-assets-meta`, so figures can be
> served back as grounded citation evidence (the Azure-native equivalent of the offline parser's local
> figure PNGs). Because the indexer's built-in image cracker is turned **off** (`imageAction: none`)
> when Document Layout is active, there are no duplicate whole-page images. **Caption quality is still
> document-dependent:** Image Analysis 3.2 returns descriptive but generic captions ("chart",
> "diagram", "a diagram of a house"), while OCR is now *much* richer because it reads figure-scoped
> crops. The lesson is to *verify what actually landed* (the chunk metrics and enrichment fields)
> rather than assume.

## Step 5 - Ask image-aware comparison prompts

- `What does the diagram say, and what extra evidence became searchable after OCR and image analysis were added?`
- `Which visual signals help the answer now that the visual profile is active?`
- `Which entity, label, or caption from the figure is most important to the workflow described here?`

## Step 6 - Explain what changed

Compared with Lab 05, this profile now adds:

- a **Document Layout** extractor that crops figures server-side and records each figure's page and bounding polygon
- OCR output from the **figure crops** (not whole pages)
- image descriptions from the image analysis skill
- detected language metadata
- knowledge-store projections that persist figure crops + location metadata to blob

This is the lab where you show why purely textual extraction misses important visual evidence -
**and** why figure-aware cropping makes the visual evidence dramatically cleaner.

### What actually landed (a real run)

On the deep-excavation engineering PDF, switching from Document Extraction to Document Layout produced
a measurable quality jump:

| | Document Extraction (whole-page) | Document Layout (figure-aware) |
| --- | --- | --- |
| Normalized images | 213 whole-page renders | 68 figure-scoped crops |
| Non-empty OCR results | 12 (mostly noise: "89 -", "17 07 2017") | 63 (real labels: piezometer / standpipe mPD readings, sheet-pile interlock & waling details) |
| Per-figure location metadata | none | 71 projections, each with `pageNumber` + `boundingPolygons` |

Captions stayed generic in both runs (Image Analysis 3.2), so the win is concentrated in **OCR
density and figure scoping**, plus the new **location metadata** that lets you cite a figure by page
and region.

## Step 7 - Extension discussion

Once this lab works, discuss these next extensions:

- `EntityRecognitionSkillV3`
- `ShaperSkill` to compose a richer per-figure object for projections
- mapping the bounding-polygon metadata into a queryable index field

Keep them out of the base workshop until the audience has seen the core visual/NLP improvement clearly.

## Success Criteria

- the document reaches `ready`
- the enrichment index recorded in the job ends with `-visual-nlp`
- the active extractor is `document_layout` (the indexer runs with `imageAction: none`)
- `LanguageDetectionSkill` records a detected language (e.g. `en`)
- the knowledge store is populated: figure crops appear in `search-image-assets` and one
  location-metadata object per crop (with `pageNumber` + `boundingPolygons`) appears in
  `search-image-assets-meta`
- `OcrSkill` and `ImageAnalysisSkill` produce real text: the `-visual-nlp` enrichment index holds the
  per-image caption and OCR collections, and `chunks_with_image_description` is **non-zero** because the
  merged document-level `image_description_text` lands on every canonical chunk
- you can explain the result honestly: captions are descriptive but generic, while OCR is now much
  richer because it runs on figure-scoped crops - judge the *quality* of the signal, not just its presence

## Code Walkthrough

This profile adds the visual and language-oriented Search skills, and selects the Document Layout
extractor:

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

The extractor is chosen by `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR`. With `document_layout`, the
skillset emits the resource-attached Document Layout skill and a merge step:

```python
# backend/services/search_skillset_enrichment.py
def _build_extractor_skill(self, *, extractor_kind=None):
    ...
    if active_extractor == "document_layout":
        return {
            "@odata.type": "#Microsoft.Skills.Util.DocumentIntelligenceLayoutSkill",
            "name": "#documentLayout",
            "context": "/document",
            "outputMode": "oneToMany",
            "outputFormat": "text",
            "extractionOptions": ["images", "locationMetadata"],
            "chunkingProperties": {"unit": "characters", "maximumLength": 2000, "overlapLength": 200},
            "inputs": [{"name": "file_data", "source": "/document/file_data"}],
            "outputs": [
                {"name": "text_sections", "targetName": "dl_text_sections"},
                {"name": "normalized_images", "targetName": "normalized_images"},
            ],
        }
```

- `extractionOptions: ["images", "locationMetadata"]` is what makes the skill crop figures and emit
  their `pageNumber` + `boundingPolygons`.
- The crops are published under `/document/normalized_images/*`, exactly where `OcrSkill` and
  `ImageAnalysisSkill` read - so those skills now run on figures, not whole pages.

These are the visual/NLP skills added by the skillset, with the output mappings that make their
results retrievable:

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

- `OcrSkill` extracts text from each normalized image into `ocr_text_chunks`. With Document Layout
  those images are figure crops, so the OCR is figure-scoped and dense.
- `ImageAnalysisSkill` emits a complex `description` object; the mapping drills into `captions/*/text`
  so the caption sentences become `image_description_chunks`.
- `LanguageDetectionSkill` runs at `/document` context and records the detected language.
- Getting the **mapping paths** right is the whole game: a skill at `/document/normalized_images/*`
  context writes its output *under that path*, so a mapping that reads `/document/<output>` silently
  captures nothing.

The crops and their location metadata are persisted by a **knowledge store** on the skillset, and the
indexer's built-in cracker is disabled so it does not produce duplicate whole-page images:

```python
# backend/services/search_skillset_enrichment.py
def _build_figure_knowledge_store(self, *, extractor_kind, include_visual_text=False):
    if extractor_kind != "document_layout" or not settings.azure_search_enable_image_serving:
        return None
    projections = [
        {"files":   [{"storageContainer": settings.azure_search_asset_store_container,          "source": "/document/normalized_images/*"}]},
        {"objects": [{"storageContainer": settings.azure_search_asset_store_metadata_container, "source": "/document/normalized_images/*"}]},
    ]
    if include_visual_text and settings.azure_search_asset_store_text_container:
        # Inline-shaped object projection: capture each figure's OCR text + caption (chart
        # numbers, axis labels) so it can travel with chunks. The base object projection
        # above only serializes the image node, NOT the enriched OCR/caption siblings.
        projections.append({"objects": [{
            "storageContainer": settings.azure_search_asset_store_text_container,
            "source": None,
            "sourceContext": "/document/normalized_images/*",
            "inputs": [
                {"name": "pageNumber", "source": "/document/normalized_images/*/locationMetadata/pageNumber"},
                {"name": "ocrText",    "source": "/document/normalized_images/*/ocr_text_chunks"},
                {"name": "caption",    "source": "/document/normalized_images/*/image_analysis/captions/*/text"},
            ],
        }]})
    return {"storageConnectionString": self._figure_knowledge_store_connection_string(), "projections": projections}

# _build_indexer_body(...) parameters.configuration:
#   "imageAction": "none" if extractor_kind == "document_layout" else "generateNormalizedImages"
```

- The **file** projection writes each crop to `search-image-assets`.
- The **object** projection writes each crop's metadata - including `pageNumber` and
  `boundingPolygons` - to `search-image-assets-meta`.
- The **inline-shaped object** projection (visual-NLP profile only) writes each figure's OCR text +
  caption to `search-image-assets-text`. This is the key to making **figure content travel with the
  chunk**: the base object projection serializes only the image node (path + page), *not* the enriched
  `ocr_text_chunks` / `image_analysis` siblings, so without this dedicated projection the chart text
  never leaves the enrichment index. Object projections cannot share a container, hence the separate
  text container.
- `imageAction: none` keeps the indexer from emitting whole-page images that would duplicate the
  Document Layout crops.

One useful comparison in this lab is **server-side** figure handling versus the **offline parser**:

```python
# backend/services/pipeline.py
figure_artifacts = intermediate.metadata.get("figure_artifacts") or []
scoped_pages = sorted({page for page in chunk.page_numbers if isinstance(page, int) and page > 0})
if scoped_pages and len(scoped_pages) <= MAX_DIRECT_CHUNK_IMAGE_PAGE_SPAN:
    ...
    chunk.image_evidence = related_figures[:4]
```

- The Document Layout skill crops figures **server-side** and persists them (plus location metadata)
  to the knowledge store.
- The offline parser separately renders pages and attaches figure thumbnails to chunks for the
  **citation UI**.
- This lab is about showing that those are complementary, not duplicate, stages: one produces
  retrievable + location-aware figure evidence in Azure, the other produces page-grounded thumbnails
  for display.

> **How the offline parser captures faithful figures.** Figure thumbnails are produced by **rendering
> each PDF page and cropping the figure region** (`_extract_pdf_figures_rendered` in
> [backend/services/parsers.py](../../backend/services/parsers.py)), not by pulling the raw embedded
> image. Engineering PDFs frequently draw figures as 1-bit image masks or soft-masked (SMask) stencils
> whose paint colour lives in the page content stream, so the raw XObject is a solid-black bitmap;
> rendering composites the page faithfully. The same render path has a vector fallback that clusters
> native chart geometry, so **vector-drawn charts** in analyst decks (which carry no embedded image at
> all) are still captured as thumbnails. The Document Layout skill solves the same problem on the
> server side via the Document Intelligence layout model.

### How figure crops become citation evidence at query time

Persisting crops to the knowledge store is only half the story. At **query time** the app joins those
crops back onto whatever citations retrieval returned, matched by page number, so figures appear as
grounded evidence in **every** retrieval mode - `Full text`, `Vector`, `Hybrid`, **and** `Agentic`.
The offline parser's `image_evidence` is empty when the native multimodal path is active, so this
join is what surfaces figures in the citation UI.

First, the object-projection metadata is read once (and cached for a short TTL) into a
`{doc_id: {page_number: [crop_path, ...]}}` map. Crucially, it cross-checks the crop container so a
metadata record that points at a crop which was never persisted is dropped - otherwise the UI would
request a crop URL that 404s into a broken image:

```python
# backend/services/chat.py - _build_native_figure_page_map (abridged)
servable_crops = set(crop_store.list_blobs())          # only crops that actually exist as blobs
...
image_path = str(doc.get("imagePath") or doc.get("name"))
if servable_crops is not None and image_path not in servable_crops:
    continue                                           # drop dangling reference (would 404)
page = int(doc["locationMetadata"]["pageNumber"])
figure_map.setdefault(doc_id, {}).setdefault(page, []).append(image_path)
```

Then `_hydrate_citations` attaches up to `MAX_IMAGE_EVIDENCE_PER_CITATION` crops to each citation that
lacks its own image evidence, matched on the citation's pages. This is a single shared chokepoint that
runs for hybrid, vector, full-text, and agentic citations alike:

```python
# backend/services/chat.py - _hydrate_citations (abridged)
if not citation.asset_image_paths and citation.doc_id and citation.page_numbers:
    doc_figures = native_figure_map.get(citation.doc_id)
    if doc_figures:
        native_paths = []
        for page in citation.page_numbers:
            for path in doc_figures.get(page, []):
                native_paths.append(path)
                if len(native_paths) >= MAX_IMAGE_EVIDENCE_PER_CITATION:
                    break
        citation.asset_image_paths = native_paths
```

- Because the join keys on `doc_id` + `page_numbers`, **Agentic** retrieval - which plans subqueries
  and returns its own citations - gets the same figure evidence as direct search; there is no
  agentic-specific image path to maintain.
- The crop-existence filter is why you no longer see broken-image placeholders: a figure whose crop
  blob is missing is simply not offered to the UI.
- The frontend renders a citation's `asset_image_paths` through `/api/native-images`, and an
  `onerror` handler removes any image that still fails, so a stray miss degrades to "no card" rather
  than a broken icon.

### How figure *text* travels with the chunk (chart-aware answers)

Surfacing the crop image is useful for a human reader, but the **answer model** cannot read pixels in
the direct-search lanes - it only sees the citation's text snippet. So a chart whose key numbers live
inside the image ("Adoption rose to 65% in 2024") would not be reflected in the answer even though the
figure is cited. The fix is to make the figure's **extracted text** ride along with the chunk.

This has two halves:

1. **Capture (ingestion side).** The inline-shaped object projection above persists each figure's
   `ocrText` (chart numbers, axis labels, callouts) and `caption` to `search-image-assets-text`, keyed
   by `pageNumber`. This only runs for the visual-NLP profile, because OCR + Image Analysis are what
   produce that text in the first place.
2. **Join (query side).** A second cached map - `{doc_id: {page_number: [figure_text, ...]}}` - is
   built from that container, and `_hydrate_citations` splices the matching figure text onto the
   citation's snippet by page:

```python
# backend/services/chat.py - _hydrate_citations (abridged)
if citation.doc_id and citation.page_numbers and native_figure_text_map:
    doc_texts = native_figure_text_map.get(citation.doc_id)
    figure_fragments = [t for page in citation.page_numbers for t in doc_texts.get(page, [])
                        if t.lower() not in _snippet_fingerprint(citation.snippet)]   # skip echoes
    if figure_fragments:
        addendum = " ".join(figure_fragments)[:MAX_FIGURE_TEXT_PER_CITATION_CHARS]
        citation.snippet = f"{citation.snippet.rstrip()}\n\n[Figure text] {addendum}"
```

- Because the snippet is the single source both the deterministic direct-search answer
  (`_build_direct_search_answer`) and the app-side LLM prompt (`_format_sources_for_prompt`) read,
  this one injection makes **every** retrieval mode chart-aware - not just the agentic lane, which
  already had figure OCR inside its in-Search enrichment index.
- A bounded length (`MAX_FIGURE_TEXT_PER_CITATION_CHARS`) and an "already in the surrounding passage"
  guard keep the addendum from drowning or echoing the prose the chunk already carries.

> **This capture takes effect on the next ingestion.** The text projection only writes blobs when the
> indexer next runs against the visual-NLP profile. Until then the query-side join is a safe no-op
> (the container is empty), so nothing regresses on previously indexed corpora - the chart text simply
> lights up automatically once documents are re-ingested.

## Configuration Knobs

| Variable | What it controls | Good workshop variation |
| --- | --- | --- |
| `WORKSHOP_SKILL_PROFILE` | Activates this profile. | `visual_nlp` |
| `AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR` | Chooses the Search-managed extractor: `document_extraction` (default, whole-page images), `document_layout` (figure-aware crops + location metadata), or `content_understanding`. | `document_layout` for this lab. |
| `AZURE_SEARCH_ASSET_STORE_CONTAINER` | Blob container for the figure crops (file projection). | `search-image-assets` |
| `AZURE_SEARCH_ASSET_STORE_METADATA_CONTAINER` | Blob container for the per-figure location metadata (object projection). | `search-image-assets-meta` |
| `AZURE_SEARCH_ASSET_STORE_TEXT_CONTAINER` | Blob container for the per-figure OCR + caption text (inline-shaped object projection) that gets joined onto citations by page so answers reflect chart content. | `search-image-assets-text` |
| `AZURE_SEARCH_ENABLE_IMAGE_SERVING` | Gates the knowledge-store projection + the `/api/native-images` serving endpoint. | Keep `true` to see crops in the UI. |
| `ENABLE_PARSER_FIGURE_EXTRACTION` | Turns on the offline parser figure path for a side-by-side comparison with the server-side crops. | Set `true` if you want chunk-linked figure thumbnails in the portal. |
| `ENABLE_IMAGE_UNDERSTANDING` | Optional per-figure Foundry vision captions for citation thumbnails. Image descriptions for retrieval already come from the Search `ImageAnalysisSkill`, so this is a separate, richer lane that is off by default to avoid Prompt-Shields throttling during burst ingestion. | Leave `false`; set `true` only if you want per-figure Foundry caption metadata on top of the built-in signal. |
| `AZURE_SEARCH_REQUIRE_BLOB_SKILLSET_SUCCESS` | Makes OCR and image-analysis failures visible. | Keep `true` in workshops. |

## Best-Practice Takeaways

- do not assume text extraction alone is enough for figure-heavy documents
- figure-aware cropping (Document Layout) makes OCR and image analysis dramatically more useful than whole-page cracking
- the server-side knowledge-store projections and the offline parser thumbnails solve different but complementary problems
- keep image evidence page-scoped and grounded so the UI does not show irrelevant visuals
- add visual skills when the document type justifies them, not by default for every corpus

## Files To Inspect

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py) for the `visual_nlp` profile.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py) for the Document Layout extractor, OCR, image analysis, language detection, and the knowledge-store projections.
- [`backend/services/parsers.py`](../../backend/services/parsers.py) for the offline parser figure path.
- [`backend/services/chat.py`](../../backend/services/chat.py) for how image evidence is surfaced to the UI.
- [`backend/app.py`](../../backend/app.py) for `/api/native-images`, which serves the projected figure crops.

## Learn References

- [Document Layout skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-document-intelligence-layout)
- [OCR skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-ocr)
- [Image Analysis skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-image-analysis)
- [Language Detection skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-language-detection)
- [Knowledge store](https://learn.microsoft.com/en-us/azure/search/knowledge-store-concept-intro)
- [Extract text from images with AI enrichment](https://learn.microsoft.com/en-us/azure/search/cognitive-search-concept-image-scenarios)
