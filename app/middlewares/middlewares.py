from fastapi.middleware.cors import CORSMiddleware

from app.config import config


def setup_middlewares(app):

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],  # Дозволяє всі HTTP-методи
        allow_headers=["*"],  # Дозволяє всі заголовки
    )
