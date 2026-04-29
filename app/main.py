from fastapi import FastAPI
from app.database import engine, Base
from app import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Drift Happens API", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Segment drift system is online."}