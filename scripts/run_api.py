"""Run the DeepScout FastAPI service."""

import uvicorn

from deepscout.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "deepscout.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
