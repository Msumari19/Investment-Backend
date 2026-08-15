from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    location = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    categories = db.relationship("Category", backref="user", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="user", cascade="all, delete-orphan")
    holdings = db.relationship("Holding", backref="user", cascade="all, delete-orphan")
    plans = db.relationship("PlanSnapshot", backref="user", cascade="all, delete-orphan")
    debts = db.relationship("Debt", backref="user", cascade="all, delete-orphan")
    plan_profile = db.relationship(
        "PlanProfile", backref="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "phone_number": self.phone_number,
            "location": self.location,
            "created_at": self.created_at.isoformat(),
        }


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'income' | 'expense'

    __table_args__ = (db.UniqueConstraint("user_id", "name", "type", name="uq_category_per_user"),)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "type": self.type}


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)  # always positive
    type = db.Column(db.String(10), nullable=False)  # 'income' | 'expense'
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("Category")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "amount": float(self.amount),
            "type": self.type,
            "category": self.category.name if self.category else None,
            "category_id": self.category_id,
            "note": self.note,
        }


class Holding(db.Model):
    """Current balance in an investment product, feeds logic.py's `holdings` arg."""
    __tablename__ = "holdings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_key = db.Column(db.String(50), nullable=False)  # must match logic.PRODUCT_RULES keys
    balance_tzs = db.Column(db.Numeric(16, 2), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "product_key", name="uq_holding_per_user_product"),)

    def to_dict(self):
        return {"product_key": self.product_key, "balance_tzs": float(self.balance_tzs)}


class PlanSnapshot(db.Model):
    """A saved output of suggest_investment_plan(), replaces track_plans.py's JSON files."""
    __tablename__ = "plan_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    input_json = db.Column(db.JSON, nullable=False)
    result_json = db.Column(db.JSON, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "input": self.input_json,
            "result": self.result_json,
        }


class PlanProfile(db.Model):
    """
    Persisted plan settings for one user -- exactly the arguments
    suggest_investment_plan() accepts beyond income and expenses.

    These were previously collected by the Plan page and thrown away on every
    request. Storing them means a plan can be regenerated from the ledger alone,
    with the request body used only for deliberate one-off overrides.
    """
    __tablename__ = "plan_profiles"

    RISK_CHOICES = ("conservative", "moderate", "aggressive")
    EMERGENCY_SOURCES = ("manual", "ledger")

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    risk_preference = db.Column(db.String(20), nullable=False, default="moderate")
    dependants = db.Column(db.Integer, nullable=False, default=0)

    self_employed = db.Column(db.Boolean, nullable=False, default=False)
    irregular_income = db.Column(db.Boolean, nullable=False, default=False)
    single_household_income = db.Column(db.Boolean, nullable=False, default=False)
    employment_uncertain = db.Column(db.Boolean, nullable=False, default=False)

    # Manually entered reserve, used when emergency_fund_source == 'manual'.
    emergency_fund_balance = db.Column(db.Numeric(16, 2), nullable=False, default=0)

    # 'manual'  -> trust emergency_fund_balance above.
    # 'ledger'  -> derive the reserve from transactions in the linked category.
    emergency_fund_source = db.Column(db.String(10), nullable=False, default="manual")
    emergency_fund_category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    emergency_fund_category = db.relationship("Category")

    def to_dict(self):
        return {
            "risk_preference": self.risk_preference,
            "dependants": self.dependants,
            "self_employed": self.self_employed,
            "irregular_income": self.irregular_income,
            "single_household_income": self.single_household_income,
            "employment_uncertain": self.employment_uncertain,
            "emergency_fund_balance": float(self.emergency_fund_balance or 0),
            "emergency_fund_source": self.emergency_fund_source,
            "emergency_fund_category_id": self.emergency_fund_category_id,
            "emergency_fund_category": (
                self.emergency_fund_category.name if self.emergency_fund_category else None
            ),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def household_factors(self):
        """The keyword arguments suggest_investment_plan() expects."""
        return {
            "self_employed": bool(self.self_employed),
            "irregular_income": bool(self.irregular_income),
            "dependants": int(self.dependants or 0),
            "single_household_income": bool(self.single_household_income),
            "employment_uncertain": bool(self.employment_uncertain),
        }


class Debt(db.Model):
    """
    One consumer debt. Feeds logic.py's `debts` gate, which blocks growth
    allocation while any balance sits at or above DEBT_GATE_ANNUAL_RATE_PCT.

    Cleared debts are kept rather than deleted so a paid-off balance still
    explains why past plan snapshots recommended repayment over investing.
    """
    __tablename__ = "debts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    name = db.Column(db.String(120), nullable=False)
    balance_tzs = db.Column(db.Numeric(16, 2), nullable=False, default=0)
    annual_interest_rate_pct = db.Column(db.Numeric(6, 2), nullable=False, default=0)

    cleared = db.Column(db.Boolean, nullable=False, default=False, index=True)
    cleared_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def mark_cleared(self):
        self.cleared = True
        self.cleared_at = datetime.utcnow()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "balance_tzs": float(self.balance_tzs or 0),
            "annual_interest_rate_pct": float(self.annual_interest_rate_pct or 0),
            "cleared": self.cleared,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_logic_dict(self):
        """The shape logic.py's _blocking_debts() reads."""
        return {
            "name": self.name,
            "balance_tzs": float(self.balance_tzs or 0),
            "annual_interest_rate_pct": float(self.annual_interest_rate_pct or 0),
        }
