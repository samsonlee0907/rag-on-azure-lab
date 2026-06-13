# Manual Test Script

Use this handout during the workshop dry run or live delivery to validate each lab outcome through the web portal.

The test document is the GEO guidance publication on **Excavation and Lateral Support (ELS) works in Hong Kong** (`DeepExcavationDesignAndConstruction.pdf`). It is a structure-heavy engineering document with chapters, factors, tables, and figures, which makes it a good corpus for comparing every retrieval mode and skill profile.

## Portal

- URL: `http://127.0.0.1:8016/` (use whatever port you launched with).
- Start the app through the helper script so `.env` is loaded: `.\scripts\run-local-app.ps1 -Port 8016`.
- Use `Custom Selection` in Chat for every test in this handout.
- Select exactly one corpus for each lab unless the handout says otherwise.

## Preparing The Corpora

Skill profiles are now chosen **per upload** from the **Skill Profile** picker on the `Document Ingestion` screen. You no longer edit `WORKSHOP_SKILL_PROFILE` or restart the app between labs.

Upload the **same file** (`DeepExcavationDesignAndConstruction.pdf`) once for each profile you want to test, selecting a different **Skill Profile** each time and keeping **Ingestion Mode** on `Hybrid: Blob + Search skillset`:

- `DeepExcavationDesignAndConstruction.pdf` · Baseline Extraction
- `DeepExcavationDesignAndConstruction.pdf` · Chunking And Vectorization
- `DeepExcavationDesignAndConstruction.pdf` · Generative Enrichment
- `DeepExcavationDesignAndConstruction.pdf` · Image And NLP Enrichment
- `DeepExcavationDesignAndConstruction.pdf` · Content Understanding Alternative (optional, Lab 08)

Each upload produces its own enrichment index (suffix `-baseline`, `-chunk-vector`, `-genai`, `-visual-nlp`, `-content-understanding`). The short document IDs change on every run, so match a corpus by its **profile title**, not by ID.

## Before You Start

1. Open the portal.
2. Go to `Knowledge Base`.
3. Confirm each uploaded corpus is in `Ready for chat`.
4. Go to `Chat`.
5. Switch to `Custom Selection`.
6. Use the corpus and retrieval mode listed for each lab below.

> All expected answers in this handout come from the document's introduction and chapter overview, so they are verifiable regardless of run. Page numbers and deeper-chapter details vary, so confirm them against the live citations rather than hard-coding them.

## Lab 03: Baseline Extraction

### Goal

Show the lexical baseline before vector and agentic retrieval are introduced.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Baseline Extraction`

### Retrieval Mode

- `full_text`

### Question

```text
How does this document define a deep excavation?
```

### Expected Result

The answer should state that a **deep excavation** is an excavation **deeper than 4.5 m**, in line with the enhanced statutory control of ELS works under the Buildings Ordinance (PNAP APP-57).

### What To Observe

- The answer is grounded and correct.
- Evidence should point to the `Overview` section in Chapter 1.
- `Agentic Retrieval Activity` should not show subqueries because this is direct lexical retrieval.

### Optional Follow-up

```text
Which document should I refer to for new permanent earth retaining walls?
```

Expected: `Geoguide 1: Guide to Retaining Wall (GEO, 2020)`. This may be weaker or noisier than the hybrid result in Lab 04. That is acceptable and useful for comparison.

## Lab 04: Chunking And Vectorization

### Goal

Show the difference between lexical, vector, and hybrid retrieval after enabling vectorization.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Chunking And Vectorization`

### Test 1

- Retrieval mode: `vector`

Question (deliberately paraphrased, no keyword overlap with "4.5 m" or "deep excavation"):

```text
How deep does a dig have to be before the stricter legal controls kick in?
```

Expected result:

- The answer should still land on the **4.5 m** threshold and the enhanced statutory control under the Buildings Ordinance.

What to observe:

- Ask the same paraphrase in `full_text` first to show the lexical miss, then in `vector` to show semantic recovery.
- This shows semantic similarity retrieval can find the right passage without relying on keyword overlap.

### Test 2

- Retrieval mode: `hybrid`

Question:

```text
Which chapter covers site investigation and selection of geotechnical parameters?
```

Expected result:

- The answer should say **Chapter 2**.

What to observe:

- This is a clear demonstration of hybrid retrieval combining the exact terms ("site investigation", "geotechnical parameters") with semantic ranking.
- Evidence should include a chapter-overview chunk from Chapter 1.

## Lab 05: Generative Enrichment

### Goal

Show that Azure AI Search skillset-based enrichment can add summaries and retrieval hints during ingestion.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Generative Enrichment`

### Retrieval Mode

- `hybrid`

### Question

```text
What is the purpose of this document and who is it intended for?
```

### Expected Result

The answer should explain that the document gives **guidance for the design and construction of ELS works in Hong Kong**, consolidates local practice and experience, provides recommendations for mitigating geotechnical risks, and is **intended for readers who have some general knowledge of ELS works**.

### What To Observe

- The answer should remain grounded and correct.
- High-level "what is this about / who is it for" questions benefit most from the generated summaries and keyword hints added during ingestion.
- The value of this lab is the ingestion-side enrichment, not necessarily a dramatic UI difference on every question.

### Optional Follow-up

```text
Summarize in concise bullets what this publication updates compared with GCO Publication No. 1/90.
```

Expected: it updates the 1990 design-methods publication to reflect advances in knowledge, technology, and modern methods for ELS works.

## Lab 06: Image And NLP Enrichment

### Goal

Show the value of visual and NLP-oriented enrichment on a document that contains diagrams, cross-sections, and engineering figures.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Image And NLP Enrichment`

### Retrieval Mode

- `agentic`

> OCR text, image descriptions, and figure fields live in the Search-managed enrichment index (`...-visual-nlp`), which the direct modes do **not** query. Run this question in **Agentic** mode so the enrichment source is actually consulted; `hybrid` alone will not surface the figure-derived evidence.

### Question

```text
What do the figures or diagrams show about excavation support systems?
```

### Expected Result

The answer should describe excavation support / lateral support arrangements (for example embedded walls and bracing or anchoring) drawn from figure and diagram content, grounded in the relevant chapters on support systems (Chapters 3 to 5).

### What To Observe

- The answer should be correct and grounded.
- The retrieval trace should reference the visual-NLP enrichment source.
- This is a strong example of figure-heavy engineering content being made searchable through OCR and image enrichment.

## Lab 07: Agentic Retrieval

### Goal

Show the official Azure AI Search agentic retrieval feature decomposing a compound question into subqueries.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Image And NLP Enrichment`

### Retrieval Mode

- `agentic`

### Question

```text
What is a deep excavation, which chapters cover the limit state design of ELS works, and what does the document say about instrumentation and monitoring?
```

### Expected Result

The answer should:

- define a deep excavation as deeper than **4.5 m**
- identify **Chapter 6** for limit state design (with ULS and SLS methods in **Chapters 7 and 8**)
- explain that **Chapter 10** covers **instrumentation and monitoring (I&M)** as essential for the safe execution of ELS works

### What To Observe

- `Agentic Retrieval Activity` should show multiple steps (this three-part question typically produces 3 subqueries).
- This is the clearest proof that the system is doing more than a single lexical search.

## Lab 08: Optional Content Understanding

### Goal

Show Search-managed semantic extraction and structure-aware chunking as an advanced alternative to the earlier extractors.

### Corpus

- `DeepExcavationDesignAndConstruction.pdf · Content Understanding Alternative`

### Retrieval Mode

- `hybrid`, then `agentic`

### Question

```text
How is this document organized, and what design factor methods does it discuss for limit state design?
```

### Expected Result

The answer should describe the chapter structure and note that limit state design (Chapter 6) discusses the **global factor** and **partial factor** methods, along with recommended factors for each.

### What To Observe

- Compare the chunk boundaries and structure handling against the Baseline and Chunk/Vector corpora for the same question.
- Content Understanding's semantic chunking should respect section and table structure better on this layout-heavy document.

> If the portal reports `azure_content_understanding_skill_available = false`, the Content Understanding profile cannot run. Confirm `AZURE_FOUNDRY_RESOURCE_ENDPOINT` is set (Lab 02) before testing this corpus.

## Grounding / Negative Checks

Run these against any corpus to confirm the system stays grounded and does not hallucinate:

```text
What is the capital of France?
```

Expected: the system should decline or state that the answer is not found in the document.

```text
What does this document say about underwater welding?
```

Expected: no grounded answer, because the topic is not in the corpus.

## Recommended Demo Sequence

If you want the shortest clean live demo, use this order:

1. `Baseline Extraction` + `full_text`
   Ask: `How does this document define a deep excavation?`
2. `Chunking And Vectorization` + `vector`
   Ask: `How deep does a dig have to be before the stricter legal controls kick in?`
3. `Chunking And Vectorization` + `hybrid`
   Ask: `Which chapter covers site investigation and selection of geotechnical parameters?`
4. `Image And NLP Enrichment` + `agentic`
   Ask: `What do the figures or diagrams show about excavation support systems?`
5. `Image And NLP Enrichment` + `agentic`
   Ask: `What is a deep excavation, which chapters cover the limit state design of ELS works, and what does the document say about instrumentation and monitoring?`

## Interpretation Guide

What the audience should notice:

- Lab 03 shows that a lexical baseline can already work when the chunking and citations are clean, but it depends on the reader using the document's own wording.
- Lab 04 shows why vector and hybrid retrieval are worth comparing directly, especially for paraphrased questions.
- Lab 05 shows that enrichment is an ingestion-quality improvement that helps high-level, summary-style questions.
- Lab 06 shows why image and NLP enrichment matter for engineering and diagram-heavy documents, and why that evidence is surfaced through agentic retrieval.
- Lab 07 shows how agentic retrieval breaks a compound question into multiple retrieval steps.
- Lab 08 shows how Search-managed semantic extraction changes chunk boundaries on a structure-heavy document.
