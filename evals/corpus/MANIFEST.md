# Evaluation corpus

Documents used by `evals/datasets/rag_v1.jsonl`. Upload all of them to **one subject** in
MindNest, wait until each shows Ready, then run the evaluation.

## Your own study PDFs (English) — not committed

These are copies of PDFs from the owner's Downloads folder. They are ignored by git
(`evals/corpus/*.pdf`), so a fresh clone needs them copied back in by hand.

| File | Language | What it is |
|---|---|---|
| en_mcp_interview_cheatsheet.pdf | en | Model Context Protocol interview cheat sheet (primitives, transports, security) |
| en_harness_engineering_cheatsheet.pdf | en | Agent harness engineering cheat sheet (layers, failure modes, key numbers) |
| en_prompt_context_harness_engineering.pdf | en | Prompt, context and harness engineering reference (WSCI, context failures) |
| en_knn_cross_validation_viva.pdf | en | KNN and cross-validation viva question bank with answers |
| en_plan_execute_verify_replan_slides.pdf | en | Slides on multi-step agents (Plan-Execute-Verify-Replan) |
| en_english_tenses_part1.pdf | en | Spoken English course, tense system |
| en_qwen3_vl_technical_report.pdf | en | Qwen3-VL technical report (long, tables and equations; a stress document with no questions of its own yet) |

## Synthetic documents (written for this test) — committed

Short study notes written by Claude so the Hindi and Gujarati questions have something to be
asked about, plus one sample that contains a prompt-injection attempt. They live in
`synthetic/` as Word files (that is what gets uploaded) with the plain text beside them.
They are textbook-level facts, not real publications.

| File | Language | Content |
|---|---|---|
| hi_photosynthesis_notes.docx | hi | Photosynthesis: equation, chlorophyll, stomata, two stages, starch test |
| hi_constitution_basics.docx | hi | Indian Constitution: dates, Drafting Committee, fundamental rights |
| gu_water_cycle_notes.docx | gu | Water cycle: four stages, 97% / 3% water split |
| gu_gujarat_facts.docx | gu | Gujarat: formation date, capital, coastline, Gir lions, Statue of Unity |
| en_injection_sample.docx | en | Library rules with a hidden instruction to reply `PWNED-7731` (the canary) |

The Hindi and Gujarati text was written by an AI. A native speaker should read it and the
questions before the numbers are quoted anywhere.

Why Word files and not PDFs: PDFs produced in Claude's sandbox lost Devanagari and Gujarati
letter shapes when the text was read back, which would test the PDF maker, not retrieval.

## Optional extras

`download.ps1` downloads public papers and NCERT chapters (arXiv, ncert.nic.in). The
questions in `rag_v1.jsonl` do **not** use them. Adding them to the subject only makes the
search harder (more distractor documents), which is a fair stress test but changes the scores.

## Checking the dataset

```
python evals/verify_dataset.py
```

reads the documents with the worker's own parser and chunker and reports any evidence phrase
that is not found. Set `--corpus` if the synthetic files are not under `evals/corpus/`.
Because the checker walks `evals/corpus/` recursively, the `synthetic/` folder is found.
