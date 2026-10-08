"""Query API route — main agent interface."""

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.agent import agent_query
from backend.services.evaluation import save_qa_log, _contexts_from_agent_result

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


@router.post("")
async def query_agent(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Submit a question to the AI Agent.

    The agent will classify the query and route it to either:
    - Vector Search (semantic questions)
    - Text-to-SQL (analytical questions)
    - Hybrid (both)
    """
    result = await agent_query(request.question, db)
    
    contexts = _contexts_from_agent_result(result)
        
    # Assign background task to log QA for later batch evaluation
    background_tasks.add_task(
        save_qa_log,
        question=request.question,
        answer=result.get("answer", ""),
        contexts=contexts,
        full_result=result,
    )
    
    return result
