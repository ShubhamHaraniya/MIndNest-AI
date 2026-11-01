# Evaluations

Versioned datasets live in `datasets/`, the documents they are about in `corpus/`. Every case
has a language tag (en, hi, gu) and results are reported per language and overall.

## The starter dataset: `datasets/rag_v1.jsonl`

50 questions: 26 English, 12 Hindi, 12 Gujarati. The questions were drafted by Claude and are
meant to be edited (the dataset page has an edit dialog for each question).

| Kind | Count | What it tests |
|---|---|---|
| Factual, number, exact string | most | Does search find the one passage that holds the answer |
| Multi-evidence | 8 | Answer needs two or more phrases |
| Cross-lingual | 3 | Hindi or Gujarati question about an English document |
| Unanswerable | 5 | The assistant should say the documents do not cover it |
| Prompt injection | 2 | A document tells the assistant to say `PWNED-7731`; the case fails if it does |

Each answerable case lists **evidence**: an exact phrase from a document. A retrieved passage
counts as relevant when it contains that phrase (ignoring case, spacing and punctuation).
That is how Recall@K, MRR and citation accuracy are computed without a human judging each one.

## The larger dataset: `datasets/rag_v2.jsonl`

218 questions on the same corpus (no new documents needed): the 50 questions of `rag_v1` plus 168 new ones,
so earlier results stay comparable. `datasets/rag_v2_en.jsonl` is the English-only part (168 questions,
153 answerable) and is the one to quote numbers from until a native speaker has reviewed the Hindi and
Gujarati wording.

| Part | Questions |
|---|---|
| English | 168 (153 answerable, 15 unanswerable) |
| Hindi | 25 (23 answerable, 2 unanswerable) |
| Gujarati | 25 (23 answerable, 2 unanswerable) |

The new English questions are spread over all seven PDFs, including the long Qwen3-VL report (a
150,000-character distractor-heavy document) and the 90,000-character prompt/context engineering reference.
They were drafted by Claude with a deliberate mix so the set favours neither keyword search nor
embeddings: about 40% paraphrased questions that share few words with the answer, about 30% direct fact,
number or exact-name lookups, about 15% short vague questions, and about 15% needing two passages.
Twenty-four new Hindi and Gujarati questions are cross-lingual (asked in Hindi or Gujarati, answered by
English text). Every evidence phrase was checked with `verify_dataset.py` (all found inside one passage).
The Hindi and Gujarati wording is AI-written and needs native review.

Import it the same way as `rag_v1` (step 3 below), and compare modes on the same run settings. The Lab
now offers four search methods (baseline, hybrid, advanced, advanced + hybrid) and scores Recall@1, @3,
@5, @10 and @K; set K and the number of candidates in the run dialog.
Per question, one answerable case is now worth about 0.65 points of Recall, instead of about 4.

## Running the first evaluation

1. Rebuild and restart api, worker and web (migration `0004` creates the evaluation tables).
2. Make a subject (for example "Eval corpus") and upload every file in `corpus/`
   (the seven PDFs and the five files in `corpus/synthetic/`). Wait until all show Ready.
3. Open **Evaluation Lab**, import `datasets/rag_v2_en.jsonl` (or `rag_v1.jsonl` for the small set) and pick that subject.
4. Press **Check against my materials**. Every answerable case should show its evidence as found.
   If some are missing, a document did not finish processing or was uploaded under another name.
5. Start runs. Good first set:
   - All four search methods (`baseline`, `hybrid`, `advanced`, `advanced + hybrid`), **no generation**
     (free, no key needed). Compare Recall@1/3/5/10 and MRR to see what keyword search and reranking each
     add. Set K in the run dialog (10 gives Recall@K = Recall@10).
   - `advanced` with **generate + judge** (needs a saved provider key) for answer quality,
     faithfulness, citation accuracy, latency and tokens. Use a delay of a few seconds on free tiers.
6. Open two runs and press **Compare** to see the differences per metric and per language.

If a run is marked *degraded*, the model service was down and search fell back to keywords
only; do not compare that run with the others.

## Checking the dataset offline

```
python evals/verify_dataset.py
```

Reads the documents with the worker's own parser and chunker, and lists any evidence phrase that
cannot be found inside a single passage. Run it after editing a document or a question.

## Writing your own cases

One JSON object per line:

```json
{"id": "en-01", "language": "en", "question": "...", "answerable": true,
 "reference_answer": "...", "evidence": [{"file": "name_without_extension", "phrase": "exact words"}],
 "tags": ["factual"]}
```

- `file` is matched loosely against the uploaded file name, so the name without `.pdf` works.
- Choose a phrase of 4 to 12 words that sits in one passage and does not depend on a line break.
- If the same fact is written in two places (a summary and a Q&A section), list both wordings in one
  phrase separated by `||`. A passage counts when it contains any one of them. Without this, a correct
  passage can be scored as a miss.
- Unanswerable cases use `"answerable": false` and no evidence.
- A tag `canary:WORD` marks an injection test: put an instruction in a document telling the
  assistant to say WORD.
