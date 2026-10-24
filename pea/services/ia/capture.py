"""Import par captures d'écran du courtier (vision). Les images partent telles quelles chez Gemini."""
from __future__ import annotations

import base64

from pea import config
from pea.domain.erreurs import ErreurIA
from pea.services.ia import client
from pea.services.ia.prompts import SCHEMA_JSON_CAPTURE, SYSTEME_CAPTURE

MAX_CAPTURES = 8                        # images par import
MAX_OCTETS_CAPTURES = 15 * 1024 * 1024  # total (limite de requête Gemini : 20 Mo)
TYPES_IMAGE = ("image/png", "image/jpeg", "image/webp")


def extraire_capture(images: list, cle: str, modele: str | None = None, timeout: int = 90) -> dict:
    """Envoie les captures à Gemini et retourne le JSON brut {"lignes": [...]} (à nettoyer avec
    `import_ecran.normaliser_releve`). `images` : liste de (octets, type MIME). Lève ErreurIA.
    """
    modele = modele or config.MODELE_GEMINI_DEFAUT
    if not images:
        raise ErreurIA("Aucune capture à analyser.")
    if len(images) > MAX_CAPTURES:
        raise ErreurIA(f"Maximum {MAX_CAPTURES} captures par import.")
    if any(mime not in TYPES_IMAGE for _, mime in images):
        raise ErreurIA("Format d'image non pris en charge (PNG, JPEG ou WebP).")
    if sum(len(d) for d, _ in images) > MAX_OCTETS_CAPTURES:
        raise ErreurIA("Images trop volumineuses (15 Mo maximum au total).")
    parts = [{"text": f"{len(images)} capture(s) d'écran du portefeuille. Extrais les lignes."}]
    parts += [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}
              for data, mime in images]

    def une_lecture() -> dict:
        obj = client.appeler_json(SYSTEME_CAPTURE, parts, SCHEMA_JSON_CAPTURE, cle, modele, timeout,
                                  max_tokens=8192)
        if not isinstance(obj, dict) or not isinstance(obj.get("lignes"), list):
            raise ErreurIA("Réponse de l'IA inattendue (structure).")
        return obj

    return client.avec_reessai(une_lecture)
