# Cloudflare Toolkit

The Cloudflare Toolkit detects three first-party command-line tools: Cloudflare `cf`, Wrangler, and `cloudflared` (Cloudflare Tunnel). It displays versions, executable paths, and an installation method when that method can be verified. Unknown ownership is never guessed for update or removal.

## Install, update, and remove

Cloudflare's `cf` CLI is offered through the official global package-manager commands: npm, Yarn, pnpm, or Bun. It requires Node.js 22.18 or later. The menu displays detected Node.js/npm versions and refuses `cf` installation, update, or authentication when the Node minimum is not met. Bun is available as a package manager but is not supported as the CLI runtime. The CLI may be added as a project dependency when a JavaScript project and lockfile are present. Updates use the detected manager's documented `@latest` install command; removal only uninstalls the `cf` package. Cloudflare `cf` credentials are separate from Wrangler credentials.

Wrangler is installed into the current JavaScript project with the detected package manager when a `package.json` exists. Without a project, the toolkit offers an npm global fallback and clearly warns that Cloudflare recommends project-local Wrangler. npm reports the package's declared engine requirement; use a supported Node.js release.

`cloudflared` uses documented package methods where available: Homebrew on macOS, Cloudflare's APT repository on Debian/Ubuntu, Cloudflare's RPM repository on supported RHEL-family systems, and the Arch community package when detected. A displayed command plan requires explicit confirmation before execution. Existing unrelated package repository/key files are not overwritten. Windows or unsupported package combinations receive the official downloads link rather than an unverified install command.

Cloudflare's published installation methods do not specify Termux/Android as a supported `cloudflared` package target. Automatic `cloudflared` installation is therefore refused on Termux; third-party Termux binaries and arbitrary downloads are not used.

Updates and removals use the detected package manager. Removal only removes the CLI package or project dependency; it does not purge credentials, tunnel configuration, Node.js, or other shared tools. If ownership cannot be verified, the toolkit refuses to guess.

## Operations and safety

`cf auth whoami` and `wrangler whoami` output is suppressed and reduced to an authentication status; account identity, credential paths, and one-time OAuth codes are not printed. Login/logout require confirmation. `cf` credentials and Wrangler credentials are checked independently.

`cf` provides CLI help, command search, and confirmed project commands. If a Wrangler configuration is present, the toolkit will not run `cf dev` or `cf deploy` until the project is intentionally migrated; it displays Cloudflare's migration guide and never runs `cf migrate` or rewrites project files automatically. Wrangler development/deployment remains available in its existing workflow, with explicit confirmation.

The tunnel menu checks local configuration by filename only and never reads `cert.pem` or tunnel credential contents. Named tunnel create/delete actions require confirmation; deletion also verifies the tunnel exists. A Quick Tunnel accepts only localhost/loopback origins, verifies that the local port is accepting connections, and warns that anyone with the temporary public URL can access the service. The tunnel runs in the foreground and Ctrl+C stops it. No tunnel starts automatically.

## Official Cloudflare documentation

- [Cloudflare `cf` CLI](https://developers.cloudflare.com/cf/)
- [`cf` install, requirements, and sign-in](https://developers.cloudflare.com/cf/get-started/)
- [`cf` Wrangler migration guide](https://developers.cloudflare.com/cf/wrangler/migrate/)
- [Wrangler installation and updates](https://developers.cloudflare.com/workers/wrangler/install-and-update/)
- [Wrangler commands and authentication](https://developers.cloudflare.com/workers/wrangler/commands/)
- [Cloudflare Tunnel downloads](https://developers.cloudflare.com/tunnel/downloads/)
- [Cloudflare package repository](https://pkg.cloudflare.com/)
- [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Create and manage locally-managed tunnels](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/)
