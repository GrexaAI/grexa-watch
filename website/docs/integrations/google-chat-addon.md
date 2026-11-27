---
title: Google Chat Workspace add-ons
---

# Google Chat Workspace add-ons

Use this setup when your Chat app is a Google Workspace add-on, including an
existing app whose add-on checkbox cannot be disabled. This fork accepts its
message, added/removed-from-space, and button-click payloads through the existing
Google Chat connector. Classic Chat apps remain supported with the optional
add-on identity setting empty. Slash/app commands, app home, and dialogs are not
implemented by this connector; leave those features unconfigured.

## Google Cloud configuration

In the app's project, open **Google Chat API > Configuration**:

1. Keep **Build this Chat app as a Google Workspace add-on** enabled.
2. Enable interactive features and joining spaces/group conversations.
3. Select **HTTP endpoint URL**, then **Use a common HTTP endpoint URL for all triggers**.
4. Enter your public events URL, such as `https://watch.grexa.ai/google-chat/events`.
5. Save and copy the managed **Service account email** shown under Connection settings.
   It has the form `service-PROJECT_NUMBER@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`.
   Google provisions it after the configuration is first saved.
6. For a converted app with older card messages, set the separate **Card Interaction URL**
   to that same events URL if Google offers the field.

## Aurora configuration

Retain the OAuth client and messaging service-account key from the
[Google Chat setup](connectors#google-chat). Add:

```dotenv
FRONTEND_URL=https://watch.grexa.ai
NEXT_PUBLIC_BACKEND_URL=https://watch.grexa.ai
GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL=service-YOUR_PROJECT_NUMBER@gcp-sa-gsuiteaddons.iam.gserviceaccount.com
```

Replace the placeholder with Google's exact managed identity. It is not the
service account in `GOOGLE_CHAT_SERVICE_ACCOUNT_KEY`, and it is not an API key.
Aurora verifies Google's token signature, the exact events URL as audience, and
the configured verified sender identity. An add-on deployment does not also
accept the classic shared sender. Without the setting, incoming add-on events
are refused. Do not disable webhook verification to work around errors.

For Helm, put this non-secret identity in `config.GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL`.
Compose passes it to the API and worker. Rebuild and recreate the fork's application
containers with `make prod-local` after changing source or environment values.

The public domain must route `/google-chat/events` and `/google-chat/callback`
to Aurora's API while `/google-chat/setup` stays on the frontend. Keep the
internal `BACKEND_URL` on its Docker/cluster address. Register the public callback
URL in the web OAuth client's authorized redirect URIs.

Ongoing messages still use `chat.bot`. This fork also requests
`chat.app.messages.readonly` for thread history, which needs Workspace
administrator approval through the Marketplace app setup. Changing the webhook
format does not grant that approval or change Aurora user/organization permissions.

### Alert and thread context

When you reply to an alert with `@watch investigate this`, Aurora requests history
for that exact thread. It includes the original message and up to nine recent
replies, removes duplicates, and presents them chronologically. This uses at most
two history requests rather than scanning unrelated space messages. It does not
load every reply in a long thread.

Context includes plain text plus visible titles, labels, paragraphs, and HTTP(S)
links from legacy `cards` and `cardsV2`, including Grafana alert cards. Card HTML
is converted to text, and the original sender name is preserved. Card actions and
hidden parameters are excluded; buttons are never executed while reading context.
Existing message and total context limits still apply. Missing history permission
leaves the investigation without previous-message context.

## Verify

Connect through **Connectors > Google Chat**. Use a registered Aurora admin/editor
account to mention the app with a bounded read-only question. Check that a response
appears in the same thread, a newly generated incident card has working buttons,
and investigation notifications arrive in the configured incidents space.
Kubernetes RBAC and command guardrails continue to apply to investigations and
button actions.

References:
[Google's event/response conversion mapping](https://developers.google.com/workspace/chat/convert),
[HTTP request verification](https://developers.google.com/workspace/chat/verify-requests-from-chat),
[Chat app authentication and approval](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app).
