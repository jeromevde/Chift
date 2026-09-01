# Starts the local web server that pretends to be Chift's invoicing API.
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from chift_api.config import get_settings
from chift_api.routes import router as invoicing_router

load_dotenv()

app = FastAPI(
    title="Chift Invoicing POC",
    description="Local Chift unified invoicing API backed by generated Hyperline connector",
    version="0.1.0",
)

app.include_router(invoicing_router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "hyperline_env": settings.hyperline_env}


def run() -> None:
    uvicorn.run("chift_api.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
