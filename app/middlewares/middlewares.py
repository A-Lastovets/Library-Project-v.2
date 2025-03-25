import logging

from fastapi.middleware.cors import CORSMiddleware

from app.config import config


def setup_middlewares(app):
    allow_origins = ["*"] if config.FRONTEND_URL == "*" else [config.FRONTEND_URL]
    logging.info(f"Allowed CORS origins: {allow_origins}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
