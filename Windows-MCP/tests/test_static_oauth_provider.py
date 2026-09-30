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


def test_authorization_metadata_matches_configured_auth_methods():
    provider = StaticClientOAuthProvider(
        base_url="https://mcp.example.com",
        pre_registered_client_id="claude",
        pre_registered_redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        token_endpoint_auth_method="none",
        valid_scopes=["mcp:access"],
    )
    provider.clients["windows"] = provider._build_static_client().model_copy(
        update={
            "client_id": "windows",
            "token_endpoint_auth_method": "client_secret_post",
            "client_secret": "secret",
        }
    )

    metadata = provider._authorization_server_metadata()

    assert metadata["issuer"] == "https://mcp.example.com/"
    assert metadata["token_endpoint_auth_methods_supported"] == ["none", "client_secret_post"]
    assert "registration_endpoint" not in metadata
