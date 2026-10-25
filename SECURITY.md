# Security Policy

## Reporting a vulnerability

Please do **not** report security vulnerabilities in public GitHub issues. Report them privately instead:

- through GitHub Private Vulnerability Reporting:
  <https://github.com/PaBu04/Lumora/security/advisories/new>
- or by e-mail to <kontakt@paulbuda.de>

Please include the Lumora version, your operating system and the steps to reproduce the problem.

## Scope

Lumora is meant to run locally on your own PC. The app server listens on `127.0.0.1` by default. It rejects
requests from other websites and requests that use a host name other than localhost. **Do not expose the server
to the internet**, for example through port forwarding, a reverse proxy, or by setting `LUMORA_HOST=0.0.0.0` on
a network you do not trust. The app has no user accounts or login.

Some parts reach the local network or the internet on purpose:

- **Phone remote** (off by default): a separate small server on all network interfaces (port 8010). It offers only
  playback controls and live cues, and every request needs the random key from the QR code.
- **WLED output**: frames are sent to your controllers via DDP (UDP), and their status is read over HTTP.
- **AI show creation**: runs your locally installed Claude Code, which talks to Anthropic.

Custom effects (shaders) run in a separate process with restricted Python. This guards against hangs and
mistakes but is **not** a security boundary. Only import projects and shaders from sources you trust.

## Support

Lumora is a private, non-commercial project. Reports are answered on a best-effort basis, without guaranteed
response times. There is no bug bounty.
