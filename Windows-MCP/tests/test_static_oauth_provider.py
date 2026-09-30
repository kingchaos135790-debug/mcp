from windows_mcp.auth.static_oauth_provider import StaticClientOAuthProvider


def test_dynamic_client_registration_enables_registration_route():
    provider = StaticClientOAuthProvider(
        base_url="https://mcp.example.com",
        pre_registered_client_id="windows",
        pre_registered_client_secret="secret",
        pre_registered_redirect_uris=["https://client.example/callback"],
        allow_dynamic_client_registration=True,
        valid_scopes=["mcp:access"],
    )

    assert provider.client_registration_options is not None
    assert provider.client_registration_options.enabled is True
    assert "/register" in {route.path for route in provider.get_routes("/mcp")}
