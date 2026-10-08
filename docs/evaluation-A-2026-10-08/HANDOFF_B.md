# รับช่วง B: Retrieval + real ingestion ของระบบ Gemini

อ่าน `REPORT_th.md`, `METRICS.json` และ `docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md` เฉพาะล่าสุด. ต่อgoalเดิม ไม่สร้างbudgetใหม่. B/Cยังไม่dispatch. Doclingค่อยทำหลังจบGemini; Geminiยังใช้targetsเดิม

Stage2checkpoint: binder1.9 raw replay479/532, primarycapture127/133และnumericmeasurable109/114, strictcorrect22/109. Sourceclassifications4casesไม่เปลี่ยนRAGlabels/scorer/aliases. อีก18literal-onlycasesและsource-page alternativesยังไม่reviewครบ ต้องคงunknown/constraint differencesตามจริง.36judgesเดิมยังunresolved;ห้ามปลอมpasses/retryเพื่อheadline

Stage4checkpoint: Gemini table component8physicalpages/10regions/169cells, baseline123/169→candidate2+local header normalization166/169, recovered43/regressed0. Referencev3แก้source-labelerrorsอย่างเปิดเผย;ทุกoldversionเก็บไว้. Prompt-onlyv1/v2และrejectedcontinuationprototypeเก็บครบ.166/169เป็นdevelopment/replay ไม่ใช่fresh final/unseen. Remaining3CPAXT132row-labelOCRerrors; numbered-list/table and N/A key/value caveatsในreport

Repoauto1/HEAD5060072892320ddf9a1ea4a3b4c317b424c3b33a, dirty/untrackedเดิมเก็บครบ. Snapshot/hash/patch `TestFile/evaluation_A_2026-10-08/{CODE_LOCK.json,candidate_code,stage_A.patch}`. Stable inputs/references/images/raw SDK outputsอยู่ `gemini_ocr/`; RAGoriginal labelsยังอยู่final133_v2 unchanged. Localstorage replay7tablesผ่าน แต่ยังไม่ใช่actualingestion acceptanceใหม่

Activeledger `TestFile/evaluation_completion_2026-10-07/resource_ledger.json`: SDK≥3347,input≥54,473,794,output≥1,816,995;330failedusageunknown;74paidpagekeys. ไม่มีprojectdeadline/countcaps.ใช้pacing/providerlimits,meterทุกSDKattempt;ไม่resetledger/journals. No owned running processes ณส่งต่อ;ตรวจRUN_STATE/PIDsอีกครั้ง. ไม่push/deploy/ลบproductionDBหรืออ้างhuman certification

Next local command: `.venv/Scripts/python.exe -m scripts.replay_gemini_header_repair --help` แล้วอ่านsource/corpus/preparation scriptsเดิมเพื่อสร้าง isolated staged corpusจากactualacceptedOCR evidenceพร้อมsource/page mappings. อย่าเริ่มranking sweepบนstale native corpusแล้วอ้างว่าGeminiOCRดีขึ้น; freeze corpus/versionก่อนpaired retrieval. Ingestion acceptanceต้องใช้real upload/scraped routeและtestDBแยก;ดู `scripts/run_ingestion_smoke_v4.py` และexistingintegration32plansก่อนdispatch ไม่จำเป็นต้องOCRทั้งรายงานซ้ำ

เมื่อBเสร็จค่อยhandoffCเพื่อfreezeใหม่และรายงานใหม่. final133ที่ใช้วิเคราะห์เป็นdevelopmentแล้ว. Qualitygoalยังpartial ไม่มีอนุญาตให้เลือกbestanswers/เปลี่ยนคะแนนเพื่อข้ามgates
