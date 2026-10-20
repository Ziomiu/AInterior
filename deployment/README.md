# Public Access and Panorama Lab

## Architecture

GitHub Pages redirects to a fixed HTTPS ngrok URL. ngrok runs on the university
host and forwards to the web reverse proxy, not to FastAPI, ComfyUI, MongoDB or
Qdrant directly. Browser login and `/api` calls share one origin. No Vite API URL,
GitHub secret, SSH password or CORS change is needed for this arrangement.

The production web server was observed on host port **80**, not 8080, on
2026-10-20. A previous local SSH `-L 8080:localhost:80` does not mean the remote
web server listens on 8080. The isolated test web server uses **5176**, backend
5558, and ComfyUI 8190, all on loopback.

## Server Setup

The prepared isolated directory is `/home/lzegar/ainterior-public-lab-20261020-01`.
Do not point the public tunnel at this lab until its tests are accepted. It uses
the separate `ainterior_replacement_lab` database, not production accounts.
Its furniture integration is not configured. The new panorama models and test
containers do not update the production application.

Connect once as the operator:

```bash
ssh -J lzegar@bastion.ii.agh.edu.pl lzegar@172.29.96.12
cd /home/lzegar/ainterior-public-lab-20261020-01
mkdir -p ~/.local/bin ~/.config/systemd/user
install -m 755 bin/ngrok ~/.local/bin/ngrok
```

Configure the **assigned public URL** from the ngrok dashboard. The helper asks
for the authtoken with hidden input; never paste it into chat or a GitHub repo:

```bash
/home/magisterka/AInterior-replacement-test/furniture-replace-service/.venv-lab/bin/python \
  deployment/configure_ngrok.py --url https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app --port 5176
~/.local/bin/ngrok config check --config ~/.config/ainterior-ngrok/ngrok.yml
install -m 644 deployment/ainterior-ngrok.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ainterior-ngrok
systemctl --user status ainterior-ngrok --no-pager
```

JSON is valid YAML; the helper writes a v3 ngrok configuration with inspection
disabled and restrictive file permissions. Avoid `set -x`, printing the config,
or passing the token on the command line.

`loginctl show-user lzegar -p Linger` reported `Linger=no`. Ask the host
administrator to enable lingering for this user (`loginctl enable-linger lzegar`)
if permitted. Without lingering or an approved system service, do not assume the
tunnel survives logout/reboot. Confirm campus policy permits the public tunnel.
No admin command has been run automatically.

Create the separate Pages repository using [pages-redirect/README.md](pages-redirect/README.md).
Publish only after testing HTTPS login and generation through the assigned URL.
The ngrok account may impose request timeouts, transfer limits and an initial
browser warning. Test a cold generation; a local nginx timeout does not override
provider limits. A disconnected browser does not cancel GPU inference.

## Panorama Models

The dedicated authenticated API is `GET /model/panorama/models` and
`POST /model/generate/panorama`. Only installed compatible checkpoints are
offered. The backend owns resolution, sampler and checkpoint mapping; clients
cannot request arbitrary checkpoint paths. Gallery records include the seed,
model, sampler and actual output resolution. SDXL profiles use `1536x768`,
Stable Diffusion 2.1 uses `1024x512`, and SD1.5/DreamCreation use `768x384`.

| Profile | Source | Revision |
| --- | --- | --- |
| RealVisXL V4 | SG161222/RealVisXL_V4.0 | 26dfe44930964cd70d0a817b6d1cc945c130e38d |
| Juggernaut XL V9 | RunDiffusion/Juggernaut-XL-v9 | cf419233522daa0b9ea36c3aff98fa2cab1fb0fb |
| SDXL Base | existing installed checkpoint | unchanged |
| Stable Diffusion 1.5 | existing installed checkpoint | unchanged |
| Stable Diffusion 2.1 | existing installed checkpoint | unchanged |
| DreamCreation Virtual 3D | existing installed checkpoint | unchanged |

The additional installed models are selectable for manual evaluation; no quality
comparison was run for them. Inpainting checkpoints are excluded from this
text-to-image workflow. SD3 is not offered because it requires a separate latent
setup and verification of its text encoders.

Review the publishers' model cards and licenses before public use. RealVisXL and
Juggernaut are photorealistic SDXL fine-tunes, **not panorama-trained models**.
The workflow improves resolution and sampling but does not enforce circular
padding or guarantee a seamless wrap or correct pole geometry. A dedicated
panorama model/LoRA or circular-diffusion workflow remains a separate quality
upgrade; do not mistake a 2:1 image and viewer for proof of spherical consistency.

The RTX 2080 Ti has 11 GB VRAM. Do not generate in this isolated ComfyUI while
production furniture/ComfyUI is working. Its separate lab queue does not
coordinate with the production GPU queue. Stop the lab ComfyUI after tests.
The Compose file intentionally has no restart policy for isolated inference.

## Production Handoff

Repository instructions mark production read-only for this session. Therefore
no production checkpoint directory, container, code, account or database is
modified by these changes. An approved operator rollout must update backend and
frontend together, install the two checkpoints, retain the shared GPU queue,
apply equivalent public proxy restrictions, and point ngrok at that web proxy.
Preserve environment files and back up application/data before rollout. Do not
expose MongoDB, ComfyUI or the ngrok inspection interface.