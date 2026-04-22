# T4 Cloudflare Tunnel Report

## Summary

- target hostname: `mcp.govpress.cloud`
- origin: `http://127.0.0.1:8001`
- transport path: `/mcp`
- tunnel status: `healthy`
- tunnel id: `79cb306b-9af1-42e6-afba-15cdd975a15f`

This stage exposed the local MCP server on server W through Cloudflare Tunnel and registered it as a user-level `systemd` service for automatic recovery after reboot.

## Services

User services installed and enabled:

- `govpress-mcp-server.service`
- `govpress-mcp-cloudflared.service`

Status at completion:

- `govpress-mcp-server.service`: `enabled`, `active`
- `govpress-mcp-cloudflared.service`: `enabled`, `active`

## Tunnel Configuration

- public hostname: `mcp.govpress.cloud`
- tunnel origin: `http://127.0.0.1:8001`
- origin request host header override: `127.0.0.1:8001`
- protocol: `http2`

The host-header override was necessary because the local MCP server rejected the proxied request with `Invalid Host header` until the Cloudflare ingress config explicitly pinned the upstream host header to the local origin.

## Smoke Tests

### Tunnel Health

- Cloudflare API tunnel status: `healthy`
- active tunnel connections: `4`

### External MCP Calls

External smoke tests were run against the public hostname.

- `tools/list`: `8`
- `get_stats.doc_count`: `130012`
- `get_stats.indexed_docs`: `129934`
- `get_stats.qdrant_points_count`: `454125`

## Notes

- Local resolver propagation lagged during setup, so the final smoke test was validated with explicit host resolution while the Cloudflare-side DNS record had already been updated.
- The public hostname now points to the MCP server, not the legacy GovPress web origin.

## Files

- `deploy/systemd/govpress-mcp-server.service`
- `deploy/systemd/govpress-mcp-cloudflared.service`
- `~/.config/systemd/user/govpress-mcp-server.service`
- `~/.config/systemd/user/govpress-mcp-cloudflared.service`

