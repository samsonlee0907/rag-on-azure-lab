"""Build all lab walkthrough notebooks with nbformat.

Writing the .ipynb files from a plain Python script (run in the terminal) avoids
the editor's notebook-create handling, which was emptying cell sources. Run:

    python notebooks/_build_notebooks.py

Then execute them with nbconvert.
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parent

SETUP = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "NB_DIR = Path.cwd()\n"
    "sys.path.insert(0, str(NB_DIR if (NB_DIR / 'lab_runtime.py').exists() else NB_DIR / 'notebooks'))\n"
    "import lab_runtime as lab\n"
    "\n"
    "info = lab.bootstrap()\n"
    "info"
)

Q1 = "What are the objectives of site investigation for ELS works?"
Q2 = "Given a site with high groundwater and clay layers, what are the key excavation risks and design considerations?"
Q_VISUAL = "What do the figures on ground settlement and wall deflection show, and what visual evidence supports the answer?"


def md(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(text)


def code(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(text)


def write(name: str, cells: list[nbf.NotebookNode]) -> None:
    nb = nbf.v4.new_notebook()
    nb.cells = cells
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    path = NB_DIR / name
    nbf.write(nb, path)
    print(f"wrote {path.name} ({len(cells)} cells)")


# --------------------------------------------------------------------------- #
# Lab 03 - Baseline extraction
# --------------------------------------------------------------------------- #

def build_lab03() -> None:
    cells = [
        md(
            "# Lab 03 \u00b7 Baseline Extraction (Notebook Walkthrough)\n\n"
            "This notebook runs the **same pipeline the web UI runs**, in-process, so you can watch ingestion happen, "
            "inspect the chunks it produces, and query the index \u2014 all with captured outputs.\n\n"
            "**Concept.** The `baseline_extract` profile uses only Azure AI Search's built-in `DocumentExtractionSkill`. "
            "No semantic chunking tuning, no generative enrichment, no visual/NLP analysis yet. This is the starting "
            "retrieval quality every later lab improves on.\n\n"
            "Source document for the whole run-through: **Deep Excavation Design and Construction.pdf**."
        ),
        md("## Step 1 \u2014 Bootstrap the backend\n\n`bootstrap()` loads the gitignored `.env`, puts the repo on `sys.path`, and confirms the live Azure configuration."),
        code(SETUP),
        md(
            "## Step 2 \u2014 Ingest with the baseline profile\n\n"
            "Full pipeline: **parse \u2192 normalize \u2192 chunk \u2192 Azure AI Search blob + skillset enrichment \u2192 publish**. "
            "The first run drives the real Azure indexer (a few minutes); re-runs reuse the cached result."
        ),
        code("job = lab.ingest(skill_profile='baseline_extract', reuse=True)\nlab.chunk_overview(job)"),
        md("`chunks_with_summary`, `chunks_with_keyword_hints`, and `chunks_with_image_description` are all **0** \u2014 baseline extraction produces plain text chunks with no enrichment."),
        md("## Step 3 \u2014 Inspect the raw chunks"),
        code(
            "import pandas as pd\n\n"
            "chunks = lab.load_chunks(job)\n"
            "pd.DataFrame([\n"
            "    {\n"
            "        'section': ' > '.join(c.get('section_path') or []) or '(root)',\n"
            "        'pages': c.get('page_numbers'),\n"
            "        'tokens': c.get('token_estimate'),\n"
            "        'text_preview': (c.get('clean_text') or '')[:120].replace(chr(10), ' '),\n"
            "    }\n"
            "    for c in chunks[:8]\n"
            "])"
        ),
        md("## Step 4 \u2014 Query with Full-Text retrieval\n\nFull-text (BM25) shines when the answer is **explicitly stated** and keyword-heavy."),
        code(
            f"Q1 = {Q1!r}\n\n"
            "resp = lab.ask(Q1, job=job, retrieval_mode='full_text', record_as='lab03_baseline_fulltext')\n"
            "lab.show_answer(resp)"
        ),
        md("### Inspect the raw scored hits\n\nThe actual Azure AI Search `@search.score` ordering that produced the answer:"),
        code("hits = lab.retrieve(Q1, job=job, retrieval_mode='full_text', top=5)\nlab.hits_table(hits)"),
        md(
            "## Takeaways\n\n"
            "- Baseline extraction gives **searchable text and structure** but no enrichment fields.\n"
            "- Full-text retrieval already answers precise, terminology-heavy questions well because question wording matches document wording.\n"
            "- Later labs ask the **same** question against richer indexes so you can see what enrichment adds.\n\n"
            "Next: **Lab 04** adds chunking + vectorization, unlocking `vector` and `hybrid` retrieval and scoring profiles."
        ),
    ]
    write("lab-03-baseline-extraction.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 04 - Chunking and vectorization (+ scoring profiles)
# --------------------------------------------------------------------------- #

def build_lab04() -> None:
    cells = [
        md(
            "# Lab 04 \u00b7 Chunking and Vectorization (Notebook Walkthrough)\n\n"
            "**Concept.** The `chunk_vector` profile adds the built-in `SplitSkill` and `AzureOpenAIEmbeddingSkill`. "
            "Every chunk now carries a 3072-dim `content_vector`, which unlocks **vector** and **hybrid** retrieval in "
            "addition to **full-text**. This lab also shows **scoring profiles** \u2014 query-time relevance tuning over the BM25 score.\n\n"
            "We ask the **same questions** as the other labs so differences are attributable to the index, not the prompt."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Ingest with the chunk + vector profile"),
        code("job = lab.ingest(skill_profile='chunk_vector', reuse=True)\nlab.chunk_overview(job)"),
        md("## Step 3 \u2014 Confirm vectors are present\n\nVector / hybrid retrieval requires an embedding per chunk. Check that the published chunks were embedded."),
        code(
            "from backend.services.indexing import build_foundry_adapter\n"
            "adapter = build_foundry_adapter()\n"
            "print('vector search available:', adapter._vector_search_available())"
        ),
        md(
            "## Step 4 \u2014 Compare retrieval modes on the SAME question\n\n"
            "Q1 is precise/keyword-heavy (favours full-text). Q2 is conceptual/multi-hop (favours vector + hybrid)."
        ),
        code(
            f"Q1 = {Q1!r}\n"
            f"Q2 = {Q2!r}\n\n"
            "for mode in ['full_text', 'vector', 'hybrid']:\n"
            "    print('=' * 80)\n"
            "    print('MODE:', mode, '| Q2 (conceptual)')\n"
            "    resp = lab.ask(Q2, job=job, retrieval_mode=mode, record_as=f'lab04_chunkvector_{mode}')\n"
            "    lab.show_answer(resp, max_citations=4)\n"
            "    print()"
        ),
        md("### Side-by-side top hits (Q2)\n\nLook at how the ordering and the winning section change between lexical, semantic, and fused retrieval."),
        code(
            "import pandas as pd\n\n"
            "rows = []\n"
            "for mode in ['full_text', 'vector', 'hybrid']:\n"
            "    for rank, hit in enumerate(lab.retrieve(Q2, job=job, retrieval_mode=mode, top=3), start=1):\n"
            "        rows.append({'mode': mode, 'rank': rank, 'score': hit['score'], 'section': hit['section'], 'pages': hit['pages']})\n"
            "pd.DataFrame(rows)"
        ),
        md(
            "## Step 5 \u2014 Scoring profiles\n\n"
            "Scoring profiles re-weight the BM25 score before fusion/semantic ranking. They apply to **full-text** and "
            "**hybrid** (not pure vector). Compare the default profile against `enrichment-weighted` (field boosts) on Q1."
        ),
        code(
            "import pandas as pd\n\n"
            "rows = []\n"
            "for profile in ['default', 'enrichment-weighted', 'freshness-boosted']:\n"
            "    for rank, hit in enumerate(lab.retrieve(Q1, job=job, retrieval_mode='full_text', scoring_profile=profile, top=3), start=1):\n"
            "        rows.append({'scoring_profile': profile, 'rank': rank, 'score': hit['score'], 'section': hit['section']})\n"
            "pd.DataFrame(rows)"
        ),
        md(
            "> On the baseline corpus the enrichment fields (`summary_text`, `keyword_hints`) are empty, so "
            "`enrichment-weighted` mostly affects results once Lab 05 enrichment is present. `freshness-boosted` uses "
            "the indexer `last_updated` high-water mark. The mechanism is identical; the visible effect grows as the "
            "index gets richer."
        ),
        md(
            "## Takeaways\n\n"
            "- Chunking + embeddings unlock **vector** and **hybrid** retrieval over the same document.\n"
            "- Conceptual/paraphrased questions (Q2) benefit most from vector and hybrid; precise lookups (Q1) stay strong on full-text.\n"
            "- **Scoring profiles** give you query-time relevance control that is complementary to the semantic ranker.\n\n"
            "Next: **Lab 05** adds generative enrichment (summaries + keyword hints) during indexing."
        ),
    ]
    write("lab-04-chunking-and-vectorization.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 05 - Generative enrichment
# --------------------------------------------------------------------------- #

def build_lab05() -> None:
    cells = [
        md(
            "# Lab 05 \u00b7 Generative Enrichment (Notebook Walkthrough)\n\n"
            "**Concept.** The `genai_enrichment` profile adds a `ChatCompletionSkill` during indexing, so each document "
            "gets **summaries** and **keyword hints** generated at ingestion time. These become first-class retrieval "
            "cues that help both hybrid search and agentic planning."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Ingest with generative enrichment"),
        code("job = lab.ingest(skill_profile='genai_enrichment', reuse=True)\nlab.chunk_overview(job)"),
        md("Compared with Labs 03\u201304, `chunks_with_summary` and `chunks_with_keyword_hints` are now **non-zero** \u2014 the generative skill populated them."),
        md("## Step 3 \u2014 Inspect the generated enrichment\n\nShow the summary + keyword hints that the `ChatCompletionSkill` produced."),
        code(
            "import pandas as pd\n\n"
            "chunks = lab.load_chunks(job)\n"
            "enriched = [c for c in chunks if c.get('summary_text')]\n"
            "pd.DataFrame([\n"
            "    {\n"
            "        'section': ' > '.join(c.get('section_path') or []) or '(root)',\n"
            "        'summary': (c.get('summary_text') or '')[:160],\n"
            "        'keyword_hints': ', '.join((c.get('keyword_hints') or [])[:6]),\n"
            "    }\n"
            "    for c in enriched[:6]\n"
            "])"
        ),
        md("## Step 4 \u2014 Query with Hybrid and Agentic\n\nGenerative cues help most on conceptual / multi-hop questions (Q2)."),
        code(
            f"Q2 = {Q2!r}\n\n"
            "print('--- HYBRID ---')\n"
            "resp_hybrid = lab.ask(Q2, job=job, retrieval_mode='hybrid', record_as='lab05_genai_hybrid')\n"
            "lab.show_answer(resp_hybrid, max_citations=4)"
        ),
        code(
            "print('--- AGENTIC ---')\n"
            "resp_agentic = lab.ask(Q2, job=job, retrieval_mode='agentic', record_as='lab05_genai_agentic')\n"
            "lab.show_answer(resp_agentic, max_citations=6)"
        ),
        md(
            "## Takeaways\n\n"
            "- Generative enrichment adds **summaries and keyword hints** at index time.\n"
            "- These cues improve hybrid relevance and give the agentic planner better material to subquery against.\n\n"
            "Next: **Lab 06** adds OCR + image analysis + language detection for diagram-heavy evidence."
        ),
    ]
    write("lab-05-generative-enrichment.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 06 - Image and NLP enrichment
# --------------------------------------------------------------------------- #

def build_lab06() -> None:
    cells = [
        md(
            "# Lab 06 \u00b7 Image and NLP Enrichment (Notebook Walkthrough)\n\n"
            "**Concept.** The `visual_nlp` profile adds `OcrSkill`, `ImageAnalysisSkill`, and `LanguageDetectionSkill` "
            "to the Blob skillset, and switches the Search-managed extractor to the **Document Layout** skill "
            "(`AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_layout`). This matters for a diagram-heavy "
            "engineering document where evidence can live in figures, not just prose.\n\n"
            "**Two ways to crop a figure (complementary, not duplicate):**\n"
            "- **Document Layout skill (server-side).** Runs inside the skillset on the billable Foundry resource. With "
            "`extractionOptions=['images','locationMetadata']` it detects figure regions, crops them, and emits each "
            "crop under `/document/normalized_images/*` together with its `pageNumber` + `boundingPolygons`. The "
            "skillset's **knowledge-store projections** persist the crops to `search-image-assets`, the location "
            "metadata to `search-image-assets-meta`, and (for the `visual_nlp` profile) each figure's OCR + caption "
            "text to `search-image-assets-text` so chart content can travel with the chunk.\n"
            "- **Offline parser (local).** Renders each PDF page and crops figure regions, attaching thumbnails to "
            "chunks for the citation UI. It is the fallback when the native/server-side path is off.\n\n"
            "**Why the extractor swap changes OCR quality.** With the default **Document Extraction** extractor the "
            "indexer's built-in cracker emits *whole-page* normalized images, so `OcrSkill` and `ImageAnalysisSkill` "
            "(both at `/document/normalized_images/*`) run on entire pages and mostly capture page noise. With "
            "**Document Layout** those same skills run on *figure-scoped crops*, so OCR reads the figure's own labels. "
            "On the deep-excavation PDF this took non-empty OCR results from ~12 (whole-page) to ~63 (figure-aware).\n\n"
            "**Where each signal lands:** the per-image caption (`captions/*/text`) and OCR collections populate the "
            "**Search-managed enrichment index** (`...-visual-nlp`) that **Agentic** retrieval can draw on; the app also "
            "merges a **document-level `image_description_text`** back onto every **canonical chunk**, so "
            "`full_text` / `vector` / `hybrid` gain a visual signal too.\n\n"
            "**Key lesson:** caption *quality* is document-dependent. Image Analysis 3.2 returns descriptive but generic "
            "captions (\u201cchart\u201d, \u201cdiagram\u201d, \u201ca diagram of a house\u201d); the big win here is OCR "
            "density + figure scoping + page/polygon **location metadata**. Always **verify what actually landed**."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md(
            "## Step 2 \u2014 Confirm the active extractor\n\n"
            "The `visual_nlp` profile uses the Document Layout extractor when "
            "`AZURE_SEARCH_SKILLSET_PREFERRED_EXTRACTOR=document_layout` and a billable Foundry resource is attached. "
            "When Document Layout is active the indexer runs with `imageAction: none` (the skill does its own "
            "figure-aware cropping, so the built-in whole-page cracker is turned off)."
        ),
        code(
            "from backend.core.config import settings\n"
            "print('preferred extractor      :', settings.azure_search_skillset_preferred_extractor)\n"
            "print('document layout available:', settings.azure_search_document_layout_skill_available)\n"
            "print('image serving enabled    :', settings.azure_search_enable_image_serving)"
        ),
        md("## Step 3 \u2014 Ingest with image + NLP enrichment"),
        code("job = lab.ingest(skill_profile='visual_nlp', reuse=True)\nlab.chunk_overview(job)"),
        md(
            "`chunks_with_image_description` is now **non-zero** - every chunk carries the merged document-level "
            "`image_description_text` assembled from the figure-scoped Image Analysis captions. The summaries and "
            "keyword hints from Lab 05 are still present too."
        ),
        md(
            "## Step 4 \u2014 Inspect the server-side enrichment (OCR + captions)\n\n"
            "The Document Layout + OCR + Image Analysis skills wrote a per-image caption and OCR collection into the "
            "`...-visual-nlp` enrichment index. Because the skills ran on **figure crops** (not whole pages), the OCR is "
            "dense and figure-scoped - real diagram labels rather than page noise."
        ),
        code(
            "vis = lab.enrichment_visual_fields(job)\n"
            "print('enrichment index   :', vis['index_name'])\n"
            "print('detected language  :', vis.get('detected_language'))\n"
            "print('caption count      :', vis.get('image_description_count'))\n"
            "print('caption sample     :', vis.get('image_description_sample'))\n"
            "print('OCR results        :', vis.get('ocr_count'),\n"
            "      '| non-empty:', vis.get('ocr_nonempty_count'))\n"
            "for t in vis.get('ocr_sample', []):\n"
            "    print('   OCR:', t[:120])"
        ),
        md(
            "## Step 5 \u2014 Inspect the figure crops + location metadata\n\n"
            "The skillset's **knowledge-store projections** persisted each figure crop to blob, plus a metadata object "
            "carrying the figure's `pageNumber` and `boundingPolygons`. This is the Azure-native, *location-aware* "
            "equivalent of the offline parser's local figure PNGs - and it is what `/api/native-images` serves back as "
            "citation evidence."
        ),
        code(
            "import pandas as pd\n\n"
            "assets = lab.figure_assets(job, limit=5)\n"
            "print('figure crops in search-image-assets      :', assets['crops'])\n"
            "print('metadata objects in search-image-assets-meta:', assets['metadata'])\n"
            "pd.DataFrame(assets['samples'])"
        ),
        md(
            "> Note: with the native/server-side path active, figures come from the **knowledge store**, not the "
            "offline parser, so canonical chunks here carry no `image_evidence` thumbnails - the figure evidence lives "
            "in `search-image-assets` instead. Set `ENABLE_PARSER_FIGURE_EXTRACTION=true` (and disable native "
            "multimodal) if you want to compare the parser's page-rendered thumbnails side by side."
        ),
        md(
            "### Making figure *text* travel with the chunk (chart-aware answers)\n\n"
            "Serving the crop image is great for a human reader, but in the direct lanes (`Full text`, `Vector`, "
            "`Hybrid`) the **answer model only sees the citation's text snippet** - it can't read pixels. So a chart "
            "whose key numbers live inside the image would not be reflected in the answer even when the figure is "
            "cited.\n\n"
            "To close that gap, the skillset adds a third knowledge-store projection - an **inline-shaped object "
            "projection** - that captures each figure's `ocrText` (chart numbers, axis labels) and `caption`, keyed by "
            "`pageNumber`, into a dedicated `search-image-assets-text` container. The base object projection only "
            "serializes the image node (path + page), *not* the enriched `ocr_text_chunks` / `image_analysis` siblings, "
            "which is why a separate, explicitly-shaped projection is required. At query time `_hydrate_citations` joins "
            "that text onto the citation snippet by page, so the figure's content flows into both the deterministic "
            "direct-search answer and the app-side LLM prompt - every retrieval mode becomes chart-aware.\n\n"
            "> **Takes effect on the next ingestion.** The text projection only writes blobs when the indexer next runs "
            "against the `visual_nlp` profile; until then the query-side join is a safe no-op (empty container), so "
            "nothing regresses on the already-indexed corpus."
        ),
        md(
            "## Step 6 \u2014 Hybrid vs Agentic on a visual question\n\n"
            "**Hybrid** now benefits directly: the merged `image_description_text` is part of every canonical chunk, so "
            "visual vocabulary (\u201cconstruction site\u201d, \u201cchart\u201d) is searchable. **Agentic** can additionally "
            "consult the Search-managed enrichment index, where the *full* per-image caption and (now much richer) OCR "
            "collections live, and tends to assemble more cross-section citations."
        ),
        code(
            f"QV = {Q_VISUAL!r}\n\n"
            "print('--- HYBRID (canonical chunk index, now carries merged captions) ---')\n"
            "resp_hybrid = lab.ask(QV, job=job, retrieval_mode='hybrid', record_as='lab06_visual_hybrid')\n"
            "lab.show_answer(resp_hybrid, max_citations=4)"
        ),
        code(
            "print('--- AGENTIC (also reads the enrichment index: full captions + OCR) ---')\n"
            "resp_agentic = lab.ask(QV, job=job, retrieval_mode='agentic', record_as='lab06_visual_agentic')\n"
            "lab.show_answer(resp_agentic, max_citations=6)"
        ),
        md(
            "## Takeaways\n\n"
            "- The **Document Layout** extractor crops figures *server-side* and records each figure's `pageNumber` + "
            "`boundingPolygons` to the knowledge store - figure-aware **and** location-aware.\n"
            "- Because OCR and Image Analysis now run on figure crops (not whole pages), the OCR is dramatically richer "
            "(real diagram labels, not page noise). Captions stay generic - judge the *quality* of each signal, not just "
            "its presence.\n"
            "- The server-side knowledge-store crops and the offline parser thumbnails solve the same problem in "
            "complementary ways; with the native path on, figures come from the knowledge store and are served via "
            "`/api/native-images`.\n"
            "- A dedicated `search-image-assets-text` projection captures each figure's OCR + caption text and "
            "`_hydrate_citations` splices it onto citations by page, so the figure's chart content travels with the "
            "chunk and **every** retrieval mode can answer about chart numbers (effective on the next ingestion).\n"
            "- Hybrid gains the merged visual summary on every chunk; Agentic additionally taps the full caption/OCR "
            "collections in the enrichment index.\n\n"
            "Next: **Lab 07** focuses on agentic retrieval mechanics (planning, subqueries, grounded synthesis)."
        ),
    ]
    write("lab-06-image-and-nlp-enrichment.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 07 - Agentic retrieval
# --------------------------------------------------------------------------- #

def build_lab07() -> None:
    cells = [
        md(
            "# Lab 07 \u00b7 Agentic Retrieval (Notebook Walkthrough)\n\n"
            "**Concept.** Agentic retrieval uses Azure AI Search's knowledge base: a planning model decomposes the "
            "question into **subqueries**, runs them across the knowledge sources, and returns grounded references that "
            "are synthesized into a cited answer. It is the strongest mode for **multi-hop** reasoning that spans sections.\n\n"
            "We run it against the generatively-enriched index (best material for the planner)."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Use the enriched corpus"),
        code("job = lab.ingest(skill_profile='genai_enrichment', reuse=True)\nlab.chunk_overview(job)"),
        md("## Step 3 \u2014 Ask a multi-hop question\n\nQ2 requires combining groundwater behaviour, clay-layer effects, and design controls \u2014 evidence that lives in different sections."),
        code(
            f"Q2 = {Q2!r}\n\n"
            "resp = lab.ask(Q2, job=job, retrieval_mode='agentic', record_as='lab07_agentic_q2')\n"
            "lab.show_answer(resp, max_citations=8)"
        ),
        md("## Step 4 \u2014 Inspect the planner activity\n\nThe diagnostics expose the subqueries the planner issued and how many references each returned."),
        code(
            "diag = resp.diagnostics or {}\n"
            "print('mode:', diag.get('mode'))\n"
            "print('answer synthesis enabled:', diag.get('answer_synthesis_enabled'))\n"
            "print('query rescue applied:', diag.get('query_rescue_applied'))\n"
            "activity = diag.get('activity') or []\n"
            "for step in activity:\n"
            "    if isinstance(step, dict):\n"
            "        print(' -', step.get('type'), '|', step.get('searchIndexArguments', {}).get('search') or step.get('knowledgeSourceName') or '', '| count=', step.get('count'))"
        ),
        md("## Step 5 \u2014 Contrast with a single-shot mode\n\nRun the same question with hybrid to feel the difference between fused single-query retrieval and planned multi-query retrieval."),
        code(
            "resp_hybrid = lab.ask(Q2, job=job, retrieval_mode='hybrid', record_as='lab07_hybrid_q2')\n"
            "lab.show_answer(resp_hybrid, max_citations=4)"
        ),
        md(
            "## Takeaways\n\n"
            "- Agentic retrieval **plans subqueries** and synthesizes a grounded, cited answer across sections.\n"
            "- It typically returns more, better-targeted citations on multi-hop questions than single-shot hybrid.\n"
            "- It is also the mode that can reach enrichment-index-only fields (e.g. OCR text from Lab 06).\n\n"
            "Next: **Lab 08** swaps in the Content Understanding extractor and compares."
        ),
    ]
    write("lab-07-agentic-retrieval.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 08 - Content Understanding (optional)
# --------------------------------------------------------------------------- #

def build_lab08() -> None:
    cells = [
        md(
            "# Lab 08 \u00b7 Content Understanding Alternative (Notebook Walkthrough)\n\n"
            "**Concept.** The `content_understanding` profile switches the Search-managed extractor to the Azure Content "
            "Understanding skill, which performs semantic chunking and richer structure-aware extraction inside the "
            "skillset itself. This is an optional, advanced comparison against the earlier `DocumentExtractionSkill` path.\n\n"
            "> This lab binds to the billable Foundry resource via the skillset's managed identity. If your environment "
            "is not enabled for it, the ingest cell will report the failure and you can skip to the comparison notebook."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Ingest with Content Understanding"),
        code(
            "try:\n"
            "    job = lab.ingest(skill_profile='content_understanding', reuse=True)\n"
            "    print(lab.chunk_overview(job))\n"
            "except Exception as exc:\n"
            "    job = None\n"
            "    print('Content Understanding ingestion not available in this environment:')\n"
            "    print(' ', exc)"
        ),
        md("## Step 3 \u2014 Compare chunk boundaries against baseline\n\nContent Understanding tends to produce semantically coherent chunks; compare the token distribution with the baseline profile."),
        code(
            "import pandas as pd\n\n"
            "if job is not None:\n"
            "    base = lab.find_existing_job(skill_profile_id='baseline_extract', file_name='Deep Excavation Design and Construction.pdf')\n"
            "    rows = []\n"
            "    for label, j in [('baseline_extract', base), ('content_understanding', job)]:\n"
            "        if j is None:\n"
            "            continue\n"
            "        ov = lab.chunk_overview(j)\n"
            "        rows.append({'profile': label, 'chunks': ov['chunk_count'], 'avg_tokens': ov['avg_tokens'], 'max_tokens': ov['max_tokens']})\n"
            "    display(pd.DataFrame(rows))\n"
            "else:\n"
            "    print('Skipped \u2014 no Content Understanding job.')"
        ),
        md("## Step 4 \u2014 Query the corpus"),
        code(
            f"Q2 = {Q2!r}\n\n"
            "if job is not None:\n"
            "    resp = lab.ask(Q2, job=job, retrieval_mode='hybrid', record_as='lab08_contentunderstanding_hybrid')\n"
            "    lab.show_answer(resp, max_citations=4)\n"
            "else:\n"
            "    print('Skipped \u2014 no Content Understanding job.')"
        ),
        md(
            "## Takeaways\n\n"
            "- Content Understanding moves semantic chunking + structure extraction **into the skillset**.\n"
            "- Compare its chunk boundaries and retrieval quality with the built-in `DocumentExtractionSkill` profiles.\n\n"
            "Next: the **comparison notebook** lays every method side by side."
        ),
    ]
    write("lab-08-content-understanding.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 09 - Multi-source knowledge routing
# --------------------------------------------------------------------------- #

Q_AI = "What does the report forecast about generative AI adoption trends and the future of the technology?"
Q_EXC = "What groundwater control measures are recommended to support a deep excavation?"
Q_COMPARE = "Compare how risk and forecasting are treated across the two indexes."


def build_lab_multi_source() -> None:
    cells = [
        md(
            "# Lab 09 \u00b7 Multi-Source Knowledge Routing (Notebook Walkthrough)\n\n"
            "**Concept.** A real assistant rarely searches a single corpus. This lab adds a **second, separate index** "
            "on a completely different topic \u2014 *the future of generative AI* \u2014 next to the deep-excavation engineering "
            "corpus the earlier labs built. With two indexes registered as Azure AI Search **knowledge sources**, the "
            "knowledge base decides, per question, **which index (or indexes) to search**.\n\n"
            "You will see three routing outcomes:\n"
            "1. an **AI-trends** question routed to the AI-trends index only,\n"
            "2. an **excavation** question routed to the engineering index only,\n"
            "3. a **compare** question fanned out across **both** indexes.\n\n"
            "> Prerequisite: the second source must be registered before you start. Set "
            "`AZURE_SEARCH_EXTRA_SOURCES_JSON` in your `.env` (see the lab doc), then restart the app. The app "
            "auto-creates the `ai-trends-index` on first ingest \u2014 you do not have to create it by hand."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md(
            "## Step 2 \u2014 Confirm the second knowledge source is registered\n\n"
            "`AZURE_SEARCH_EXTRA_SOURCES_JSON` is parsed at startup into `settings.azure_search_extra_sources`. If the "
            "list below is empty, set the variable in `.env` and restart the kernel before continuing."
        ),
        code(
            "from backend.core.config import settings\n"
            "extra = [(s.knowledge_source_name, s.index_name) for s in settings.azure_search_extra_sources]\n"
            "print('Extra knowledge sources:', extra or 'NONE \u2014 set AZURE_SEARCH_EXTRA_SOURCES_JSON and restart')\n"
            "for s in settings.azure_search_extra_sources:\n"
            "    print(' route_keywords:', s.route_keywords)\n"
            "    print(' assignment_keywords:', s.assignment_keywords)"
        ),
        md(
            "## Step 3 \u2014 Ingest both corpora\n\n"
            "The engineering corpus already exists from the earlier labs; the AI-trends PDF is ingested into the "
            "**separate** `ai-trends-index`. Ingest-time routing reads the document's name and section headings and "
            "matches them against each source's `assignment_keywords` \u2014 the filename tokens `future` and `trends` send "
            "this document to the AI-trends source. Both runs reuse cached results when available."
        ),
        code(
            "ai_job = lab.ingest(pdf_path='data/ai-future-trends.pdf', skill_profile='genai_enrichment', reuse=True)\n"
            "try:\n"
            "    exc_job = lab.ingest(skill_profile='genai_enrichment', reuse=True)\n"
            "except FileNotFoundError:\n"
            "    # The engineering corpus was already ingested by earlier labs; reuse it without the source file.\n"
            "    exc_job = lab.find_existing_job(skill_profile_id='genai_enrichment',\n"
            "                                    file_name='Deep Excavation Design and Construction.pdf')\n\n"
            "ai_diag = ai_job.publish_status.diagnostics or {}\n"
            "exc_diag = (exc_job.publish_status.diagnostics or {}) if exc_job else {}\n"
            "print('Excavation doc ->', exc_diag.get('index_name'))\n"
            "print('AI-trends doc  ->', ai_diag.get('index_name'),\n"
            "      '| assignment_mode:', ai_diag.get('assignment_mode'),\n"
            "      '| matched:', ai_diag.get('assignment_matches'))\n"
            "print('All publishable indexes:', ai_diag.get('index_names'))"
        ),
        md(
            "## Step 4 \u2014 Preview routing *before* searching\n\n"
            "`route_preview` runs the same knowledge-source routing the live retrieve path uses, but stops before "
            "issuing any request \u2014 so it is instant and free. Watch the `routing_mode` and the indexes it selects for "
            "each question."
        ),
        code(
            f"Q_AI = {Q_AI!r}\n"
            f"Q_EXC = {Q_EXC!r}\n"
            f"Q_COMPARE = {Q_COMPARE!r}\n\n"
            "import pandas as pd\n\n"
            "rows = []\n"
            "for label, q in [('AI trends', Q_AI), ('Excavation', Q_EXC), ('Compare', Q_COMPARE)]:\n"
            "    rp = lab.route_preview(q)\n"
            "    rows.append({\n"
            "        'question': label,\n"
            "        'routing_mode': rp['routing_mode'],\n"
            "        'selected_indexes': ', '.join(rp['selected_search_indexes']),\n"
            "        'matched_terms': '; '.join(\n"
            "            f\"{idx}:{terms}\" for idx, terms in rp['matched_terms_by_index'].items() if terms\n"
            "        ),\n"
            "    })\n"
            "pd.DataFrame(rows)"
        ),
        md(
            "### Read the routing table\n\n"
            "- **AI trends** \u2192 `keyword_routed` to the **AI-trends index** because the question matched that source's "
            "`route_keywords` (trends, future, forecast, generative\u2026).\n"
            "- **Excavation** \u2192 `keyword_routed` to the **primary engineering index** \u2014 the term *excavation* matches "
            "the corpus published there.\n"
            "- **Compare** \u2192 `cross_source_intent`: compare/across language tells the router to query **both** indexes "
            "so the answer can draw from each."
        ),
        md(
            "## Step 5 \u2014 Prove it: hybrid search shows which index served each hit\n\n"
            "No `doc_ids` are pinned, so the **router** (not a manual selection) decides the scope. Each hit carries the "
            "index it came from."
        ),
        code(
            "hits, diag = lab.multi_source_search(Q_AI, retrieval_mode='hybrid', top=5)\n"
            "print('routing_mode:', diag.get('routing_mode'), '| indexes:', diag.get('selected_search_indexes'))\n"
            "pd.DataFrame(hits)"
        ),
        code(
            "hits, diag = lab.multi_source_search(Q_EXC, retrieval_mode='hybrid', top=5)\n"
            "print('routing_mode:', diag.get('routing_mode'), '| indexes:', diag.get('selected_search_indexes'))\n"
            "pd.DataFrame(hits)"
        ),
        md(
            "Each question's hits come **only** from the relevant index \u2014 the AI question never pulls excavation "
            "chunks, and vice versa. That isolation is what keeps grounded answers on-topic in a multi-corpus assistant."
        ),
        md(
            "## Step 6 \u2014 A grounded answer that picks the right source automatically\n\n"
            "`ask_corpus` runs a full chat turn in `auto` corpus mode \u2014 the knowledge base routes across every ready "
            "corpus, exactly like the deployed assistant. The AI question is answered from the AI-trends index."
        ),
        code(
            "resp = lab.ask_corpus(Q_AI, retrieval_mode='agentic')\n"
            "lab.show_answer(resp, max_citations=4)"
        ),
        md("## Step 7 — The cross-source question is routed to both indexes\n\n"
           "Routing fans the query out across **both** indexes (see Step 4). The planner then grounds the synthesized "
           "answer in whichever retrieved chunks are most relevant — so the citations may lean toward one corpus even "
           "though both were searched."),
        code(
            "resp = lab.ask_corpus(Q_COMPARE, retrieval_mode='agentic')\n"
            "lab.show_answer(resp, max_citations=6)"
        ),
        md(
            "## Takeaways\n\n"
            "- A knowledge base can reference **multiple knowledge sources**, each backed by its **own index**.\n"
            "- **Ingest-time** routing (`assignment_keywords`) decides which index a document lands in; **query-time** "
            "routing (`route_keywords`, compare-intent, auto-broadcast) decides which index answers a question.\n"
            "- Routing modes: `keyword_routed` (a source's hints matched), `cross_source_intent` (compare/across "
            "language \u2192 all sources), `broad_auto` (no hint matched but few enough sources to fan out), "
            "`primary_default` (fall back to the main index).\n"
            "- Tune `route_keywords` per source and `AZURE_SEARCH_AUTO_BROADCAST_LIMIT` to balance precision against "
            "recall as you add more corpora.\n\n"
            "Next: the **comparison notebook** lays every retrieval method side by side."
        ),
    ]
    write("lab-09-multi-source-routing.ipynb", cells)


# --------------------------------------------------------------------------- #
# Lab 10 - Comparison / summary
# --------------------------------------------------------------------------- #

def build_comparison() -> None:
    cells = [
        md(
            "# Comparison Summary \u00b7 Methods and Results Side by Side\n\n"
            "This notebook does two things:\n"
            "1. Runs a **controlled matrix** \u2014 the same two anchor questions across all four retrieval modes on a single "
            "rich index \u2014 so differences are attributable to the retrieval method.\n"
            "2. Loads every **recorded lab run** (from `notebooks/results/lab_runs.jsonl`) into one comparison table.\n\n"
            "**Anchor questions**\n"
            "- **Q1 (precise / keyword):** site-investigation objectives \u2014 favours full-text.\n"
            "- **Q2 (conceptual / multi-hop):** groundwater + clay risks and design \u2014 favours vector / hybrid / agentic."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Use the richest index for a fair cross-mode comparison"),
        code(
            "job = lab.ingest(skill_profile='visual_nlp', reuse=True)\n"
            "lab.chunk_overview(job)"
        ),
        md("## Step 3 \u2014 Controlled matrix: 2 questions \u00d7 4 retrieval modes\n\nEach cell is a full grounded chat turn (retrieval + synthesis), the same as the UI."),
        code(
            f"Q1 = {Q1!r}\n"
            f"Q2 = {Q2!r}\n\n"
            "import pandas as pd\n\n"
            "matrix = []\n"
            "for qlabel, q in [('Q1 precise', Q1), ('Q2 multi-hop', Q2)]:\n"
            "    for mode in ['full_text', 'vector', 'hybrid', 'agentic']:\n"
            "        resp = lab.ask(q, job=job, retrieval_mode=mode, record_as=f'compare_{mode}_{qlabel.split()[0]}')\n"
            "        diag = resp.diagnostics or {}\n"
            "        top = resp.citations[0] if resp.citations else None\n"
            "        matrix.append({\n"
            "            'question': qlabel,\n"
            "            'mode': mode,\n"
            "            'citations': len(resp.citations),\n"
            "            'answer_chars': len(resp.answer),\n"
            "            'synthesis': diag.get('answer_synthesis_enabled'),\n"
            "            'top_section': (' > '.join(top.section_path) if top and top.section_path else (top.title if top else '\u2014')),\n"
            "        })\n"
            "df = pd.DataFrame(matrix)\n"
            "df"
        ),
        md("### Read the matrix\n\nExpect full-text to win on Q1's exact terminology, vector/hybrid to broaden Q2 recall, and agentic to return the most cross-section citations on Q2."),
        md("## Step 4 \u2014 Answers side by side (Q2)\n\nThe qualitative difference is clearest on the multi-hop question."),
        code(
            "for mode in ['full_text', 'vector', 'hybrid', 'agentic']:\n"
            "    print('=' * 80)\n"
            "    print('MODE:', mode)\n"
            "    resp = lab.ask(Q2, job=job, retrieval_mode=mode)\n"
            "    print(resp.answer.strip()[:700])\n"
            "    print()"
        ),
        md("## Step 5 \u2014 Every recorded lab run\n\nThis pulls the runs each lab notebook recorded, so you can compare ingestion profiles and modes across the whole workshop."),
        code(
            "import pandas as pd\n\n"
            "runs = lab.load_runs()\n"
            "print('recorded runs:', len(runs))\n"
            "if runs:\n"
            "    rdf = pd.DataFrame([\n"
            "        {\n"
            "            'label': r['label'],\n"
            "            'skill_profile': r['skill_profile'],\n"
            "            'retrieval_mode': r['retrieval_mode'],\n"
            "            'scoring_profile': r['scoring_profile'],\n"
            "            'citations': r['citation_count'],\n"
            "            'elapsed_s': r['elapsed_s'],\n"
            "            'answer_preview': r['answer'][:90].replace(chr(10), ' '),\n"
            "        }\n"
            "        for r in runs\n"
            "    ])\n"
            "    display(rdf)"
        ),
        md(
            "## How to choose a retrieval mode\n\n"
            "| Mode | Best for | Why |\n"
            "| --- | --- | --- |\n"
            "| **Full-text** | exact terminology, definitions, standards, tables | lexical BM25 matches explicit wording |\n"
            "| **Vector** | paraphrased / conceptual questions | embedding similarity finds meaning, not words |\n"
            "| **Hybrid** | precise + contextual answers | fuses keyword precision with semantic recall |\n"
            "| **Agentic** | multi-hop reasoning, synthesis across sections | plans subqueries and grounds a cited answer |\n\n"
            "And across ingestion profiles: each enrichment layer (chunking \u2192 vectors \u2192 generative cues \u2192 visual/NLP) "
            "adds retrievable signal, with the biggest gains showing up on conceptual and diagram-grounded questions."
        ),
    ]
    write("lab-10-comparison-summary.ipynb", cells)


if __name__ == "__main__":
    build_lab03()
    build_lab04()
    build_lab05()
    build_lab06()
    build_lab07()
    build_lab08()
    build_lab_multi_source()
    build_comparison()
    print("ALL_NOTEBOOKS_BUILT")
