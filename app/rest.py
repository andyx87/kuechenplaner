"""REST-API fuer die Web-App. Spiegelt die Service-Schicht."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from .schemas import OAuthEntscheidung, PatErstellen

from . import adminstats, angebote_import, audit, bilder, chat, config, guided, ki, kontoloeschung, pdf, ratelimit, rezept_adapt, rezept_link, rezept_suche, services, userauth, vision

router = APIRouter(prefix="/api")


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


MAX_UPLOAD = 20 * 1024 * 1024            # 20 MB Standard (Fotos, Bilder, Chat-Anhänge)
MAX_UPLOAD_PDF = 50 * 1024 * 1024        # 50 MB für PDF-Prospekte – Server rendert sie seitenweise klein
MAX_UPLOAD_CHAT_GESAMT = 80 * 1024 * 1024  # Gesamt-Obergrenze für alle Anhänge EINER Chat-Nachricht


def _pruefe_upload_groesse(n: int, maxn: int = MAX_UPLOAD) -> None:
    if n > maxn:
        mb = maxn // (1024 * 1024)
        raise HTTPException(413, f"Datei zu groß (max. {mb} MB). Bitte kleiner oder komprimiert hochladen.")


async def auth(authorization: str | None = Header(default=None)):
    """Session-Auth: validiert den Bearer-Token, setzt den Mandanten-Kontext."""
    ctx = await userauth.context_from_token(_token(authorization))
    if not ctx:
        raise HTTPException(status_code=401, detail="nicht angemeldet")
    userauth.current_account.set(ctx["account_id"])
    userauth.current_user.set(ctx["user_id"])
    return ctx


# ---------- Auth-Routen (öffentlich bzw. eigene Auth) ----------

@router.post("/auth/register")
async def auth_register(body: dict, request: Request):
    ip = ratelimit.client_ip(request)
    ratelimit.pruefe(f"register:ip:{ip}", limit=5, fenster_s=3600)  # F6: Registrierungs-Flut bremsen
    res = await userauth.register(body.get("email", ""), body.get("password", ""), body.get("name", ""),
                                  bootstrap_token=body.get("bootstrap_token"))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.get("/auth/einladung/{token}")
async def auth_einladung_info(token: str):
    info = await userauth.einladung_info(token)
    if not info:
        raise HTTPException(404, "Einladung nicht gefunden")
    return info


@router.post("/auth/einladung-einloesen")
async def auth_einladung_einloesen(body: dict, request: Request):
    ip = ratelimit.client_ip(request)
    ratelimit.pruefe(f"invite:ip:{ip}", limit=10, fenster_s=900)  # F6
    res = await userauth.einladung_einloesen(
        body.get("token"), body.get("name", ""), body.get("password", ""), body.get("email"))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/auth/login")
async def auth_login(body: dict, request: Request):
    # F6: Brute-Force bremsen – pro IP und (gezielt) pro E-Mail/Konto.
    ip = ratelimit.client_ip(request)
    email = (body.get("email", "") or "").strip().lower()
    ratelimit.pruefe(f"login:ip:{ip}", limit=15, fenster_s=300)
    if email:
        # S4 (AND-24/AND-33): Bucket-Schlüssel aus gekappter, gehashter E-Mail
        # statt roher Eingabe (begrenzter Speicher, keine Klartext-Adressen).
        ratelimit.pruefe(f"login:email:{ratelimit.email_schluessel(email)}", limit=8, fenster_s=900,
                         meldung="Zu viele Anmeldeversuche. Bitte in ein paar Minuten erneut versuchen.")
    res = await userauth.login(body.get("email", ""), body.get("password", ""))
    if res.get("error"):
        raise HTTPException(401, res["error"])
    return res


@router.post("/auth/passwort-reset-anfordern")
async def auth_passwort_reset_anfordern(body: dict, request: Request):
    # Gibt immer ok zurück (keine Auskunft, ob die E-Mail existiert).
    # F6: Reset-Mail-Flooding bremsen – pro IP und pro Ziel-E-Mail.
    ip = ratelimit.client_ip(request)
    email = (body.get("email", "") or "").strip().lower()
    ratelimit.pruefe(f"reset:ip:{ip}", limit=5, fenster_s=900)
    if email:
        ratelimit.pruefe(f"reset:email:{ratelimit.email_schluessel(email)}", limit=3, fenster_s=3600)  # S4
    return await userauth.passwort_reset_anfordern(body.get("email", ""))


@router.post("/auth/passwort-reset")
async def auth_passwort_reset(body: dict):
    res = await userauth.passwort_reset_ausfuehren(body.get("token", ""), body.get("password", ""))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/auth/konto-loeschen-anfordern")
async def auth_konto_loeschen_anfordern(body: dict, request: Request):
    """Öffentliche Anforderung der Kontolöschung (Web-Adresse ohne Anmeldung, zusätzlich
    zum In-App-Weg). Mailt einen Bestätigungslink;
    gelöscht wird erst nach dem Klick (s. app/kontoloeschung.py). Antwort bewusst
    neutral – keine Auskunft, ob die E-Mail ein Konto hat. Rate-Limit wie beim
    Passwort-Reset (Mail-Flooding / Enumeration bremsen)."""
    ip = ratelimit.client_ip(request)
    email = (body.get("email", "") or "").strip().lower()
    ratelimit.pruefe(f"konto-loeschen:ip:{ip}", limit=5, fenster_s=900)
    if email:
        ratelimit.pruefe(f"konto-loeschen:email:{ratelimit.email_schluessel(email)}", limit=3, fenster_s=3600)  # S4
    return await kontoloeschung.anfordern(email)


@router.post("/auth/konto-loeschen")
async def auth_konto_loeschen(body: dict, request: Request):
    """Führt die Kontolöschung aus – NIE allein auf Basis einer E-Mail-Eingabe,
    sondern nur mit dem Bestätigungstoken aus der Mail. Dieselbe Logik wie
    POST /konto/loeschen (Modus 'selbst')."""
    ip = ratelimit.client_ip(request)
    ratelimit.pruefe(f"konto-loeschen-confirm:ip:{ip}", limit=10, fenster_s=900)
    res = await kontoloeschung.bestaetigen((body or {}).get("token", ""))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/auth/email-verifizieren")
async def auth_email_verifizieren(body: dict):
    res = await userauth.email_verifizieren(body.get("token", ""))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/auth/logout")
async def auth_logout(authorization: str | None = Header(default=None)):
    return await userauth.logout(_token(authorization))



@router.get("/auth/me")
async def auth_me(authorization: str | None = Header(default=None)):
    me = await userauth.me_for_token(_token(authorization))
    if not me:
        raise HTTPException(401, "nicht angemeldet")
    return me


# ---------- Claude & MCP: OAuth-Zustimmung, verbundene Apps, persönliche Tokens ----------

def _mcp_aktiv() -> None:
    if not config.MCP_ENABLED:
        raise HTTPException(404, "MCP ist auf diesem Server deaktiviert.")


@router.get("/mcp/info")
async def mcp_info(ctx=Depends(auth)):
    """Daten für die Einstellungsseite: MCP-URL und ob der Endpunkt aktiv ist."""
    return {"aktiv": config.MCP_ENABLED, "mcp_url": f"{config.PUBLIC_URL}/mcp",
            "https": config.PUBLIC_URL.startswith("https://")}


@router.get("/oauth/anfrage/{anfrage}")
async def oauth_anfrage_info(anfrage: str, ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    info = await oauth.anfrage_info(anfrage, ctx["account_id"])
    if not info:
        raise HTTPException(404, "Diese Verbindungsanfrage ist abgelaufen oder ungültig. Bitte in der App neu verbinden.")
    return info


@router.post("/oauth/anfrage/{anfrage}")
async def oauth_anfrage_entscheiden(anfrage: str, body: OAuthEntscheidung, ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    res = await oauth.anfrage_entscheiden(anfrage, ctx["user_id"], ctx["account_id"], body.zustimmen, body.scopes)
    if not res:
        raise HTTPException(404, "Diese Verbindungsanfrage ist abgelaufen oder ungültig.")
    return res


@router.get("/verbindungen")
async def verbindungen(ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    return {"apps": await oauth.verbindungen_liste(ctx["user_id"], ctx["account_id"]),
            "tokens": await oauth.pat_liste(ctx["user_id"], ctx["account_id"]),
            "mcp_url": f"{config.PUBLIC_URL}/mcp"}


@router.delete("/verbindungen/apps/{grant_id}")
async def verbindung_widerrufen(grant_id: int, ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    if not await oauth.verbindung_widerrufen(grant_id, ctx["user_id"], ctx["account_id"]):
        raise HTTPException(404, "Verbindung nicht gefunden.")
    return {"ok": True}


@router.post("/verbindungen/tokens")
async def token_erstellen(body: PatErstellen, ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    res = await oauth.pat_erstellen(ctx["user_id"], ctx["account_id"], body.name, list(body.scopes), body.gueltig_tage)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.delete("/verbindungen/tokens/{token_id}")
async def token_widerrufen(token_id: int, ctx=Depends(auth)):
    _mcp_aktiv()
    from . import oauth
    if not await oauth.pat_widerrufen(token_id, ctx["user_id"]):
        raise HTTPException(404, "Token nicht gefunden.")
    return {"ok": True}


async def admin_auth(ctx=Depends(auth)):
    """Wie auth, aber nur für Plattform-Super-Admins."""
    if not await userauth.ist_super_admin(ctx["user_id"]):
        raise HTTPException(status_code=403, detail="nur Super-Admin")
    return ctx


async def support_auth(ctx=Depends(auth)):
    """Wie auth, aber für Super-Admin ODER Support."""
    if not await userauth.ist_admin_oder_support(ctx["user_id"]):
        raise HTTPException(status_code=403, detail="nur Admin/Support")
    return ctx


def _ki_noetig(faehigkeit: str = "text") -> None:
    """503, wenn die KI-Fähigkeit auf dieser Instanz nicht eingerichtet ist."""
    if not ki.verfuegbar(faehigkeit):
        raise ki.KiNichtKonfiguriert(faehigkeit)


async def ki_auth(ctx=Depends(auth)):
    """Wie auth, blockiert aber Nutzer ohne KI-Freigabe (harte Server-Barriere) und
    Instanzen ohne konfigurierten KI-Anbieter (503).
    Owner/Super-Admin immer erlaubt; sonst account_mitglied.ki_erlaubt."""
    _ki_noetig("text")
    if not await userauth.darf_ki(ctx["user_id"], ctx["account_id"]):
        raise HTTPException(status_code=403, detail="KI-Funktionen sind für dich deaktiviert.")
    return ctx


async def ki_vision_auth(ctx=Depends(ki_auth)):
    """Wie ki_auth, zusätzlich muss ein bildfähiges Modell konfiguriert sein."""
    _ki_noetig("vision")
    return ctx


@router.get("/ki/status")
async def ki_status(ctx=Depends(auth)):
    """Welche KI-Funktionen diese Instanz anbietet und ob der Nutzer sie nutzen darf.
    Die Web-App blendet danach die KI-Knöpfe ein oder aus. Enthält keine URLs/Schlüssel."""
    st = ki.status()
    st["darf_ki"] = bool(await userauth.darf_ki(ctx["user_id"], ctx["account_id"]))
    return st


@router.get("/einladungen", dependencies=[Depends(auth)])
async def einladungen_liste():
    return await userauth.list_einladungen()


@router.post("/einladungen")
async def einladung_anlegen(body: dict, ctx=Depends(auth)):
    res = await userauth.create_einladung(body.get("email", ""), ctx["user_id"])
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.delete("/einladungen/{eid}", dependencies=[Depends(auth)])
async def einladung_stornieren(eid: int):
    return await userauth.cancel_einladung(eid)


@router.get("/konto/vorrat-modus")
async def vorrat_modus_get(ctx=Depends(auth)):
    """Vorrat-Modus: 'voll' (App-Vorrat) oder 'light' (Freitext bei der Generierung)."""
    return await services.get_vorrat_modus(ctx["account_id"])


@router.put("/konto/vorrat-modus")
async def vorrat_modus_put(body: dict, ctx=Depends(auth)):
    return await services.set_vorrat_modus(ctx["account_id"], (body or {}).get("modus"))


@router.post("/konto/loeschen")
async def konto_loeschen(body: dict, ctx=Depends(auth)):
    """Self-Service: eigenes Konto löschen. modus='selbst' (nur eigener Login; letzter
    Nutzer → ganzer Haushalt) oder 'haushalt' (nur Eigentümer; kompletter Haushalt)."""
    modus = (body or {}).get("modus")
    modus = modus if modus in ("selbst", "haushalt") else "selbst"
    res = await services.loesche_eigenes_konto(modus)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.get("/konto/export")
async def konto_export(ctx=Depends(auth)):
    """DSGVO-Datenexport (Art. 15 Auskunft / Art. 20 Portabilität): alle Konto-Daten
    als JSON-Download."""
    import json
    data = await services.export_konto_daten()
    if data.get("error"):
        raise HTTPException(400, data["error"])
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=topfplan-datenexport.json"},
    )


@router.get("/admin/users", dependencies=[Depends(support_auth)])
async def admin_users_get(q: str | None = None, limit: int = 25, offset: int = 0, sort: str = "id_desc"):
    """Paginierte/suchbare Nutzerliste fürs Backoffice (skaliert bei vielen Nutzern)."""
    return await userauth.list_users_paged(q=q, limit=limit, offset=offset, sort=sort)


@router.get("/admin/kennzahlen", dependencies=[Depends(support_auth)])
async def admin_kennzahlen_get():
    """KPI-Übersicht fürs Admin-Dashboard (Nutzer, Haushalte, Aktivität, Rezepte)."""
    return await adminstats.kennzahlen()


@router.put("/admin/users/{uid}/angebote-upload")
async def admin_user_upload_put(uid: int, body: dict, ctx=Depends(admin_auth)):
    res = await userauth.set_darf_angebote_upload(uid, bool(body.get("erlaubt")))
    audit.log_admin_action(ctx, "user.angebote_upload.setzen", "user:" + str(uid),
                            neu={"erlaubt": bool(body.get("erlaubt"))})
    return res


@router.put("/admin/users/{uid}/ki")
async def admin_user_ki_put(uid: int, body: dict, ctx=Depends(admin_auth)):
    """Super-Admin: KI-Nutzung eines Users erlauben/sperren."""
    res = await userauth.set_mitglied_ki(uid, bool(body.get("erlaubt")))
    audit.log_admin_action(ctx, "user.ki.setzen", "user:" + str(uid),
                            neu={"erlaubt": bool(body.get("erlaubt"))})
    return res


@router.put("/admin/users/{uid}/rolle")
async def admin_user_rolle_put(uid: int, body: dict, ctx=Depends(admin_auth)):
    """Super-Admin vergibt/entzieht die Support-Rolle (oder 'super_admin')."""
    res = await userauth.set_plattform_rolle(uid, body.get("rolle"), ctx["user_id"])
    audit.log_admin_action(ctx, "user.rolle.setzen", "user:" + str(uid),
                            alt=res.get("alt_rolle"), neu=res.get("plattform_rolle") if not res.get("error") else None)
    if res.get("error") == "letzter_super_admin":
        raise HTTPException(409, "letzter_super_admin")
    return res


@router.put("/admin/users/{uid}/aktiv")
async def admin_user_aktiv_put(uid: int, body: dict, ctx=Depends(admin_auth)):
    """Super-Admin sperrt/entsperrt einen Nutzer (Notfall-Hebel). Gesperrte können sich
    nicht mehr einloggen und werden sofort ausgeloggt."""
    res = await userauth.set_user_aktiv(uid, bool(body.get("aktiv")), ctx["user_id"])
    audit.log_admin_action(ctx, "user.aktiv.setzen", "user:" + str(uid),
                            alt=res.get("alt_aktiv"), neu=res.get("aktiv") if not res.get("error") else None)
    if res.get("error") == "letzter_super_admin":
        raise HTTPException(409, "letzter_super_admin")
    return res


# ---------- Bugreports ----------

@router.post("/bugreport", dependencies=[Depends(auth)])
async def bugreport_create(body: dict, user_agent: str = Header(default="")):
    """In-App-Fehlermeldung des aktuellen Nutzers."""
    return await services.create_bugreport(
        body.get("text", ""), body.get("seite"), user_agent
    )


@router.get("/admin/bugreports", dependencies=[Depends(support_auth)])
async def bugreport_list(nur_offen: bool = False):
    return await services.list_bugreports(nur_offen)


@router.put("/admin/bugreports/{bid}")
async def bugreport_status(bid: int, body: dict, ctx=Depends(support_auth)):
    res = await services.set_bugreport_status(bid, body.get("status", "offen"))
    audit.log_admin_action(ctx, "bugreport.status.setzen", "bugreport:" + str(bid),
                            neu={"status": body.get("status", "offen")})
    return res


# ---------- Zutaten-Kuratierung (Super-Admin) ----------

@router.get("/admin/zutaten-kuratierung", dependencies=[Depends(admin_auth)])
async def zutaten_kuratierung_get():
    return await services.list_kuratier_kandidaten()


@router.post("/admin/zutaten/{zid}/global")
async def zutat_global_post(zid: int, ctx=Depends(admin_auth)):
    res = await services.zutat_global_machen(zid)
    audit.log_admin_action(ctx, "zutat.global_machen", "zutat:" + str(zid))
    return res


@router.post("/admin/zutaten/{zid}/merge")
async def zutat_merge_post(zid: int, body: dict, ctx=Depends(admin_auth)):
    res = await services.merge_zutat(zid, int(body.get("ziel_id")))
    audit.log_admin_action(ctx, "zutat.merge", "zutat:" + str(zid),
                            neu={"ziel_id": int(body.get("ziel_id"))})
    return res


@router.post("/admin/zutaten/{zid}/kuratieren")
async def zutat_kuratieren_post(zid: int, body: dict, ctx=Depends(admin_auth)):
    """Ziel-Name (Freitext): gleichnamigen globalen Master mergen, sonst neu global anlegen."""
    res = await services.kuratiere_zutat_auf_name(zid, body.get("name", ""))
    audit.log_admin_action(ctx, "zutat.kuratieren", "zutat:" + str(zid),
                            neu={"name": body.get("name", "")})
    return res


# ---------- Pydantic-Modelle ----------

class GeraetIn(BaseModel):
    name: str
    typ: str | None = None
    notizen: str | None = None
    standard: bool = True


class HeuteIn(BaseModel):
    geraet_ids: list[int] = []


class VorratItem(BaseModel):
    name: str
    menge: float
    einheit: str
    ablaufdatum: str | None = None
    lagerort_id: int | None = None
    ort: str | None = None
    kategorie: str | None = None


class VorratUpdate(BaseModel):
    menge: float
    einheit: str
    ablaufdatum: str | None = None
    lagerort_id: int | None = None
    ort: str | None = None


class ZutatIn(BaseModel):
    name: str
    menge: float | None = None
    einheit: str | None = None
    optional: bool = False


class RezeptGeraetIn(BaseModel):
    geraet_id: int | None = None
    name: str | None = None
    pflicht: bool = True


class VarianteIn(BaseModel):
    geraet: str | None = None   # Geraetename oder null (= ohne Geraet)
    text: str = ""


class KomponenteIn(BaseModel):
    titel: str = ""
    varianten: list[VarianteIn] = []


class RezeptIn(BaseModel):
    name: str
    beschreibung: str | None = None
    anleitung: str | None = None
    portionen: int = 2
    dauer_minuten: int | None = None
    quelle: str | None = None
    gang: str | None = None
    kueche: str | None = None
    zutaten: list[ZutatIn] = []
    geraete: list[RezeptGeraetIn] = []
    zubereitung: list[KomponenteIn] = []


class KochenIn(BaseModel):
    faktor: float = 1.0


class GeraetUpdate(BaseModel):
    name: str | None = None
    typ: str | None = None
    notizen: str | None = None
    standard: bool | None = None


# ---------- Geraete ----------

@router.get("/geraete", dependencies=[Depends(auth)])
async def geraete():
    return await services.list_geraete()


@router.post("/geraete", dependencies=[Depends(auth)])
async def geraet_anlegen(g: GeraetIn):
    return await services.add_geraet(g.name, g.typ, g.notizen, g.standard)


@router.get("/geraete/heute", dependencies=[Depends(auth)])
async def geraete_heute():
    return await services.get_geraete_heute()


@router.put("/geraete/heute", dependencies=[Depends(auth)])
async def geraete_heute_setzen(h: HeuteIn):
    return await services.set_geraete_heute(h.geraet_ids)


@router.put("/geraete/{gid}", dependencies=[Depends(auth)])
async def geraet_aktualisieren(gid: int, g: GeraetUpdate):
    res = await services.update_geraet(gid, g.name, g.typ, g.notizen, g.standard)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/geraete/{gid}", dependencies=[Depends(auth)])
async def geraet_loeschen(gid: int):
    return await services.delete_geraet(gid)


# ---------- Personen / Haushalt ----------

class PersonIn(BaseModel):
    name: str
    rolle: str = "erwachsener"          # 'erwachsener' | 'kind'
    kcal_ziel: int | None = None
    eiweiss_pct: int = 30
    fett_pct: int = 30
    kh_pct: int = 40
    portionsfaktor: float = 1.0
    aktiv: bool = True
    ernaehrung: str | None = None       # None = unveraendert lassen (Editor ohne Praeferenz-Felder)
    allergien: str | None = None
    mag_nicht: str | None = None
    mag_gern: str | None = None


@router.get("/personen", dependencies=[Depends(auth)])
async def personen():
    return await services.list_personen()


class PersonenHeuteIn(BaseModel):
    person_ids: list[int] = []


@router.get("/personen/heute", dependencies=[Depends(auth)])
async def personen_heute():
    return await services.list_personen_heute()


@router.put("/personen/heute", dependencies=[Depends(auth)])
async def personen_heute_setzen(p: PersonenHeuteIn):
    return await services.set_personen_heute(p.person_ids)


@router.post("/personen", dependencies=[Depends(auth)])
async def person_anlegen(p: PersonIn):
    return await services.add_person(p.name, p.rolle, p.kcal_ziel, p.eiweiss_pct,
                                     p.fett_pct, p.kh_pct, p.portionsfaktor, p.aktiv,
                                     p.ernaehrung or "", p.allergien or "",
                                     p.mag_nicht or "", p.mag_gern or "")


@router.put("/personen/{pid}", dependencies=[Depends(auth)])
async def person_aktualisieren(pid: int, p: PersonIn):
    res = await services.update_person(pid, p.name, p.rolle, p.kcal_ziel, p.eiweiss_pct,
                                       p.fett_pct, p.kh_pct, p.portionsfaktor, p.aktiv,
                                       p.ernaehrung, p.allergien, p.mag_nicht, p.mag_gern)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/personen/{pid}", dependencies=[Depends(auth)])
async def person_loeschen(pid: int):
    return await services.delete_person(pid)


@router.get("/personen/{pid}/notizen", dependencies=[Depends(auth)])
async def person_notizen(pid: int):
    return await services.list_person_notizen(pid)


@router.post("/personen/{pid}/notizen", dependencies=[Depends(auth)])
async def person_notiz_add(pid: int, body: dict):
    return await services.add_person_notiz(pid, body.get("text", ""))


@router.put("/personen/notizen/{nid}", dependencies=[Depends(auth)])
async def person_notiz_update(nid: int, body: dict):
    return await services.update_person_notiz(nid, body.get("text", ""))


@router.delete("/personen/notizen/{nid}", dependencies=[Depends(auth)])
async def person_notiz_delete(nid: int):
    return await services.delete_person_notiz(nid)


@router.get("/konto/chat-memory", dependencies=[Depends(auth)])
async def chat_memory_get():
    return {"aktiv": await services.get_chat_memory_aktiv()}


@router.put("/konto/chat-memory", dependencies=[Depends(auth)])
async def chat_memory_put(body: dict):
    return await services.set_chat_memory_aktiv(bool(body.get("aktiv", True)))


@router.get("/konto/auto-bild", dependencies=[Depends(auth)])
async def auto_bild_get():
    return {"aktiv": await services.get_auto_bild()}


@router.put("/konto/auto-bild", dependencies=[Depends(auth)])
async def auto_bild_put(body: dict):
    return await services.set_auto_bild(bool(body.get("aktiv", True)))


class AbwesenheitRegelIn(BaseModel):
    woche_typ: str = "alle"
    von_wochentag: int
    von_mahlzeit: str
    bis_wochentag: int
    bis_mahlzeit: str
    folgewoche: bool = False
    notiz: str | None = None


@router.get("/personen/verfuegbarkeit", dependencies=[Depends(auth)])
async def personen_verfuegbarkeit(datum: str, mahlzeit: str = "Abendessen"):
    from datetime import date as date_t
    ids = await services.get_verfuegbar(date_t.fromisoformat(datum), mahlzeit)
    return {"datum": datum, "mahlzeit": mahlzeit, "person_ids": ids}


@router.get("/personen/{pid}/abwesenheit", dependencies=[Depends(auth)])
async def abwesenheit_regeln(pid: int):
    # Regeln sind bereits in list_personen enthalten; dieser Endpunkt dient als direkter Zugriff
    from .db import acquire
    async with acquire() as con:
        rows = await con.fetch(
            "SELECT * FROM person_abwesenheit_regel WHERE person_id=$1 ORDER BY id", pid
        )
    return [dict(r) for r in rows]


@router.post("/personen/{pid}/abwesenheit", dependencies=[Depends(auth)])
async def abwesenheit_regel_anlegen(pid: int, r: AbwesenheitRegelIn):
    return await services.add_abwesenheit_regel(
        pid, r.woche_typ, r.von_wochentag, r.von_mahlzeit,
        r.bis_wochentag, r.bis_mahlzeit, r.folgewoche, r.notiz,
    )


@router.delete("/personen/abwesenheit/{rid}", dependencies=[Depends(auth)])
async def abwesenheit_regel_loeschen(rid: int):
    return await services.delete_abwesenheit_regel(rid)


# ---------- Lagerorte ----------

class LagerortIn(BaseModel):
    name: str
    sortierung: int = 0


@router.get("/lagerorte", dependencies=[Depends(auth)])
async def lagerorte():
    return await services.list_lagerorte()


@router.post("/lagerorte", dependencies=[Depends(auth)])
async def lagerort_anlegen(l: LagerortIn):
    return await services.add_lagerort(l.name, l.sortierung)


@router.put("/lagerorte/{lid}", dependencies=[Depends(auth)])
async def lagerort_aktualisieren(lid: int, l: LagerortIn):
    res = await services.update_lagerort(lid, l.name, l.sortierung)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/lagerorte/{lid}", dependencies=[Depends(auth)])
async def lagerort_loeschen(lid: int):
    return await services.delete_lagerort(lid)


@router.delete("/lagerorte/{lid}/vorrat", dependencies=[Depends(auth)])
async def lagerort_vorrat_leeren(lid: int):
    """Loescht ALLE Vorrats-Artikel dieses Lagerorts (fuer 'Bereich neu erfassen')."""
    return await services.delete_vorrat_by_lagerort(lid)


# ---------- Zutaten ----------

@router.get("/zutaten", dependencies=[Depends(auth)])
async def zutaten():
    return await services.list_zutaten()


@router.post("/zutaten", dependencies=[Depends(auth)])
async def zutat_anlegen(body: dict):
    """Legt eine Zutat an. Ohne kanonische_zutat_id eine Master-Zutat."""
    return await services.create_zutat(
        body.get("name"), body.get("standard_einheit"), body.get("kategorie"),
        bool(body.get("grundzutat", False)), body.get("gebinde_menge"),
        body.get("gebinde_einheit"), body.get("kanonische_zutat_id"),
    )


@router.get("/zutaten/master", dependencies=[Depends(auth)])
async def zutaten_master():
    return await services.list_master_zutaten()


@router.get("/zutaten/unmapped", dependencies=[Depends(auth)])
async def zutaten_unmapped():
    return await services.list_unmapped_zutaten()


@router.get("/zutaten/unbestaetigt", dependencies=[Depends(auth)])
async def zutaten_unbestaetigt():
    return await services.list_unbestaetigte_zuordnungen()


@router.put("/zutaten/{zid}/grundzutat", dependencies=[Depends(auth)])
async def zutat_grundzutat(zid: int, body: dict):
    return await services.set_grundzutat(zid, bool(body.get("grundzutat", True)))


@router.put("/zutaten/{zid}/kanonisch", dependencies=[Depends(auth)])
async def zutat_kanonisch(zid: int, body: dict):
    return await services.set_kanonische_zutat(
        zid, body.get("master_zutat_id"), bool(body.get("fixiert", False))
    )


@router.put("/zutaten/{zid}/gebinde", dependencies=[Depends(auth)])
async def zutat_gebinde(zid: int, body: dict):
    return await services.set_gebinde(zid, body.get("gebinde_menge"), body.get("gebinde_einheit"))


@router.put("/zutaten/{zid}/name", dependencies=[Depends(auth)])
async def zutat_name(zid: int, body: dict):
    return await services.rename_zutat(zid, body.get("name", ""))


@router.delete("/zutaten/{zid}", dependencies=[Depends(auth)])
async def zutat_delete(zid: int):
    return await services.delete_zutat(zid)


# ---------- Vorrat ----------

@router.get("/vorrat", dependencies=[Depends(auth)])
async def vorrat():
    return await services.list_vorrat()


@router.get("/vorrat/aggregiert", dependencies=[Depends(auth)])
async def vorrat_aggregiert():
    return await services.vorrat_aggregiert()


@router.post("/vorrat", dependencies=[Depends(auth)])
async def vorrat_hinzufuegen(items: list[VorratItem]):
    return await services.add_vorrat([i.model_dump() for i in items])


@router.put("/vorrat/{vid}", dependencies=[Depends(auth)])
async def vorrat_aktualisieren(vid: int, v: VorratUpdate):
    res = await services.update_vorrat(vid, v.menge, v.einheit, v.ablaufdatum, v.lagerort_id)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/vorrat/{vid}", dependencies=[Depends(auth)])
async def vorrat_loeschen(vid: int):
    return await services.delete_vorrat(vid)


@router.post("/vorrat/foto", dependencies=[Depends(ki_vision_auth)])
async def vorrat_foto(datei: UploadFile = File(...)):
    """Foto -> KI (Vision) -> Vorschlagsliste (KEIN automatischer Eintrag).
    Die Web-App zeigt die Liste zum Bearbeiten und postet sie dann an /vorrat."""
    raw = await datei.read()
    _pruefe_upload_groesse(len(raw))
    b64 = base64.b64encode(raw).decode("ascii")
    media_type = datei.content_type or "image/jpeg"
    vorschlag = await vision.foto_zu_items(b64, media_type)
    return {"vorschlag": vorschlag}


@router.post("/geraete/foto", dependencies=[Depends(ki_vision_auth)])
async def geraete_foto(datei: UploadFile = File(...)):
    """Foto -> KI erkennt Kuechengeraete -> Vorschlagsliste (kein automatischer Eintrag)."""
    raw = await datei.read()
    _pruefe_upload_groesse(len(raw))
    b64 = base64.b64encode(raw).decode("ascii")
    media_type = datei.content_type or "image/jpeg"
    try:
        return {"vorschlag": await vision.foto_zu_geraeten(b64, media_type)}
    except Exception:
        return {"vorschlag": [], "hinweis": "Bild konnte nicht verarbeitet werden."}


# ---------- Rezepte ----------

@router.get("/rezepte", dependencies=[Depends(auth)])
async def rezepte(query: str | None = None, gang: str | None = None, kueche: str | None = None,
                  zutaten: str | None = None, markt: str | None = None, vorrat: int = 1):
    zlist = [z for z in (zutaten or "").split(",") if z.strip()] or None
    return await services.search_rezepte(query, gang=gang, kueche=kueche, zutaten=zlist,
                                         markt=markt, vorrat_aktiv=bool(vorrat))


@router.get("/rezepte/kategorien", dependencies=[Depends(auth)])
async def rezepte_kategorien():
    return await services.rezept_kategorien()


@router.get("/rezepte/vorschlagen", dependencies=[Depends(auth)])
async def rezepte_vorschlagen(limit: int = 10):
    return await services.rezepte_vorschlagen(limit)


@router.get("/rezepte/aus-angeboten", dependencies=[Depends(auth)])
async def rezepte_aus_angeboten(haendler: str, datum: str, limit: int = 8):
    """Koch-Ideen aus den am Datum gueltigen Angeboten eines Markts."""
    from datetime import date as dt_date
    return await services.rezepte_aus_angeboten(haendler, dt_date.fromisoformat(datum), limit)


@router.get("/rezepte/{rezept_id}/angebote", dependencies=[Depends(auth)])
async def rezept_angebote(rezept_id: int, markt: str | None = None, datum: str | None = None):
    """Welche Zutaten dieses Rezepts sind aktuell im Angebot der gewaehlten Maerkte?"""
    from datetime import date as dt_date
    d = dt_date.fromisoformat(datum) if datum else None
    return await services.rezept_angebote(rezept_id, markt, d)


@router.post("/rezepte/geraete-anpassen", dependencies=[Depends(ki_auth)])
async def rezepte_geraete_anpassen():
    """Passt die Zubereitung aller Rezepte per KI an die aktuellen Geraete an (Hintergrund)."""
    job_id = await rezept_adapt.starte()
    return {"job_id": job_id}


@router.get("/rezepte/geraete-anpassen-status/{job_id}", dependencies=[Depends(auth)])
async def rezepte_geraete_anpassen_status(job_id: str):
    s = rezept_adapt.status(job_id)
    if s is None:
        raise HTTPException(404, "unbekannter Job")
    return s


@router.post("/rezepte/{rid}/an-geraete-anpassen", dependencies=[Depends(ki_auth)])
async def rezept_an_geraete_anpassen(rid: int):
    """Passt EIN Rezept (z.B. frisch importiertes) an die eigenen Geräte an (KI)."""
    res = await rezept_adapt.adaptiere_eines(rid)
    if res.get("error"):
        raise HTTPException(404, res["error"])
    return res


@router.post("/rezepte/generieren", dependencies=[Depends(ki_auth)])
async def rezept_generieren(body: dict):
    """KI-Rezept aus Vorrat + heutigen Geraeten + Vorlieben (+ optional Angeboten +
    Wunsch). Speichert nicht – Rueckgabe wird im Frontend importiert/eingeplant."""
    return await chat.generiere_rezept(
        body.get("wunsch"),
        body.get("haendler") or None,
        body.get("vorrat", True) is not False,
        body.get("person_ids") or None,
        body.get("portionen") or None,
        freitext_vorrat=body.get("freitext_vorrat") or None,
    )


@router.get("/rezepte/{rid}", dependencies=[Depends(auth)])
async def rezept(rid: int):
    res = await services.get_rezept(rid)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.get("/rezepte/{rid}/vorrat-check", dependencies=[Depends(auth)])
async def rezept_vorrat_check(rid: int):
    """Verfuegbarkeit jeder Pflicht-Zutat im Vorrat (Basis Faktor 1)."""
    res = await services.check_vorrat_fuer_rezept(rid)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


class BewertungIn(BaseModel):
    sterne: int
    kommentar: str | None = None


@router.put("/rezepte/{rid}/bewertung", dependencies=[Depends(auth)])
async def rezept_bewertung_setzen(rid: int, b: BewertungIn):
    if not 1 <= b.sterne <= 5:
        raise HTTPException(400, "Sterne muss zwischen 1 und 5 liegen")
    return await services.set_bewertung(rid, b.sterne, b.kommentar)


@router.delete("/rezepte/{rid}/bewertung", dependencies=[Depends(auth)])
async def rezept_bewertung_loeschen(rid: int):
    return await services.delete_bewertung(rid)


@router.post("/rezepte/{rid}/in-warenkorb", dependencies=[Depends(auth)])
async def rezept_in_warenkorb(rid: int):
    """Pflicht-Zutaten des Rezepts in den Warenkorb legen (verknüpft mit dem Rezept)."""
    return await services.rezept_zutaten_in_warenkorb(rid)


@router.put("/rezepte/{rid}/veroeffentlicht")
async def rezept_veroeffentlicht(rid: int, body: dict, ctx=Depends(auth)):
    """Veröffentlichen (für alle Konten sichtbar) bleibt Super-Admins vorbehalten.
    Das ZURÜCKZIEHEN (auf privat) darf jeder Eigentümer für sein eigenes Rezept –
    RLS stellt sicher, dass nur eigene Rezepte betroffen sind.
    globalisieren=True macht nicht-globale Zutaten vor der Freigabe global."""
    will_publish = bool(body.get("veroeffentlicht", True))
    admin = await userauth.ist_super_admin(ctx["user_id"])
    if will_publish and not admin:
        raise HTTPException(403, "Veröffentlichen ist nur Admins erlaubt")
    # Zurückziehen/Entfernen: Eigentümer nur eigene (RLS); Admin darf jedes (Bypass).
    return await services.set_veroeffentlicht(
        rid, will_publish, bool(body.get("globalisieren", False)), als_admin=admin)


@router.post("/rezepte/{rid}/bild", dependencies=[Depends(auth)])
async def rezept_bild_upload(rid: int, datei: UploadFile = File(...)):
    """Eigenes Bild hochladen -> 1:1-Zuschnitt + max 1024 -> beim Rezept speichern."""
    raw = await datei.read()
    _pruefe_upload_groesse(len(raw))
    try:
        data_url = bilder.quadrat_resize(raw)
    except Exception:
        raise HTTPException(400, "Bild konnte nicht verarbeitet werden")
    res = await services.set_rezept_bild(rid, data_url)
    if res.get("error"):
        raise HTTPException(404, res["error"])
    return {**res, "bild": data_url}


@router.post("/rezepte/{rid}/bild/generieren", dependencies=[Depends(ki_auth)])
async def rezept_bild_generieren(rid: int):
    """Bild per KI erzeugen und beim Rezept speichern."""
    _ki_noetig("bild")
    r = await services.get_rezept(rid)
    if r is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    data_url = await bilder.generiere_rezeptbild(r["name"], r.get("beschreibung"), r.get("zutaten"))
    if not data_url:
        raise HTTPException(502, "Bildgenerierung derzeit nicht verfügbar")
    res = await services.set_rezept_bild(rid, data_url)
    if res.get("error"):
        raise HTTPException(404, res["error"])
    return {**res, "bild": data_url}


@router.post("/rezepte/{rid}/guided", dependencies=[Depends(ki_auth)])
async def rezept_guided(rid: int, body: dict | None = None):
    """Guided-Cooking-Schritte (KI-strukturiert, je Varianten-Kombination gecacht).
    body: {varianten:[idx je Komponente], force:bool}."""
    body = body or {}
    varianten = body.get("varianten") if isinstance(body.get("varianten"), list) else None
    res = await guided.get_guided(rid, varianten, bool(body.get("force")))
    if res.get("error"):
        raise HTTPException(502, res["error"])
    return res


@router.post("/rezepte/{rid}/guided/frage", dependencies=[Depends(ki_auth)])
async def rezept_guided_frage(rid: int, body: dict):
    """KI-Assistent im Kochmodus: kurze Antwort zur Frage im Kontext des Schritts."""
    res = await guided.frage(rid, (body or {}).get("schritt"), (body or {}).get("frage", ""))
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.delete("/rezepte/{rid}/bild", dependencies=[Depends(auth)])
async def rezept_bild_loeschen(rid: int):
    return await services.set_rezept_bild(rid, None)


@router.get("/rezepte/{rid}/bild", dependencies=[Depends(auth)])
async def rezept_bild_get(rid: int):
    """Nur das Bild (Data-URL) für Listen-Thumbnails (owner-only)."""
    return await services.get_rezept_bild(rid)


@router.post("/rezepte/{rid}/importieren", dependencies=[Depends(auth)])
async def rezept_importieren(rid: int):
    """Öffentliches Rezept als eigene Kopie übernehmen (ohne Bild)."""
    return await services.importiere_rezept(rid)


class LinkImportBody(BaseModel):
    url: str


@router.post("/rezepte/aus-link", dependencies=[Depends(ki_auth)])
async def rezept_aus_link(body: LinkImportBody):
    """Rezept aus einem Link (Instagram-Reel/-Post) importieren – KI liest die Caption."""
    return await rezept_link.importiere_aus_link(body.url)


class DateiImportBody(BaseModel):
    dateien: list[dict]  # [{data: base64, media_type, filename}]


@router.post("/rezepte/aus-dateien", dependencies=[Depends(ki_vision_auth)])
async def rezept_aus_dateien(body: DateiImportBody):
    """Rezept aus hochgeladenen Screenshots/Fotos und/oder PDFs importieren (KI-Vision)."""
    dateien = body.dateien or []
    gesamt = sum(len(d.get("data") or "") for d in dateien) * 3 // 4
    if gesamt > MAX_UPLOAD_CHAT_GESAMT:
        raise HTTPException(413, "Dateien insgesamt zu groß (max. 80 MB). Bitte weniger/kleiner hochladen.")
    return await rezept_link.importiere_aus_dateien(dateien)


class SucheBody(BaseModel):
    query: str
    nur_eigene: bool = False


# Alt-Pfad /rezepte/ki-suche bleibt als Alias für noch gecachte Frontend-Bundles.
# Kein ki_auth mehr: die Suche ist lexikalisch (ohne KI) und steht auch
# Mitgliedern ohne KI-Freigabe offen.
@router.post("/rezepte/suche", dependencies=[Depends(auth)])
@router.post("/rezepte/ki-suche", dependencies=[Depends(auth)])
async def rezept_suche_route(body: SucheBody):
    """Rezeptsuche: Freitext → passende Rezepte, gerankt (lexikalisch, ohne KI)."""
    return await rezept_suche.suche(body.query, body.nur_eigene)


@router.post("/rezepte", dependencies=[Depends(auth)])
async def rezept_anlegen(r: RezeptIn):
    return await services.add_rezept(
        r.name, r.beschreibung, r.anleitung, r.portionen, r.dauer_minuten, r.quelle,
        [z.model_dump() for z in r.zutaten], [g.model_dump() for g in r.geraete],
        [k.model_dump() for k in r.zubereitung], r.gang, r.kueche,
    )


@router.put("/rezepte/{rid}", dependencies=[Depends(auth)])
async def rezept_aktualisieren(rid: int, r: RezeptIn):
    res = await services.update_rezept(
        rid, r.name, r.beschreibung, r.anleitung, r.portionen, r.dauer_minuten, r.quelle,
        [z.model_dump() for z in r.zutaten], [g.model_dump() for g in r.geraete],
        [k.model_dump() for k in r.zubereitung], r.gang, r.kueche,
    )
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/rezepte/{rid}", dependencies=[Depends(auth)])
async def rezept_loeschen(rid: int):
    return await services.delete_rezept(rid)


@router.get("/rezepte/{rid}/kochen/vorschau", dependencies=[Depends(auth)])
async def kochen_vorschau(rid: int):
    res = await services.kochen_vorschau(rid)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.post("/rezepte/{rid}/kochen", dependencies=[Depends(auth)])
async def kochen_bestaetigen(rid: int, k: KochenIn):
    res = await services.kochen_bestaetigen(rid, k.faktor)
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


# ---------- Startseite ----------

@router.get("/start", dependencies=[Depends(auth)])
async def start():
    """Startseiten-Daten: Angebote passend zu Vorlieben + sofort kochbare Rezepte."""
    return await services.start_uebersicht()


# ---------- Wochenplaner ----------

class PlanEintragIn(BaseModel):
    datum: str                   # YYYY-MM-DD
    mahlzeit: str = "Abendessen"
    rezept_id: int | None = None
    notiz: str | None = None
    person_ids: list[int] = []
    portionen: float | None = None
    gaeste: int = 0


@router.get("/plan", dependencies=[Depends(auth)])
async def wochenplan(datum: str):
    from datetime import date as dt_date
    d = dt_date.fromisoformat(datum)
    return await services.list_wochenplan(d)


@router.post("/plan", dependencies=[Depends(auth)])
async def plan_eintrag_anlegen(e: PlanEintragIn):
    from datetime import date as dt_date
    return await services.add_plan_eintrag(
        dt_date.fromisoformat(e.datum), e.mahlzeit, e.rezept_id,
        e.notiz, e.person_ids, e.portionen, e.gaeste,
    )


@router.put("/plan/{eid}", dependencies=[Depends(auth)])
async def plan_eintrag_aktualisieren(eid: int, e: PlanEintragIn):
    from datetime import date as dt_date
    res = await services.update_plan_eintrag(
        eid, dt_date.fromisoformat(e.datum), e.mahlzeit, e.rezept_id,
        e.notiz, e.person_ids, e.portionen, e.gaeste,
    )
    if res is None:
        raise HTTPException(404, "nicht gefunden")
    return res


@router.delete("/plan/{eid}", dependencies=[Depends(auth)])
async def plan_eintrag_loeschen(eid: int):
    return await services.delete_plan_eintrag(eid)


@router.put("/plan/{eid}/gekocht", dependencies=[Depends(auth)])
async def plan_eintrag_gekocht(eid: int, body: dict):
    return await services.plan_gekocht_setzen(eid, bool(body.get("gekocht", True)))


@router.get("/plan/einkaufstage", dependencies=[Depends(auth)])
async def einkaufstage(datum: str):
    from datetime import date as dt_date
    return await services.list_einkaufstage(dt_date.fromisoformat(datum))


@router.post("/plan/einkaufstage", dependencies=[Depends(auth)])
async def einkaufstag_toggle(body: dict):
    from datetime import date as dt_date
    return await services.toggle_einkaufstag(dt_date.fromisoformat(body["datum"]))


@router.post("/plan/einkaufstage/markt", dependencies=[Depends(auth)])
async def einkaufstag_markt(body: dict):
    """Markt eines Einkaufstags setzen. body: {datum, haendler}; haendler leer = frei."""
    from datetime import date as dt_date
    return await services.set_einkaufstag_markt(
        dt_date.fromisoformat(body["datum"]), body.get("haendler"))


@router.post("/plan/einkaufstage/haendler", dependencies=[Depends(auth)])
async def einkaufstag_haendler(body: dict):
    """Mehrere Märkte eines Einkaufstags setzen. body: {datum, haendler: [...]}."""
    from datetime import date as dt_date
    return await services.set_einkaufstag_haendler(
        dt_date.fromisoformat(body["datum"]), body.get("haendler") or [])


@router.get("/plan/einkaufsliste", dependencies=[Depends(auth)])
async def einkaufsliste(datum: str):
    from datetime import date as dt_date
    return await services.get_einkaufsliste(dt_date.fromisoformat(datum))


@router.get("/plan/einkaufsliste/extra", dependencies=[Depends(auth)])
async def einkaufsliste_extra():
    return await services.list_einkauf_extra()


@router.post("/plan/einkaufsliste/extra", dependencies=[Depends(auth)])
async def einkaufsliste_extra_hinzufuegen(body: dict):
    # body: {"artikel": [{name, menge?, einheit?}, ...]}
    return await services.add_einkauf_extra(body.get("artikel", []))


@router.delete("/plan/einkaufsliste/extra/{extra_id}", dependencies=[Depends(auth)])
async def einkaufsliste_extra_loeschen(extra_id: int):
    return await services.delete_einkauf_extra(extra_id)


# ---------- Supermarkt-Angebote ----------

@router.get("/angebote", dependencies=[Depends(auth)])
async def angebote(datum: str | None = None):
    """Aktuelle Supermarkt-Angebote (gueltig am Datum, default heute)."""
    from datetime import date as dt_date
    d = dt_date.fromisoformat(datum) if datum else None
    return await services.get_angebote(d)


@router.get("/angebote/uebersicht", dependencies=[Depends(auth)])
async def angebote_uebersicht():
    """Aktuelle UND kommende Angebote (noch nicht abgelaufen) fuer die Uebersicht."""
    return await services.get_angebote_uebersicht()


@router.get("/angebote/maerkte", dependencies=[Depends(auth)])
async def angebote_maerkte(datum: str):
    """Maerkte mit am Datum gueltigen Angeboten (Auswahl 'wo einkaufen?')."""
    from datetime import date as dt_date
    return await services.maerkte_fuer_datum(dt_date.fromisoformat(datum))


@router.delete("/angebote/blatt")
async def angebote_blatt_loeschen(gueltig_von: str, gueltig_bis: str,
                                  haendler: str | None = None, ctx=Depends(auth)):
    """Löscht ein komplettes Angebotsblatt (Markt + Zeitraum). Super-Admin darf
    auch globale Admin-Angebote, normale User nur ihre EIGENEN (RLS)."""
    admin = await userauth.ist_super_admin(ctx["user_id"])
    return await services.delete_angebote_blatt(haendler, gueltig_von, gueltig_bis, admin=admin)


@router.delete("/angebote/{angebot_id}")
async def angebot_loeschen(angebot_id: int, ctx=Depends(auth)):
    """Löscht ein Angebot. Super-Admin darf alles (auch globale Admin-Angebote),
    normale User nur ihre EIGENEN (RLS)."""
    admin = await userauth.ist_super_admin(ctx["user_id"])
    return await services.delete_angebot(angebot_id, admin=admin)


@router.post("/angebote/import")
async def angebote_import_bulk(body: list[dict], ctx=Depends(auth)):
    """Bulk-Import von Angeboten (JSON; ergänzt). Nur freigeschaltete User/Super-Admin."""
    if not await userauth.darf_angebote_upload(ctx["user_id"]):
        raise HTTPException(403, "Angebots-Upload für dieses Konto nicht freigeschaltet")
    return await services.import_angebote(body)


@router.post("/angebote/import-datei")
async def angebote_import_datei(
    datei: UploadFile = File(...),
    haendler: str = Form(""),
    gueltig_von: str = Form(""),
    gueltig_bis: str = Form(""),
    bilder: bool = Form(True),
    ctx=Depends(auth),
):
    """Prospekt (PDF/Bild) hochladen -> Hintergrund-Verarbeitung. Markt/Zeitraum sind
    optional; die KI erkennt sie sonst selbst. bilder=Produktausschnitte aus dem
    Prospekt mit speichern (etwas teurer, da Vision pro Seite). Gibt job_id zurueck."""
    if not await userauth.darf_angebote_upload(ctx["user_id"]):
        raise HTTPException(403, "Angebots-Upload für dieses Konto nicht freigeschaltet")
    if not (datei.filename or "").lower().endswith(".json"):
        # Prospekt (PDF/Bild) braucht ein Prospekt-/Vision-Modell -> sonst 503. JSON geht auch
        # ohne KI (die KI-Nachbearbeitung wird dann übersprungen, s. angebote_import._run).
        ki.modell_fuer_zweck("angebote-import")
    # Der aufwendigste KI-Zweck (1 Modellaufruf je Seite, bis 24 Seiten) bekommt eine
    # Obergrenze je Nutzer: 10 Prospekte/Tag decken jeden realen Haushalt.
    ratelimit.pruefe(f"angebote-import:user:{ctx['user_id']}", limit=10, fenster_s=86400)
    b = await datei.read()
    _ist_pdf = (datei.filename or "").lower().endswith(".pdf") or datei.content_type == "application/pdf"
    _pruefe_upload_groesse(len(b), MAX_UPLOAD_PDF if _ist_pdf else MAX_UPLOAD)
    job_id = await angebote_import.starte_import(
        b, datei.filename or "datei", haendler or None, gueltig_von or None, gueltig_bis or None,
        mit_bildern=bool(bilder))
    return {"job_id": job_id}


@router.post("/angebote/import-fortsetzen/{job_id}", dependencies=[Depends(auth)])
async def angebote_import_fortsetzen(job_id: str, body: dict):
    """Nach Rueckfrage: fehlende Markt-/Zeitraum-Angaben nachreichen und importieren."""
    res = await angebote_import.fortsetzen(
        job_id, body.get("haendler"), body.get("gueltig_von"), body.get("gueltig_bis"))
    if res is None:
        raise HTTPException(404, "unbekannter oder bereits abgeschlossener Job")
    return angebote_import.status(job_id)


@router.get("/angebote/import-status/{job_id}", dependencies=[Depends(auth)])
async def angebote_import_status(job_id: str):
    s = angebote_import.status(job_id)
    if s is None:
        raise HTTPException(404, "unbekannter Job")
    return s


@router.post("/angebote/master", dependencies=[Depends(auth)])
async def angebote_master(body: list[dict]):
    """Setzt nachtraeglich master_zutat_id bestehender Angebote.
    body: [{angebot_id, master_zutat_id}]; master_zutat_id=null hebt auf."""
    return await services.set_angebote_master(body)


def _pdf_to_image_data_urls(b64_pdf: str, max_seiten: int = 16) -> list[str]:
    """Rendert die ersten Seiten eines base64-PDF zu PNG-Data-URLs fuer die Vision-Eingabe
    (max. ~1600 px laengste Kante). Gibt [] zurueck, wenn das PDF nicht lesbar ist."""
    try:
        return pdf.pdf_zu_data_urls(base64.b64decode(b64_pdf), max_seiten)
    except Exception:
        return []


class ChatBody(BaseModel):
    history: list[dict] | None = None
    message: str | None = None
    images: list[dict] | None = None  # [{data: base64, media_type: 'image/jpeg'}]


def _chat_verlauf(body: ChatBody) -> list[dict]:
    """Baut den Nachrichtenverlauf inkl. neuer Nachricht + Bildanhaengen (multimodal)."""
    verlauf = [dict(m) for m in (body.history or [])]
    if body.images:
        # Mehrere Anhänge erlaubt (Fotos/Screenshots/PDF, auch mehrseitig). Pro Datei
        # PDF 50 MB / Bild 20 MB (Base64 ~4/3 der Binärgröße); Gesamt gedeckelt, damit
        # eine einzelne Anfrage nicht explodiert.
        def _bin(img):
            return len(img.get("data") or "") * 3 // 4

        def _ist_pdf(img):
            return (img.get("media_type") == "application/pdf"
                    or (img.get("filename") or "").lower().endswith(".pdf"))

        for img in body.images:
            if _bin(img) > (MAX_UPLOAD_PDF if _ist_pdf(img) else MAX_UPLOAD):
                raise HTTPException(413, "Eine Datei ist zu groß (PDF max. 50 MB, Bild max. 20 MB). "
                                         "Bitte kleiner oder komprimiert hochladen.")
        if sum(_bin(img) for img in body.images) > MAX_UPLOAD_CHAT_GESAMT:
            raise HTTPException(413, "Anhänge insgesamt zu groß (max. 80 MB pro Nachricht). "
                                     "Bitte in mehreren Nachrichten oder kleiner hochladen.")
        parts: list[dict] = []
        if body.message:
            parts.append({"type": "text", "text": body.message})
        for img in body.images:
            data = img.get("data")
            if not data:
                continue
            mt = img.get("media_type") or "image/jpeg"
            name = (img.get("filename") or "").lower()
            if mt == "application/pdf" or name.endswith(".pdf"):
                urls = _pdf_to_image_data_urls(data)
                if urls:
                    parts += [{"type": "image_url", "image_url": {"url": u}} for u in urls]
                else:
                    parts.append({"type": "text", "text": "(PDF konnte nicht gelesen werden)"})
            else:
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mt};base64,{data}"}})
        if not body.message:
            parts.insert(0, {"type": "text", "text": "(Datei angehängt)"})
        verlauf.append({"role": "user", "content": parts})
    elif body.message is not None:
        verlauf.append({"role": "user", "content": body.message})
    return verlauf


@router.post("/chat", dependencies=[Depends(ki_auth)])
async def chat_endpoint(body: ChatBody):
    """In-App-Chat (synchron). Siehe /chat/start für den Hintergrund-Lauf."""
    return await chat.run(_chat_verlauf(body))


@router.post("/chat/transkribieren", dependencies=[Depends(ki_auth)])
async def chat_transkribieren(datei: UploadFile = File(...)):
    """Sprachaufnahme -> Text. Nur aktiv, wenn eine Transkription konfiguriert ist."""
    _ki_noetig("spracheingabe")
    raw = await datei.read()
    _pruefe_upload_groesse(len(raw))
    if not raw:
        raise HTTPException(400, "leere Audiodatei")
    try:
        return {"text": await ki.transkribiere(raw, datei.content_type or "audio/webm")}
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.post("/chat/start", dependencies=[Depends(ki_auth)])
async def chat_start(body: ChatBody):
    """Startet die Chat-Antwort im Hintergrund und liefert sofort eine job_id.
    Die Anfrage laeuft weiter, auch wenn der Nutzer das Fenster schliesst."""
    return {"job_id": chat.starte(_chat_verlauf(body))}


@router.get("/chat/status/{job_id}", dependencies=[Depends(auth)])
async def chat_status(job_id: str):
    s = chat.status(job_id)
    if not s or (s.get("account_id") is not None and s["account_id"] != userauth.current_account.get()):
        raise HTTPException(404, "Job nicht gefunden")
    return {"status": s["status"], "antwort": s.get("antwort"),
            "tools_genutzt": s.get("tools_genutzt", []), "error": s.get("error")}


@router.get("/kalender.ics")
async def kalender_ics(token: str = ""):
    """Speiseplan als iCalendar-Feed zum Abonnieren in einer Kalender-App.
    Bewusst OHNE Bearer-Auth: Kalender rufen die URL ohne Login ab. Schutz ueber den
    KALENDER_TOKEN im Query (?token=...); steht die App hinter einem Zugangsschutz,
    muss dieser Pfad dort freigegeben sein."""
    if not config.KALENDER_TOKEN or token != config.KALENDER_TOKEN:
        raise HTTPException(status_code=403, detail="ungueltiger oder fehlender Token")
    # F10: Feed ist bewusst der Speiseplan des Eigentümer-Kontos (globaler Token). Konto
    # explizit setzen, da acquire() ohne Kontext jetzt fail-closed ist (kein impliziter
    # Zugriff auf Konto 1). Perspektivisch: Token pro Konto → Feed je Mandant (Follow-up).
    userauth.current_account.set(1)
    ics = await services.build_speiseplan_ics()
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=speiseplan.ics"},
    )
