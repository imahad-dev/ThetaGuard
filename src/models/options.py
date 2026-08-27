from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class OptionContract(BaseModel):
    symbol: str = Field(description="Underlying symbol (SPY or QQQ)")
    option_symbol: str = Field(description="OSI format option symbol (e.g. SPY260831P00530000)")
    option_type: OptionType = Field(default=OptionType.PUT)
    strike_price: float = Field(gt=0, description="Strike price in USD")
    expiration_date: date = Field(description="Expiration date (Mon/Wed/Fri)")
    bid: float = Field(ge=0, default=0.0, description="Current bid price")
    ask: float = Field(ge=0, default=0.0, description="Current ask price")
    mid: float = Field(ge=0, default=0.0, description="Midpoint price (bid+ask)/2")
    delta: Optional[float] = Field(default=None, description="Option delta greek (-1.0 to 1.0)")
    gamma: Optional[float] = Field(default=None)
    theta: Optional[float] = Field(default=None)
    vega: Optional[float] = Field(default=None)
    implied_volatility: Optional[float] = Field(default=None, description="Annualized IV")
    open_interest: int = Field(ge=0, default=0)
    volume: int = Field(ge=0, default=0)

    @field_validator("symbol")
    @classmethod
    def validate_underlying(cls, v: str) -> str:
        sym = v.upper().strip()
        if sym not in ("SPY", "QQQ"):
            raise ValueError(f"Option underlying must be 'SPY' or 'QQQ'. Received: {v}")
        return sym


class PutCreditSpread(BaseModel):
    """
    Represents a defined-risk vertical put credit spread:
    - Short Put: higher strike (closer to money, delta -0.15 to -0.20), sold to collect premium.
    - Long Put: lower strike ($5 width lower), bought to define max risk and cap collateral.
    """
    underlying: str = Field(description="SPY or QQQ")
    expiration_date: date = Field(description="Option expiration date")
    short_leg: OptionContract = Field(description="Short Put Leg")
    long_leg: OptionContract = Field(description="Long Put Leg (Protective Put)")
    
    quantity: int = Field(gt=0, default=1, description="Number of contracts")
    spread_width: float = Field(gt=0, default=5.0, description="Strike difference (short strike - long strike)")
    net_credit_per_share: float = Field(gt=0, description="Net premium collected per share (e.g. $0.65)")
    
    # Financial metrics per contract (x100 multiplier)
    max_profit: float = Field(description="Total maximum credit collected = net_credit * 100 * quantity")
    max_loss: float = Field(description="Defined maximum risk = (spread_width - net_credit) * 100 * quantity")
    collateral_required: float = Field(description="Margin required = spread_width * 100 * quantity")
    
    take_profit_target_price: float = Field(description="Debit price to buy back spread at 50% max profit")
    stop_loss_trigger_price: float = Field(description="Debit price to close spread at 200% loss")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("underlying")
    @classmethod
    def validate_underlying(cls, v: str) -> str:
        sym = v.upper().strip()
        if sym not in ("SPY", "QQQ"):
            raise ValueError(f"Spread underlying must be SPY or QQQ. Received: {v}")
        return sym

    @classmethod
    def create(
        cls,
        underlying: str,
        short_leg: OptionContract,
        long_leg: OptionContract,
        quantity: int = 1,
    ) -> "PutCreditSpread":
        if short_leg.strike_price <= long_leg.strike_price:
            raise ValueError(
                f"Invalid Put Credit Spread: Short strike ({short_leg.strike_price}) must be higher "
                f"than Long strike ({long_leg.strike_price})."
            )
        if short_leg.expiration_date != long_leg.expiration_date:
            raise ValueError(
                f"Expiration mismatch: Short ({short_leg.expiration_date}) vs Long ({long_leg.expiration_date})"
            )

        spread_width = round(short_leg.strike_price - long_leg.strike_price, 2)
        
        # Net credit is calculated using conservative execution prices:
        # Sell short leg at bid, buy long leg at ask (or mid if bid/ask spread is tight)
        short_credit = short_leg.bid if short_leg.bid > 0 else short_leg.mid
        long_debit = long_leg.ask if long_leg.ask > 0 else long_leg.mid
        net_credit = round(short_credit - long_debit, 2)

        if net_credit <= 0.05:
            # Fallback to mid if bid/ask spread is wide in after-hours
            net_credit = max(0.10, round(short_leg.mid - long_leg.mid, 2))

        max_profit = round(net_credit * 100.0 * quantity, 2)
        max_loss = round((spread_width - net_credit) * 100.0 * quantity, 2)
        collateral = round(spread_width * 100.0 * quantity, 2)

        # TP: Buy back spread when its value drops by 50% (pay 50% of original credit)
        take_profit_price = round(net_credit * 0.50, 2)
        # SL: Close spread if debit to buy back reaches 3x original credit (loss = 200% of credit)
        stop_loss_price = round(net_credit * 3.00, 2)

        return cls(
            underlying=underlying.upper(),
            expiration_date=short_leg.expiration_date,
            short_leg=short_leg,
            long_leg=long_leg,
            quantity=quantity,
            spread_width=spread_width,
            net_credit_per_share=net_credit,
            max_profit=max_profit,
            max_loss=max_loss,
            collateral_required=collateral,
            take_profit_target_price=take_profit_price,
            stop_loss_trigger_price=stop_loss_price,
        )
