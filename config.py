import os

# Get the directory of the current file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    # SQLAlchemy database URI
    # Set DATABASE_URL in the environment; the SQLite path is a local fallback only
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT secret key for signing tokens
    # IMPORTANT: Change this to a secure value in production and set via environment variable
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60 * 24 * 7  # 7 days, adjust as needed

    # CORS origins configuration
    # Comma-separated list of allowed frontend origins
    # Set CORS_ORIGINS environment variable on Render to your frontend's URL
    # Fallback to common local development ports if not set
    _default_origins = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"

    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
        if origin.strip()
    ]