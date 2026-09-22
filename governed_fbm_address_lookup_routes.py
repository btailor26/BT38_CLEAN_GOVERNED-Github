"""Governed Google address lookup for standalone manual shipping.

Google Places is called only from explicit manual-shipping address actions. The
API key stays server-side. No polling, marketplace read, or stock mutation.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, request
from flask_login import login_required


governed_fbm_address_lookup_bp = Blueprint("governed_fbm_address_lookup", __name__)


def _api_key() -> str:
    return str(os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()


def _google_json(method: str, url: str, api_key: str, *, body=None, field_mask: str | None = None):
    headers={"Accept":"application/json","Content-Type":"application/json","X-Goog-Api-Key":api_key}
    if field_mask:
        headers["X-Goog-FieldMask"]=field_mask
    data=json.dumps(body).encode("utf-8") if body is not None else None
    req=Request(url,headers=headers,data=data,method=method)
    with urlopen(req,timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _clean(value) -> str:
    return str(value or "").strip()


def _google_error(exc: HTTPError):
    if exc.code in (401,403):
        return jsonify({"success":False,"message":"Google address lookup authentication failed. Check GOOGLE_MAPS_API_KEY and Places API (New) access."}),502
    if exc.code==429:
        return jsonify({"success":False,"message":"Google address lookup rate limit reached. Try again shortly."}),429
    return jsonify({"success":False,"message":f"Google address lookup failed (HTTP {exc.code})."}),502


@governed_fbm_address_lookup_bp.get("/fbm/manual/address-lookup")
@login_required
def manual_address_lookup():
    postcode=" ".join(str(request.args.get("postcode") or "").upper().split())
    compact="".join(postcode.split())
    if not compact or len(compact)<5 or len(compact)>7:
        return jsonify({"success":False,"message":"Enter a valid UK postcode."}),400
    api_key=_api_key()
    if not api_key:
        return jsonify({"success":False,"message":"Google address lookup is not configured. Set GOOGLE_MAPS_API_KEY on BT38."}),503
    try:
        payload=_google_json(
            "POST","https://places.googleapis.com/v1/places:autocomplete",api_key,
            body={"input":postcode,"includedRegionCodes":["gb"],"regionCode":"uk","languageCode":"en"},
            field_mask="suggestions.placePrediction.placeId,suggestions.placePrediction.text.text",
        )
    except HTTPError as exc:
        return _google_error(exc)
    except (URLError,TimeoutError,ValueError):
        return jsonify({"success":False,"message":"Google address lookup is unavailable."}),502

    addresses=[]
    for item in (payload or {}).get("suggestions") or []:
        prediction=item.get("placePrediction") if isinstance(item,dict) else None
        if not isinstance(prediction,dict):
            continue
        place_id=_clean(prediction.get("placeId"))
        label=_clean((prediction.get("text") or {}).get("text"))
        if place_id and label:
            addresses.append({"id":place_id,"label":label})
    return jsonify({
        "success":True,"postcode":postcode,"addresses":addresses,
        "message":f"{len(addresses)} address{'es' if len(addresses)!=1 else ''} found.",
        "property_lookup":True,"provider":"google_places",
    })


@governed_fbm_address_lookup_bp.get("/fbm/manual/address-lookup/<path:place_id>")
@login_required
def manual_address_details(place_id: str):
    api_key=_api_key()
    if not api_key:
        return jsonify({"success":False,"message":"Google address lookup is not configured. Set GOOGLE_MAPS_API_KEY on BT38."}),503
    try:
        payload=_google_json(
            "GET",f"https://places.googleapis.com/v1/places/{quote(place_id,safe='')}",api_key,
            field_mask="formattedAddress,addressComponents,postalAddress",
        )
    except HTTPError as exc:
        return _google_error(exc)
    except (URLError,TimeoutError,ValueError):
        return jsonify({"success":False,"message":"Google address lookup is unavailable."}),502

    components={}
    for part in (payload or {}).get("addressComponents") or []:
        if not isinstance(part,dict):
            continue
        for kind in part.get("types") or []:
            components[kind]=_clean(part.get("longText") or part.get("shortText"))
    number=components.get("street_number","")
    route=components.get("route","")
    premise=components.get("premise","") or components.get("subpremise","")
    line1=" ".join(v for v in (premise,number,route) if v).strip()
    city=components.get("postal_town") or components.get("locality") or components.get("administrative_area_level_2","")
    region=components.get("administrative_area_level_2") or components.get("administrative_area_level_1","")
    postcode=components.get("postal_code","")
    if not line1:
        formatted=_clean((payload or {}).get("formattedAddress"))
        line1=formatted.split(",")[0].strip() if formatted else ""
    return jsonify({"success":True,"provider":"google_places","address":{
        "ship_to_address":line1,"ship_to_address2":"","ship_to_city":city,
        "ship_to_region":region,"ship_to_postcode":postcode,"ship_to_country":"GB",
    }})
