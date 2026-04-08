import asyncio
import json
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.services.agent import agent_query
from backend.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine)
logging.basicConfig(level=logging.INFO)

async def main():
    async with SessionLocal() as session:
        res = await agent_query('จำนวนหุ้นสามัญที่ธนาคารถือใน บริษัทหลักทรัพย์จัดการกองทุน กรุงศรี จำกัด มีจำนวนกี่หุ้น?', session)
        with open('trace_output.txt', 'w', encoding='utf-8') as f:
            f.write(json.dumps(res, ensure_ascii=False, indent=2))
        print("Done! See trace_output.txt")

if __name__ == '__main__':
    asyncio.run(main())
