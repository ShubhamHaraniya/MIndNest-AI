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

## Running the first evaluation

1. Rebuild and restart api, worker and web (migration `0004` creates the evaluation tables).
2. Make a subject (for example "Eval corpus") and upload every file in `corpus/`
   (the seven PDFs and the five files in `corpus/synthetic/`). Wait until all show Ready.
3. Open **Evaluation Lab**, import `datasets/rag_v1.jsonl` and pick that subject.
4. Press **Check against my materials**. Every answerable case should show its evidence as found.
   If some are missing, a document did not finish processing or was uploaded under another name.
5. Start runs. Good first set:
   - `baseline`, `hybrid` and `advanced` search, **no generation** (free, no key needed). Compare
     Recall@K and MRR to see what keyword search and reranking each add.
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
