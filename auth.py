import re
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(?:\+255|0)([67]\d{8})$")


def normalize_phone(raw_phone):
    """Converts 0XXXXXXXXX or +255XXXXXXXXX into a consistent +255XXXXXXXXX format.
    Returns None if the input doesn't match a valid Tanzanian mobile number.
    """
    raw_phone = (raw_phone or "").strip().replace(" ", "")
    match = PHONE_RE.match(raw_phone)
    if not match:
        return None
    return "+255" + match.group(1)


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    phone_raw = data.get("phone_number") or ""
    location = (data.get("location") or "").strip()

    if not EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not location:
        return jsonify({"error": "Location is required"}), 400

    phone_number = normalize_phone(phone_raw)
    if not phone_number:
        return jsonify({"error": "Enter a valid Tanzanian phone number (e.g. 0712345678 or +255712345678)"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with that email already exists"}), 409
    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({"error": "An account with that phone number already exists"}), 409

    user = User(email=email, name=name, phone_number=phone_number, location=location)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.to_dict()}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.to_dict()}), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "Not found"}), 404
    return jsonify(user.to_dict()), 200