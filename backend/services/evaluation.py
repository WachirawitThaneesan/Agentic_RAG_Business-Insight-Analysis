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
)

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

async def run_evaluation(data: list[dict], output_csv: str = "ragas_evaluation_results.csv"):
    """
    Run Ragas evaluation on a list of samples.
    """
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig
    
    logger.info("Configuring Ragas to use local Ollama models (LLM and Embeddings)...")
    
    local_llm = ChatOllama(model=settings.OLLAMA_LLM_MODEL, base_url=settings.OLLAMA_HOST, temperature=0.1)
    local_embeddings = OllamaEmbeddings(model=settings.EMBED_MODEL, base_url=settings.OLLAMA_HOST)
    
    ragas_llm = LangchainLLMWrapper(local_llm)
    ragas_emb = LangchainEmbeddingsWrapper(local_embeddings)

    df = pd.DataFrame(data)
    dataset = Dataset.from_pandas(df)

    # Check if ground_truth is fully populated (required for Recall/Precision)
    has_ground_truth = all(bool(str(d.get("ground_truth", "")).strip()) for d in data)
    
    if has_ground_truth:
        logger.info("Ground truth is properly provided. Running ALL 4 metrics.")
        metrics = [context_precision, context_recall, faithfulness, answer_relevancy]
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
    for metric_name, score in result.items():
        print(f"{metric_name:20s}: {score:.4f}")
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
            {
                "question": "บริษัท A มีรายได้ไตรมาสล่าสุดเท่าไร?",
                "answer": "บริษัท A มีรายได้ไตรมาสล่าสุดอยู่ที่ 500 ล้านบาท",
                "contexts": [
                    "รายงานประจำไตรมาส: บริษัท A สรุปรายได้รวมทั้งสิ้น 500 ล้านบาท เติบโตขึ้น 10% จากปีที่แล้ว"
                ],
                "ground_truth": "500 ล้านบาท"
            }
        ]
    
    asyncio.run(run_evaluation(data))

if __name__ == "__main__":
    main()
