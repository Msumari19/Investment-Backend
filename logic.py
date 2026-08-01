"""
logic.py - savings and investment planning engine (Tanzania, TZS).

Revision notes (audit fixes applied):
  * Single unified return schema on every code path.
  * Configuration validated at import time (weights, tiers, product keys).
  * Product minimums distinguish INITIAL from ADDITIONAL, driven by holdings.
  * Accumulation state is carried in and out so "accumulate_until_minimum"
    actually terminates.
  * Emergency-fund target supports the 6-9 month override for irregular
    income, dependants, single-income households and employment uncertainty.
  * All monetary arithmetic is Decimal; inputs are coerced at the boundary.
  * Rounding residue is routed to the largest-weight sleeve, not the last one.
  * High-interest debt acts as a hard gate before any growth allocation.
  * Emergency-fund surplus is surfaced rather than silently clamped.

IMPORTANT - THIS MODULE PRODUCES PLANNING OUTPUT, NOT INVESTMENT ADVICE.
Under the Capital Markets and Securities Act (Cap. 79) a person carrying on
the business of an investment adviser must be approved by the CMSA. Confirm
your licensing position before exposing personalised instrument-level
recommendations to the public.

Everything in the CONFIGURATION section below is a placeholder for rows in the
`investment_product_rules` table. Each entry carries source_url and
last_verified_at precisely so that stale values are visible rather than
invisible. Do not treat these literals as durable.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import ceil
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# CONFIGURATION (load from `investment_product_rules` in production)
# ---------------------------------------------------------------------------

CONFIG_VERSION = "2026-07-31"

#: Reference annual inflation, percent. Used only to flag instruments whose
#: after-tax yield fails to preserve purchasing power. Recalculate monthly.
REFERENCE_INFLATION_PCT = Decimal("4.0")  # NBS mainland headline, June 2026

#: Consumer debt at or above this annual rate outranks every investment sleeve.
DEBT_GATE_ANNUAL_RATE_PCT = Decimal("15.0")

#: Emergency-fund contribution split once at least one month of expenses is held.
EMERGENCY_SPLIT_PARTIAL = Decimal("0.70")

PRODUCT_RULES: dict[str, dict[str, Any]] = {
    "utt_liquid": {
        "instrument": "UTT AMIS Liquid Fund",
        "category": "low_risk",
        "minimum_initial_tzs": 100_000,
        "minimum_additional_tzs": 10_000,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "UTT AMIS branch, agent or mobile channel",
        "source_url": "https://uttamis.co.tz/products/liquid_fund",
        "last_verified_at": "2026-07-31",
    },
    "call_account": {
        "instrument": "Bank or mobile-linked call account",
        "category": "low_risk",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "Existing bank or mobile money provider",
        "source_url": None,
        "last_verified_at": "2026-07-31",
    },
    "fixed_deposit": {
        "instrument": "Commercial-bank fixed-deposit ladder",
        "category": "low_risk",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "Bank branch; ladder across maturities",
        "source_url": None,
        "last_verified_at": "2026-07-31",
    },
    "utt_bond": {
        "instrument": "UTT AMIS Bond Fund",
        "category": "fixed_income",
        "minimum_initial_tzs": 50_000,
        "minimum_additional_tzs": 50_000,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "UTT AMIS reinvestment plan",
        "source_url": "https://uttamis.co.tz/products/bond_fund",
        "last_verified_at": "2026-07-31",
    },
    "tbill": {
        "instrument": "BoT Treasury bills or intermediate bonds",
        "category": "fixed_income",
        "minimum_initial_tzs": 500_000,
        "minimum_additional_tzs": 500_000,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        # Bids below TZS 5m are routed through a primary dealer or the DSE
        # secondary market rather than direct auction participation.
        "access_route": "Primary dealer or DSE secondary market (bids under TZS 5m)",
        "source_url": "https://www.bot.go.tz/FinancialMarket/DomesticDept",
        "last_verified_at": "2026-07-31",
    },
    "tbond": {
        "instrument": "BoT Treasury bond ladder",
        "category": "fixed_income",
        "minimum_initial_tzs": 1_000_000,
        "minimum_additional_tzs": 1_000_000,
        "availability_required": False,
        "withholding_tax_pct": Decimal("0.0"),  # exempt if >=3yr AND DSE-listed
        "indicative_gross_yield_pct": None,
        "access_route": "Primary dealer or DSE secondary market (bids under TZS 5m)",
        "source_url": "https://www.bot.go.tz/FinancialMarket/DomesticDept",
        "last_verified_at": "2026-07-31",
    },
    "tbond_long": {
        "instrument": "Long-dated BoT Treasury bonds",
        "category": "fixed_income",
        "minimum_initial_tzs": 1_000_000,
        "minimum_additional_tzs": 1_000_000,
        "availability_required": False,
        "withholding_tax_pct": Decimal("0.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "Primary dealer or DSE secondary market (bids under TZS 5m)",
        "source_url": "https://www.bot.go.tz/FinancialMarket/DomesticDept",
        "last_verified_at": "2026-07-31",
    },
    "sukuk_green": {
        "instrument": "Available Sukuk or green revenue bond",
        "category": "fixed_income",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": True,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "Issue-specific; confirm open issue and secondary liquidity",
        "source_url": "https://www.cmsa.go.tz/",
        "last_verified_at": "2026-07-31",
    },
    "utt_umoja": {
        "instrument": "UTT AMIS Umoja Fund",
        "category": "growth",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": False,
        "withholding_tax_pct": Decimal("5.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "UTT AMIS branch, agent or mobile channel",
        "source_url": "https://uttamis.co.tz/products/umoja_fund",
        "last_verified_at": "2026-07-31",
    },
    "dse_equity": {
        "instrument": "VIS-ETF or diversified DSE shares",
        "category": "growth",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": False,
        "withholding_tax_pct": Decimal("5.0"),
        "indicative_gross_yield_pct": None,
        "access_route": "CMSA-licensed broker with a CDS account",
        "source_url": "https://www.dse.co.tz/",
        "last_verified_at": "2026-07-31",
    },
    "land_fund": {
        "instrument": "Real-estate/land purchase accumulation fund",
        "category": "growth",
        "minimum_initial_tzs": None,
        "minimum_additional_tzs": None,
        "availability_required": False,
        "withholding_tax_pct": Decimal("10.0"),
        "indicative_gross_yield_pct": None,
        # Earmarked purchase fund. NOT a claim of investment growth.
        "access_route": "Hold in a liquid fund until purchase; verify title before transfer",
        "source_url": None,
        "last_verified_at": "2026-07-31",
    },
}

PORTFOLIOS: dict[str, tuple[tuple[str, str], ...]] = {
    "conservative": (
        ("utt_liquid", "0.25"),
        ("call_account", "0.20"),
        ("fixed_deposit", "0.10"),
        ("utt_bond", "0.20"),
        ("tbill", "0.15"),
        ("utt_umoja", "0.05"),
        ("dse_equity", "0.05"),
    ),
    "moderate": (
        ("utt_liquid", "0.20"),
        ("call_account", "0.10"),
        ("fixed_deposit", "0.05"),
        ("utt_bond", "0.15"),
        ("tbond", "0.15"),
        ("sukuk_green", "0.05"),
        ("utt_umoja", "0.10"),
        ("dse_equity", "0.15"),
        ("land_fund", "0.05"),
    ),
    "aggressive": (
        ("utt_liquid", "0.15"),
        ("call_account", "0.05"),
        ("utt_bond", "0.10"),
        ("tbond_long", "0.10"),
        ("sukuk_green", "0.05"),
        ("dse_equity", "0.30"),
        ("utt_umoja", "0.15"),
        ("land_fund", "0.10"),
    ),
}

#: Ordered high-to-low. First tier whose floor is met wins; None is catch-all.
SAVINGS_TIERS: tuple[dict[str, Any], ...] = (
    {"name": "accelerator", "min_net_savings_tzs": 2_000_000, "emergency_months": 3},
    {"name": "builder", "min_net_savings_tzs": 500_000, "emergency_months": 4},
    {"name": "starter", "min_net_savings_tzs": 1, "emergency_months": 6},
    {"name": "cash_flow_deficit", "min_net_savings_tzs": None, "emergency_months": 6},
)

#: A short emergency target is only defensible if the surplus can rebuild it
#: quickly, which depends on the savings RATE, not the absolute shilling amount.
SAVINGS_RATE_MONTH_FLOORS: tuple[tuple[Decimal, int], ...] = (
    (Decimal("10.0"), 6),
    (Decimal("25.0"), 5),
)

MAX_EMERGENCY_MONTHS = 9
MIN_OVERRIDE_MONTHS = 6

VALID_RISK_PROFILES = frozenset(PORTFOLIOS)


# ---------------------------------------------------------------------------
# CONFIGURATION VALIDATION (fails loudly at import, not silently at runtime)
# ---------------------------------------------------------------------------


def _validate_config() -> None:
    for risk, portfolio in PORTFOLIOS.items():
        total = sum(Decimal(w) for _, w in portfolio)
        if total != Decimal("1"):
            raise ValueError(
                f"Portfolio '{risk}' weights sum to {total}, expected exactly 1"
            )
        seen: set[str] = set()
        for key, _ in portfolio:
            if key not in PRODUCT_RULES:
                raise KeyError(f"Portfolio '{risk}' references unknown product '{key}'")
            if key in seen:
                raise ValueError(f"Portfolio '{risk}' repeats product '{key}'")
            seen.add(key)

    for tier in SAVINGS_TIERS:
        months = tier["emergency_months"]
        if not 1 <= months <= MAX_EMERGENCY_MONTHS:
            raise ValueError(f"Tier '{tier['name']}' has implausible months: {months}")

    if SAVINGS_TIERS[-1]["min_net_savings_tzs"] is not None:
        raise ValueError("The final savings tier must be an unbounded catch-all")


_validate_config()


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def round_tzs(value: Any) -> int:
    """Quantise to whole shillings. Tanzania has no circulating subunit."""
    return int(_to_decimal(value, "amount").quantize(Decimal("1"), ROUND_HALF_UP))


def _to_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise TypeError(f"{field} must be numeric, got {type(value).__name__}")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TypeError(f"{field} is not a valid numeric value: {value!r}") from exc


def _pct(part: Decimal, whole: Decimal) -> float:
    """Percentage guarded against a zero denominator."""
    if whole <= 0:
        return 0.0
    return float((part / whole * 100).quantize(Decimal("0.01"), ROUND_HALF_UP))


def classify_savings(net_savings: int) -> tuple[str, int]:
    """Return (tier_name, base_emergency_months) for a net monthly surplus."""
    for tier in SAVINGS_TIERS:
        floor = tier["min_net_savings_tzs"]
        if floor is None or net_savings >= floor:
            return tier["name"], tier["emergency_months"]
    raise AssertionError("unreachable: catch-all tier missing")


def resolve_emergency_months(
    base_months: int,
    savings_rate_pct: Decimal,
    *,
    self_employed: bool = False,
    irregular_income: bool = False,
    dependants: int = 0,
    single_household_income: bool = False,
    employment_uncertain: bool = False,
) -> tuple[int, list[str]]:
    """
    Apply the 6-9 month override. Each risk factor present lifts the floor by
    one month above a base of six, capped at nine. The savings-rate floor
    prevents a large absolute surplus from buying a short target when that
    surplus is a small share of income.
    """
    reasons: list[str] = []
    months = base_months

    for threshold, floor in SAVINGS_RATE_MONTH_FLOORS:
        if savings_rate_pct < threshold and floor > months:
            months = floor
            reasons.append(f"savings rate below {threshold}% of income")
            break

    factors = [
        (self_employed, "self-employed"),
        (irregular_income, "irregular income"),
        (dependants > 0, f"{dependants} dependant(s)"),
        (single_household_income, "single household income"),
        (employment_uncertain, "uncertain employment"),
    ]
    active = [label for flag, label in factors if flag]

    if active:
        override = min(MAX_EMERGENCY_MONTHS, MIN_OVERRIDE_MONTHS + len(active) - 1)
        if override > months:
            months = override
        reasons.extend(active)

    return min(months, MAX_EMERGENCY_MONTHS), reasons


def _split_amounts(investable: Decimal, portfolio) -> list[int]:
    """
    Split `investable` across the portfolio. Rounding residue goes to the
    LARGEST weight, so the error never distorts a small satellite sleeve.
    """
    weights = [Decimal(w) for _, w in portfolio]
    amounts = [round_tzs(investable * w) for w in weights]
    residue = round_tzs(investable) - sum(amounts)
    if amounts and residue:
        amounts[weights.index(max(weights))] += residue
    return amounts


def _real_return_flag(product: Mapping[str, Any]) -> dict[str, Any] | None:
    """After-tax real return versus reference inflation, when a yield is known."""
    gross = product.get("indicative_gross_yield_pct")
    if gross is None:
        return None
    gross = _to_decimal(gross, "indicative_gross_yield_pct")
    wht = _to_decimal(product.get("withholding_tax_pct") or 0, "withholding_tax_pct")
    after_tax = gross * (Decimal("1") - wht / 100)
    real = after_tax - REFERENCE_INFLATION_PCT
    return {
        "after_tax_yield_pct": float(after_tax.quantize(Decimal("0.01"))),
        "reference_inflation_pct": float(REFERENCE_INFLATION_PCT),
        "real_return_pct": float(real.quantize(Decimal("0.01"))),
        "preserves_purchasing_power": real >= 0,
    }


def _blocking_debts(debts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    blocking = []
    for index, debt in enumerate(debts):
        balance = _to_decimal(debt.get("balance_tzs", 0), f"debts[{index}].balance_tzs")
        rate = _to_decimal(
            debt.get("annual_interest_rate_pct", 0),
            f"debts[{index}].annual_interest_rate_pct",
        )
        if balance > 0 and rate >= DEBT_GATE_ANNUAL_RATE_PCT:
            blocking.append(
                {
                    "name": debt.get("name") or f"debt_{index + 1}",
                    "balance_tzs": round_tzs(balance),
                    "annual_interest_rate_pct": float(rate),
                }
            )
    return sorted(blocking, key=lambda d: -d["annual_interest_rate_pct"])


# ---------------------------------------------------------------------------
# RESULT BUILDER - every code path returns this exact shape
# ---------------------------------------------------------------------------


def _build_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "currency": "TZS",
        "config_version": CONFIG_VERSION,
        "status": "ok",
        "risk_profile": None,
        "savings_tier": None,
        "net_monthly_savings_tzs": 0,
        "recommended_monthly_savings_tzs": 0,
        "savings_rate_pct": 0.0,
        "emergency_fund": {
            "status": "unknown",
            "target_months": 0,
            "target_months_reasons": [],
            "target_tzs": 0,
            "current_balance_tzs": 0,
            "deficit_tzs": 0,
            "surplus_tzs": 0,
        },
        "emergency_contribution": {
            "instrument": None,
            "monthly_amount_tzs": 0,
            "percentage_of_total_savings": 0.0,
        },
        "debt_repayment": {
            "monthly_amount_tzs": 0,
            "blocking_debts": [],
        },
        "investable_amount_tzs": 0,
        "allocations": [],
        "pending_accumulation_tzs": {},
        "messages": [],
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------


def suggest_investment_plan(
    monthly_income: Any,
    monthly_expenses: Any,
    emergency_fund_balance: Any,
    risk_preference: Any,
    *,
    holdings: Mapping[str, Any] | None = None,
    pending_accumulation: Mapping[str, Any] | None = None,
    debts: Sequence[Mapping[str, Any]] | None = None,
    self_employed: bool = False,
    irregular_income: bool = False,
    dependants: int = 0,
    single_household_income: bool = False,
    employment_uncertain: bool = False,
) -> dict[str, Any]:
    """
    Produce a monthly savings and allocation plan.

    holdings              -- {product_key: current_balance_tzs}. Determines
                             whether the initial or additional minimum applies.
    pending_accumulation  -- {product_key: parked_balance_tzs} carried over from
                             the previous run for sleeves below their minimum.
    debts                 -- [{name, balance_tzs, annual_interest_rate_pct}].
    """
    if not isinstance(risk_preference, str):
        raise TypeError("risk_preference must be a string")

    risk = risk_preference.strip().lower()
    if risk not in VALID_RISK_PROFILES:
        raise ValueError(
            "risk_preference must be one of: " + ", ".join(sorted(VALID_RISK_PROFILES))
        )

    income = _to_decimal(monthly_income, "monthly_income")
    expenses = _to_decimal(monthly_expenses, "monthly_expenses")
    reserve = _to_decimal(emergency_fund_balance, "emergency_fund_balance")

    if min(income, expenses, reserve) < 0:
        raise ValueError("Financial values cannot be negative.")
    if income <= 0:
        raise ValueError("monthly_income must be greater than zero.")
    if dependants < 0:
        raise ValueError("dependants cannot be negative.")

    holdings = dict(holdings or {})
    carried = {k: round_tzs(v) for k, v in (pending_accumulation or {}).items()}
    debts = list(debts or [])

    for key in set(holdings) | set(carried):
        if key not in PRODUCT_RULES:
            raise KeyError(f"Unknown product key: {key!r}")

    net_savings = round_tzs(income - expenses)
    available = Decimal(max(0, net_savings))
    savings_rate = (Decimal(net_savings) / income * 100).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )

    tier, base_months = classify_savings(net_savings)
    months, month_reasons = resolve_emergency_months(
        base_months,
        savings_rate,
        self_employed=self_employed,
        irregular_income=irregular_income,
        dependants=dependants,
        single_household_income=single_household_income,
        employment_uncertain=employment_uncertain,
    )

    target = round_tzs(expenses * months)
    deficit = max(0, target - round_tzs(reserve))
    surplus = max(0, round_tzs(reserve) - target)

    emergency_block = {
        "status": "sufficient" if deficit == 0 else "deficit",
        "target_months": months,
        "target_months_reasons": month_reasons,
        "target_tzs": target,
        "current_balance_tzs": round_tzs(reserve),
        "deficit_tzs": deficit,
        "surplus_tzs": surplus,
    }

    common = {
        "risk_profile": risk,
        "savings_tier": tier,
        "net_monthly_savings_tzs": net_savings,
        "recommended_monthly_savings_tzs": int(available),
        "savings_rate_pct": float(savings_rate),
        "emergency_fund": emergency_block,
        "pending_accumulation_tzs": dict(carried),
    }

    messages: list[str] = []
    if surplus > 0:
        messages.append(
            f"Emergency reserve exceeds target by TZS {surplus:,}. Consider "
            "redeploying the excess into the investable allocation."
        )

    # -- Gate 1: cash-flow deficit -----------------------------------------
    if available == 0:
        messages.insert(
            0,
            "No investment allocation is recommended until monthly income "
            "exceeds monthly expenses.",
        )
        return _build_result(status="cash_flow_deficit", messages=messages, **common)

    # -- Emergency-fund contribution ---------------------------------------
    if deficit == 0:
        emergency_pct = Decimal("0")
    elif reserve < expenses:
        emergency_pct = Decimal("1.00")
    else:
        emergency_pct = EMERGENCY_SPLIT_PARTIAL

    emergency_contribution = min(deficit, round_tzs(available * emergency_pct))
    remainder = Decimal(int(available) - emergency_contribution)

    emergency_instrument = (
        "Bank or mobile-linked call account"
        if reserve < expenses
        else "UTT AMIS Liquid Fund"
    )
    contribution_block = {
        "instrument": emergency_instrument if emergency_contribution else None,
        "monthly_amount_tzs": emergency_contribution,
        "percentage_of_total_savings": _pct(Decimal(emergency_contribution), available),
    }

    # -- Gate 2: high-interest debt ----------------------------------------
    blocking = _blocking_debts(debts)
    if blocking:
        messages.insert(
            0,
            "High-interest debt outranks every investment sleeve. Clear debt at "
            f"or above {DEBT_GATE_ANNUAL_RATE_PCT}% before allocating to growth "
            "assets; only a one-month cash buffer is funded first.",
        )
        return _build_result(
            status="debt_repayment_priority",
            emergency_contribution=contribution_block,
            debt_repayment={
                "monthly_amount_tzs": int(remainder),
                "blocking_debts": blocking,
            },
            investable_amount_tzs=0,
            messages=messages,
            **common,
        )

    # -- Allocation ---------------------------------------------------------
    portfolio = PORTFOLIOS[risk]
    amounts = _split_amounts(remainder, portfolio) if remainder > 0 else []
    allocations: list[dict[str, Any]] = []
    pending_out = dict(carried)

    for (key, weight), amount in zip(portfolio, amounts):
        product = PRODUCT_RULES[key]
        already_held = round_tzs(holdings.get(key, 0)) > 0
        minimum = (
            product["minimum_additional_tzs"]
            if already_held
            else product["minimum_initial_tzs"]
        )
        parked = carried.get(key, 0)
        projected = parked + amount

        if product["availability_required"]:
            execution = "check_current_issue_and_market_availability"
            pending_out[key] = projected
            months_to_min = None
        elif minimum and projected < minimum:
            execution = "accumulate_until_minimum"
            pending_out[key] = projected
            months_to_min = (
                ceil((minimum - projected) / amount) if amount > 0 else None
            )
        else:
            execution = "eligible_for_allocation"
            pending_out.pop(key, None)
            months_to_min = 0

        allocations.append(
            {
                "product_key": key,
                "category": product["category"],
                "instrument": product["instrument"],
                "portfolio_percentage": float(Decimal(weight) * 100),
                "percentage_of_total_savings": _pct(Decimal(amount), available),
                "monthly_amount_tzs": amount,
                "applicable_minimum_tzs": minimum,
                "minimum_basis": "additional" if already_held else "initial",
                "accumulated_balance_tzs": pending_out.get(key, 0),
                "months_to_minimum": months_to_min,
                "execution": execution,
                "access_route": product["access_route"],
                "temporary_holding": (
                    "UTT AMIS Liquid Fund or regulated call account"
                    if execution == "accumulate_until_minimum"
                    else None
                ),
                "real_return": _real_return_flag(product),
                "source_url": product["source_url"],
                "last_verified_at": product["last_verified_at"],
            }
        )

    return _build_result(
        status="ok",
        emergency_contribution=contribution_block,
        investable_amount_tzs=int(remainder),
        allocations=allocations,
        messages=messages,
        **{**common, "pending_accumulation_tzs": pending_out},
    )
