---
title: Redash MCP
---

# Redash MCP

Connect Redash queries, dashboards, and results through the community-maintained
[suthio/redash-mcp server](https://github.com/suthio/redash-mcp). The fork's
development and production Compose files include its pinned `v0.1.2` image.
The service is optional and enabled with the `redash` Compose profile.

## Start the service on the Aurora VM

After merging the integration, run on `grexa-watch`:

```bash
cd /root/aurora
git pull --ff-only origin main
```

Add these values to `/root/aurora/.env`. If `COMPOSE_PROFILES` already exists,
append `redash` to its comma-separated list rather than adding another entry.

```dotenv
REDASH_URL=https://data.grexa.ai
COMPOSE_PROFILES=redash
```

Start only the MCP service; Aurora does not need rebuilding for this addition:

```bash
docker compose -p aurora -f docker-compose.prod-local.yml up -d --no-deps redash-mcp
docker compose -p aurora -f docker-compose.prod-local.yml logs --tail=50 redash-mcp
```

The container listens at `http://redash-mcp:3000/mcp` on Aurora's Docker network.
It publishes no host port and needs no nginx changes. Requests come from Aurora's
backend, so browser Origin headers are rejected and only the internal service
hostname and loopback hosts are allowed. The MCP container must be able to reach
the configured Redash URL; if a gateway protects Redash, its separate authentication
must also be configured before queries can work.

## Add the credentials in Aurora

1. In Redash, use a dedicated non-admin account with access to the required data
   sources. Open its profile and copy its **User API Key**. A Query API Key only
   grants access to one saved query and cannot provide general discovery.
2. Open [Watch's Custom MCP setup](https://watch.grexa.ai/mcp/auth).
3. Choose **Set authentication manually**, then use:

   | Field | Value |
   | --- | --- |
   | Name | `redash` |
   | Server URL | `http://redash-mcp:3000/mcp` |
   | Authentication | Bearer token |
   | Token | The dedicated Redash user's API key |

4. Connect and inspect the discovered tools. Manual authentication is important:
   some MCP discovery requests can succeed without querying Redash, even though
   the tools require a key.

Aurora sends the stored key on each MCP request. The MCP service forwards it to
Redash using Redash's API authentication scheme. Do not put `REDASH_API_KEY` into
Compose or commit keys to the repository. Aurora shares this connection and its
Redash identity across the organization; it does not automatically use each
Aurora user's own Redash account.

## Investigation access

This server is not inherently read-only. Its tools also support creating,
updating, and archiving Redash objects. Keep those tools on **Confirm** in Aurora.
For background investigations, allow only the inspected read tools needed, such
as query/dashboard discovery and cached results. Use database credentials with
read-only grants behind Redash for investigation data sources. A non-admin
Redash account alone does not guarantee that arbitrary SQL cannot write data.

The Compose service sets a 30-second Redash timeout and a 100-result response
limit. A response limit does not limit the cost or duration of the underlying
database query. Start with a discovery-only prompt:

> Using Redash, list up to five saved queries and their IDs. Do not execute,
> refresh, create, update, or delete anything.

Read-only listing and query retrieval use the existing [custom MCP](./custom-mcp-servers.md)
flow. Future `make prod-local` deployments include Redash while its profile remains
enabled in `.env`.

References: [Redash API keys](https://redash.io/help/user-guide/integrations-and-api/api/),
[MCP server HTTP transport and authentication](https://github.com/suthio/redash-mcp#streamable-http-transport).
