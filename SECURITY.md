# Security policy

## Scope

This software reads market data and writes local files. It never places
orders or calls account endpoints. The only secret it handles is a provider
API token.

## Supported versions

The latest minor release on `main` receives fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting (Security tab, "Report a
vulnerability") rather than a public issue. Include steps to reproduce and
the affected version. Expect an acknowledgement within a week.

## Token handling

- `TRADIER_TOKEN` is read from the environment only. `LiveConfig` rejects
  credential-looking keys, and provider errors are recorded without headers
  or response bodies.
- `scripts/set_tradier_token.sh` stores the token outside the repository with
  owner-only permissions. The Docker and systemd examples pass it through the
  environment.
- If a token is committed or logged by mistake, revoke it with the provider
  first, then remove it from history.
