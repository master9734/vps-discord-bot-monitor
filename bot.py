import os
import json
import asyncio
import docker
import discord
import pytz
import shutil
import platform
from datetime import datetime, timezone
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", CHANNEL_ID))
OFFLINE_ROLE_ID = int(os.getenv("OFFLINE_ROLE_ID", "0"))
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "30"))

IGNORE_CONTAINERS = {
    x.strip().lower()
    for x in os.getenv("IGNORE_CONTAINER_NAME", "").split(",")
    if x.strip()
}

STATE_FILE = "dashboard_state.json"

BST = pytz.timezone("Asia/Dhaka")
IST = pytz.timezone("Asia/Kolkata")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

docker_client = docker.from_env()

dashboard_message_id = None
last_status_map = {}
stats_cache = {}   # {container_name: stats_dict}


# ----------------------------
# Utility
# ----------------------------
def now_bst_ist():
    now_bst = datetime.now(BST).strftime("%d %b %Y • %I:%M %p BST")
    now_ist = datetime.now(IST).strftime("%I:%M %p IST")
    return f"{now_bst} | {now_ist}"


def is_bot_container(name: str):
    name = name.lower().replace("/", "").strip()

    if name in IGNORE_CONTAINERS:
        return False

    return (
        name.endswith("-bot")
        or name.endswith("_bot")
        or name == "bot"
        or "-bot-" in name
        or "_bot_" in name
        or "bot-" in name
        or name == "bot-monitor"
    )


def clean_container_name(name: str):
    return name.replace("/", "").strip()


def shorten_name(name: str):
    raw = clean_container_name(name)

    known_prefixes = [
        "bot-monitor",
        "arena-bot",
        "gbrp-status-bot",
        "pdm-overwatcher-bot",
        "money-logs-bot",
    ]

    for prefix in known_prefixes:
        if raw.startswith(prefix):
            return prefix

    return raw


def save_state():
    global dashboard_message_id
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"dashboard_message_id": dashboard_message_id}, f)
    except Exception as e:
        print(f"Failed to save state: {e}")


def load_state():
    global dashboard_message_id
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                dashboard_message_id = data.get("dashboard_message_id")
    except Exception as e:
        print(f"Failed to load state: {e}")


def format_duration(seconds: int):
    if seconds < 0:
        seconds = 0

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")

    return " ".join(parts)


def get_all_relevant_containers():
    try:
        containers = docker_client.containers.list(all=True)
        bots = [c for c in containers if is_bot_container(c.name)]
        return sorted(bots, key=lambda x: x.name.lower())
    except Exception as e:
        print(f"Error listing containers: {e}")
        return []


def get_fast_container_status(container):
    """
    FAST + safe container info.
    No blocking Docker stats here.
    """
    try:
        container.reload()
        state = container.attrs.get("State", {})
        status = state.get("Status", "unknown")
        started_at = state.get("StartedAt", "")
        finished_at = state.get("FinishedAt", "")

        docker_uptime = "Unknown"

        try:
            now_utc = datetime.now(timezone.utc)

            if status == "running" and started_at and started_at != "0001-01-01T00:00:00Z":
                started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                delta = now_utc - started_dt
                docker_uptime = f"Up {format_duration(int(delta.total_seconds()))}"

            elif status in ["exited", "dead", "created", "paused", "restarting"]:
                if finished_at and finished_at != "0001-01-01T00:00:00Z":
                    finished_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                    delta = now_utc - finished_dt
                    docker_uptime = f"{status.capitalize()} {format_duration(int(delta.total_seconds()))} ago"
                else:
                    docker_uptime = status.capitalize()
            else:
                docker_uptime = status.capitalize()

        except Exception:
            docker_uptime = status.capitalize()

        return {
            "status": status,
            "docker_uptime": docker_uptime,
        }

    except Exception:
        return {
            "status": "unknown",
            "docker_uptime": "Unknown",
        }


def fetch_container_stats_blocking(container):
    """
    Runs in background thread only.
    """
    try:
        container.reload()
        state = container.attrs.get("State", {})
        status = state.get("Status", "unknown")

        cpu_percent = 0.0
        mem_usage_mib = 0.0
        mem_limit_gib = 0.0

        if status == "running":
            try:
                stats = container.stats(stream=False)

                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
                )
                num_cpus = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))

                if system_delta > 0 and cpu_delta > 0:
                    cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0

                mem_usage = stats["memory_stats"].get("usage", 0)
                mem_limit = stats["memory_stats"].get("limit", 1)

                mem_usage_mib = mem_usage / (1024 * 1024)
                mem_limit_gib = mem_limit / (1024 * 1024 * 1024)
            except Exception:
                pass

        return {
            "cpu_percent": round(cpu_percent, 2),
            "mem_usage_mib": round(mem_usage_mib, 2),
            "mem_limit_gib": round(mem_limit_gib, 2),
        }

    except Exception:
        return {
            "cpu_percent": 0.0,
            "mem_usage_mib": 0.0,
            "mem_limit_gib": 0.0,
        }


# ----------------------------
# VPS Stats
# ----------------------------
def get_system_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        return format_duration(int(uptime_seconds))
    except Exception:
        return "Unknown"


def get_host_memory():
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.replace(":", "").split()
                meminfo[parts[0]] = int(parts[1])

        total_kb = meminfo.get("MemTotal", 0)
        available_kb = meminfo.get("MemAvailable", 0)
        used_kb = total_kb - available_kb

        total_gb = total_kb / 1024 / 1024
        used_gb = used_kb / 1024 / 1024
        percent = (used_kb / total_kb * 100) if total_kb > 0 else 0

        return round(used_gb, 2), round(total_gb, 2), round(percent, 1)
    except Exception:
        return 0.0, 0.0, 0.0


def get_disk_usage():
    try:
        total, used, free = shutil.disk_usage("/")
        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        percent = (used / total * 100) if total > 0 else 0
        return round(used_gb, 2), round(total_gb, 2), round(percent, 1)
    except Exception:
        return 0.0, 0.0, 0.0


def get_vps_stats():
    used_ram, total_ram, ram_percent = get_host_memory()
    used_disk, total_disk, disk_percent = get_disk_usage()
    uptime = get_system_uptime()

    try:
        total_containers = len(docker_client.containers.list(all=True))
        running_containers = len(docker_client.containers.list())
    except Exception:
        total_containers = 0
        running_containers = 0

    # VPS CPU = sum of bot/container cached CPU values
    total_cpu = 0.0
    for data in stats_cache.values():
        total_cpu += data.get("cpu_percent", 0.0)

    return {
        "cpu_percent": round(total_cpu, 2),
        "used_ram": used_ram,
        "total_ram": total_ram,
        "ram_percent": ram_percent,
        "used_disk": used_disk,
        "total_disk": total_disk,
        "disk_percent": disk_percent,
        "uptime": uptime,
        "running_containers": running_containers,
        "total_containers": total_containers,
        "hostname": platform.node() or "VPS",
    }


# ----------------------------
# Embed
# ----------------------------
def build_dashboard_embed():
    vps = get_vps_stats()

    embed = discord.Embed(
        title="🤖 VPS Bot Monitor",
        description="Live status of VPS + all detected bot containers.",
        color=discord.Color.blurple()
    )

    # VPS monitor always at top
    embed.add_field(
        name=f"🖥️ VPS Monitor • {vps['hostname']}",
        value=(
            f"**CPU:** `{vps['cpu_percent']}%`\n"
            f"**RAM:** `{vps['used_ram']}GB / {vps['total_ram']}GB ({vps['ram_percent']}%)`\n"
            f"**Disk:** `{vps['used_disk']}GB / {vps['total_disk']}GB ({vps['disk_percent']}%)`\n"
            f"**Uptime:** `{vps['uptime']}`\n"
            f"**Docker:** `{vps['running_containers']}/{vps['total_containers']} running`"
        ),
        inline=False
    )

    containers = get_all_relevant_containers()

    if not containers:
        embed.add_field(
            name="No bot containers found",
            value="No Docker bot containers were detected.",
            inline=False
        )
    else:
        for container in containers:
            fast = get_fast_container_status(container)
            cached = stats_cache.get(container.name, {
                "cpu_percent": 0.0,
                "mem_usage_mib": 0.0,
                "mem_limit_gib": 0.0,
            })

            name = shorten_name(container.name)

            running = fast["status"] == "running"
            status_icon = "🟢" if running else "🔴"
            status_text = "Online" if running else "Offline"

            value = (
                f"**Status:** {status_icon} {status_text}\n"
                f"**Docker:** `{fast['docker_uptime']}`\n"
                f"**CPU:** `{cached['cpu_percent']}%`\n"
                f"**RAM:** `{cached['mem_usage_mib']}MiB / {cached['mem_limit_gib']}GiB`"
            )

            embed.add_field(
                name=f"📦 {name}",
                value=value,
                inline=False
            )

    embed.set_footer(text=f"Last checked: {now_bst_ist()}")
    return embed


# ----------------------------
# Alerts
# ----------------------------
async def send_alerts_if_needed():
    global last_status_map

    alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not alert_channel:
        return

    containers = get_all_relevant_containers()
    current_status_map = {}

    for container in containers:
        fast = get_fast_container_status(container)
        name = shorten_name(container.name)
        current_status = "online" if fast["status"] == "running" else "offline"
        current_status_map[name] = current_status

        previous_status = last_status_map.get(name)

        if previous_status is None:
            continue

        if previous_status != current_status:
            role_ping = f"<@&{OFFLINE_ROLE_ID}> " if OFFLINE_ROLE_ID else ""

            if current_status == "offline":
                await alert_channel.send(
                    f"{role_ping}🚨 **{name}** is now **OFFLINE**.\nChecked: `{now_bst_ist()}`"
                )
            elif current_status == "online":
                await alert_channel.send(
                    f"{role_ping}✅ **{name}** is back **ONLINE**.\nChecked: `{now_bst_ist()}`"
                )

    last_status_map = current_status_map


# ----------------------------
# Background stats updater
# ----------------------------
async def refresh_stats_cache():
    global stats_cache

    containers = get_all_relevant_containers()
    new_cache = {}

    async def fetch_one(container):
        data = await asyncio.to_thread(fetch_container_stats_blocking, container)
        return container.name, data

    tasks_list = [fetch_one(c) for c in containers]

    if tasks_list:
        results = await asyncio.gather(*tasks_list, return_exceptions=True)
        for item in results:
            if isinstance(item, Exception):
                continue
            name, data = item
            new_cache[name] = data

    stats_cache = new_cache


# ----------------------------
# View
# ----------------------------
class RestartDropdown(discord.ui.Select):
    def __init__(self):
        containers = get_all_relevant_containers()

        options = []
        for c in containers[:25]:
            label = shorten_name(c.name)[:100]
            options.append(discord.SelectOption(label=label, value=c.name))

        if not options:
            options = [discord.SelectOption(label="No bot containers found", value="none")]

        super().__init__(
            placeholder="Select a bot container to restart...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="restart_dropdown"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if self.values[0] == "none":
                await interaction.response.send_message("No bot containers found.", ephemeral=True)
                return

            container_name = self.values[0]
            display_name = shorten_name(container_name)

            await interaction.response.defer(ephemeral=True)

            container = docker_client.containers.get(container_name)
            await asyncio.to_thread(container.restart)

            await asyncio.sleep(3)
            await refresh_stats_cache()
            await update_dashboard_message()

            await interaction.followup.send(
                f"✅ Restarted **{display_name}** successfully.",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.followup.send(
                    f"❌ Failed to restart container.\n```{e}```",
                    ephemeral=True
                )
            except Exception:
                pass


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RestartDropdown())

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, custom_id="refresh_dashboard")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            await refresh_stats_cache()
            await update_dashboard_message()
            await interaction.followup.send("🔄 Dashboard refreshed.", ephemeral=True)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Refresh failed.\n```{e}```", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Restart All", style=discord.ButtonStyle.danger, custom_id="restart_all_bots")
    async def restart_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            containers = get_all_relevant_containers()

            if not containers:
                await interaction.response.send_message("No bot containers found.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            for container in containers:
                try:
                    await asyncio.to_thread(container.restart)
                except Exception:
                    pass

            await asyncio.sleep(5)
            await refresh_stats_cache()
            await update_dashboard_message()

            await interaction.followup.send(
                "✅ All detected bot containers have been restarted.",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Restart all failed.\n```{e}```", ephemeral=True)
            except Exception:
                pass


# ----------------------------
# Dashboard handling
# ----------------------------
def build_dashboard_view():
    return DashboardView()


async def find_existing_dashboard_message(channel):
    async for msg in channel.history(limit=50):
        if msg.author.id == bot.user.id and msg.embeds:
            embed = msg.embeds[0]
            if embed.title == "🤖 VPS Bot Monitor":
                return msg
    return None


async def update_dashboard_message():
    global dashboard_message_id

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    embed = build_dashboard_embed()
    view = build_dashboard_view()

    if dashboard_message_id:
        try:
            msg = await channel.fetch_message(dashboard_message_id)
            await msg.edit(embed=embed, view=view)
            return
        except discord.NotFound:
            dashboard_message_id = None
            save_state()
        except Exception as e:
            print(f"Edit known dashboard failed: {e}")

    try:
        existing = await find_existing_dashboard_message(channel)
        if existing:
            dashboard_message_id = existing.id
            save_state()
            await existing.edit(embed=embed, view=view)
            return
    except Exception as e:
        print(f"Existing dashboard lookup failed: {e}")

    try:
        msg = await channel.send(embed=embed, view=view)
        dashboard_message_id = msg.id
        save_state()
    except Exception as e:
        print(f"Failed to create dashboard: {e}")


# ----------------------------
# Tasks
# ----------------------------
@tasks.loop(seconds=REFRESH_SECONDS)
async def auto_refresh_dashboard():
    await refresh_stats_cache()
    await update_dashboard_message()
    await send_alerts_if_needed()


# ----------------------------
# Events
# ----------------------------
@bot.event
async def on_ready():
    global last_status_map

    print(f"Logged in as {bot.user}")
    load_state()

    bot.add_view(DashboardView())

    containers = get_all_relevant_containers()
    for c in containers:
        fast = get_fast_container_status(c)
        name = shorten_name(c.name)
        last_status_map[name] = "online" if fast["status"] == "running" else "offline"

    await refresh_stats_cache()
    await update_dashboard_message()

    if not auto_refresh_dashboard.is_running():
        auto_refresh_dashboard.start()


bot.run(DISCORD_TOKEN)