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
