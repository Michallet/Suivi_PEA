"""Mesures de performance avec faux clients qui comptent les appels (critères d'acceptation du README).

    python -m tests.mesures docs/mesures_avant.json

Même script avant et après la refonte : compare les budgets de la section 6 du prompt de migration.
"""
from __future__ import annotations

import json
import resource
import sys
import time
import warnings

from tests.fakes import FauxSupabase, FauxYahoo, base_fictive
from tests.harnais import nouvelle_app

warnings.filterwarnings("ignore")


def compteurs(base: FauxSupabase, yahoo: FauxYahoo) -> dict:
    sup = base.resume()
    return {"supabase_total": len(base.appels), "supabase_detail": dict(sorted(sup.items())),
            "yahoo_total": yahoo.total(), "yahoo_detail": dict(sorted(yahoo.appels.items())),
            "yahoo_telechargements_groupes": yahoo.appels.get("download", 0)}


def remise_a_zero(base: FauxSupabase, yahoo: FauxYahoo) -> None:
    base.remise_a_zero()
    yahoo.appels.clear()
    yahoo.journal_appels.clear()


def cliquer(at, libelle: str):
    return next(b for b in at.button if b.label == libelle)


def mesurer() -> dict:
    res: dict = {}

    # 1. première session à froid + rerun à chaud -----------------------------------------------------
    at, base, yahoo = nouvelle_app("theo")
    t = time.perf_counter()
    at.run()
    froid_s = time.perf_counter() - t
    assert not at.exception, [e.value for e in at.exception]
    res["session_a_froid"] = {**compteurs(base, yahoo), "secondes": round(froid_s, 2)}
    remise_a_zero(base, yahoo)
    t = time.perf_counter()
    at.run()
    res["rerun_complet_caches_chauds"] = {**compteurs(base, yahoo), "secondes": round(time.perf_counter() - t, 2)}

    # 2. interaction sur un widget (sélection de l'axe de la matrice) -----------------------------------
    remise_a_zero(base, yahoo)
    cases = [c for c in at.checkbox if c.key in ("qd_wl", "c.qd.wl")]
    if cases:
        cases[0].check().run()
        res["interaction_widget"] = compteurs(base, yahoo)

    # 3. un utilisateur clique sur 🔄 : coût pour l'ensemble des comptes -------------------------------------
    remise_a_zero(base, yahoo)
    cliquer(at, "🔄").click().run()
    res["clic_actualiser_theo"] = compteurs(base, yahoo)
    remise_a_zero(base, yahoo)
    at2, _, _ = nouvelle_app("alice", base, yahoo, vider=False)
    at2.run()
    res["session_alice_apres_clic_de_theo"] = compteurs(base, yahoo)

    # 4. dix sessions actives (3 comptes), sans vider les caches ---------------------------------------------
    at, base, yahoo = nouvelle_app("theo")
    sessions = []
    for n in range(10):
        a = nouvelle_app(("theo", "alice", "demo")[n % 3], base, yahoo, vider=False)[0]
        a.run()
        sessions.append(a)
    res["dix_sessions"] = {**compteurs(base, yahoo)}
    for a in sessions:  # chacune refait un rerun complet
        a.run()
    res["dix_sessions_puis_un_rerun_chacune"] = compteurs(base, yahoo)

    # 5. mémoire maximale du processus de test (Ko) ---------------------------------------------------------------
    res["memoire_max_ko"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return res


if __name__ == "__main__":
    sortie = sys.argv[1] if len(sys.argv) > 1 else "docs/mesures.json"
    r = mesurer()
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    for k, v in r.items():
        if isinstance(v, dict):
            print(f"{k:42s} supabase={v['supabase_total']:3d} yahoo={v['yahoo_total']:3d} "
                  f"groupés={v['yahoo_telechargements_groupes']} {v.get('secondes', '')}")
        else:
            print(f"{k}: {v}")
