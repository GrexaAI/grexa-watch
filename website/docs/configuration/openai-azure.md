---
title: OpenAI and Azure OpenAI
---

# OpenAI and Azure OpenAI

This fork defaults to three OpenAI models. The chat picker exposes these choices;
historical model mappings and prices remain available for existing sessions.

| Model | Recommended use |
|---|---|
| `openai/gpt-6.2-sol` | Chat, code tracing, and root-cause investigations |
| `openai/gpt-6.1-terra` | Images, visual analysis, and an alternative investigator |
| `openai/gpt-6-luna` | Summaries, enrichment, memory selection, and small checks |

These are defaults, not a claim that every API project or Azure region can serve
every model. Confirm access before enabling automatic investigations.

## Model roles

The following defaults apply when an environment override is empty. They are also
set explicitly in `.env.example` and the Helm chart.

| Variable | Default |
|---|---|
| `MAIN_MODEL` | `openai/gpt-6.2-sol` |
| `RCA_MODEL` | `openai/gpt-6.2-sol` |
| `RCA_ORCHESTRATOR_MODEL` | `openai/gpt-6.2-sol` |
| `RCA_SUBAGENT_MODEL` | `openai/gpt-6.1-terra` |
| `VISION_MODEL` | `openai/gpt-6.1-terra` |
| `SUMMARIZATION_MODEL` | `openai/gpt-6-luna` |
| `ENRICHMENT_MODEL` | `openai/gpt-6-luna` |
| `MEMORY_SELECTOR_MODEL` | `openai/gpt-6-luna` |
| `RECURRENCE_AGENT_MODEL` | `openai/gpt-6-luna` |
| `JIRA_RCA_JUDGE_MODEL` | `openai/gpt-6-luna` |
| `GUARDRAILS_LLM_MODEL` | `openai/gpt-6-luna` |

Orchestration stays disabled unless `ORCHESTRATOR_ENABLED=true`. Changing model
roles does not enable it. `RCA_MODEL` now has an explicit default: the legacy
`RCA_OPTIMIZE_COSTS` switch no longer selects a different investigator. Override
`RCA_MODEL` directly instead.

Embeddings stay optional to avoid changing existing correlation behavior or vector
dimensions on upgrade. The recommended OpenAI setting is
`EMBEDDING_MODEL=openai/text-embedding-3-small`. Deploy that embedding model
separately in Azure if enabling it. Language models are not embedding models.

## Direct OpenAI

In `.env`:

```dotenv
LLM_PROVIDER_MODE=direct
OPENAI_API_KEY=YOUR_OPENAI_PROJECT_KEY
OPENAI_BASE_URL=
OPENAI_DEPLOYMENTS=
OPENAI_REASONING_EFFORT=low
```

Leave `OPENAI_BASE_URL` empty to use the SDK's public OpenAI endpoint. The legacy
`OPENAI_API_BASE` variable is accepted, but `OPENAI_BASE_URL` takes precedence.
Neither variable belongs in frontend or `NEXT_PUBLIC_*` configuration.

## Azure OpenAI with API-key authentication

1. In Azure AI Foundry, create deployments for the model roles you intend to use.
   The deployment must support Responses API, streaming, function calling, and
   structured output. Availability depends on your subscription, region, and quota.
2. Copy the resource's API key and v1 endpoint. Do not use a public OpenAI project
   key with an Azure endpoint.
3. Configure the same OpenAI provider with Azure's endpoint and deployment aliases:

```dotenv
LLM_PROVIDER_MODE=direct
OPENAI_API_KEY=YOUR_AZURE_RESOURCE_KEY
OPENAI_BASE_URL=https://YOUR_RESOURCE.openai.azure.com/openai/v1/
OPENAI_DEPLOYMENTS='{"gpt-6.2-sol":"investigate","gpt-6.1-terra":"visual","gpt-6-luna":"utility"}'
OPENAI_REASONING_EFFORT=low
```

Keep the canonical `openai/gpt-...` IDs in model-role variables and in the chat
picker. The provider replaces the native ID with the deployment name only when
making the API request. Usage estimates resolve aliases back to canonical IDs.
If deployments have the same names as their models, no mapping is needed.
Unmapped IDs are sent unchanged; the provider never silently substitutes another
model or switches from Azure to the public endpoint.

If enabling embeddings, add the embedding deployment to the same JSON object:

```dotenv
EMBEDDING_MODEL=openai/text-embedding-3-small
OPENAI_DEPLOYMENTS='{"gpt-6.2-sol":"investigate","gpt-6.1-terra":"visual","gpt-6-luna":"utility","text-embedding-3-small":"embeddings"}'
```

This configuration uses API keys. Microsoft Entra token refresh/managed identity
is not configured by these variables.

For Helm, put the endpoint, aliases, reasoning, and role values under `config`.
Keep the resource key under `secrets.llm.OPENAI_API_KEY`, or use the chart's
existing-secret integration. Never put API keys in a ConfigMap.

## Cost controls and estimates

`OPENAI_REASONING_EFFORT` defaults to `low`, replacing the previous forced `high`.
Use `medium` or `high` only when the task needs more reasoning. Sol requires at
least `low`; `none`/`minimal` are raised to `low` for Sol. Guardrails remain enabled
and use the smallest supported reasoning setting for their configured model.

Prices shown in the picker and usage tracker are estimates based on OpenAI
Standard rates, including cache-read and long-context tiers for the three new
models. They are not Azure billing quotes. Azure region, deployment type, caching,
and your contract can change the actual bill. Compare with the provider invoice.
These settings do not enforce a per-investigation dollar budget.

## Build and apply

Changes to source require custom images. From the fork checkout:

```bash
docker compose -f docker-compose.prod-local.yml config --quiet
docker compose -f docker-compose.prod-local.yml build \
  frontend aurora-server chatbot celery_worker celery_beat aurora-mcp slack_socket_mode
docker compose -f docker-compose.prod-local.yml up -d --no-build --no-deps \
  --force-recreate frontend aurora-server chatbot celery_worker celery_beat aurora-mcp slack_socket_mode
```

Do not run upstream `make prod-prebuilt` afterward: it pulls upstream images and
replaces these builds. Recreate application containers after changing `.env`;
restarting alone does not apply new container environment values.

After deployment, hard-refresh the browser and start a new chat. Check that only
the three OpenAI models appear. Test a short message, a bounded read-only tool
call, and one background investigation; check the provider dashboard for the
deployment used and actual usage. Automated tests exercise Azure request routing
with a mock HTTP transport and do not prove access to your live Azure deployments.

References: [OpenAI model selection](https://developers.openai.com/api/docs/guides/model-selection),
[Azure OpenAI v1 API](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle).
