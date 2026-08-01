from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import db, jwt
from auth import auth_bp
from transactions import tx_bp
from plans import plans_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt.init_app(app)
    CORS(app)  # tighten origins before deploying publicly

    app.register_blueprint(auth_bp)
    app.register_blueprint(tx_bp)
    app.register_blueprint(plans_bp)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @jwt.unauthorized_loader
    def unauthorized(reason):
        return jsonify({"error": "Missing or invalid token"}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify({"error": "Invalid token"}), 422

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    print("""
Backend running:
  Health:  GET  http://localhost:5000/api/health
  Auth:    POST http://localhost:5000/api/auth/register  {email, password}
           POST http://localhost:5000/api/auth/login     {email, password}
  Tx:      GET/POST http://localhost:5000/api/transactions
  Plan:    POST http://localhost:5000/api/plans/generate
""")
    app.run(host="127.0.0.1", port=5000, debug=True)
