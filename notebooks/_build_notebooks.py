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
            "**Concept.** The `visual_nlp` profile adds `OCRSkill`, `ImageAnalysisSkill`, and `LanguageDetectionSkill`. "
            "This matters for a diagram-heavy engineering document where evidence lives in figures, not just prose.\n\n"
            "**Critical nuance (which fields reach which retrieval mode):**\n"
            "- **Image descriptions** (`image_description_text`) are merged back onto the canonical chunks \u2192 visible to `full_text` / `vector` / `hybrid`.\n"
            "- **OCR text** and **detected language** live only in the Search-managed enrichment index \u2192 surfaced by **Agentic** retrieval.\n\n"
            "So Hybrid reflects image descriptions, while Agentic additionally brings in OCR text the direct modes cannot reach."
        ),
        md("## Step 1 \u2014 Bootstrap"),
        code(SETUP),
        md("## Step 2 \u2014 Ingest with image + NLP enrichment"),
        code("job = lab.ingest(skill_profile='visual_nlp', reuse=True)\nlab.chunk_overview(job)"),
        md("`chunks_with_image_description` should now be **non-zero** \u2014 image analysis descriptions were merged onto the canonical chunks."),
        md("## Step 3 \u2014 Inspect the image descriptions merged onto chunks"),
        code(
            "import pandas as pd\n\n"
            "chunks = lab.load_chunks(job)\n"
            "with_img = [c for c in chunks if c.get('image_description_text')]\n"
            "print('chunks carrying image descriptions:', len(with_img))\n"
            "pd.DataFrame([\n"
            "    {\n"
            "        'section': ' > '.join(c.get('section_path') or []) or '(root)',\n"
            "        'pages': c.get('page_numbers'),\n"
            "        'image_description': (c.get('image_description_text') or '')[:180],\n"
            "    }\n"
            "    for c in with_img[:6]\n"
            "])"
        ),
        md("## Step 4 \u2014 Hybrid vs Agentic on a visual question\n\nHybrid reflects the merged image descriptions; Agentic additionally reaches the OCR text in the enrichment index."),
        code(
            f"QV = {Q_VISUAL!r}\n\n"
            "print('--- HYBRID (sees image descriptions) ---')\n"
            "resp_hybrid = lab.ask(QV, job=job, retrieval_mode='hybrid', record_as='lab06_visual_hybrid')\n"
            "lab.show_answer(resp_hybrid, max_citations=4)"
        ),
        code(
            "print('--- AGENTIC (adds OCR from enrichment index) ---')\n"
            "resp_agentic = lab.ask(QV, job=job, retrieval_mode='agentic', record_as='lab06_visual_agentic')\n"
            "lab.show_answer(resp_agentic, max_citations=6)"
        ),
        md(
            "## Takeaways\n\n"
            "- Image-analysis descriptions are merged to canonical chunks, so **Hybrid can already reflect visual evidence**.\n"
            "- OCR text and detected language are enrichment-index-only, so **Agentic surfaces evidence the direct modes cannot**.\n"
            "- For diagram-heavy documents, compare Hybrid and Agentic to see the full benefit of visual + NLP enrichment.\n\n"
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
# Lab 09 - Comparison / summary
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
    write("lab-09-comparison-summary.ipynb", cells)


if __name__ == "__main__":
    build_lab03()
    build_lab04()
    build_lab05()
    build_lab06()
    build_lab07()
    build_lab08()
    build_comparison()
    print("ALL_NOTEBOOKS_BUILT")
