class Urls:
    # Since September 2026 catalogue searches are served from the dedicated
    # api.vinted.<tld> host. The legacy www-host endpoint returns 404.
    VINTED_API_URL = "/svc-catalogue"
    VINTED_PRODUCTS_ENDPOINT = "items"
    VINTED_AUTH_HOST_PREFIX = "www."
    VINTED_API_HOST_PREFIX = "api."
