# AI visual audit of all 20 Thai final reference facts

**Reviewer:** Codex AI assistant, 2026-09-28. **Scope:** original source PDFs,
not extracted OCR, search snippets, or model predictions. This is a second
visual pass over every labeled *physical PDF page*, with text extraction used
as a cross-check for disputed financial-note passages. It is **not** an
independent human review or evidence that AI review is more accurate than a
qualified human reader.

- SCBX 2567 annual report: 351 pages, SHA-256
  `c9f3b1fd6951f696023ae87111797bfefd2dfb49cbdf36e164260d673903a10d`.
- Thai Union 2567 One Report: 217 physical pages, SHA-256
  `61eba982038eb8382a2c78412738fc2562ff2f3ee83d0ffb29d6afc585a3dbd1`.
  Each physical page is a two-page printed spread.

The **20/20 primary labels match** the displayed value, year, unit, and
measure on their cited original PDF pages. Several questions share a page;
20 checks are not 20 independent documents.

| ID | Physical PDF page | Observed original-page evidence | AI decision |
| --- | --- | --- | --- |
| TF01 | [SCBX 9](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=9) | Operating revenue, 2567: **172.4 billion baht**; the separate net-profit card is 43.9. | Matches |
| TF02 | [SCBX 9](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=9) | Non-performing loans divided by total loans: **3.37%**; the separate CET1 ratio is 17.7%. | Matches |
| TF03 | [SCBX 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | Consolidated financial position, total assets, 2567 column: **3,487 billion baht**. | Matches |
| TF04 | [SCBX 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | Consolidated financial position, deposits, 2567 column: **2,474 billion baht**. | Matches |
| TF05 | [SCBX 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | Consolidated performance, total operating income, **2566** column: **171.1 billion baht**. | Matches |
| TF06 | [SCBX 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | Consolidated performance, net profit **attributable to the company**, 2567: **43.9 billion baht**. | Matches |
| TF07 | [SCBX 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | Consolidated financial ratios, net interest margin (NIM), 2567: **3.8%**. | Matches |
| TF08 | [SCBX 20](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=20) | Securities table, earnings per share, 2567: **13.05 baht**. | Matches |
| TF09 | [SCBX 20](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=20) | Securities table, dividend per share for 2567: **10.44 baht**. A footnote says the final dividend was proposed for shareholder approval in 2568. | Matches, with proposal caveat |
| TF10 | [SCBX 33](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=33) | Revenue-share table, **Gen 2**, 2567 column: **16%**. The `2` is part of the segment name. | Matches |
| TF11 | [TU 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | Financial infographic, sales revenue, 2567: **138.4 billion baht**. | Matches |
| TF12 | [TU 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | Financial infographic, EBITDA, 2567: **13.4 billion baht**. | Matches |
| TF13 | [TU 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | Financial infographic, total liabilities, 2567: **98.6 billion baht**. | Matches |
| TF14 | [TU 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | Financial infographic, net profit attributable to owners of parent, 2567: **5.0 billion baht** at one displayed decimal. | Matches displayed precision |
| TF15 | [TU 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | Per-share infographic, dividend per share, 2567: **0.66 baht**. | Matches |
| TF16 | [TU 21](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=21) | DJSI sustainability image for 2567 visibly states **85/100 points**. | Matches |
| TF17 | [TU 21](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=21) | FTSE4Good Emerging Index heading states **9 consecutive years**. | Matches |
| TF18 | [TU 40](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=40) | Tuna competition narrative says first-half 2567 trading grew **12%** year on year. | Matches |
| TF19 | [TU 65](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=65) | Operating-efficiency table, average collection period, 2567: **36 days**. | Matches |
| TF20 | [TU 65](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=65) | Same table, average inventory period, 2567: **152 days**. | Matches |

## Alternate evidence and rounding decisions

| ID | Proposed page | AI decision | Reason |
| --- | --- | --- | --- |
| TF06 | [SCBX 111](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=111) | **Exclude as complete alternate** | It reports *consolidated net profit* of 43.9 billion baht, but does not explicitly say *attributable to the company*. It corroborates the amount, while page 19 supports the exact requested row. |
| TF08 | [SCBX 252](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=252) | Accept | Note 41 gives consolidated basic earnings per share of 13.05 baht in the 2567 column. |
| TF09 | [SCBX 252](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=252) | Accept with proposal caveat | Note 42 states a proposed dividend of 10.44 baht per share for 2567 operations. This agrees with the page 20 table and its footnote. |
| TF14 | [TU 194](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=194) | Accept with declared rounding | The 2567 consolidated column gives 4,984,894 **thousand** baht for parent-owner profit from continuing operations and shows no discontinued-operation amount. That is 4.984894 billion baht, which rounds half up to the page 18 display of 5.0 billion at one decimal. Company-only columns and other profit rows do not qualify. |

The [conservative AI adjudication](heldout_thai_final_adjudication_v3_ai_review.json)
and [separate rescore](step8_thai_rescore_v3_ai_review/README.md) retain the
frozen 2026-09-27 metrics. The previous v2 rescore remains a historical
provisional pass that counted SCBX page 111. Neither rescore is a new test or
evidence of improved model performance.
