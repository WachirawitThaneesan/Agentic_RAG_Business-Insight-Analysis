# Gemini-Assisted RAG Evaluation on 498 Business Report Questions

## Main Findings

The system was evaluated on the complete set of **498 development questions** drawn from four business reports: CPAXT, EGCO, PTT, and PTTEP. All 498 questions have saved system outputs and valid AI evaluation records. The evaluation provides a complete record of the question set rather than relying on a small demonstration sample.

**All eight answer and evidence quality metrics exceeded 80% under conservative aggregation across the full 498-question set.** The conservative scores range from **85.96% to 96.69%**. This calculation retains every question in the denominator and assigns zero to a metric when its question-level score is unavailable or not applicable.

The results indicate strong performance in retrieving relevant evidence, producing relevant answers, and supporting claims with citations. Context recall reached **96.52%**, answer relevance reached **96.69%**, and faithfulness reached **93.81%**, using the conservative full-set calculation. Citation precision and citation recall reached **93.31%** and **93.71%**, respectively.

## Results Across the Full Question Set

The conservative full-set score is the primary result reported below. The number of assessable questions is also shown to make metric coverage transparent.

| Evaluation Metric | Conservative Score Across All 498 Questions | Assessable Questions |
|---|---:|---:|
| Faithfulness | **93.81%** | 470/498 |
| Factual precision | **89.70%** | 470/498 |
| Factual recall | **89.63%** | 498/498 |
| Context recall | **96.52%** | 498/498 |
| Context precision (Average Precision) | **85.96%** | 497/498 |
| Answer relevance | **96.69%** | 498/498 |
| Citation precision | **93.31%** | 469/498 |
| Citation recall | **93.71%** | 469/498 |

Faithfulness measures whether answer claims are supported by the retrieved evidence. Factual precision assesses the correctness of those claims against the reference evidence, while factual recall assesses coverage of the facts required to answer the question. Context recall measures evidence coverage, and context precision evaluates the ordering of relevant evidence. Answer relevance assesses how directly the response addresses the question. Citation metrics evaluate the citations actually emitted by the system and their support for the corresponding claims.

## Evaluation Method and Scope

The evaluation used a frozen system configuration with lexical-first retrieval. The pipeline combines Typhoon for prose extraction, Gemini for table extraction, and Gemini for answer generation. The corpus contains recorded OCR outputs and previously available report text; this evaluation does not represent fresh OCR processing of every page in all four reports.

AI judgments were checked against the saved answers, captured evidence, and reference material. The audit enforced claim identity and quote-binding constraints, and citation assessment used the application's actual emitted citation links. Operational evaluation failures were recovered using the same saved answers. Previously valid decisions were retained, and answers were not regenerated to select more favorable outcomes.

For a metric with question-level scores between zero and one, the conservative score is calculated as:

**Conservative score = sum of available question-level scores / 498 × 100%.**

Unavailable and not-applicable scores contribute zero. This is a conservative aggregation of the recorded AI assessments, rather than a statistical confidence interval or an independent human certification. Valid evaluation records indicate that the audit outputs satisfy the evaluation protocol; they do not indicate that every answer is correct. The eight percentages are separate quality metrics, rather than a single overall answer-accuracy rate.

The question set was used during development. These findings therefore support a preliminary research presentation; generalization to previously unseen reports remains to be evaluated.

## Technical Challenges and Future Work

### Satisfying All Answer Requirements Simultaneously

Business-report questions often require several conditions to hold together: the correct entity, financial or operational measure, reporting scope, year, unit, required facts, and supporting PDF page. Strong average performance on individual metrics can coexist with a lower success rate when every condition must be satisfied simultaneously for each answer.

As a diagnostic baseline for future work, **302 of 498 answers (60.64%)** satisfied the current complete-answer contract, with **59 answers remaining unresolved under that contract**. This result identifies a stricter integration challenge beyond the eight individual metrics above. Future work will examine incomplete fact coverage, the relationship between cited pages and the reference requirements, and unresolved evidence judgments. Improvements will be assessed against the preserved baseline using the same question set and evaluation rules.

### Preserving Complete Numerical Relationships

A numerical answer must preserve more than its value. It must associate that value with the correct company or subject, measure, unit, sign, performance or target year, document, physical PDF page, and comparison condition. Additional complexity arises from consolidated versus separate results, parent and subsidiary entities, before-and-after values, ranges, and the distinction between a report's publication year and the year of an event or target.

The current strict numerical diagnostic verified **18 of 102 required relationships (17.65%)** across **94 numerical questions**, with **15 relationships remaining unresolved**. This percentage measures complete relationship preservation under the frozen contract, rather than the correctness of the numerical value alone. Literal company and measure checks also require source-based investigation when different expressions may refer to the same underlying relationship; the current scores have not been increased through retrospective alias changes.

Future work will review the requirements of all 94 numerical questions against the original PDFs independently of the system-generated answers. A review packet has been prepared, but the review is not yet complete. This will help distinguish generation errors, missing annotations, and possible ambiguities in entity, measure, year, or page requirements. Any justified reference or measurement revision will be documented, versioned, and applied equally to baseline and candidate systems while preserving the original results.

### Independent Validation and Generalization

The next validation stage will include independent human review and evaluation on previously unseen reports. Further system development will focus on explicit numerical roles and time context, complete fact coverage, and consistent page-level provenance. Controlled comparisons will retain regressions and unresolved cases so that improved annotation coverage is not mistaken for improved factual correctness.

## Summary

The complete 498-question evaluation demonstrates encouraging answer and evidence quality, with **all eight conservative full-set metrics above 80%**. These results provide a credible basis for presenting research progress. Continued work will address the more demanding requirements of complete-answer consistency, numerical relationship preservation, and generalization beyond the development set.

## Supporting Evidence

- [Recorded metrics, coverage, and input hashes](../TestFile/published_2026-10-08/metrics498.json)
- [Lossless archive of saved outputs for all 498 questions](../TestFile/published_2026-10-08/evidence/full498-generation.zip)
- [Per-question evaluation results](../TestFile/published_2026-10-08/contract_details498.json)
- [Strict numerical diagnostics for all 102 required relationships](../TestFile/published_2026-10-08/numeric_diagnosis102.json)
- [Prepared source-review protocol and checkpoint archive](../TestFile/published_2026-10-08/evidence/source-review-and-checkpoints.zip)

The [publication package](../TestFile/published_2026-10-08/README.md) lists archive contents and checksums. Original local file bytes are preserved inside the selected archives. Source PDFs are supplied separately.
