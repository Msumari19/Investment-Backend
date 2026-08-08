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