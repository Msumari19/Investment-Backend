from datetime import datetime, date
from calendar import monthrange
from decimal import Decimal

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Transaction, Holding, PlanSnapshot
from logic import suggest_investment_plan

plans_bp = Blueprint("plans", __name__, url_prefix="/api/plans")


def _current_month_bounds():
    today = date.today()
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start, end


@plans_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_plan():
    """
    Builds a plan from real ledger data for the given/current month, merged
    with any manual overrides (risk_preference, dependants, debts, etc.)
    passed in the request body. Saves the result as a PlanSnapshot.
    """
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    start, end = _current_month_bounds()
    txs = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.date >= start,
        Transaction.date <= end,
    ).all()

    income = sum((t.amount for t in txs if t.type == "income"), Decimal("0"))
    expenses = sum((t.amount for t in txs if t.type == "expense"), Decimal("0"))

    holdings = {
        h.product_key: float(h.balance_tzs)
        for h in Holding.query.filter_by(user_id=user_id).all()
    }

    # Allow manual override of income/expenses (e.g. mid-month estimate) but
    # default to what the ledger actually shows.
    plan_input = {
        "monthly_income": data.get("monthly_income", float(income)),
        "monthly_expenses": data.get("monthly_expenses", float(expenses)),
        "emergency_fund_balance": data.get("emergency_fund_balance", 0),
        "risk_preference": data.get("risk_preference", "moderate"),
        "self_employed": data.get("self_employed", False),
        "irregular_income": data.get("irregular_income", False),
        "dependants": data.get("dependants", 0),
        "single_household_income": data.get("single_household_income", False),
        "employment_uncertain": data.get("employment_uncertain", False),
        "holdings": holdings,
        "pending_accumulation": data.get("pending_accumulation", {}),
        "debts": data.get("debts", []),
    }

    try:
        result = suggest_investment_plan(**plan_input)
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 400

    snapshot = PlanSnapshot(user_id=user_id, input_json=plan_input, result_json=result)
    db.session.add(snapshot)
    db.session.commit()

    return jsonify(snapshot.to_dict()), 200


@plans_bp.route("/history", methods=["GET"])
@jwt_required()
def history():
    user_id = int(get_jwt_identity())
    snapshots = (
        PlanSnapshot.query.filter_by(user_id=user_id)
        .order_by(PlanSnapshot.created_at.desc())
        .limit(24)
        .all()
    )
    return jsonify([s.to_dict() for s in snapshots]), 200


@plans_bp.route("/holdings", methods=["GET", "PUT"])
@jwt_required()
def holdings():
    user_id = int(get_jwt_identity())

    if request.method == "GET":
        rows = Holding.query.filter_by(user_id=user_id).all()
        return jsonify([h.to_dict() for h in rows]), 200

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be {product_key: balance_tzs, ...}"}), 400

    for product_key, balance in data.items():
        row = Holding.query.filter_by(user_id=user_id, product_key=product_key).first()
        if row:
            row.balance_tzs = Decimal(str(balance))
        else:
            db.session.add(Holding(user_id=user_id, product_key=product_key, balance_tzs=Decimal(str(balance))))
    db.session.commit()

    rows = Holding.query.filter_by(user_id=user_id).all()
    return jsonify([h.to_dict() for h in rows]), 200
