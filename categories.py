from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Category, Transaction, PlanProfile

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


@cat_bp.route("/<int:cat_id>", methods=["PUT"])
@jwt_required()
def update_category(cat_id):
    """
    Rename a category. The type is deliberately fixed: switching an expense
    category to income would leave existing transactions filed under a type
    they no longer match.
    """
    user_id = int(get_jwt_identity())
    category = Category.query.filter_by(id=cat_id, user_id=user_id).first()
    if not category:
        return jsonify({"error": "Category not found"}), 404

    data = request.get_json(silent=True) or {}

    if "type" in data and data["type"] != category.type:
        return jsonify({
            "error": "A category's type cannot be changed. Create a new "
                     "category instead."
        }), 400

    if "name" not in data:
        return jsonify({"error": "name is required"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    if name == category.name:
        return jsonify(category.to_dict()), 200

    clash = Category.query.filter_by(
        user_id=user_id, name=name, type=category.type
    ).first()
    if clash:
        return jsonify({"error": "A category with that name and type already exists"}), 409

    category.name = name
    db.session.commit()
    return jsonify(category.to_dict()), 200


@cat_bp.route("/<int:cat_id>", methods=["DELETE"])
@jwt_required()
def delete_category(cat_id):
    """
    Transactions keep their history: deleting a category leaves them
    uncategorised rather than removing them. Pass ?force=1 to delete a
    category that still has transactions filed against it.
    """
    user_id = int(get_jwt_identity())
    category = Category.query.filter_by(id=cat_id, user_id=user_id).first()
    if not category:
        return jsonify({"error": "Category not found"}), 404

    in_use = Transaction.query.filter_by(user_id=user_id, category_id=cat_id).count()

    forced = request.args.get("force") in ("1", "true", "yes")
    if in_use and not forced:
        return jsonify({
            "error": f"{in_use} transaction(s) still use this category",
            "transaction_count": in_use,
            "hint": "Retry with ?force=1 to delete it and leave those "
                    "transactions uncategorised",
        }), 409

    # Detach rather than cascade, so the ledger keeps its rows.
    Transaction.query.filter_by(user_id=user_id, category_id=cat_id).update(
        {"category_id": None}
    )

    # A plan profile tracking this category falls back to its manual figure.
    PlanProfile.query.filter_by(
        user_id=user_id, emergency_fund_category_id=cat_id
    ).update({"emergency_fund_category_id": None, "emergency_fund_source": "manual"})

    db.session.delete(category)
    db.session.commit()
    return jsonify({"deleted": cat_id, "transactions_uncategorised": in_use}), 200
