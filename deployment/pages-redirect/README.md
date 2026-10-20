# AInterior Pages Redirect

Use this directory's **contents**, including `.github`, as the root of a new GitHub
repository. No application code, SSH password or tunnel token belongs in that repo.

1. Create the repository and upload these files on `main`.
2. In Settings > Secrets and variables > Actions > Variables, add `APP_URL` with
   the assigned HTTPS ngrok URL, for example `https://your-name.ngrok-free.app`.
   This is a public URL, not a secret.
3. In Settings > Pages > Build and deployment, select **GitHub Actions**.
4. Run **Deploy AInterior Redirect** from Actions, or push to `main`.

Users open the Pages URL and are redirected to the application. They log in
there; Pages never receives passwords or tokens. The address bar changes to the
ngrok URL. This is a redirect, not an iframe or a browser-side SSH tunnel.

If `APP_URL` changes, update the variable and rerun the workflow. A free ngrok
endpoint may show an initial provider warning and has account-dependent traffic
limits. The university host and tunnel agent must remain running.