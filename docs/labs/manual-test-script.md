# Manual Test Script

Use this handout during the workshop dry run or live delivery to validate each lab outcome through the web portal.

## Portal

- URL: `http://127.0.0.1:8130/`
- Use `Custom Selection` in Chat for every test in this handout.
- Select exactly one corpus for each lab unless the handout says otherwise.

## Corpora In This Run

At the time this handout was created, the portal exposed these four corpora:

- `Building Construction Handbook.pdf · Baseline Extraction · 8cb313c1`
- `Building Construction Handbook.pdf · Chunking And Vectorization · 636f07a4`
- `Building Construction Handbook.pdf · Generative Enrichment · 1a534162`
- `Building Construction Handbook.pdf · Image And NLP Enrichment · 1e4e3d36`

If you rerun the workshop, the short document IDs will change. Match the corpus by the workshop profile title, not just by the ID.

## Before You Start

1. Open the portal.
2. Go to `Knowledge Base`.
3. Confirm the four corpora above are in `Ready for chat`.
4. Go to `Chat`.
5. Switch to `Custom Selection`.
6. Use the corpus and retrieval mode listed for each lab below.

## Lab 03: Baseline Extraction

### Goal

Show the lexical baseline before vector and agentic retrieval are introduced.

### Corpus

- `Building Construction Handbook.pdf · Baseline Extraction · 8cb313c1`

### Retrieval Mode

- `full_text`

### Question

```text
What are the basic components of paint?
```

### Expected Result

The answer should list:

- Binder
- Pigment
- Solvents and Thinners

### What To Observe

- The answer is grounded and correct.
- Evidence should point to the paint section around pages `642-643`.
- `Agentic Retrieval Activity` should not show subqueries because this is direct lexical retrieval.

### Optional Follow-up

```text
Which page covers paints and painting?
```

This may be weaker or noisier than the hybrid result in Lab 04. That is acceptable and useful for comparison.

## Lab 04: Chunking And Vectorization

### Goal

Show the difference between lexical, vector, and hybrid retrieval after enabling vectorization.

### Corpus

- `Building Construction Handbook.pdf · Chunking And Vectorization · 636f07a4`

### Test 1

- Retrieval mode: `vector`

Question:

```text
What are the basic components of paint?
```

Expected result:

- Binder
- Pigment
- Solvents and Thinners

What to observe:

- The result should still be correct.
- This shows semantic similarity retrieval can land on the right passage without relying only on keyword overlap.

### Test 2

- Retrieval mode: `hybrid`

Question:

```text
Which page covers paints and painting?
```

Expected result:

- The answer should say `page 634`.

What to observe:

- This is one of the clearest demonstrations of the value of hybrid retrieval.
- Evidence should include a `table_of_contents` chunk around pages `6-7`.

## Lab 05: Generative Enrichment

### Goal

Show that Azure AI Search skillset-based enrichment can add summaries and hints during ingestion.

### Corpus

- `Building Construction Handbook.pdf · Generative Enrichment · 1a534162`

### Retrieval Mode

- `hybrid`

### Question

```text
What are the basic components of paint?
```

### Expected Result

The answer should still correctly list:

- Binder
- Pigment
- Solvents and Thinners

### What To Observe

- The answer should remain grounded and correct.
- On this handbook, the visible improvement may be subtle because the source is already well-structured.
- The value of this lab is the ingestion-side enrichment, not necessarily a dramatic UI difference on every question.

### Optional Follow-up

```text
Summarize the main paint components in concise bullets.
```

## Lab 06: Image And NLP Enrichment

### Goal

Show the value of visual and NLP-oriented enrichment on a document that contains diagrams, labels, and construction visuals.

### Corpus

- `Building Construction Handbook.pdf · Image And NLP Enrichment · 1e4e3d36`

### Retrieval Mode

- `hybrid`

### Question

```text
What three groups can suspended ceilings be placed in?
```

### Expected Result

The answer should list:

- Jointless suspended ceilings
- Panelled suspended ceilings
- Decorative and open suspended ceilings

### What To Observe

- The answer should be correct and grounded.
- Evidence should point near pages `639-642`.
- This is a strong example of a figure-heavy or detail-heavy section being retrieved cleanly.

## Lab 07: Agentic Retrieval

### Goal

Show the official Azure AI Search agentic retrieval feature decomposing a compound question into subqueries.

### Corpus

- `Building Construction Handbook.pdf · Image And NLP Enrichment · 1e4e3d36`

### Retrieval Mode

- `agentic`

### Question

```text
What are the basic components of paint, and which page covers paints and painting?
```

### Expected Result

The answer should:

- list the three paint components
- say that `Paints and painting` is on `page 634`

### What To Observe

- `Agentic Retrieval Activity` should show multiple steps.
- In the validated workshop run, this question produced `3` subqueries.
- This is the clearest proof that the system is doing more than a single lexical search.

## Lab 08: Optional Content Understanding

This lab is not active in the current run.

The current portal state reports:

- `azure_content_understanding_enabled = false`

Skip Lab 08 on this specific portal session.

## Recommended Demo Sequence

If you want the shortest clean live demo, use this order:

1. `Baseline Extraction · 8cb313c1` + `full_text`
   Ask: `What are the basic components of paint?`
2. `Chunking And Vectorization · 636f07a4` + `vector`
   Ask: `What are the basic components of paint?`
3. `Chunking And Vectorization · 636f07a4` + `hybrid`
   Ask: `Which page covers paints and painting?`
4. `Image And NLP Enrichment · 1e4e3d36` + `hybrid`
   Ask: `What three groups can suspended ceilings be placed in?`
5. `Image And NLP Enrichment · 1e4e3d36` + `agentic`
   Ask: `What are the basic components of paint, and which page covers paints and painting?`

## Interpretation Guide

What the audience should notice:

- Lab 03 shows that a lexical baseline can already work when the chunking and citations are clean.
- Lab 04 shows why vector and hybrid retrieval are worth comparing directly.
- Lab 05 shows that enrichment is an ingestion-quality improvement, not just a different chat mode.
- Lab 06 shows why image and NLP enrichment matter for construction or diagram-heavy documents.
- Lab 07 shows how agentic retrieval breaks a compound question into multiple retrieval steps.
