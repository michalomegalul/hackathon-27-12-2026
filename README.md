- Live app: **https://hack.dobsinsky.dev** (the `/test` page is `https://hack.dobsinsky.dev/test`)
- Code: `git@github.com:michalomegalul/hackathon-27-12-2026.git`
- Server login: `ssh <your-username>@ssh.dobsinsky.dev`

## 1. udelej ssh pokud nemas
```
ssh-keygen -t ed25519
```

```
cat ~/.ssh/id_ed25519.pub
```

posli mi to na discord

## 2. Connect to ssh

```
sudo pacman -S cloudflared
```

Then add this to `~/.ssh/config` (create the file if missing):

```
Host ssh.dobsinsky.dev
  ProxyCommand cloudflared access ssh --hostname %h
  User <USERNAME>
```

Connect:

```
ssh <USERNAME>@ssh.dobsinsky.dev
```

## 3. Working on the project

You are on a shared Linux box. You can use `sudo` and `docker` without a password.

**The app deploys itself.** Every 30 seconds the server checks `main` on GitHub.
If there is a new commit it rebuilds with `docker compose up -d --build`.
30 sec is delay for deploy


Useful commands on the server:

```
cd /opt/app                          # the deployed code
docker compose ps                    # what is running
docker compose logs -f               # live logs
sudo journalctl -u deploy -n 20      # did the last auto-deploy work?
```
