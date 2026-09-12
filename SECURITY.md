# Security scope

SyncGuard 0.2 is a loopback-only development MVP with synthetic data, one demo organization and no authentication. Its public demo API does not accept upstream URLs or credentials. HTTP adapters use server-side configuration and perform read operations only. Redirects and cross-collection OData nextLink values are rejected; failures do not expose upstream bodies or credential URLs.

Do not expose these demo services to the Internet. Production onboarding needs authentication, tenant authorization, managed secrets, approved upstream destinations, retention and deployment controls. The simulator is test infrastructure.

Before a commit, run `python tools/check_secrets.py`. This detects common key formats and tracked environment files; it cannot prove arbitrary business content is non-confidential. Review staged changes as well. The example database password is public, synthetic and intended only for local development.

Report a vulnerability privately to the repository owner. Do not include live credentials or customer records in a public issue. If a credential is accidentally published, revoke it at its provider; deleting it from the latest source does not remove Git history.
