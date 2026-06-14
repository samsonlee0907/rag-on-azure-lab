# Lab Walkthrough Notebooks

Executable companions to the workshop labs in [`docs/labs/`](../docs/labs/). Each
notebook drives the **same backend pipeline the web UI runs** — in-process —
against live Azure AI Search, so the committed outputs are real ingestion stats,
real retrieval hits, and real grounded answers (not mock-ups).

All notebooks use one anchor document so results are directly comparable:
*Deep Excavation Design and Construction* (GEO Publication No. 1/2023).

## Notebooks

| Notebook | Lab | Skill profile | Shows |
| --- | --- | --- | --- |
| [lab-03-baseline-extraction.ipynb](lab-03-baseline-extraction.ipynb) | Lab 03 | `baseline_extract` | Plain text extraction + chunking, lexical (full-text) retrieval as the control group. |
| [lab-04-chunking-and-vectorization.ipynb](lab-04-chunking-and-vectorization.ipynb) | Lab 04 | `chunk_vector` | Embeddings added; full-text vs vector vs hybrid side-by-side, plus scoring profiles. |
| [lab-05-generative-enrichment.ipynb](lab-05-generative-enrichment.ipynb) | Lab 05 | `genai_enrichment` | Summaries + keyword hints generated at index time; hybrid and agentic retrieval. |
| [lab-06-image-and-nlp-enrichment.ipynb](lab-06-image-and-nlp-enrichment.ipynb) | Lab 06 | `visual_nlp` | OCR / image-analysis / NLP enrichment; a figure-grounded visual question. |
| [lab-07-agentic-retrieval.ipynb](lab-07-agentic-retrieval.ipynb) | Lab 07 | `genai_enrichment` | Agentic (knowledge-base) retrieval deep dive with planner activity diagnostics. |
| [lab-08-content-understanding.ipynb](lab-08-content-understanding.ipynb) | Lab 08 | `content_understanding` | Content Understanding enrichment profile; hybrid retrieval. |
| [lab-09-comparison-summary.ipynb](lab-09-comparison-summary.ipynb) | — | `visual_nlp` | A rubric-scored 2-question × 4-mode matrix, full answers side by side, and every lab's recorded run, with a mode-selection guide. |

## Anchor questions

Two questions are deliberately chosen to expose how retrieval mode changes results:

- **Q1 — precise / keyword-heavy:** *"What are the objectives of site investigation
  for ELS works?"* The wording matches the document, so lexical full-text already
  does well.
- **Q2 — conceptual / multi-hop:** *"Given a site with high groundwater and clay
  layers, what are the key excavation risks and design considerations?"* This rewards
  vector and hybrid retrieval and, especially, agentic planning.
- **Q-visual (Lab 06 only):** *"What do the figures on ground settlement and wall
  deflection show, and what visual evidence supports the answer?"* Exercises the
  image/OCR enrichment surface.

The comparison notebook (lab-09) scores each answer against a **rubric** — the key
points a strong answer should contain — so you can judge which mode answered more
completely (e.g. `8/8` vs `1/8`) even without reading the source document, and it
prints the **full answers** side by side so the detail is preserved for comparison.

## Running them

The notebooks read configuration from the repository `.env` (gitignored) and
import the backend directly. The shared engine is [lab_runtime.py](lab_runtime.py).

```powershell
# from the repo root, with .env populated for your Azure resources
python -m nbconvert --to notebook --execute --inplace `
  --ExecutePreprocessor.timeout=1200 notebooks\lab-03-baseline-extraction.ipynb
```

Ingestion is cached: `lab.ingest(..., reuse=True)` reuses a previously completed
run for the same profile + file, so re-running a notebook is fast and only the
first run pays the full Azure indexing cost. Run labs 03–08 before
`lab-09-comparison-summary.ipynb` if you want its "recorded runs" table populated
(it also runs its own controlled matrix independently).

To regenerate the notebook scaffolding from code, run
[_build_notebooks.py](_build_notebooks.py). To pre-warm every profile's ingestion
in one pass, run [_pre_ingest.py](_pre_ingest.py).

## Notes

- `baseline_extract` is intentionally the only profile **without** vector
  embeddings — it is the lexical control group, so vector/hybrid modes are not
  offered there.
- Results are recorded to `results/lab_runs.jsonl` for the comparison notebook.
