# Checkpoint A: OCR Gemini และ numeric/context — 8 ตุลาคม 2026

รอบนี้แก้ header normalization, schema/prompt ของ Gemini table reader, การเก็บ source metadata และ numeric capture พร้อม paired development evidence. **Quality goal รวมยัง partial**; ยังไม่เริ่ม Docling, B/C หรือ final generation/audit เดิมซ้ำ ไม่มี commit/push/deploy หรือการเขียน/ลบ production DB

Scope ของ OCR คือ **Gemini อ่านตารางใน pipeline เดิม Typhoon-text/Gemini-tables** ตาม config จริง ไม่ใช่ Gemini-only ทั้งข้อความและตาราง ผู้ใช้สั่งทำต่อหลังปรับแผน จึงใช้ระบบเดิมเป็น working assumption และแจ้ง scope ก่อน dispatch. Gemini คง targets เดิม; เฉพาะ Docling รอบหลังไม่บังคับ >90%

## ผล OCR ที่เทียบได้

เลือก physical development pages 8 หน้า/4 รายงานก่อน candidate changes ผ่าน production region renderer 300 DPI เป็น 10 regions. Numeric denominator เป็น 169 เซลล์บน 5 หน้าตาราง/3 issuers; อีก 3 หน้าเป็น layout/key-value/negative controls ไม่ใช่ numeric denominator. Codex ตรวจภาพ PDF ต้นฉบับ; human_confirmed=false

| ระบบ/วิธี | ผ่าน strict source-cell | Accuracy | Numeric unknown | Regional errors |
|---|---:|---:|---:|---:|
| Live baseline / prompt เดิม | 123/169 | 72.78% | 0 | 1/10 |
| Live candidate1 / prompt+schema | 151/169 | 89.35% | 0 | 0/10 |
| Live candidate2 / prompt refinement | 124/169 | 73.37% | 0 | 0/10 |
| Candidate2 raw + deterministic header replay | **166/169** | **98.22%** | **0** | **0/10** |

ทุกแถวใช้ **reference v3 และ scorer functions เดียวกัน**. Baseline→final replay กู้43เซลล์ ถอย0; ห้ามตีความผลเป็นการเลือก best answer รายข้อ: ใช้ candidate2 ทั้งชุดแล้วสลับ normalizer เดียวกันทั้งหมด. Prompt-only results ที่ไม่ดีเก็บครบ และชี้ว่าการย้ำ prompt อย่างเดียวไม่เสถียร

Final row เป็น **local replay บน raw SDK output จริง** ไม่ใช่ fresh cloud generation หลัง normalizer patch. Raw10/10regions ของ candidate2 reproduce saved tables ด้วย old normalizer ก่อนใช้ new normalizer. ไม่มีข้อมูล reference ถูกส่งเข้า inference. Scorerตรวจ unique row/year/statement scope, signed value, explicit unit และ registered physical page; ไม่เลือก matching location ที่คะแนนดีที่สุด. Source images/hash/model/temperature เดียวกันทุก live arm

Normalizing เฉพาะ audit-status column ที่ว่างทุกแถว มีวันที่ตรงกับคอลัมน์งบข้างหน้า และไม่มี data values ของตนเอง ทำให้ compound header กลับเป็นคอลัมน์เดียว โดยไม่สร้างค่า/ปีใหม่. Columnsที่มีค่า ต่างวันที่ หรือเป็นงบคนละประเภทไม่ถูกยุบ. เก็บ original header/index repair provenance ผ่าน raw artifacts, normalized tables, chunks และ page API

ยังผิด3เซลล์บนCPAXT132เพราะชื่อรายการ “เงินลงทุนในบริษัทร่วม” ถูกอ่านเป็น “เงินลงทุนในบริษัทรวม”. ค่าตัวเลขตรงแต่ relation ไม่ผ่าน ไม่แก้ด้วย gold replacement. Per-page correct: CPAXT13242/45, CPAXT13321/21, CPAXT13451/51, EGCO3712/12, PTT3940/40. ตัวเลขนี้ไม่ใช่ full-report accuracy หรือ unseen test; CI bootstrap ของ5 source pages ใน METRICS.json เป็น descriptive และกว้าง

## Reference corrections และข้อจำกัดการวัด

- v1→v2: ผมอ่านส่วนบนของCPAXT134พลาดและกำหนดให้ต้องใช้หัวจาก133 ทั้งที่134มีหัวครบ. ตรวจภาพขยายแล้วถอนข้อกำหนดนั้น; prototype continuation ถูกเก็บเป็น rejected และไม่ได้ใช้ในแอป
- v2→v3: เพิ่ม qualifier ที่พิมพ์จริง “ชำระภายในหนึ่งปี” ให้3lease selectors เพื่อแยกจาก noncurrent row. คง value/unit/year/page และ scoring functions เดิม. เป็น reference repair ที่เข้มขึ้น ไม่ใช่ system gain
- ทุก reference version และคะแนนก่อนแก้เก็บครบ. Main comparison คำนวณ baseline/candidate ใหม่ด้วยv3เดียวกัน; ห้ามนำ72/169จากv1มาเทียบ166/169แล้วอ้าง system delta
- Candidateยังแปลง numbered company list บนPTT39leftเป็นตาราง แม้เนื้อหารายชื่อมีจริง; table-structure precision ยังไม่ certified. PTT85navigationคืน0tablesทั้งสองregions. CPAXT38key/value N/Aไม่คืนเป็นตารางในcandidate2; prose retention/end-to-end effectยังไม่ได้วัดใหม่
- PTTEP223เป็นmerged continuation; entityของแถวแรกไม่อยู่ในหน้าปัจจุบัน จึงไม่สร้าง full numeric score จากแถวนั้น. ยังไม่มีคะแนน chart relations หรือ whole-page CER/WER. คะแนน125/132ในaudit191probesเก่าและ16cellbenchmarkเป็นคนละชุด/วิธี ห้ามใช้เป็นpaired delta

## Stage4 source/context checkpoint

Page endpointเดิม reparses Typhoon prose ที่ถูกเอาGemini tablesออกไปแล้ว จึงคืนraw_tablesว่าง และ rebuild stored tablesโดยทิ้งcaption/page/provider/unit. แก้ให้ใช้ raw table chunksจริง เก็บgeometry/unit/header repairs และคืน source metadataจากstored rows/chunksของtable identityเดียวกัน. Metadataที่ไม่มีหรือขัดกันคงunknown และไม่ยืมจากตารางข้างเคียง

ใช้ helperเดียวกันกับ single-page และ bulk data endpoints และไม่รวม distinct table names/pages/headers ด้วย display prefix. Local stored-row/chunk reconstruction7/7tablesผ่าน caption/page/provider/source hash/unit/raw-artifact checks และไม่เปลี่ยนheaders/values. นี่เป็น **local replay**, ไม่ใช่ actual upload/ingestion acceptance รอบใหม่; งานนั้นอยู่B

## Stage2 numeric/capture checkpoint

Capturev1.9แก้ false rejection ของ numbered identifiers เช่น “ครั้งที่1”, “หุ้นกู้ลำดับที่10”, proper-nameท้ายเลข และ compound unit “ร้อยละต่อปี”. ปริมาณจริงในmeasure เช่น63แห่ง/9เดือนยังถูกปฏิเสธเมื่อไม่มี annotationแยก. ไม่เติม document/page/valueจากgoldและไม่เปลี่ยนproseที่บันทึกไว้

Replay532saved answers: พบ exact raw generation479, อีก53คงoriginal captureไว้โดยไม่ reconstruct. Answer/claims/citations/contextทุกrecordไม่เปลี่ยน. Capture recovered10records, regressions0; strict numeric regressions0. Primary lexical_first captured124→127/133 (93.23→95.49%); required numeric measurable106→109/114 (92.98→95.61%). **Strict correctยัง22** จึงเป็น22/109=20.18%บนmeasured subset ไม่ใช่ความแม่นยำ95%

Across4arms: captured498→508/532; numeric measurable421→434/456; correct66→69. การเปิดให้วัดได้มากขึ้นเผย known wrong relations เพิ่มด้วย จึงไม่ใช่การเพิ่มคะแนนโดยซ่อนfailures

ตรวจ source6pages/4casesแยก: H004_1เป็นliteral wording/legal-name differenceที่sourceรองรับ; H037_3เป็นissuer-vs-project field scope; H022_1มีข้อมูลซ้ำถูกต้องบนphysical114แม้labelล็อก6; H007_1เลือกtotal net profit4040.30แทน2184ที่footnoteนิยามattributable to parent. Frozen RAGlabels/scorer/aliasesและraw scoresไม่เปลี่ยน. ไม่ถือว่า20literal-onlyfailuresทั้งหมดควรผ่าน; อีก18ยังไม่ตรวจต้นฉบับในรอบนี้. Gold-page difference28กรณีเดิมไม่เท่ากับwrong emitted physical page: accepted factsผูกกับregistered source pageแล้ว

36judge failuresเดิมคงunresolved:13non-JSON/empty-response outcomes,21invalid/missing evidence fragments,2invalid claim identity schema. ไม่มี retry เพราะการทดลองนี้ไม่ได้เปลี่ยนsaved answersและไม่ควร rerun final audit เพื่อเพิ่มheadline; exact-payload protocolต้องรักษาหากมีเหตุผลretryภายหลัง

## Tests, usage และงานต่อ

Broad regression323passed; focused storage/chunk checks7passed (มีoverlapกับbroad), one preexisting Pydanticwarning. Offline reproductionของfinal header replayกลับได้166/169. Source/labels/scorer hashes, code snapshotและisolated patchอยู่ในevidence root. No owned evaluation processค้าง

Actual SDKเพิ่ม36attempts:baseline15(5SDKerrors),candidate1 11(1SDKerror),candidate2 10. Known inputเพิ่ม126,680/output14,419;6failed calls usageไม่ครบ. สะสม **SDK≥3347/input≥54,473,794/output≥1,816,995**, failed-usage-unknown330. Ledgerkeys74รวม8originalPDF/pagekeysใหม่;เป็น8หน้าที่อ่านซ้ำ ไม่ใช่8unseenpages และhistorical derivative keysไม่ถูกreset. Interrupted historical usageยังunknown; USDcost=N/A

เป้าหมายGeminiรวมยังไม่จบ: retrieval, full ingestion acceptance, answer/citation/strict numeric quality และunseen reportsยังต้องทำตามA/B/C. ก่อนBต้องfreeze stable source/corpus/codeจากcheckpointและรักษาremaining source/reference issues. ไม่เปิดDoclingก่อนGemini evaluationจบ. ดู HANDOFF_B.md และ COMMANDS.md สำหรับขอบเขต/คำสั่งรับช่วง

Evidence: `TestFile/evaluation_A_2026-10-08/`; metrics: `METRICS.json`; patch: `stage_A.patch`; checkpointsแยก `stage2_capture_replay/`, `stage2_source_review/`, `stage4_storage_replay/`, `gemini_ocr/`. Old final answers/reference/scorerและverified archiveไม่ถูกเขียนทับ; active resource ledgerอัปเดตตามactual attempts
