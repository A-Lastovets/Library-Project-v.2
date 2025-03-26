import logging

from fastapi.middleware.cors import CORSMiddleware

from app.config import config


def setup_middlewares(app):
    allow_origins = config.allowed_origins
    logging.info(f"Allowed CORS origins: {allow_origins}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
