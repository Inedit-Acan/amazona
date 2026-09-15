from fastapi import FastAPI

app = FastAPI(title="AMAZONA Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "amazona-backend"}
