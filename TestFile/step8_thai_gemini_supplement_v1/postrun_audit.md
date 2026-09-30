# Post-run audit of the supplemental Gemini answers

The saved `metrics.json` remains the automatic score from the frozen
supplemental method. This audit was performed after predictions and does not
change that score or the reference labels. Independent second review is still
pending.

- **TF10, app Gemini:** The response says SCBX Gen 2 contributed **16%** of
  2567 revenue and exposes the preselected SCBX physical PDF page **33**.
  The reference is 16% on page 33. The numeric scorer returns `False` because
  it parses `Gen 2` as another answer number. Replacing just `Gen 2` with
  `Gen two` makes the same answer pass. This is a scorer false negative in
  the automatic **2/20** app result. It does not justify changing any other
  prediction or claiming general accuracy.
- **TF09, app Gemini:** The response says **10.44 baht**, matching the
  reference value, but does not expose the preselected PDF page **20**.
  The fact counts correct, while strict labeled-page exposure does not.
- **TF18, app Gemini:** The response says the Thai Union tuna market grew
  **12%** and exposes the preselected physical PDF page **40**. Both the
  fact and strict page check pass.
- **TF08, BM25 + Gemini:** The response says **13.05 baht**, matching the
  reference value, while its top-three passage list misses preselected SCBX
  page **20**. The automatic fact score passes but strict page exposure fails;
  this is not a verified source-grounded answer.

The 20 questions come from two reports and several share pages. The online
run followed inspection of the offline final scores. The automatic totals
remain **6/20** for BM25 + Gemini and **2/20** for app Gemini.
