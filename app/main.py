from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

load_dotenv() 

from app.database import SessionLocal, init_db
from app.routers import attempts, history, problems
from app.seed import seed_problems

app = FastAPI(title="LLD Practice Platform")

app.include_router(problems.router)
app.include_router(attempts.router)
app.include_router(history.router)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        seed_problems(db)
    finally:
        db.close()

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
