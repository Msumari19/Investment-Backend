from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Transaction, Category

tx_bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return amount if amount > 0 else None


@tx_bp.route("", methods=["GET"])
@jwt_required()
def list_transactions():
    user_id = int(get_jwt_identity())
    query = Transaction.query.filter_by(user_id=user_id)

    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    tx_type = request.args.get("type")

    if start:
        query = query.filter(Transaction.date >= start)
    if end:
        query = query.filter(Transaction.date <= end)
    if tx_type in ("income", "expense"):
        query = query.filter(Transaction.type == tx_type)

    txs = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    return jsonify([t.to_dict() for t in txs]), 200


@tx_bp.route("", methods=["POST"])
@jwt_required()
def create_transaction():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    amount = _parse_amount(data.get("amount"))
    tx_type = data.get("type")
    tx_date = _parse_date(data.get("date")) or datetime.utcnow().date()

    if amount is None:
        return jsonify({"error": "amount must be a positive number"}), 400
    if tx_type not in ("income", "expense"):
        return jsonify({"error": "type must be 'income' or 'expense'"}), 400

    category_id = data.get("category_id")
    if category_id is not None:
        category = Category.query.filter_by(id=category_id, user_id=user_id).first()
        if not category:
            return jsonify({"error": "Unknown category_id"}), 400

    txn = Transaction(
        user_id=user_id,
        date=tx_date,
        amount=amount,
        type=tx_type,
        category_id=category_id,
        note=data.get("note"),
    )
    db.session.add(txn)
    db.session.commit()
    return jsonify(txn.to_dict()), 201


@tx_bp.route("/<int:tx_id>", methods=["PUT"])
@jwt_required()
def update_transaction(tx_id):
    user_id = int(get_jwt_identity())
    txn = Transaction.query.filter_by(id=tx_id, user_id=user_id).first()
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    data = request.get_json(silent=True) or {}

    if "amount" in data:
        amount = _parse_amount(data["amount"])
        if amount is None:
            return jsonify({"error": "amount must be a positive number"}), 400
        txn.amount = amount
    if "type" in data:
        if data["type"] not in ("income", "expense"):
            return jsonify({"error": "type must be 'income' or 'expense'"}), 400
        txn.type = data["type"]
    if "date" in data:
        parsed = _parse_date(data["date"])
        if not parsed:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        txn.date = parsed
    if "category_id" in data:
        txn.category_id = data["category_id"]
    if "note" in data:
        txn.note = data["note"]

    db.session.commit()
    return jsonify(txn.to_dict()), 200


@tx_bp.route("/<int:tx_id>", methods=["DELETE"])
@jwt_required()
def delete_transaction(tx_id):
    user_id = int(get_jwt_identity())
    txn = Transaction.query.filter_by(id=tx_id, user_id=user_id).first()
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    db.session.delete(txn)
    db.session.commit()
    return jsonify({"deleted": tx_id}), 200


@tx_bp.route("/summary", methods=["GET"])
@jwt_required()
def summary():
    """Monthly income/expense totals -- what feeds the investment engine."""
    user_id = int(get_jwt_identity())
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))

    query = Transaction.query.filter_by(user_id=user_id)
    if start:
        query = query.filter(Transaction.date >= start)
    if end:
        query = query.filter(Transaction.date <= end)

    txs = query.all()
    income = sum((t.amount for t in txs if t.type == "income"), Decimal("0"))
    expenses = sum((t.amount for t in txs if t.type == "expense"), Decimal("0"))

    by_category = {}
    for t in txs:
        if t.type == "expense":
            name = t.category.name if t.category else "Uncategorized"
            by_category[name] = by_category.get(name, Decimal("0")) + t.amount

    return jsonify({
        "total_income": float(income),
        "total_expenses": float(expenses),
        "net": float(income - expenses),
        "expenses_by_category": {k: float(v) for k, v in by_category.items()},
    }), 200
