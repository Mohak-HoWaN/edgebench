import uvicorn

from .config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("edgebench.main:app", host=s.host, port=s.port, log_config=None)
