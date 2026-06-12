# Lab 06 - Visual And NLP Enrichment

## Goal

Add visual and language-oriented skills to the same document:

- `OcrSkill`
- `ImageAnalysisSkill`
- `LanguageDetectionSkill`

Then compare how `Hybrid` retrieval changes for diagram-heavy or image-heavy questions.

Set:

```dotenv
WORKSHOP_SKILL_PROFILE=visual_nlp
```

## Step 1 - Restart the app

Restart after changing `.env`.

## Step 2 - Verify the active profile

Open [http://127.0.0.1:8016/api/workshop/profiles](http://127.0.0.1:8016/api/workshop/profiles) and confirm:

- `active_profile_id` is `visual_nlp`
- the target enrichment index name ends with `-visual-nlp`

## Step 3 - Upload the same document again

Use the same diagram-heavy file.

## Step 4 - Use `Hybrid` retrieval mode

This lab keeps the retrieval mode fixed on `Hybrid` so the audience can isolate the effect of the new skills.

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
- enrichment metadata includes OCR or image-analysis outputs
- the enrichment index recorded in the job ends with `-visual-nlp`
- hybrid retrieval shows stronger evidence for diagram- or figure-oriented questions than the previous lab

## What To Inspect In This Repo

```text
Profile: visual_nlp
Built-in skill focus:
- OcrSkill
- ImageAnalysisSkill
- LanguageDetectionSkill

Retrieval focus:
- hybrid
- optional comparison with agentic retrieval
```

- [`backend/services/workshop_profiles.py`](../../backend/services/workshop_profiles.py)
  The `visual_nlp` profile declares the visual and language-oriented enrichment track.
- [`backend/services/search_skillset_enrichment.py`](../../backend/services/search_skillset_enrichment.py)
  Inspect `_profile_uses_visual_nlp()`, `_build_ocr_skill()`, `_build_image_analysis_skill()`, and `_build_language_detection_skill()`. This is where the Search-managed skillset adds OCR text, image descriptions, and detected language.
- [`backend/services/parsers.py`](../../backend/services/parsers.py)
  Inspect the figure extraction and normalization path. This helps explain the difference between parser-side figure handling and Search-managed OCR or image analysis.
- [`backend/services/chat.py`](../../backend/services/chat.py)
  Inspect the evidence hydration path if you want to explain how OCR or image-derived evidence becomes visible in the portal.

## Learn References

- [OCR skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-ocr)
- [Image Analysis skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-image-analysis)
- [Language Detection skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-language-detection)
- [Extract text from images with AI enrichment](https://learn.microsoft.com/en-us/azure/search/cognitive-search-concept-image-scenarios)
