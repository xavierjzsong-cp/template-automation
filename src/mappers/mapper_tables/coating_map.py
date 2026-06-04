from __future__ import annotations


COATING_MAP = {
    "base_coating": {
        "alloy_steel": "CSP-158, CSP-99",
        "chrome_steel": "CSP-99",
        "nickel_alloy": "CSP-99",
    },
    "internal_seal_surface": {
        "alloy_steel": "CSP-134 AFTER COATING",
        "chrome_steel": "CSP-70",
        "nickel_alloy": "CSP-70",
    },
    "oring_groove_surfaces": {
        "alloy_steel": "CSP-134 AFTER COATING",
        "chrome_steel": "CSP-99",
        "nickel_alloy": "CSP-99",
    },
    "polished_seal_bore_surface": {
        "alloy_steel": "CSP-134 AFTER COATING",
        "chrome_steel": "CSP-99",
        "nickel_alloy": "CSP-99",
    },
    "premium_threads": {
        "alloy_steel": "CSP-83",
        "chrome_steel": "CSP-83",
        "nickel_alloy": "CSP-83",
    },
    "api_threads": {
        "alloy_steel": "CSP-118",
        "chrome_steel": "CSP-118",
        "nickel_alloy": "CSP-118",
    },
    "stub_acme_box_thread": {
        "alloy_steel": "CSP-28 (Mask all seal surface)",
        "chrome_steel": "CSP-70 (Mask the O-ring groove and not seal surface, if applicable)",
        "nickel_alloy": "CSP-70 (Mask the O-ring groove and not seal surface, if applicable)",
    },
    "stub_acme_pin_thread": {
        "alloy_steel": "CSP-28 (Mask all seal surface)",
        "chrome_steel": "CSP-28 (Mask all seal surface)",
        "nickel_alloy": "CSP-28 (Mask all seal surface)",
    },
    "un_box_pin_threads": {
        "alloy_steel": "CSP-16 / CSP-158",
        "chrome_steel": "CSP-70",
        "nickel_alloy": "CSP-70",
    },
    "tools_enter_seal_bore": {
        "alloy_steel": "CSP-70",
        "chrome_steel": "CSP-70",
        "nickel_alloy": "CSP-70",
    },
}