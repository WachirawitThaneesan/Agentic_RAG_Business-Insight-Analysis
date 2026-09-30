# Post-run Thai final evidence audit

This inspection happened **after** the frozen 20-question output. It does not
change `metrics.json`, the reference labels, or the method lock. One reader
checked the noted original PDF pages visually; an independent reviewer is
still needed before using these judgments as thesis ground truth.

| Item | Saved result | Original-PDF inspection | Interpretation |
| --- | --- | --- | --- |
| TF01, SCBX PDF p. 9 | BM25 retrieved the labeled page but answered **43.9 billion baht**. | Page 9 labels **172.4 billion** as operating revenue and **43.9 billion** as net profit. | Correct-page retrieval did not preserve the measure/value relationship. Automatic answer failure stands. |
| TF02, SCBX PDF p. 9 | BM25 retrieved the labeled page but answered **17.7%**. | Page 9 labels **3.37%** as non-performing loans / loans and **17.7%** as CET1 capital. | Another row/label mix-up; automatic failure stands. |
| TF06, SCBX PDF pp. 19 and 111 | The agent answered **43.9 billion baht** but cited p. 111 rather than the preselected p. 19. | Page 111's 2567 performance paragraph explicitly reports SCBX net profit **43.9 billion baht**; p. 19 has the detailed consolidated table. | The automatic fact score is correct; the one-page citation label likely understates valid evidence. The strict citation score remains unchanged. |
| TF10, TF16, TF17 | BM25 answered **16**, **85**, and **9** and cited the labeled pages 33, 21, and 21, respectively. | The pages show **16%** Gen 2 revenue, **85/100 points** DJSI, and **9 consecutive years** in FTSE4Good. | The bare numbers are plausible given the question wording, but the automatic grader requires an explicit unit. All three remain `needs_review`, not automatic passes. |
| TF14, Thai Union PDF pp. 18 and 194 | BM25 answered **4,984,894 thousand baht** on p. 194; the preselected infographic p. 18 says **5.0 billion baht**. | Page 194's 2567 consolidated note labels 4,984,894 thousand baht as net profit attributable to the parent from continuing operations, with no discontinued-operation amount. That is 4.984894 billion baht, which rounds to 5.0 billion at the infographic's precision. | A one-reader post-run audit finds the answer numerically and contextually equivalent, with a valid alternate source page. The exact automatic answer and citation failures remain unchanged. A future grader should define rounding precision *before* an untouched test. |
| TF18, Thai Union PDF p. 40 | The agent exposed the labeled page but abstained. | The tuna narrative states first-half 2567 trade grew **12%** year on year. | Retrieval alone did not yield an answer. Automatic answer failure stands. |

These examples show why page Hit@5, fact correctness, and citation validity
must be reported separately. The reference identifies one expected page per
question; annotating every alternate support page and acceptable rounding
requires an independent pass before future testing.
