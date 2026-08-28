"""Banco Central — SGS (séries temporais). SELIC meta = série 432."""
import httpx

_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"


def taxa_selic() -> dict:
    try:
        r = httpx.get(_URL, timeout=10.0)
        r.raise_for_status()
        item = r.json()[0]
        return {"ok": True, "selic_meta_aa": float(item["valor"]), "data": item["data"]}
    except Exception as e:  # noqa: BLE001 — ferramenta devolve erro explícito
        return {"ok": False, "erro": f"API do BCB indisponível: {e}"}
