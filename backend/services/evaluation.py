"""Ragas Evaluation Pipeline.

Metrics covered:
1. Context Precision (ความแม่นยำของ Context ที่ถูกดึงมา)
2. Context Recall (ความครอบคลุมของ Context ที่ถูกดึงมาเมื่อเทียบกับเนื้อหาจริง)
3. Faithfulness (คำตอบอ้างอิงจาก Context ที่หามาได้จริง ไม่แต่งเอง)
4. Answer Relevancy (คำตอบตรงคำถามหรือไม่)

Usage:
    python -m backend.services.evaluation
"""

import os
import json
import logging
import asyncio
import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy,
    answer_correctness,
    answer_similarity
)

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

async def run_evaluation(data: list[dict], output_csv: str = "ragas_evaluation_results.csv"):
    """
    Run Ragas evaluation on a list of samples.
    """
    from langchain_ollama import OllamaEmbeddings
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig
    
    logger.info("Configuring Ragas evaluator to use OpenTyphoon 30B v2.5 (Cloud) and Local Nomic Embeddings...")
    
    # 1. Evaluator (Judge): Use Typhoon 30B v2.5 for high-precision JSON parsing
    typhoon_api_url = settings.TYPHOON_OCR_ENDPOINT.replace("/ocr", "") if settings.TYPHOON_OCR_ENDPOINT else "https://api.opentyphoon.ai/v1"
    evaluator_llm = ChatOpenAI(
        model="typhoon-v2.5-30b-a3b-instruct",
        api_key=settings.TYPHOON_API_KEY,
        base_url=typhoon_api_url,
        temperature=0.1,
        max_tokens=4096,
        max_retries=2
    )
    
    # 2. Embeddings: Keep using Nomic (Local) since chunks were embedded with it
    local_embeddings = OllamaEmbeddings(model=settings.EMBED_MODEL, base_url=settings.OLLAMA_HOST)
    
    ragas_llm = LangchainLLMWrapper(evaluator_llm)
    ragas_emb = LangchainEmbeddingsWrapper(local_embeddings)

    df = pd.DataFrame(data)
    dataset = Dataset.from_pandas(df)

    # Check if ground_truth is fully populated (required for Recall/Precision)
    has_ground_truth = all(bool(str(d.get("ground_truth", "")).strip()) for d in data)
    
    if has_ground_truth:
        logger.info("Ground truth is properly provided. Running ALL metrics (Including relaxed semantic metrics).")
        metrics = [context_precision, context_recall, faithfulness, answer_relevancy, answer_similarity, answer_correctness]
    else:
        logger.warning("Some records are missing 'ground_truth'. Running only reference-less metrics (Faithfulness, Answer Relevancy).")
        metrics = [faithfulness, answer_relevancy]

    logger.info(f"Running Ragas evaluation on {len(data)} samples using Local Ollama...")
    
    run_config = RunConfig(timeout=600, max_workers=1, max_retries=2)
    
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=ragas_llm,
        embeddings=ragas_emb,
        run_config=run_config,
    )
    
    result_df = result.to_pandas()
    result_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    logger.info(f"Evaluation complete. Results saved to {output_csv}")
    
    print("\n" + "="*40)
    print("      Ragas Evaluation Scores     ")
    print("="*40)
    # Safely compute mean from dataframe due to changing ragas EvaluationResult API
    for metric in metrics:
        if metric.name in result_df.columns:
            score = result_df[metric.name].mean()
            print(f"{metric.name:20s}: {score:.4f}")
    print("="*40 + "\n")
    
    return result

async def save_qa_log(question: str, answer: str, contexts: list[str]):
    """Save real-time query to a history file for later batch evaluation."""
    log_entry = {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": ""  # Leave blank for users to fill in manually later
    }
    
    log_file = "qa_history.json"
    
    try:
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = []
    except Exception:
        history = []
        
    history.append(log_entry)
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)
        
    logger.info(f"Saved Q&A log to {log_file} for future batch evaluation.")

def main():
    logging.basicConfig(level=logging.INFO)
    
    log_file = "qa_history.json"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} historical queries from {log_file} for batch evaluation.")
        if len(data) == 0:
            logger.error(f"No records found in {log_file}.")
            return
    else:
        logger.info(f"No {log_file} found. Using dummy data...")
        data = [
            # ----- Semantic Search Questions -----
            {
                "question": "นโยบายการจ่ายเงินปันผลของบริษัท PTT เป็นอย่างไร?",
                "answer": "บริษัท PTT มีนโยบายจ่ายเงินปันผลไม่ต่ำกว่าร้อยละ 25 ของกำไรสุทธิหลังหักภาษีและสำรองตามกฎหมาย",
                "contexts": ["นโยบายการจ่ายเงินปันผล PTT สรุปได้ว่า บริษัทจะพิจารณาจ่ายเงินปันผลในอัตราไม่น้อยกว่าร้อยละ 25.0 ของกำไรสุทธิในแต่ละปีหลังหักเงินสำรองต่างๆ ตามกฎหมาย"],
                "ground_truth": "ไม่ต่ำกว่าร้อยละ 25 ของกำไรสุทธิหลังหักสำรองตามกฎหมาย"
            },
            {
                "question": "แผนกลยุทธ์ด้านความยั่งยืน (ESG) ดำเนินการอย่างไรในปี 2568?",
                "answer": "บริษัทตั้งเป้าหมายลดการปล่อยก๊าซเรือนกระจกให้ได้ 20% ภายในปี 2568 และเพิ่มการใช้พลังงานสะอาดเป็น 30%",
                "contexts": ["กลยุทธ์ด้าน ESG ในปี 2568: บริษัทประกาศเจตนารมณ์ในการลดปริมาณการปล่อยก๊าซเรือนกระจกเพื่อบรรลุเป้าหมาย 20% ภายในปี 2568 และมุ่งเน้นการใช้แหล่งพลังงานสะอาดให้ถึงสัดส่วน 30% ของพลังงานทั้งหมด"],
                "ground_truth": "ตั้งเป้าลดก๊าซเรือนกระจก 20% และเพิ่มสัดส่วนพลังงานสะอาด 30%"
            },
            {
                "question": "ปัจจัยความเสี่ยงหลักต่อการดำเนินธุรกิจในรายงานประจำปีระบุไว้อย่างไร?",
                "answer": "ความเสี่ยงหลักประกอบด้วย อัตราดอกเบี้ยนโยบายที่เพิ่มขึ้น นโยบายขอสินเชื่อที่เข้มงวด และต้นทุนวัสดุก่อสร้างที่ปรับตัวสูงขึ้น",
                "contexts": ["รายงานปัจจัยความเสี่ยง ปี 2566: ปัจจัยความเสี่ยงที่มีผลกระทบต่อธุรกิจหลักคือ แนวโน้มอัตราดอกเบี้ยนโยบายที่เพิ่มสูงขึ้น การปฏิเสธสินเชื่อ (Rejection Rate) ที่เข้มงวดขึ้นจากธนาคารพาณิชย์ และราคาวัสดุก่อสร้างที่แพงขึ้น"],
                "ground_truth": "อัตราดอกเบี้ยเพิ่มสูงขึ้น, การระมัดระวังการปล่อยสินเชื่อของธนาคาร, และต้นทุนวัสดุก่อสร้างสูงขึ้น"
            },
            # ----- Structure/SQL Questions -----
            {
                "question": "สินทรัพย์รวมของธนาคารทิสโก้ในปี 2566 มีมูลค่าเท่าไร?",
                "answer": "ธนาคารทิสโก้มีสินทรัพย์รวมในปี 2566 เท่ากับ 259,101 ล้านบาท",
                "contexts": ["งบแสดงฐานะการเงิน ธนาคารทิสโก้ จำกัด (มหาชน): รายการ สินทรัพย์รวม | ปี 2566 (259,101 ล้านบาท) | ปี 2565 (260,119 ล้านบาท)"],
                "ground_truth": "259,101 ล้านบาท"
            },
            {
                "question": "กำไรสุทธิของ ปตท.สผ. ในปี 2565 มีจำนวนเท่าไร เมื่อเทียบกับปีที่แล้ว?",
                "answer": "กำไรสุทธิในปี 2565 เพิ่มขึ้นเป็น 70,901 ล้านบาท จากเดิม 38,864 ล้านบาทในปี 2564",
                "contexts": ["ผลการดำเนินงาน ปตท.สผ.: สำหรับงวดปี 2565 มีกำไรสุทธิจำนวน 70,901 ล้านบาท เทียบกับกำไรสุทธิจำนวน 38,864 ล้านบาท ในงวดปี 2564 แสดงการเพิ่มขึ้นร้อยละ 82.4"],
                "ground_truth": "70,901 ล้านบาท (เพิ่มจาก 38,864 ล้านบาทในปี 2564)"
            },
            {
                "question": "หนี้สินรวมของบริษัทในปี 2565 และ 2566 ต่างกันเป็นมูลค่ากี่ล้านบาท?",
                "answer": "หนี้สินรวมปี 2566 คือ 1,500 ล้านบาทและปี 2565 คือ 1,450 ล้านบาท ดังนั้นต่างกัน 50 ล้านบาท",
                "contexts": ["ตารางสรุปฐานะการเงิน: รายการ หนี้สินรวม | ปี 2566 มีจำนวน 1,500 ล้านบาท | ปี 2565 มีจำนวน 1,450 ล้านบาท"],
                "ground_truth": "แตกต่างกัน 50 ล้านบาท"
            },
            {
                "question": "ปีใดที่มีอัตรากำไรพื้นฐานต่อหุ้น (EPS) สูงที่สุดในช่วงปี 2564-2566 และมีค่าเท่าไร?",
                "answer": "ปี 2566 เป็นปีที่มีกำไรต่อหุ้นสูงสุด โดยมีค่าเท่ากับ 12.50 บาท",
                "contexts": ["ข้อมูลสถิติสำคัญ อัตรากำไรพื้นฐานต่อหุ้น (บาท): ปี 2564 = 8.10, ปี 2565 = 10.20, ปี 2566 = 12.50"],
                "ground_truth": "ปี 2566 ที่ราคา 12.50 บาท"
            },
            # ----- Hybrid / Multi-Hop Questions -----
            {
                "question": "สาเหตุใดที่ทำให้ค่าใช้จ่ายในการขายและบริหารเพิ่มขึ้น 15% ในปี 2566?",
                "answer": "ค่าใช้จ่ายในการขายและบริหารเพิ่มขึ้น 15% เนื่องจากการปรับโครงสร้างเงินเดือนและค่าใช้จ่ายการตลาดเพื่อเปิดตัวโครงการใหม่",
                "contexts": ["คำอธิบายและการวิเคราะห์ของฝ่ายจัดการ (MD&A): ค่าใช้จ่ายในการขายและบริหารในปี 2566 เพิ่มขึ้นร้อยละ 15 (จาก 4,000 ล้านบาท เป็น 4,600 ล้านบาท) สาเหตุหลักมาจากการปรับฐานค่าตอบแทนพนักงานบุคลากร และค่าใช้จ่ายด้านการส่งเสริมการขายโครงการอสังหาริมทรัพย์ใหม่"],
                "ground_truth": "การปรับฐานค่าตอบแทนพนักงานและการส่งเสริมการขายโครงการใหม่"
            },
            {
                "question": "บริษัทในเครือบริษัทย่อยที่มีสัดส่วนการถือหุ้น 100% มีอะไรบ้าง และมีทุนจดทะเบียนรวมกันทั้งหมดเท่าไร?",
                "answer": "บริษัทที่ถือหุ้น 100% คือ บริษัท เอบีซี จำกัด (100 ล้านบาท) และ บริษัท เอ็กซ์วายซี จำกัด (50 ล้านบาท) รวมทุนจดทะเบียน 150 ล้านบาท",
                "contexts": [
                    "โครงสร้างกลุ่มบริษัท: บริษัท เอบีซี จำกัด (สัดส่วนร้อยละ 100) ทุนจดทะเบียน 100 ล้านบาท",
                    "โครงสร้างกลุ่มบริษัท: บริษัท เอ็กซ์วายซี จำกัด (สัดส่วนร้อยละ 100) ทุนจดทะเบียน 50 ล้านบาท",
                    "โครงสร้างกลุ่มบริษัท: บริษัท ก่อสร้าง จำกัด (สัดส่วนร้อยละ 50) ทุนจดทะเบียน 200 ล้านบาท"
                ],
                "ground_truth": "มี 2 บริษัท (เอบีซี และ เอ็กซ์วายซี) ทุนจดทะเบียนรวม 150 ล้านบาท"
            },
            {
                "question": "อัตราส่วนหนี้ที่ไม่ก่อให้เกิดรายได้ (NPL) ลดลงเหลือ 3.19% มาจากมาตรการใด?",
                "answer": "NPL ลดลงมาตรการการจัดการหนี้ด้อยคุณภาพอย่างรัดกุมด้วยการปรับโครงสร้างหนี้และการตัดจำหน่ายหนี้สูญ",
                "contexts": ["การบริหารคุณภาพสินทรัพย์: อัตราส่วน NPL ณ สิ้นปีลดลงมาอยู่ที่ระดับร้อยละ 3.19 โดยธนาคารมีมาตรการจัดการหนี้ด้อยคุณภาพอย่างรัดกุม ผ่านการเปิดรับเจรจาปรับโครงสร้างหนี้ (Debt Restructuring) และการพิจารณาตัดจำหน่ายหนี้สูญ (Write-off) ไปบางส่วนในไตรมาสที่ 4"],
                "ground_truth": "การเจรจาปรับโครงสร้างหนี้เชิงรุก และการตัดจำหน่ายหนี้สูญ (Write-off)"
            }
        ]
    
    asyncio.run(run_evaluation(data))

if __name__ == "__main__":
    main()
