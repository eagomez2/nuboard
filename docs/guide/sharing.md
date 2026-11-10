# Sharing from a cloud machine

Your runs are on a cloud VM or a cluster node, and you want to look at them
from your laptop, or show them to a colleague. `nuboard up` serves the viewer
from the machine that holds the runs, so the question is only how a browser
reaches it. There are three ways:

| | Who can open it | What they need | Exposed to the network |
| --- | --- | --- | --- |
| [SSH port forwarding](#ssh-port-forwarding) | you, and anyone you give SSH access | SSH access to the machine | nothing: the viewer only listens on the machine itself |
| [A token on the network](#a-token-on-the-network) | anyone who has the link and can reach the port | the link (a browser is enough) | the port, in plain HTTP |
| [HTTPS behind a reverse proxy](#https-behind-a-reverse-proxy) | anyone who has the link | the link | an HTTPS port, run by a proxy you set up |

Start with SSH port forwarding. Use a token when someone without SSH access
needs to look, and only on a network you trust (a VPN, a private network, or a
firewall rule that lets only their address in). Put a proxy with HTTPS in
front when the viewer must be reachable over the internet.

Whichever you pick, keep the viewer running with `tmux` or `screen` so it
survives when your SSH session ends, and stop it (Ctrl+C) when nobody needs
it.

## SSH port forwarding

Start the viewer as usual on the remote machine. It listens on `127.0.0.1`,
so nothing outside the machine can reach it:

```console
gpu-box$ nuboard up ~/experiments
nuboard serving /home/me/experiments (31 runs) at http://localhost:6070/  (Ctrl+C to stop)
```

Then, on your laptop, forward a local port to it and open
<http://localhost:6070/>:

```console
laptop$ ssh -N -L 6070:localhost:6070 me@gpu-box
```

`-L 6070:localhost:6070` sends your laptop's port 6070 to port 6070 on
`gpu-box`, and `-N` holds the tunnel open without starting a shell. If 6070 is
taken on your laptop, use another local port: `-L 8080:localhost:6070` and
open <http://localhost:8080/>. If `nuboard up` printed another port (6070 was
taken on the server), forward that one.

To reach a compute node behind a login node, as on a SLURM cluster, jump
through the login node:

```console
laptop$ ssh -N -J me@login.cluster -L 6070:localhost:6070 me@node042
```

**VS Code Remote-SSH** forwards ports for you: when `nuboard up` prints its
link in the integrated terminal, VS Code offers to open it, and the **Ports**
panel lists the forwarded port. The same works in other editors with remote
development.

!!! tip "Pros and cons"

    **Accessibility.** Each viewer needs SSH access to the machine (or to a
    login node in front of it) and an `ssh` command running while they look.
    That suits you and your teammates, but not a reviewer or a manager without
    an account. Nothing has to change in the firewall.

    **Security.** This is the safest option. The viewer is not reachable from
    the network at all, and everything travels inside the encrypted SSH
    connection. Only people who can already log in to the machine can open
    it. No token is needed, since only the machine itself can connect.

## A token on the network

`--host 0.0.0.0` makes the viewer listen on every network interface. Anyone
who reaches it could read your runs and change notes, tags, reports and
hypothesis boards, so it then asks for a random access token, as Jupyter does:

```console
gpu-box$ nuboard up ~/experiments --host 0.0.0.0
nuboard serving /home/me/experiments (31 runs) at http://gpu-box:6070/?token=3f9c…e1  (Ctrl+C to stop)
  Open the link above once per browser; it signs the browser in.
```

Send the link to whoever should look. If the printed host name does not
resolve from their side, replace `gpu-box` with the machine's IP address.
Opening the link signs their browser in for 30 days with a cookie and removes
the token from the address bar. Without the link, the viewer shows a sign-in
form where the token can be pasted.

- **A fixed token.** Each start makes a new token, which signs everyone out.
  To keep links and bookmarks working across restarts, set one yourself with
  `--token VALUE` or the `NUBOARD_TOKEN` environment variable. Treat it like a
  password: long and random, for example from `python -c "import secrets;
  print(secrets.token_hex(24))"`.
- **Opening the port.** On a cloud VM, the provider's firewall (a security
  group on AWS, firewall rules on Google Cloud, a network security group on
  Azure) must allow the port, 6070 by default. Allow only the addresses that
  need it, not `0.0.0.0/0`.
- **Read-only viewers.** Artifacts are read-only unless you add
  `--edit-artifacts`. Add `--read-only-reports` so viewers cannot edit
  reports or upload files into them, `--read-only-hypotheses` so they cannot
  change hypothesis boards, and `--read-only-directions` so they cannot save
  which way is better for a scalar.
- **Scripts** send the token in a header: `Authorization: token VALUE`.

`--no-token` serves the network address without a token. Anyone who can reach
the port can then use the viewer, so keep it for a network where that is
already true, such as a machine only you can reach.

!!! tip "Pros and cons"

    **Accessibility.** The easiest option for others: they need only a
    browser and the link, with no account and no SSH. It works from a phone
    or a tablet. You need to be able to open a port on the machine, and they
    need a network path to it (the same VPN or office network, or an address
    you allowed in the firewall).

    **Security.** The token keeps out anyone who does not have the link, but
    it travels in plain HTTP. Anyone who can watch the network between the
    browser and the machine (shared Wi-Fi, a hotel network) can read it and
    the data you look at. Anyone with the link has the same access you have:
    they can read every run under the folder you served, and change notes,
    tags, reports and boards unless you add `--read-only-reports` and
    `--read-only-hypotheses`. A
    forwarded link keeps working until you change the token. Use it on
    networks you trust, limit the port to known addresses, and stop the viewer
    when you are done.

## HTTPS behind a reverse proxy

To reach the viewer over the internet, put a web server that handles HTTPS in
front of it, on its own host name, and keep a token. The viewer stays on
`127.0.0.1`, where it accepts only requests addressed to `localhost`, so the
proxy must send that host name. With [Caddy](https://caddyserver.com/), which
gets a certificate by itself:

```text title="Caddyfile"
nuboard.example.com {
    reverse_proxy 127.0.0.1:6070 {
        header_up Host localhost
    }
}
```

```console
gpu-box$ NUBOARD_TOKEN=… nuboard up ~/experiments --read-only-reports --read-only-hypotheses
```

Open `https://nuboard.example.com/?token=…` once per browser. The proxy also
passes live updates through: they use Server-Sent Events, a long-lived HTTP
response.

!!! tip "Pros and cons"

    **Accessibility.** Like a token on the network, others need only a
    browser and the link, and now from anywhere. You need a host name that
    points to the machine, an open HTTPS port and a proxy to keep running.

    **Security.** HTTPS encrypts the token and the data on the way, which
    fixes the main weakness of the plain token. The viewer is still reachable
    by anyone on the internet who has the link, and the token is the only
    thing that stands in the way: use a long one, add the `--read-only-…` flags,
    and stop the viewer when it is no longer needed. For more control (single
    sign-on, a list of allowed users), put an authenticating proxy in front;
    the viewer has no user accounts of its own.

Services that publish a local port under a public URL, such as ngrok or
Cloudflare Tunnel, work the same way: keep a token, and have them send
`Host: localhost` (or run the viewer with `--host 0.0.0.0`, which accepts any
host name and then always asks for a token).

## Sharing without a server

You do not always need a running viewer. A run is a folder, so you can copy
the runs to your laptop (`rsync -a gpu-box:experiments/ ~/gpu-runs/`) and
open them there, or merge them into your own folder with
[`nuboard merge`](machines.md). A [report](reports.md#sharing) exported as HTML is a
single file with its charts and figures, which opens offline in any browser
and can be attached to an email.
