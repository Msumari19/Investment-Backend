from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import db, jwt
from auth import auth_bp
from transactions import tx_bp
from plans import plans_bp
from categories import cat_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt.init_app(app)
    # Only the origins listed in Config.CORS_ORIGINS (via CORS_ORIGINS env var)
    # may make cross-origin requests, and only to /api/* routes.
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    app.register_blueprint(auth_bp)
    app.register_blueprint(tx_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(cat_bp)

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

app = create_app()
if __name__ == "__main__":
    import os
    print("""
Backend running:
  Health:  GET  http://localhost:5000/api/health
  Auth:    POST http://localhost:5000/api/auth/register  {email, password}
           POST http://localhost:5000/api/auth/login     {email, password}
  Tx:      GET/POST http://localhost:5000/api/transactions
  Cat:     GET/POST http://localhost:5000/api/categories
  Plan:    POST http://localhost:5000/api/plans/generate
""")
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)