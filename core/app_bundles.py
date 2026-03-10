"""
Titan V11.3 — App Bundle System (Expanded)
Country-specific banking/fintech + BNPL + crypto + social + delivery bundles.
7 bundles covering US, UK, EU markets.
"""

VIRTUAL_NUMBER_APPS = {
    "numero": {"name": "Numero eSIM", "pkg": "com.numero.numero", "supports": ["US", "GB", "CA", "AU", "DE", "FR"]},
    "textnow": {"name": "TextNow", "pkg": "com.enflick.android.TextNow", "supports": ["US", "CA"]},
    "google_voice": {"name": "Google Voice", "pkg": "com.google.android.apps.googlevoice", "supports": ["US"]},
    "fanytel": {"name": "Fanytel Business", "pkg": "com.fanytel.business", "supports": ["US", "GB", "CA"]},
}

APP_BUNDLES = {
    "us_banking": {
        "name": "US Banking & Fintech", "country": "US",
        "apps": [
            {"pkg": "com.venmo", "name": "Venmo"},
            {"pkg": "com.paypal.android.p2pmobile", "name": "PayPal"},
            {"pkg": "com.chase.sig.android", "name": "Chase"},
            {"pkg": "com.wf.wellsfargomobile", "name": "Wells Fargo"},
            {"pkg": "com.onedebit.chime", "name": "Chime"},
            {"pkg": "com.squareup.cash", "name": "Cash App"},
            {"pkg": "com.zellepay.zelle", "name": "Zelle"},
            {"pkg": "com.transferwise.android", "name": "Wise"},
            {"pkg": "com.bankofamerica.cashpromobile", "name": "Bank of America"},
            {"pkg": "com.sofi.mobile", "name": "SoFi"},
        ],
    },
    "uk_banking": {
        "name": "UK Banking & Fintech", "country": "GB",
        "apps": [
            {"pkg": "com.monzo.android", "name": "Monzo"},
            {"pkg": "com.revolut.revolut", "name": "Revolut"},
            {"pkg": "com.starlingbank.android", "name": "Starling"},
            {"pkg": "com.barclays.android.barclaysmobilebanking", "name": "Barclays"},
            {"pkg": "uk.co.hsbc.hsbcukmobilebanking", "name": "HSBC"},
            {"pkg": "com.transferwise.android", "name": "Wise"},
            {"pkg": "uk.co.natwest.nrb", "name": "NatWest"},
            {"pkg": "com.paypal.android.p2pmobile", "name": "PayPal"},
        ],
    },
    "eu_banking": {
        "name": "EU Banking & Fintech", "country": "EU",
        "apps": [
            {"pkg": "de.number26.android", "name": "N26"},
            {"pkg": "com.revolut.revolut", "name": "Revolut"},
            {"pkg": "com.transferwise.android", "name": "Wise"},
            {"pkg": "com.bunq.android", "name": "bunq"},
            {"pkg": "com.ing.mobile", "name": "ING"},
            {"pkg": "com.paypal.android.p2pmobile", "name": "PayPal"},
        ],
    },
    "us_bnpl": {
        "name": "US Buy Now Pay Later", "country": "US",
        "apps": [
            {"pkg": "com.klarna.android", "name": "Klarna"},
            {"pkg": "com.afterpay.caportal", "name": "Afterpay"},
            {"pkg": "com.affirm.central", "name": "Affirm"},
            {"pkg": "com.quadpay.quadpay", "name": "Zip"},
            {"pkg": "com.sezzle.sezzle", "name": "Sezzle"},
        ],
    },
    "crypto": {
        "name": "Crypto Wallets & Exchanges", "country": "ALL",
        "apps": [
            {"pkg": "com.coinbase.android", "name": "Coinbase"},
            {"pkg": "com.binance.dev", "name": "Binance"},
            {"pkg": "com.kraken.trade", "name": "Kraken"},
            {"pkg": "com.wallet.crypto.trustapp", "name": "Trust Wallet"},
            {"pkg": "com.coinomi.wallet", "name": "Coinomi"},
            {"pkg": "piuk.blockchain.android", "name": "Blockchain.com"},
        ],
    },
    "social": {
        "name": "Social Media", "country": "ALL",
        "apps": [
            {"pkg": "com.instagram.android", "name": "Instagram"},
            {"pkg": "com.zhiliaoapp.musically", "name": "TikTok"},
            {"pkg": "com.twitter.android", "name": "X (Twitter)"},
            {"pkg": "com.facebook.katana", "name": "Facebook"},
            {"pkg": "com.whatsapp", "name": "WhatsApp"},
            {"pkg": "org.telegram.messenger", "name": "Telegram"},
            {"pkg": "com.snapchat.android", "name": "Snapchat"},
        ],
    },
    "delivery": {
        "name": "Delivery & Shopping", "country": "US",
        "apps": [
            {"pkg": "com.dd.doordash", "name": "DoorDash"},
            {"pkg": "com.ubercab.eats", "name": "Uber Eats"},
            {"pkg": "com.instacart.client", "name": "Instacart"},
            {"pkg": "com.amazon.mShop.android.shopping", "name": "Amazon"},
            {"pkg": "com.grubhub.android", "name": "Grubhub"},
        ],
    },
    "wallets": {
        "name": "Payment Wallets", "country": "ALL",
        "apps": [
            {"pkg": "com.google.android.apps.walletnfcrel", "name": "Google Pay / Wallet",
             "has_payment": True, "login_required": True, "data_priority": "high"},
            {"pkg": "com.samsung.android.spay", "name": "Samsung Pay",
             "has_payment": True, "login_required": True, "data_priority": "high"},
            {"pkg": "com.paypal.android.p2pmobile", "name": "PayPal",
             "has_payment": True, "login_required": True, "data_priority": "high"},
            {"pkg": "com.venmo", "name": "Venmo",
             "has_payment": True, "login_required": True, "data_priority": "medium"},
            {"pkg": "com.squareup.cash", "name": "Cash App",
             "has_payment": True, "login_required": True, "data_priority": "medium"},
        ],
    },
    "browsers": {
        "name": "Web Browsers", "country": "ALL",
        "apps": [
            {"pkg": "com.android.chrome", "name": "Google Chrome"},
            {"pkg": "org.mozilla.firefox", "name": "Firefox"},
            {"pkg": "com.sec.android.app.sbrowser", "name": "Samsung Internet"},
            {"pkg": "com.brave.browser", "name": "Brave"},
            {"pkg": "com.duckduckgo.mobile.android", "name": "DuckDuckGo"},
        ],
    },
    "google_essential": {
        "name": "Google Essentials", "country": "ALL",
        "apps": [
            {"pkg": "com.google.android.youtube", "name": "YouTube"},
            {"pkg": "com.google.android.gm", "name": "Gmail"},
            {"pkg": "com.google.android.apps.maps", "name": "Google Maps"},
            {"pkg": "com.google.android.apps.docs", "name": "Google Drive"},
            {"pkg": "com.google.android.apps.photos", "name": "Google Photos"},
            {"pkg": "com.google.android.keep", "name": "Google Keep"},
            {"pkg": "com.google.android.calendar", "name": "Google Calendar"},
        ],
    },
    "shopping": {
        "name": "Shopping & E-Commerce", "country": "US",
        "apps": [
            {"pkg": "com.amazon.mShop.android.shopping", "name": "Amazon"},
            {"pkg": "com.ebay.mobile", "name": "eBay"},
            {"pkg": "com.walmart.android", "name": "Walmart"},
            {"pkg": "com.target.ui", "name": "Target"},
            {"pkg": "com.bestbuy.android", "name": "Best Buy"},
        ],
    },
}

COUNTRY_BUNDLES = {
    "US": ["us_banking", "us_bnpl", "wallets", "social", "delivery", "shopping", "browsers", "google_essential"],
    "GB": ["uk_banking", "wallets", "social", "browsers", "google_essential"],
    "DE": ["eu_banking", "wallets", "social", "browsers", "google_essential"],
    "FR": ["eu_banking", "wallets", "social", "browsers", "google_essential"],
}

GMS_COMPONENTS = [
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.vending",
    "com.google.android.setupwizard",
    "com.google.android.ext.services",
]


def get_bundles_for_country(country: str) -> list:
    keys = COUNTRY_BUNDLES.get(country, ["social"])
    return [APP_BUNDLES[k] for k in keys if k in APP_BUNDLES]


def list_all_bundles() -> list:
    return [{"key": k, "name": v["name"], "country": v["country"], "app_count": len(v["apps"])}
            for k, v in APP_BUNDLES.items()]
