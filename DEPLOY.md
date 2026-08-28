# Hosting it

Four routes, from free-and-instant to paid-and-tidy. Pick by whether you want a
signup, a card, and whether it has to be up when your laptop is not.

| Route | Cost | Signup | Always up |
|---|---|---|---|
| Your laptop plus a Cloudflare Tunnel | free | none | no, only while your laptop runs |
| GitHub Codespaces | free within quota | GitHub account, no card | no, while the codespace runs |
| Google Cloud Run | free at this workload | Google account **and card** | yes, scales to zero when idle |
| Fly.io | pennies a month idle, ~5.70 USD if always on | Fly account and card | yes |

**If you want it running in the next five minutes with no account anywhere,
run `share.ps1` on Windows or `./share.sh` on macOS or Linux.** One command: it
installs what it needs, generates a password, starts the app, opens a tunnel and
prints a ready-to-send message with the address and login. See the first section
below. If you want a URL that works whether or not your laptop is on, and you
are willing to attach a card that will not be charged at this usage, Cloud Run
is the free one.

---

## One command, no account: share.ps1 / share.sh

    Windows:        right-click share.ps1 and Run with PowerShell
    macOS / Linux:  ./share.sh

It creates a virtual environment beside the script, installs the pinned
dependencies, generates a random password, starts the app on localhost, fetches
`cloudflared` if it is not already there, opens a Cloudflare quick tunnel, and
prints a block you can paste straight to whoever is testing, containing the
`https://<something>.trycloudflare.com` address and the login.

No Docker involved: it uses Python directly, which is one fewer thing to go
wrong. Requires Python 3.9 or newer.

The window has to stay open. Ctrl+C stops the tunnel and the app, and the
address dies with it. Run it again for a fresh address and a fresh password.

**If no address appears**, the script prints the tunnel log and says so. The
usual cause is a corporate network blocking Cloudflare's tunnel endpoints, which
is common and nothing to do with this app. The app is still running locally, and
Cloud Run below does not depend on your network in the same way.

---

## Google Cloud Run, free at this workload

Cloud Run bills per request and scales to zero, and Google's always-free monthly
allowance is 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests
([Cloud Run pricing](https://cloud.google.com/run/pricing)).

A full build, verify and viewer cycle measured 2.3 seconds and 497 MB. At 1 GiB
and roughly 3 seconds a request that is about **60,000 requests a month inside
the free allowance**, and even if every single request were a 30-second cold
start you would get about 6,000 of those free. Two people evaluating a prototype
will not come close. The allowance is per billing account and resets monthly.

A billing account with a card is required to enable the service, but nothing is
charged while you stay inside the allowance. Set a budget alert at a pound if
that makes you more comfortable.

    ./cloudrun.sh <your-gcp-project-id>            # region defaults to London

The script enables the APIs, generates a password and stores it in Secret
Manager, builds from this Dockerfile with Cloud Build, and deploys with
`--min-instances 0` so idle costs nothing. It prints the URL and the password at
the end. Redeploy any time by running it again.

To take it down: `gcloud run services delete drawing-to-solid --region europe-west2`

## GitHub Codespaces, free and no card

A personal GitHub account includes 120 core-hours and 15 GB-month on the free
plan, 180 hours on Pro, and **no card is needed**: usage simply stops when the
quota runs out rather than billing you
([Codespaces billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-codespaces/about-billing-for-github-codespaces)).

Push this folder to a repository, open it in a Codespace, then:

    docker compose up -d

In the Ports panel, set port 8000 to Public and share the forwarded URL. On a
2-core machine, 120 hours is about 60 hours of uptime a month, which is plenty
for an evaluation. Set `AUTH_USER` and `AUTH_PASS` first: a public forwarded
port is reachable by anyone with the link. The codespace stops when idle and the
URL dies with it.

## Oracle Cloud Always Free

Oracle's always-free tier includes an ARM VM with enough memory to run this
comfortably and no time limit, which on paper is the best free option. It is not
the first one to reach for because account approval is unreliable and sometimes
takes days or fails outright. If you already have an Oracle account, install
Docker on the VM and use the compose file.

---

## Fly.io

Gets Ujjwal a private HTTPS URL he can open from his MacBook with nothing
installed. Roughly ten minutes, most of it the first image build.

## Before you start

Install the CLI and sign in. Fly asks for a card even though occasional use here
costs pennies; if that is a blocker, the tunnel option at the bottom needs no
account at all.

    # Windows, in PowerShell
    pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"

    # macOS or Linux
    curl -L https://fly.io/install.sh | sh

    fly auth signup     # or: fly auth login

## Deploy

From this folder:

    fly launch --no-deploy --copy-config --name drawing-to-solid-eg

Pick your own name; it becomes `https://<name>.fly.dev` and has to be unique
across Fly. Answer no to Postgres, Redis and any other extras: this app needs
none of them. `--copy-config` makes it keep the `fly.toml` here rather than
writing a fresh one.

Set the login before the first deploy, so the app is never briefly open:

    fly secrets set AUTH_USER=ujjwal AUTH_PASS='<a long random password>'

Generate the password rather than inventing one:

    python -c "import secrets; print(secrets.token_urlsafe(24))"

Then:

    fly deploy

The first build uploads the context and builds the image on Fly's builder, which
takes several minutes because OpenCASCADE is large. Later deploys reuse the
cached layers.

    fly open          # opens the URL
    fly logs          # follow what it is doing
    fly status        # is the machine up, stopped, or unhealthy

Send Ujjwal the URL and the username and password. His browser will prompt for
them, and Fly serves everything over HTTPS so they are never sent in clear.

## What it costs

Fly has no free compute allowance any more; it is pay as you go. A
`shared-cpu-1x` machine with 1 GB bills about **5.70 USD a month if left running
continuously** ([Fly pricing](https://fly.io/docs/about/pricing/)).

This config does not leave it running. `auto_stop_machines = "stop"` with
`min_machines_running = 0` stops the machine when nobody is using it, and a
stopped machine is charged only for its root filesystem, around 15 cents per GB
per 30 days. For two people trying a prototype, expect well under a pound a
month. The cost of that is a cold start of a few seconds on the first request
after an idle spell, which for this use is a fair trade.

If you would rather it always answer instantly, set `min_machines_running = 1`
and accept the ~5.70 USD.

## Sizing

A full build, verify and viewer cycle measured 497 MB peak, of which 456 MB is
importing OpenCASCADE, and took 2.3 seconds. 1 GB therefore has roughly double
the headroom needed for one request at a time, which suits two users. If you
ever see an out-of-memory kill in `fly logs`:

    fly scale memory 2048

Render's free instance type is more memory constrained than this app's measured
peak, which is why this config targets Fly.

## Routine operations

    fly deploy                        # ship a change
    fly secrets set AUTH_PASS='...'   # rotate the password, redeploys automatically
    fly logs                          # tail
    fly machine list                  # see machine state
    fly apps destroy <name>           # tear the whole thing down

Results are written inside the machine and disappear when it restarts. That is
deliberate: every result is reproducible from its spec, and nothing here is
worth persisting. If you want them kept, add a volume and mount it at `/out`.

## What this is and is not

It is a prototype behind one shared password. That is proportionate for two
named colleagues evaluating it over HTTPS. It is **not** hardened for the open
internet: there is no rate limiting, and anyone with the password can make the
server do CPU work. Do not put anything commercially sensitive through it, and
take it down when the evaluation is finished.

The one route left open without a password is `/healthz`, which returns the word
`ok` so Fly's health checks work. It exposes nothing else.

## Your own machine plus a tunnel, free and no signup

The quickest route, and free. Run it locally and give Ujjwal a temporary HTTPS
URL:

    docker compose up -d
    cloudflared tunnel --url http://localhost:8000

That prints a `https://<random>.trycloudflare.com` address which works until you
stop it. Set `AUTH_USER` and `AUTH_PASS` in the compose file first, because that
URL is reachable by anyone who has it. Only up while your laptop is on.
