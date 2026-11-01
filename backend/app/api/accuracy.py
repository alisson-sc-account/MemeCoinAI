"""Aba "Acertos": quantos sinais de subida/queda acertaram e quais."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.views import token_link, token_ref
from app.db import get_db
from app.engine import accuracy
from app.schemas import AccuracyItem, AccuracyPage

router = APIRouter(tags=["accuracy"], dependencies=[Depends(current_user)])

PREDICTION_LABEL = {"buy": "Deve subir", "sell": "Deve descer", "hold": "Observar (sem previsão)"}


@router.get("/accuracy", response_model=AccuracyPage)
def list_accuracy(
    db: Session = Depends(get_db),
    horizon: Literal["15m", "1h", "6h"] = "1h",
    action: Literal["buy", "sell"] | None = None,
    tier: Literal["priority_buy", "possible_buy", "watch", "sell"] | None = None,
    result: Literal["hit", "miss", "pending", "unevaluable"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    items = accuracy.evaluate_signals(db)
    summary = accuracy.summarize(items)
    rows = [i for i in items
            if (action is None or i["signal"].action == action)
            and (tier is None or i["tier"] == tier)
            and (tier == "watch" or i["signal"].action != "hold")  # Observar só quando pedido
            and (result is None or i["results"][horizon]["status"] == result)]
    start = (page - 1) * page_size
    out = [
        AccuracyItem(
            signal_id=i["signal"].id, token=token_ref(i["token"]), link=token_link(i["token"]),
            action=i["signal"].action, tier=i["tier"], tier_label=accuracy.TIER_LABELS[i["tier"]],
            prediction=PREDICTION_LABEL[i["signal"].action], strength=i["signal"].strength,
            headline=i["signal"].headline, created_at=i["signal"].created_at,
            reference_price_usd=i["signal"].reference_price_usd, results=i["results"],
        )
        for i in rows[start:start + page_size]
    ]
    return AccuracyPage(horizon=horizon, summary=summary, items=out, total=len(rows), page=page,
                        page_size=page_size, rules_version=accuracy.RULES_VERSION)
