import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # Swap this for a Postgres URL later, e.g.
    # postgresql://user:pass@host:5432/dbname
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # CHANGE THIS before deploying anywhere real. Set via env var in production.
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60 * 24 * 7  # 7 days, tune to taste

# Comma-separated list of allowed frontend origins, e.g.
    # "https://myapp.com,https://www.myapp.com". Set CORS_ORIGINS in Render's
    # environment variables once you have a real frontend domain. Falls back
    # to common local dev ports (Vite, CRA) so local frontend work isn't blocked.
    _default_origins = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
        if origin.strip()
    ]
