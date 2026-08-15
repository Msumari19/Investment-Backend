from datetime import date
from calendar import monthrange
from math import ceil
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Transaction, Holding, PlanSnapshot, PlanProfile, Debt, Category
from logic import suggest_investment_plan, PRODUCT_RULES

plans_bp = Blueprint("plans", __name__, url_prefix="/api/plans")


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _current_month_bounds():
    today = date.today()
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start, end


def _get_or_create_profile(user_id):
    """
    Profiles are created lazily -- on first read or write of the Plan page,
    never at registration. Users who never open the page never get a row.
    """
    profile = PlanProfile.query.filter_by(user_id=user_id).first()
    if profile is None:
        profile = PlanProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    return profile


def _parse_decimal(value, field, *, allow_negative=False):
    """Returns (Decimal, None) or (None, error_message)."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, f"{field} must be a number"
    if not allow_negative and parsed < 0:
        return None, f"{field} cannot be negative"
    return parsed, None


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _ledger_emergency_balance(user_id, category_id):
    """
    Derive the reserve from tagged transactions: money moved into the fund is
    logged as an expense against the category, money taken out as income.
    Never returns a negative balance.
    """
    rows = Transaction.query.filter_by(user_id=user_id, category_id=category_id).all()
    paid_in = sum((t.amount for t in rows if t.type == "expense"), Decimal("0"))
    taken_out = sum((t.amount for t in rows if t.type == "income"), Decimal("0"))
    return max(Decimal("0"), paid_in - taken_out)


def _resolve_emergency_balance(user_id, profile, data):
    """
    Three-way precedence:
      1. request body      -- a deliberate one-off override, not persisted
      2. ledger            -- when the profile opts in and names a category
      3. stored profile    -- the manually entered figure

    Returns (balance, source_label).
    """
    if "emergency_fund_balance" in data:
        parsed, error = _parse_decimal(data["emergency_fund_balance"], "emergency_fund_balance")
        if error:
            raise ValueError(error)
        return parsed, "request_override"

    if profile.emergency_fund_source == "ledger" and profile.emergency_fund_category_id:
        return (
            _ledger_emergency_balance(user_id, profile.emergency_fund_category_id),
            "ledger",
        )

    return Decimal(str(profile.emergency_fund_balance or 0)), "profile"


# ---------------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------------


@plans_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    return jsonify(_get_or_create_profile(user_id).to_dict()), 200


@plans_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    profile = _get_or_create_profile(user_id)

    if "risk_preference" in data:
        risk = (data.get("risk_preference") or "").strip().lower()
        if risk not in PlanProfile.RISK_CHOICES:
            return jsonify({
                "error": "risk_preference must be one of: "
                         + ", ".join(PlanProfile.RISK_CHOICES)
            }), 400
        profile.risk_preference = risk

    if "dependants" in data:
        try:
            dependants = int(data["dependants"])
        except (TypeError, ValueError):
            return jsonify({"error": "dependants must be a whole number"}), 400
        if dependants < 0:
            return jsonify({"error": "dependants cannot be negative"}), 400
        profile.dependants = dependants

    for flag in (
        "self_employed",
        "irregular_income",
        "single_household_income",
        "employment_uncertain",
    ):
        if flag in data:
            setattr(profile, flag, _parse_bool(data[flag]))

    if "emergency_fund_balance" in data:
        balance, error = _parse_decimal(
            data["emergency_fund_balance"], "emergency_fund_balance"
        )
        if error:
            return jsonify({"error": error}), 400
        profile.emergency_fund_balance = balance

    if "emergency_fund_source" in data:
        source = (data.get("emergency_fund_source") or "").strip().lower()
        if source not in PlanProfile.EMERGENCY_SOURCES:
            return jsonify({
                "error": "emergency_fund_source must be one of: "
                         + ", ".join(PlanProfile.EMERGENCY_SOURCES)
            }), 400
        profile.emergency_fund_source = source

    if "emergency_fund_category_id" in data:
        category_id = data["emergency_fund_category_id"]
        if category_id is None:
            profile.emergency_fund_category_id = None
        else:
            category = Category.query.filter_by(id=category_id, user_id=user_id).first()
            if not category:
                return jsonify({"error": "Unknown category_id"}), 400
            profile.emergency_fund_category_id = category.id

    if (
        profile.emergency_fund_source == "ledger"
        and not profile.emergency_fund_category_id
    ):
        return jsonify({
            "error": "Choose a category to track the emergency fund, "
                     "or set the source back to manual"
        }), 400

    db.session.commit()
    return jsonify(profile.to_dict()), 200


# ---------------------------------------------------------------------------
# DEBTS
# ---------------------------------------------------------------------------


@plans_bp.route("/debts", methods=["GET"])
@jwt_required()
def list_debts():
    user_id = int(get_jwt_identity())
    query = Debt.query.filter_by(user_id=user_id)

    if request.args.get("include_cleared") not in ("1", "true", "yes"):
        query = query.filter(Debt.cleared.is_(False))

    debts = query.order_by(
        Debt.cleared.asc(), Debt.annual_interest_rate_pct.desc(), Debt.id.desc()
    ).all()
    return jsonify([d.to_dict() for d in debts]), 200


@plans_bp.route("/debts", methods=["POST"])
@jwt_required()
def create_debt():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    balance, error = _parse_decimal(data.get("balance_tzs", 0), "balance_tzs")
    if error:
        return jsonify({"error": error}), 400

    rate, error = _parse_decimal(
        data.get("annual_interest_rate_pct", 0), "annual_interest_rate_pct"
    )
    if error:
        return jsonify({"error": error}), 400

    debt = Debt(
        user_id=user_id,
        name=name,
        balance_tzs=balance,
        annual_interest_rate_pct=rate,
    )
    db.session.add(debt)
    db.session.commit()
    return jsonify(debt.to_dict()), 201


@plans_bp.route("/debts/<int:debt_id>", methods=["PUT"])
@jwt_required()
def update_debt(debt_id):
    user_id = int(get_jwt_identity())
    debt = Debt.query.filter_by(id=debt_id, user_id=user_id).first()
    if not debt:
        return jsonify({"error": "Debt not found"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        debt.name = name

    if "balance_tzs" in data:
        balance, error = _parse_decimal(data["balance_tzs"], "balance_tzs")
        if error:
            return jsonify({"error": error}), 400
        debt.balance_tzs = balance

    if "annual_interest_rate_pct" in data:
        rate, error = _parse_decimal(
            data["annual_interest_rate_pct"], "annual_interest_rate_pct"
        )
        if error:
            return jsonify({"error": error}), 400
        debt.annual_interest_rate_pct = rate

    if "cleared" in data:
        if _parse_bool(data["cleared"]):
            debt.mark_cleared()
        else:
            debt.cleared = False
            debt.cleared_at = None

    db.session.commit()
    return jsonify(debt.to_dict()), 200


@plans_bp.route("/debts/<int:debt_id>", methods=["DELETE"])
@jwt_required()
def delete_debt(debt_id):
    """
    Soft delete. The row is kept so a paid-off balance still explains why past
    plan snapshots recommended repayment over investing. Pass ?hard=1 to
    actually remove it.
    """
    user_id = int(get_jwt_identity())
    debt = Debt.query.filter_by(id=debt_id, user_id=user_id).first()
    if not debt:
        return jsonify({"error": "Debt not found"}), 404

    if request.args.get("hard") in ("1", "true", "yes"):
        db.session.delete(debt)
        db.session.commit()
        return jsonify({"deleted": debt_id, "mode": "hard"}), 200

    debt.mark_cleared()
    db.session.commit()
    return jsonify({"cleared": debt_id, "mode": "soft", "debt": debt.to_dict()}), 200


# ---------------------------------------------------------------------------
# GATE NARRATIVE
#
# logic.py answers "what should happen". This layer answers "why is that all
# I got, and what changes it". It reads the engine's output and derives no
# figures of its own, so the two can never disagree.
# ---------------------------------------------------------------------------


def _entry_thresholds():
    """Product minimums that are actually reachable, cheapest first."""
    rows = [
        (rules["minimum_initial_tzs"] or 0, rules["instrument"])
        for rules in PRODUCT_RULES.values()
        if not rules["availability_required"]
    ]
    return sorted(rows)


def _reachable_products(investable):
    return [
        instrument
        for minimum, instrument in _entry_thresholds()
        if minimum <= investable
    ]


def _next_threshold(investable):
    """The cheapest product still out of reach, and what it costs to unlock."""
    for minimum, instrument in _entry_thresholds():
        if minimum > investable:
            return {
                "instrument": instrument,
                "threshold_tzs": minimum,
                "shortfall_tzs": minimum - investable,
            }
    return None


def _months_to_close(deficit, monthly):
    if monthly <= 0:
        return None
    return ceil(deficit / monthly)


def _build_gate(result):
    """
    Classify why the plan looks the way it does, so an empty allocations table
    reads as an explanation rather than a blank panel.
    """
    status = result["status"]
    investable = result["investable_amount_tzs"]
    emergency = result["emergency_fund"]
    contribution = result["emergency_contribution"]["monthly_amount_tzs"]

    if status == "cash_flow_deficit":
        return {
            "level": 0,
            "key": "no_surplus",
            "headline": "There is nothing left to allocate",
            "detail": (
                "Expenses match or exceed income this month, so no savings or "
                "investment plan can be built yet. Closing that gap is the "
                "first move."
            ),
            "months_until_investing": None,
            "investable_now_tzs": 0,
            "reachable_products": [],
            "next_step": None,
        }

    if status == "debt_repayment_priority":
        blocking = result["debt_repayment"]["blocking_debts"]
        monthly = result["debt_repayment"]["monthly_amount_tzs"]
        owed = sum(d["balance_tzs"] for d in blocking)
        return {
            "level": 1,
            "key": "debt_first",
            "headline": "High-interest debt comes before investing",
            "detail": (
                f"TZS {owed:,} across {len(blocking)} debt(s) costs more in "
                "interest than any sleeve here is expected to return. Every "
                "shilling beyond the cash buffer goes there first."
            ),
            "months_until_investing": _months_to_close(owed, monthly),
            "investable_now_tzs": 0,
            "reachable_products": [],
            "next_step": "Clear the highest-rate debt first.",
        }

    if investable <= 0:
        months = _months_to_close(emergency["deficit_tzs"], contribution)
        return {
            "level": 2,
            "key": "buffer_first",
            "headline": "Building your safety buffer first",
            "detail": (
                f"The whole surplus of TZS {contribution:,} is going into your "
                f"emergency fund, which is TZS {emergency['deficit_tzs']:,} "
                f"short of a {emergency['target_months']}-month target. "
                "Investing starts once that reserve is in place."
            ),
            "months_until_investing": months,
            "investable_now_tzs": 0,
            "reachable_products": [],
            "next_step": (
                f"About {months} more month(s) at this rate."
                if months else None
            ),
        }

    reachable = _reachable_products(investable)
    upcoming = _next_threshold(investable)

    if upcoming and len(reachable) < len(_entry_thresholds()):
        return {
            "level": 3,
            "key": "narrow_menu",
            "headline": f"TZS {investable:,} is investable this month",
            "detail": (
                f"{len(reachable)} product(s) are open to you at this amount. "
                f"{upcoming['instrument']} needs TZS "
                f"{upcoming['threshold_tzs']:,} to enter, so contributions "
                "toward it accumulate until they clear that bar."
            ),
            "months_until_investing": 0,
            "investable_now_tzs": investable,
            "reachable_products": reachable,
            "next_step": (
                f"TZS {upcoming['shortfall_tzs']:,} more per month unlocks "
                f"{upcoming['instrument']}."
            ),
        }

    return {
        "level": 4,
        "key": "full_portfolio",
        "headline": f"TZS {investable:,} is investable this month",
        "detail": "Every product in this portfolio is open to you at this amount.",
        "months_until_investing": 0,
        "investable_now_tzs": investable,
        "reachable_products": reachable,
        "next_step": None,
    }


# ---------------------------------------------------------------------------
# PLAN GENERATION
# ---------------------------------------------------------------------------


@plans_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_plan():
    """
    Builds a plan from the ledger and the user's saved profile. Everything the
    engine needs is persisted, so this works with an empty request body.
    Values passed in the body override the stored ones for that call only.
    """
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    profile = _get_or_create_profile(user_id)

    start, end = _current_month_bounds()
    txs = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.date >= start,
        Transaction.date <= end,
    ).all()

    income = sum((t.amount for t in txs if t.type == "income"), Decimal("0"))

    # Contributions to a tracked emergency fund are logged as expenses. Left in
    # the total they inflate the target (expenses x months), which then demands
    # more saving -- so they are excluded when the fund is ledger-tracked.
    excluded_category_id = (
        profile.emergency_fund_category_id
        if profile.emergency_fund_source == "ledger"
        else None
    )
    expenses = sum(
        (
            t.amount
            for t in txs
            if t.type == "expense"
            and (excluded_category_id is None or t.category_id != excluded_category_id)
        ),
        Decimal("0"),
    )

    try:
        emergency_balance, emergency_source = _resolve_emergency_balance(
            user_id, profile, data
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    holdings = {
        h.product_key: float(h.balance_tzs)
        for h in Holding.query.filter_by(user_id=user_id).all()
    }

    if "debts" in data:
        debts = data["debts"]
        debts_source = "request_override"
    else:
        debts = [
            d.to_logic_dict()
            for d in Debt.query.filter_by(user_id=user_id, cleared=False).all()
        ]
        debts_source = "profile"

    factors = profile.household_factors()

    plan_input = {
        "monthly_income": data.get("monthly_income", float(income)),
        "monthly_expenses": data.get("monthly_expenses", float(expenses)),
        "emergency_fund_balance": float(emergency_balance),
        "risk_preference": data.get("risk_preference", profile.risk_preference),
        "self_employed": _parse_bool(data.get("self_employed", factors["self_employed"])),
        "irregular_income": _parse_bool(
            data.get("irregular_income", factors["irregular_income"])
        ),
        "dependants": data.get("dependants", factors["dependants"]),
        "single_household_income": _parse_bool(
            data.get("single_household_income", factors["single_household_income"])
        ),
        "employment_uncertain": _parse_bool(
            data.get("employment_uncertain", factors["employment_uncertain"])
        ),
        "holdings": holdings,
        "pending_accumulation": data.get("pending_accumulation", {}),
        "debts": debts,
    }

    try:
        result = suggest_investment_plan(**plan_input)
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 400

    # Why the plan looks the way it does -- derived from the engine's output,
    # never recomputed, so the narrative cannot drift from the numbers.
    result["gate"] = _build_gate(result)

    # Record where each input came from, so the Plan page can show whether a
    # figure was typed, derived from the ledger, or overridden for this call.
    plan_input["_sources"] = {
        "emergency_fund_balance": emergency_source,
        "debts": debts_source,
        "excluded_expense_category_id": excluded_category_id,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }

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
            db.session.add(
                Holding(
                    user_id=user_id,
                    product_key=product_key,
                    balance_tzs=Decimal(str(balance)),
                )
            )
    db.session.commit()

    rows = Holding.query.filter_by(user_id=user_id).all()
    return jsonify([h.to_dict() for h in rows]), 200
