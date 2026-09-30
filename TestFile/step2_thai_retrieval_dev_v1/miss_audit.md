# Thai retrieval miss audit (development set)

This audit covers the **15 misses in the frozen app top five**, scored under
the conservative v3 AI PDF evidence review. “New rank” is the first accepted
physical PDF page in the revised app top five; `>5` remains a strict miss.
Several causes overlap. The explanations combine saved rankings with inspection
of the source PDF text and layout; they are diagnostic observations, not a
separate causal experiment for every question.

| Question | Target page | Observed reason the frozen app missed | New rank |
| --- | --- | --- | ---: |
| TF01 | SCBX 9 | The revenue infographic is short; dense results favoured longer revenue discussion pages. The new app puts page 9 at rank 7. SCBX page 19 ranks first and appears to state the same 2567 operating revenue, but it is **not** an accepted alternate in v3. | >5 |
| TF02 | SCBX 9 | The NPL ratio appears in the infographic, while semantic and hybrid results favoured other asset-quality pages. Thai keyword ranking surfaces the infographic. | 1 |
| TF03 | SCBX 19 | PDF text repeats Thai vowel and tone marks in the financial table; other balance-sheet pages ranked above it. Normalizing searchable text surfaces the table. | 1 |
| TF04 | SCBX 19 | The deposit row has the same broken Thai font encoding, and the original keyword arm included Thai Union pages. Company scoping and normalization surface SCBX 19. | 1 |
| TF05 | SCBX 19 | The 2566 comparison value is in the 2567 report table. Query contains both 2566 and “not 2567,” so a strict report-year filter would be unsafe. | 2 |
| TF06 | SCBX 19 | Other SCBX net-profit narratives, especially page 111, competed with the parent-attributable table row. Page 111 remains insufficient for this exact question under v3. | 2 |
| TF07 | SCBX 19 | NIM occurs on several pages; the compact 3.8% table row remains below the first five in the new app (rank 7). Page-aware layout regions rank page 19 third in the separate layout test. | >5 |
| TF08 | SCBX 20 or 252 | The EPS table text has repeated Thai marks. The accepted alternate note on page 252 is retrieved first. | 1 |
| TF11 | Thai Union 18 | On the infographic, the chart label and 138.4 value are separate PDF text objects. The page now ranks second, but this does not prove the label/value pair was preserved for answering. | 2 |
| TF12 | Thai Union 18 | The EBITDA chart caption sits above its values; the original full-page chunks buried that layout relationship. The page now ranks first. | 1 |
| TF13 | Thai Union 18 | The liabilities chart has the same separated label/value layout and PDF font artifacts. The page now ranks first. | 1 |
| TF15 | Thai Union 18 | The dividend-per-share chart was overshadowed by dividend text elsewhere. Company scoping and normalized term matching rank the infographic third. | 3 |
| TF16 | Thai Union 21 | The DJSI statement is on page 21, but semantic results favoured other sustainability pages. Thai keyword ranking ranks it first. | 1 |
| TF19 | Thai Union 65 | This physical PDF page contains a two-page printed spread. Ratio labels and year values occupy separate text blocks; the new page ranking finds it, but exact cell association still requires checking. | 1 |
| TF20 | Thai Union 65 | The inventory-days row has the same spread layout and corrupted Thai glyphs. The new page ranking finds it. | 1 |

The new app misses **TF01 and TF07** by the strict v3 page rule. The first
unscored alternate for TF01 (SCBX page 19) should be checked in a new,
separately versioned adjudication before anyone treats it as a citation pass.
No label or frozen result was changed for this retrieval experiment.
