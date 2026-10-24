from tests.fakes import FauxSupabase, FauxYahoo, base_fictive


def test_faux_supabase_filtre_et_compte():
    b = base_fictive()
    r = b.table("transactions").select("id,isin").eq("user_id", "theo").execute()
    assert r.data and set(r.data[0]) == {"id", "isin"}
    assert b.nb("select", "transactions") == 1
    n = b.table("transactions").select("id", count="exact", head=True).eq("user_id", "alice").execute()
    assert n.count == 9 and b.nb() == 2


def test_faux_supabase_upsert_et_cascade():
    b = base_fictive()
    b.table("tickers").upsert([{"user_id": "theo", "isin": "X", "ticker": "T"}], on_conflict="user_id,isin").execute()
    b.table("tickers").upsert([{"user_id": "theo", "isin": "X", "ticker": "T2"}], on_conflict="user_id,isin").execute()
    assert [l["ticker"] for l in b.lignes("tickers", "theo") if l["isin"] == "X"] == ["T2"]
    sid = b.lignes("scenarios", "theo")[0]["id"]
    b.table("scenario_trades").insert({"user_id": "theo", "scenario_id": sid, "isin": "X"}).execute()
    b.table("scenarios").delete().eq("id", sid).eq("user_id", "theo").execute()
    assert not b.lignes("scenario_trades", "theo")


def test_faux_yahoo_compte():
    y = FauxYahoo(indisponibles={"KO.PA"})
    assert y.Ticker("ALP.PA").fast_info.last_price > 0
    assert y.Ticker("KO.PA").fast_info.last_price is None
    assert y.appels["fast_info"] == 2
