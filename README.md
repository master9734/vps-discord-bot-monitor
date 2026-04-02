# 👁️ VPS & Discord bot monitoring system

A clean and powerful **VPS & Discord bot monitoring system** built for VPS / Docker environments.  
This bot watches all your running Discord bot containers, shows their live status in a dashboard, and alerts you if any bot goes offline or comes back online.

Designed for developers managing multiple Docker-based Discord bots.

---

## ✨ Features

- 📊 **Live Bot Monitoring Dashboard**
  - Automatically lists detected bot containers
  - Clean status embed in Discord
  - Auto-refreshes every few seconds

- 🖥️ **Docker Container Monitoring**
  - Detects bot containers automatically
  - Tracks:
    - Online / Offline status
    - Docker uptime
    - CPU usage
    - RAM usage

- 🔔 **Offline / Online Alerts**
  - Sends instant alert when a bot goes offline
  - Sends recovery alert when a bot comes back online
  - Optional role ping support

- 🎛️ **Discord Control Panel**
  - Refresh dashboard manually
  - Restart individual bot containers
  - Restart all detected bot containers

- 🤖 **Smart Bot Detection**
  - Automatically detects containers with names like:
    - `-bot`
    - `_bot`
    - `bot`

---

## 🧠 Use Case

Perfect for:

- FiveM server developers
- VPS Discord bot hosting
- OP-FW infrastructure monitoring
- Developers running multiple Docker bots
- PDM / sales / monitoring bot management

---

## ⚙️ Requirements

- Python **3.10+**
- Docker installed and running
- A VPS / Linux server
- Discord Bot Token
- Access to your Docker containers

---

## 📦 Installation

```bash
git clone https://github.com/master9734/opfw-pdm-overwatcher-bot.git
```
```bash
- cd opfw-pdm-overwatcher-bot
```
```bash
- pip install -r requirements.txt
```

## 📚 Dependencies

This project uses:

- discord.py==2.4.0
- docker==7.1.0
- python-dotenv==1.0.1
- pytz==2025.1


# 🔐 Environment Setup

Create a .env file in the project folder:
```env
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_discord_server_id
CHANNEL_ID=dashboard_channel_id
ALERT_CHANNEL_ID=alert_channel_id
OFFLINE_ROLE_ID=role_id_for_alert_ping
REFRESH_SECONDS=30
```


▶️ Run the Bot
```bash
python bot.py
```

# 🐳 Docker / Compose (Optional)

If you want to run it inside Docker, use your own Dockerfile / docker-compose.yml.

Example:
```yaml
version: '3.8'

services:
  pdm-overwatcher:
    build: .
    container_name: pdm-overwatcher
    restart: always
    env_file:
      - .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```
# ⚠️ Important:
- To monitor and restart Docker containers, this bot must have access to:
```bash
/var/run/docker.sock
```
## 🧩 Main Functions
 ### 📡 Dashboard

Shows all detected bot containers in a Discord embed with:

- Status
- Docker uptime
- CPU usage
- RAM usage

### 🔄 Refresh Button

 Updates the dashboard instantly.

### ♻️ Restart Dropdown

 Lets you restart a selected bot container directly from Discord.

### 🚨 Restart All

 Restarts all detected bot containers with one click.

### 🔔 Alert System

Sends a message when a bot:

- goes OFFLINE
- comes back ONLINE

# 🛠️ Detection Rules

This bot automatically monitors containers whose names contain or end with:

- -bot
- _bot
- bot

That means if you add a new Docker bot container later, it can appear automatically without manually editing the code.

# 📌 Notes
- This bot is built for monitoring + container control
- It does not modify your database
- It only interacts with your Docker containers
- Best used on the same VPS where your bots are hosted


# 🧑‍💻 Author

Developed by MasteR

# 📜 License

This project is licensed under the MIT License.