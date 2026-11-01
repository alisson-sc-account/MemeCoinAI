"""Previsões favoritadas (`fav-1`): ganho no clique, ganho atual, isolamento e relatório."""
from datetime import timedelta

from app.db import utcnow
from app.ingest.service import track_token
from app.models import Favorite, LiveQuote, PairSnapshot, Signal, User
from tests.conftest import SOL_MINT

API = "/api/v1/favorites"


def _setup(db, ref=0.000002):
    token, _ = track_token(db, "solana", SOL_MINT)
    created = utcnow() - timedelta(hours=1)
    sig = Signal(token_id=token.id, created_at=created, last_confirmed_at=created, action="buy", strength="strong",
                 status="active", headline="Comprar", reasons=["Volume subindo"], risk_score=20, risk_level="low",
                 opportunity_score=70, reference_price_usd=ref, estimates=[], rules_version="sig-1")
    db.add(sig)
    db.commit()
    return token, sig


def _snap(db, token, ago, price, tag):
    db.add(PairSnapshot(pair_id=token.primary_pair_id, source="test", received_at=utcnow() - timedelta(minutes=ago),
                        normalizer_version="t", payload_hash=tag, price_usd=price))
    db.commit()


def _add(c, **kw):
    return c.post(API, json={"chain_id": "solana", "address": SOL_MINT, **kw})


def test_favorite_records_gain_until_that_moment(auth_client, fake_dex, db):
    token, sig = _setup(db)
    _snap(db, token, 40, 0.000005, "a")  # melhor momento
    _snap(db, token, 30, 0.000001, "b")  # pior momento
    db.add(LiveQuote(token_id=token.id, source="jupiter_price", received_at=utcnow(), price_usd=0.000003))
    db.commit()
    r = _add(auth_client)
    assert r.status_code == 201
    j = r.json()
    assert j["signal_id"] == sig.id and j["tier_label"] == "Compra prioritária" and j["prediction"] == "Deve subir"
    assert j["reference_price_usd"] == 0.000002 and j["price_at_favorite"] == 0.000003
    assert abs(j["gain_at_favorite"] - 0.5) < 1e-9
    assert abs(j["max_gain_until_favorite"] - 1.5) < 1e-9 and abs(j["min_gain_until_favorite"] + 0.5) < 1e-9
    assert j["specs"]["signal"]["reasons"] == ["Volume subindo"] and j["specs"]["market"]["liquidity_usd"]


def test_gain_is_frozen_at_the_click(auth_client, fake_dex, db):
    token, _ = _setup(db)
    db.add(LiveQuote(token_id=token.id, source="jupiter_price", received_at=utcnow(), price_usd=0.000003))
    db.commit()
    assert _add(auth_client).status_code == 201
    db.add(LiveQuote(token_id=token.id, source="jupiter_price", received_at=utcnow() + timedelta(seconds=1), price_usd=0.000009))
    db.commit()
    i = auth_client.get(API).json()["items"][0]
    assert abs(i["gain_at_favorite"] - 0.5) < 1e-9 and i["price_at_favorite"] == 0.000003  # preço triplicou: o registro não muda
    assert i["value_of_100_usd_at_favorite"] == 150.0 and "gain_now" not in i
    assert auth_client.get(API).json()["summary"]["best_gain"] == i["gain_at_favorite"]


def test_repeat_is_idempotent_and_new_signal_is_new_favorite(auth_client, fake_dex, db):
    token, sig = _setup(db)
    first = _add(auth_client).json()
    assert _add(auth_client).json()["id"] == first["id"] and auth_client.get(API).json()["summary"]["count"] == 1
    sig.status = "superseded"
    db.add(Signal(token_id=token.id, action="sell", strength="strong", status="active", headline="Vender", reasons=[],
                  risk_score=70, risk_level="high", opportunity_score=10, reference_price_usd=0.000003, estimates=[],
                  rules_version="sig-1"))
    db.commit()
    assert _add(auth_client).json()["id"] != first["id"]
    assert _add(auth_client, signal_id=sig.id).json()["id"] == first["id"]  # favorita a previsão que estava na tela


def test_missing_data_is_null_not_zero(auth_client, fake_dex, db):
    token, _ = track_token(db, "solana", SOL_MINT)
    db.query(PairSnapshot).delete()
    db.commit()
    j = _add(auth_client).json()
    assert j["signal_id"] is None and j["gain_at_favorite"] is None
    s = auth_client.get(API).json()["summary"]
    assert s["with_gain"] == 0 and s["avg_gain_at_favorite"] is None
    assert "sem dado" in auth_client.get(f"{API}/report").json()["text"]


def test_errors_and_isolation(auth_client, client, fake_dex, db):
    assert _add(auth_client).status_code == 404  # token desconhecido
    _setup(db)
    assert _add(auth_client, signal_id=999_999).status_code == 404
    fav = _add(auth_client).json()
    other = db.get(Favorite, fav["id"])
    mine, other.user_id = other.user_id, db.query(User).filter(User.username == "natan").one().id
    db.commit()
    assert auth_client.get(API).json()["items"] == []  # favorito de outro usuário não aparece
    assert auth_client.delete(f"{API}/{fav['id']}").status_code == 404
    other.user_id = mine
    db.commit()
    assert auth_client.delete(f"{API}/{fav['id']}").status_code == 204 and auth_client.get(API).json()["items"] == []


def test_report_has_gains_and_specifications(auth_client, fake_dex, db):
    _setup(db)
    _add(auth_client)
    text = auth_client.get(f"{API}/report").json()["text"]
    assert "Ganho desde o sinal" not in text and "Preço atual" not in text
    for part in ("Ganho até ali", "Melhor momento", "Pior momento", "Liquidez", "Volume subindo",
                 SOL_MINT, '"specs"', '"market"', "Compra prioritária", "sem taxas"):
        assert part in text, part
