from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Category

cat_bp = Blueprint("categories", __name__, url_prefix="/api/categories")


@cat_bp.route("", methods=["GET"])
@jwt_required()
def list_categories():
    user_id = int(get_jwt_identity())
    query = Category.query.filter_by(user_id=user_id)

    cat_type = request.args.get("type")
    if cat_type in ("income", "expense"):
        query = query.filter(Category.type == cat_type)

    categories = query.order_by(Category.name.asc()).all()
    return jsonify([c.to_dict() for c in categories]), 200


@cat_bp.route("", methods=["POST"])
@jwt_required()
def create_category():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    cat_type = data.get("type")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if cat_type not in ("income", "expense"):
        return jsonify({"error": "type must be 'income' or 'expense'"}), 400

    existing = Category.query.filter_by(user_id=user_id, name=name, type=cat_type).first()
    if existing:
        return jsonify({"error": "A category with that name and type already exists"}), 409

    category = Category(user_id=user_id, name=name, type=cat_type)
    db.session.add(category)
    db.session.commit()
    return jsonify(category.to_dict()), 201


@cat_bp.route("/<int:cat_id>", methods=["DELETE"])
@jwt_required()
def delete_category(cat_id):
    user_id = int(get_jwt_identity())
    category = Category.query.filter_by(id=cat_id, user_id=user_id).first()
    if not category:
        return jsonify({"error": "Category not found"}), 404

    db.session.delete(category)
    db.session.commit()
    return jsonify({"deleted": cat_id}), 200