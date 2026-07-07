# ABOUTME: Unit tests for build_bootstrap_managed_mcp_servers() - the shared helper
# ABOUTME: that decides which managedMcpServers entries are safe to return via bootstrap


class TestBuildBootstrapManagedMcpServers:
    def test_empty_config_returns_empty_list(self, idx):
        assert idx.build_bootstrap_managed_mcp_servers({}) == []

    def test_http_transport_passed_through(self, idx):
        config = {
            'managedMcpServers': [
                {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
            ]
        }
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert result == [
            {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
        ]

    def test_sse_transport_passed_through(self, idx):
        config = {
            'managedMcpServers': [
                {'name': 'internal-tools', 'transport': 'sse', 'url': 'https://mcp.example.corp/sse'},
            ]
        }
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert len(result) == 1
        assert result[0]['transport'] == 'sse'

    def test_stdio_transport_in_managedMcpServers_is_dropped(self, idx):
        config = {
            'managedMcpServers': [
                {'name': 'local-tool', 'transport': 'stdio', 'command': 'npx'},
            ]
        }
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert result == []

    def test_missing_transport_field_is_dropped(self, idx):
        """A managedMcpServers entry with no transport field is not
        conclusively network-based, so it must not be forwarded."""
        config = {'managedMcpServers': [{'name': 'ambiguous', 'url': 'https://example.com'}]}
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert result == []

    def test_mcpServerTemplates_converted_to_stdio_entries(self, idx):
        """mcpServerTemplates (local command+args) are converted to stdio
        managedMcpServers entries. Desktop will drop these client-side when
        served via bootstrap, but MDM-based delivery still needs this shape."""
        config = {
            'mcpServerTemplates': [
                {'name': 'aws-documentation', 'command': 'uvx', 'args': ['awslabs.aws-documentation-mcp-server@latest']},
            ]
        }
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert result == [{
            'name': 'aws-documentation',
            'transport': 'stdio',
            'command': 'uvx',
            'args': ['awslabs.aws-documentation-mcp-server@latest'],
        }]

    def test_combines_http_managed_and_stdio_templates(self, idx):
        config = {
            'managedMcpServers': [
                {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
            ],
            'mcpServerTemplates': [
                {'name': 'local-tool', 'command': 'npx', 'args': ['-y', 'some-server']},
            ],
        }
        result = idx.build_bootstrap_managed_mcp_servers(config)
        names = {s['name'] for s in result}
        assert names == {'aws-knowledge', 'local-tool'}

    def test_non_dict_entries_in_managedMcpServers_are_ignored(self, idx):
        config = {'managedMcpServers': ['not-a-dict', 123, None]}
        result = idx.build_bootstrap_managed_mcp_servers(config)
        assert result == []
