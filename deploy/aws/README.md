# AWS deployment using the private ChatGPT tunnel

This directory prepares a single Ubuntu 24.04 x86_64 server. The London deployment
passed migration, live discovery, private tunnel and reboot checks on 19 September
2026; see [verification status](../../docs/verification.md) for the separate
ChatGPT conversation result. The current deployed revision is
`baf2013293169b6196323b2de50ac8b1103316c3`; its 10-tool read-only surface and live
provider search passed direct MCP HTTP acceptance. ChatGPT Settings now lists all ten
tools, and real ChatGPT live-search and evidence calls succeeded after an initial
discovery failure. Use an eligible EC2
`t3.small` (2 GiB RAM) while evaluating the AWS Free plan. Verify the account's
current plan, credits, regional launch estimate and expiry before launching.
Lightsail requires a Paid plan; do not upgrade implicitly. Credits are temporary,
and budget alerts are notifications rather than spending limits.

## Server settings

- Ubuntu 24.04 LTS, x86_64; `t3.small`; CPU credit mode **standard**.
- Encrypted gp3 storage, initially 20 GiB. Preserve the data volume on termination.
- No application IAM role or AWS API credentials are needed.
- No public HTTP, HTTPS, 8383 or 8384 inbound rules. The private tunnel connects out.
- Preserve outbound DNS, HTTPS and the official tunnel client's required egress.
  The verified deployment uses the security group's default outbound rule; a
  custom egress policy needs its own connectivity checks.
- If using SSH, allow port 22 only from the administrator's current IP, with a key.
- Do not put runtime keys, API keys or database contents in EC2 user data.
- Confirm recurring compute, storage and public IPv4 costs in the chosen region.

The service listens only on loopback. Separate restricted system users run the
application and official OpenAI tunnel client. Neither needs root privileges or
instance metadata access. The root-owned runtime key is delivered through systemd
credentials, not a command-line secret. This is the private-tunnel hosting option;
public OAuth hosting is documented separately in the main deployment guide.

## Install an exact revision

Clone this repository on the VM and check out the reviewed full commit SHA. Use a
clean checkout, then run `sudo bash deploy/aws/install.sh FULL_COMMIT_SHA`.
The installer supports a fresh VM only and refuses an existing installation.
It installs hash-pinned dependencies and a checksum-verified OpenAI tunnel client,
validates service definitions, and leaves every service stopped and disabled.

Set the existing tunnel ID in `/etc/career-search/tunnel.env` using `sudoedit`.
Transfer the existing runtime key only over an authenticated encrypted connection
to this verified server. Install it as `/etc/career-search/runtime.key`, root-owned,
mode 0600. Never paste it into shell commands, user data, source files or logs.
The configuration files in `/etc/career-search` also remain root-owned mode 0600.

## Move the database and cut over

1. Stop discovery and other writers on the old host. Create a consistent snapshot
   with `career-backup --database PATH_TO_DB --directory PRIVATE_BACKUP_DIR`.
   Do not copy a live SQLite database file while ignoring its WAL file.
2. Transfer the resulting backup over authenticated SSH. Install it as
   `/var/lib/career-search/career.sqlite3`, owned by `career-search:career-search`,
   mode 0600. Compare job, profile and history counts with the source snapshot.
3. Start the application: `sudo systemctl start career-search.service`.
4. Run `/opt/career-search/venv/bin/python deploy/aws/verify_readonly.py` from the
   checkout. It verifies the exact ten read-only tools and real HTTP reads without
   contacting a job provider or printing personal records. A separate direct HTTP live
   provider call on the current revision also passed; the acceptance evidence is in
   [verification status](../../docs/verification.md). The ChatGPT check below remains
   separate; real live-search calls succeeded after an initial ChatGPT discovery failure.
5. Stop the old host's tunnel runtime before starting this server's tunnel.
   Keep only one authoritative database, watcher and tunnel connection.
6. Start `career-tunnel.service`; verify both HTTP endpoints at
   `http://127.0.0.1:8384/healthz` and `/readyz` return success.
7. Run `sudo systemctl start career-watcher.service` once. Inspect discovery source
   status as well as service exit status: a successful process can still report a
   temporarily unavailable provider. Confirm saved jobs and provenance through MCP.
8. Run `sudo systemctl start career-backup.service`. Open the latest backup with
   SQLite read-only, run `PRAGMA integrity_check`, and compare record counts.
9. Enable the application, tunnel and timers:
   `sudo systemctl enable career-search.service career-tunnel.service` and
   `sudo systemctl enable --now career-watcher.timer career-backup.timer`.
10. Reboot and repeat health/read checks before calling the migration complete.

The watcher discovers jobs every six hours; it does not apply or send messages.
The backup timer creates a consistent private snapshot daily and retains seven.
These backups are on the same disk and do **not** protect against disk/account
loss. Agree on an off-host backup or EBS snapshot policy and its costs separately.
Preserve a verified local backup before terminating any instance.

## ChatGPT acceptance check

The verified 19 September ChatGPT conversation used the earlier nine-tool interface and
successfully called `get_profile`, `search_saved_jobs`, and the four evidence tools. The
current AWS revision has since passed direct HTTP live-search acceptance. ChatGPT Settings
was refreshed and shows ten READ tools, including `search_live_jobs`; the first new
conversation initially failed to discover that action, then a retry succeeded with a real
request/response card. The post-fix test returned four relevant roles and passed detail
and fit-evidence calls. In a fresh conversation with Developer Mode available, explicitly
select Career Search MCP, call live search, and inspect its per-source status. Also use
a returned live ID with `get_job_detail` or an evidence
tool. A conversation reporting `This conversation does not support developer MCPs` cannot
validate the integration. Never claim ChatGPT success from server health or direct HTTP
checks alone.

Adzuna remains disabled until official credentials are configured securely.
Scout remains disabled until its provider accepts ChatGPT's OAuth callback and a
live search succeeds. No server deployment fixes those provider prerequisites.

## Operations and rollback

Inspect `systemctl status` and targeted `journalctl` output; never log credentials
or full personal records. To roll back, stop the AWS watcher and tunnel first,
back up any new data, and reconcile it before restoring the old host. Do not
silently overwrite either database. Review upgrades separately; the fresh-server
installer intentionally refuses to replace an existing deployment.

CI installs the exact revision on Ubuntu 24.04 and tests actual HTTP reads and a
backup under the service restrictions. It uses no AWS resources or tunnel key.
The current revision's AWS service and live-provider acceptance are recorded in
[verification status](../../docs/verification.md); ChatGPT verification of the new
tool succeeded after a discovery retry. Future revisions require their own deployment acceptance.
