"""IA (Gemini) : prompts, contexte, validation, client HTTP, analyse, import par captures, chat, concurrent.

Ce paquet remplace l'ancien `llm.py` ; ses noms publics sont ré-exportés ici pour que `from pea.services import ia as llm`
suffise à l'interface actuelle.
"""
from pea.config import (MAX_APPELS_PAR_JOUR, MAX_CHAT_PAR_JOUR, MAX_IMPORTS_PAR_JOUR, MAX_SUGGESTIONS_PAR_JOUR,
                        MODELE_GEMINI_DEFAUT as MODELE_DEFAUT)
from pea.domain.erreurs import ErreurIA
from pea.services.ia.analyse import analyser
from pea.services.ia.capture import MAX_CAPTURES, MAX_OCTETS_CAPTURES, TYPES_IMAGE, extraire_capture
from pea.services.ia.chat import MAX_TOKENS_CHAT, MAX_TOURS_CHAT, discuter
from pea.services.ia.client import URL, _en_majuscules, _payload_json, _post, _texte_reponse, appeler_json, avec_reessai
from pea.services.ia.concurrent import demander_candidats, suggerer
from pea.services.ia.contexte import construire_contexte, construire_contexte_scenario
from pea.services.ia.prompts import (AVERTISSEMENT, CLES, CRITERES, EXEMPLE, EXEMPLE_SCENARIO, LIBELLES, MAX_MOTS_REPONSE,
                                     POINTS_MAX_PAR_CRITERE, PROMPTS_FICHIER, PROMPTS_MD, SCHEMA_JSON,
                                     SCHEMA_JSON_CAPTURE, SCHEMA_JSON_CONCURRENT, SCHEMA_JSON_SCENARIO, SYSTEME,
                                     SYSTEME_CAPTURE, SYSTEME_CAPTURE_DEFAUT, SYSTEME_CHAT, SYSTEME_CHAT_DEFAUT,
                                     SYSTEME_DEFAUT, SYSTEME_SCENARIO, SYSTEME_SCENARIO_DEFAUT, VERSION_PROMPT,
                                     charger_prompts_md)
from pea.services.ia.validation import (MAX_MOTS_POINT, MAX_MOTS_SYNTHESE, _parser_json, _tronquer_mots,
                                        note_globale, valider_resultat)

__all__ = [n for n in dir() if not n.startswith("__")]
