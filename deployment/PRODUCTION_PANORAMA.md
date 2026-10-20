# Panorama Rollout and ngrok

This is an **operator-run** deployment. Production has not been changed by the
assistant. No further generation/quality checks are required by this handoff.
The current High/4K implementation is prepared in the isolated lab; do not treat
this document as confirmation of an end-to-end 4K quality result.

## Apply the Prepared Release

First stop accepting new generations and wait for active jobs to finish. The
rollout has a short interruption for frontend, backend and ComfyUI. It does not
change MongoDB, Qdrant, furniture inference, their volumes, or the production
Git checkout. It retains the existing private manual Compose override and the
active furniture-service key. The script refuses a different host/configuration
or a nonempty GPU queue. Keep traffic closed throughout deployment: the idle
check is not a lock against new requests.

Connect from your laptop, then run **on the university host**:

```bash
ssh -J lzegar@bastion.ii.agh.edu.pl lzegar@172.29.96.12
cd /home/lzegar/ainterior-public-lab-20261020-01
bash deployment/deploy_panorama_production.sh --check
bash deployment/deploy_panorama_production.sh --apply
```

`--check` only inspects inputs and idle queues. `--apply` copies the prepared
backend files, built frontend, ComfyUI nodes, two additional SDXL checkpoints
and RealESRGAN weights to a timestamped directory under `~/ainterior-releases`.
It pins the currently running image IDs: no image rebuild, image pull, Git pull,
or model download happens during rollout. It stops the three isolated lab
services before restarting only production `comfyui`, `backend` and `frontend`.
The private release remains independent of the lab after deployment.

The script prints the release directory and exact rollback command. Do not
delete that directory: it supplies read-only mounts for the running services.
Its `compose.env`, `active.json`, and `rollback.json` contain secrets and must
never be uploaded to GitHub, printed in chat, or made publicly readable.

For later operations retain both original Compose files, the release overlay,
and the release's `--env-file`. Do not use a bare `docker compose up` from the
production checkout: that would omit the panorama mounts and saved overrides.
The app still runs the production accounts/database; lab accounts do not carry
over. Existing admin endpoints remain behind application authorization; internal
GPU admission endpoints and API documentation are blocked by the public proxy.

## Start ngrok

ngrok runs on **biomobi**, not on the laptop or bastion. Production HTTP is
`127.0.0.1:80`; the public origin is
`https://utility-rover-fanatic.ngrok-free.dev`.

```bash
cd /home/lzegar/ainterior-public-lab-20261020-01
mkdir -p ~/.local/bin ~/.config/systemd/user
install -m 755 bin/ngrok ~/.local/bin/ngrok
/home/magisterka/AInterior-replacement-test/furniture-replace-service/.venv-lab/bin/python \
  deployment/configure_ngrok.py \
  --url https://utility-rover-fanatic.ngrok-free.dev --port 80
~/.local/bin/ngrok config check --config ~/.config/ainterior-ngrok/ngrok.yml
~/.local/bin/ngrok start ainterior --config ~/.config/ainterior-ngrok/ngrok.yml
```

Type the authtoken only into the helper's hidden terminal prompt. Do not put it
in chat, browser code, GitHub secrets, or a command's arguments. The helper
disables the local request inspector and stores the token with permissions
`0600`. Confirm campus policy allows the public tunnel before starting it.

The equivalent forwarding command, once authenticated, is:

```bash
~/.local/bin/ngrok http 80 \
  --url https://utility-rover-fanatic.ngrok-free.dev --inspect=false \
  --config ~/.config/ainterior-ngrok/ngrok.yml
```

Run **one** of `ngrok start` and `ngrok http`, not both. Do not publish ComfyUI,
MongoDB, Qdrant, port 5555 or the ngrok inspection interface. Forward the web
server only. The nginx proxy and frontend `/api` calls preserve same-origin
login without a CORS or frontend API URL change. No SSH passwords are needed by
end users. An initial ngrok warning page and account request/transfer/time limits
may apply; nginx timeouts cannot override provider limits.

## Keep It Running

After the foreground tunnel works, press Ctrl+C in that terminal and install the
prepared user service:

```bash
cd /home/lzegar/ainterior-public-lab-20261020-01
install -m 644 deployment/ainterior-ngrok.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ainterior-ngrok
systemctl --user status ainterior-ngrok --no-pager
```

`Linger=no` was observed for `lzegar`. Ask the host administrator to enable
lingering for that user if permitted, or use an approved system service. Until
then the tunnel is **not guaranteed** to survive logout/reboot. No privileged
command is run by the rollout or helper.

## GitHub Pages

Use the contents of [pages-redirect](pages-redirect) as a new repository root,
including its `.github` directory. Add an Actions **variable** `APP_URL` set to
`https://utility-rover-fanatic.ngrok-free.dev`, select GitHub Actions in Pages
settings, and run **Deploy AInterior Redirect**. No secret is needed on GitHub.
Pages redirects to ngrok; it does not mask that address or host a tunnel.