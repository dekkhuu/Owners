import os
import json
import asyncio
import datetime
import secrets
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
import discord
from discord.ext import commands, tasks

ALLOWED_GUILD_ID = 1503922700408586240
VERIFY_ROLE_ID = 1515041455805304953
TOKEN = os.getenv("DISCORD_TOKEN")

# Đường dẫn Discord OAuth2 Xác minh
DISCORD_OAUTH_URL = "https://discord.com/oauth2/authorize?client_id=1551121062295502848&response_type=code&redirect_uri=https%3A%2F%2Fbirthdaytime.shopaccvt.site%2Foauth_callback.php&scope=identify"
VERIFY_API_URL = os.getenv(
    "VERIFY_API_URL",
    "https://birthdaytime.shopaccvt.site/verification_api.php"
)
VERIFY_API_SECRET = os.getenv("VERIFY_API_SECRET") or TOKEN

if not TOKEN:
    raise RuntimeError("Thiếu biến môi trường DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

GUILD = discord.Object(id=ALLOWED_GUILD_ID)

# =========================
# AUTO MODERATION
# =========================
AUTO_MUTE_SECONDS = 24 * 60 * 60

SPAM_MESSAGE_LIMIT = 3
SPAM_WINDOW_SECONDS = 2

BLOCKED_DOMAINS = {
    "grabify.link",
    "iplogger.org",
    "iplogger.com",
    "2no.co",
    "yip.su",
    "tinyurl.com",
    "bit.ly",
}

NSFW_KEYWORDS = {
    "porn", "xxx", "nsfw", "sex", "nude", "nudity",
    "hentai", "pornhub", "xvideos", "xnxx",
    "18+", "18plus", "adult", "onlyfans",
}

SCAM_FILE_KEYWORDS = {
    "freefire hack", "free fire hack", "roblox hack",
    "roblox bypass", "freefire bypass", "free fire bypass",
    "tool bypass email", "bypass email", "email bypass",
    "stealer", "token grabber", "cookie grabber", "keygen",
}

GAMBLING_KEYWORDS = {
    "tài xỉu", "tai xiu", "taixiu", "casino", "bet",
    "cá cược", "ca cuoc", "soi cầu", "soi cau",
    "nổ hũ", "no hu", "slot", "kèo cược", "keo cuoc",
}

MONEY_LINK_KEYWORDS = {
    "kiếm tiền", "kiem tien", "make money", "earn money",
    "nhận tiền", "nhan tien", "hoa hồng", "hoa hong",
    "referral", "cash", "coin",
}

DRUG_KEYWORDS = {
    "ma túy", "ma tuy", "cần sa", "can sa", "cocaine",
    "heroin", "meth", "amphetamine", "mdma",
    "thuốc lắc", "thuoc lac",
}

GORE_KEYWORDS = {
    "gore", "bloody", "máu me", "mau me",
    "chém giết", "chem giet", "thảm sát", "tham sat",
}

SUSPICIOUS_FILE_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".scr", ".msi", ".com", ".vbs",
    ".js", ".jar", ".ps1", ".hta", ".apk", ".dll", ".vn",
}

bot.spam_tracker = {}
bot.muted_users = set()


def normalize_domain(url: str) -> str:
    url = url.lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("/", 1)[0].split(":", 1)[0]


def contains_blocked_link(content: str) -> tuple[bool, str]:
    urls = re.findall(r"(?:https?://|www\.)[^\s<>()]+", content.lower())
    lower = content.lower()

    for raw_url in urls:
        domain = normalize_domain(raw_url)

        if domain == "blazemarket.online" or domain.endswith(".blazemarket.online"):
            continue

        if domain in BLOCKED_DOMAINS:
            return True, "Gửi link lạ hoặc link có dấu hiệu scam."

        if any(k in lower for k in GAMBLING_KEYWORDS):
            return True, "Gửi/quảng bá link tài xỉu hoặc cờ bạc không được phép."

        if any(k in lower for k in MONEY_LINK_KEYWORDS):
            return True, "Gửi link kiếm tiền không được phép. Ngoại lệ duy nhất là blazemarket.online."

        return True, "Gửi website/link lạ không được phép."

    if any(k in lower for k in GAMBLING_KEYWORDS):
        return True, "Quảng bá tài xỉu/cờ bạc không được phép."

    if any(k in lower for k in MONEY_LINK_KEYWORDS):
        return True, "Quảng bá/link kiếm tiền không được phép. Ngoại lệ duy nhất là blazemarket.online."

    return False, ""


def contains_rule_violation_text(content: str) -> tuple[bool, str]:
    lower = content.lower()

    if any(k in lower for k in SCAM_FILE_KEYWORDS):
        return True, "Gửi file/tool scam, hack hoặc bypass không được phép."

    if any(k in lower for k in NSFW_KEYWORDS):
        return True, "Gửi/quảng bá nội dung 18+ không được phép."

    if any(k in lower for k in GORE_KEYWORDS):
        return True, "Gửi nội dung máu me không được phép."

    if any(k in lower for k in DRUG_KEYWORDS):
        return True, "Tổ chức/quảng bá việc sử dụng chất kích thích không được phép."

    return False, ""


def contains_nsfw_attachment(message: discord.Message) -> tuple[bool, str]:
    suspicious_keywords = NSFW_KEYWORDS | SCAM_FILE_KEYWORDS | GORE_KEYWORDS

    for attachment in message.attachments:
        name = (attachment.filename or "").lower()
        extension = Path(name).suffix

        if any(k in name for k in suspicious_keywords):
            if any(k in name for k in NSFW_KEYWORDS):
                return True, "Gửi ảnh/video có dấu hiệu nội dung 18+."
            if any(k in name for k in GORE_KEYWORDS):
                return True, "Gửi ảnh/video có dấu hiệu máu me."
            return True, "Gửi file/tool scam hoặc bypass không được phép."

        if extension in SUSPICIOUS_FILE_EXTENSIONS:
            return True, "Gửi file/tool không được phép."

    return False, ""


def is_spam(message: discord.Message) -> bool:
    now = time.monotonic()
    user_id = message.author.id
    entries = bot.spam_tracker.setdefault(user_id, [])

    entries[:] = [t for t in entries if now - t <= SPAM_WINDOW_SECONDS]
    entries.append(now)

    return len(entries) >= SPAM_MESSAGE_LIMIT


async def notify_and_mute(member: discord.Member, reason: str):
    guild = member.guild
    until = discord.utils.utcnow() + datetime.timedelta(seconds=AUTO_MUTE_SECONDS)

    try:
        await member.timeout(until, reason=f"AutoMod: {reason}")
    except (discord.Forbidden, discord.HTTPException):
        return False

    bot.muted_users.add(member.id)

    embed = discord.Embed(
        title="Bạn đã bị mute",
        description=(
            "**Bạn đã bị cấm chat trong 24h, vì lý do:**\n"
            f"> {reason}"
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Thời gian", value="24 giờ", inline=True)
    embed.add_field(name="Server", value=guild.name, inline=True)
    embed.set_footer(text="BirthdayTime AutoMod")

    try:
        await member.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

    bot.spam_tracker.pop(member.id, None)
    return True


def _verification_api_request(method: str = "GET", user_id: int | None = None):
    if not VERIFY_API_SECRET:
        raise RuntimeError("VERIFY_API_SECRET is not configured for the bot")

    query = {"action": "pending"}
    url = VERIFY_API_URL
    if method == "GET" and user_id is not None:
        query["user_id"] = str(user_id)
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{urllib.parse.urlencode(query)}"
    payload = None
    if method == "POST":
        payload = json.dumps({
            "action": "acknowledge",
            "user_id": str(user_id),
        }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "X-Verify-Secret": VERIFY_API_SECRET,
            "Content-Type": "application/json",
        },
        method=method,
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _publish_presence_batch(presences: list[dict]):
    if not VERIFY_API_SECRET:
        raise RuntimeError("VERIFY_API_SECRET is not configured for the bot")

    payload = json.dumps({
        "action": "presence_batch",
        "presences": presences,
    }).encode("utf-8")
    request = urllib.request.Request(
        VERIFY_API_URL,
        data=payload,
        headers={
            "X-Verify-Secret": VERIFY_API_SECRET,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def presence_payload(member: discord.Member) -> dict:
    activities = []
    for activity in member.activities[:10]:
        name = getattr(activity, "name", None)
        if not name:
            continue
        activities.append({
            "name": str(name),
            "details": str(getattr(activity, "details", "") or ""),
            "state": str(getattr(activity, "state", "") or ""),
            "type": int(activity.type.value),
        })
    return {
        "user_id": str(member.id),
        "status": member.status.name,
        "activities": activities,
    }


async def publish_guild_presences(guild: discord.Guild):
    if not VERIFY_API_SECRET:
        return
    members = list(guild.members)
    for start in range(0, len(members), 500):
        payload = [presence_payload(member) for member in members[start:start + 500]]
        await asyncio.to_thread(_publish_presence_batch, payload)


@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    if after.guild.id != ALLOWED_GUILD_ID or not VERIFY_API_SECRET:
        return
    try:
        await asyncio.to_thread(_publish_presence_batch, [presence_payload(after)])
    except Exception as exc:
        print(f"Could not publish presence for {after.id}: {type(exc).__name__}: {exc}")


async def approved_verification_ids(user_id: int | None = None) -> set[int]:
    result = await asyncio.to_thread(_verification_api_request, "GET", user_id)
    ids = result.get("user_ids")
    if not isinstance(ids, list):
        raise RuntimeError("Verification API returned an invalid user_ids list")
    try:
        return {int(value) for value in ids}
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Verification API returned an invalid Discord user ID") from exc


async def process_approved_verification(user_id: int) -> bool:
    guild = bot.get_guild(ALLOWED_GUILD_ID)
    if guild is None:
        raise RuntimeError("Verification guild is not available in the bot cache")

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return False

    role = guild.get_role(VERIFY_ROLE_ID)
    if role is None:
        raise RuntimeError("Verification role was not found in the guild")

    if role not in member.roles:
        await member.add_roles(role, reason="Website Discord OAuth verification")

    await asyncio.to_thread(_verification_api_request, "POST", user_id)
    print(f"Verification role granted to Discord user {user_id}.")
    return True


@tasks.loop(seconds=30)
async def verification_queue_worker():
    try:
        user_ids = await approved_verification_ids()
    except Exception as exc:
        print(f"Verification queue API error: {type(exc).__name__}: {exc}")
        return

    for user_id in user_ids:
        try:
            await process_approved_verification(user_id)
        except Exception as exc:
            print(f"Could not process verification for {user_id}: {type(exc).__name__}: {exc}")


@verification_queue_worker.before_loop
async def before_verification_queue_worker():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    for guild in bot.guilds:
        if guild.id != ALLOWED_GUILD_ID:
            try:
                await guild.leave()
                print(f"Đã rời server không được phép: {guild.name} ({guild.id})")
            except Exception as e:
                print(f"Lỗi khi rời server: {e}")

    try:
        synced = await bot.tree.sync(guild=GUILD)
        print(f"Đã sync {len(synced)} slash commands.")
    except Exception as e:
        print(f"Lỗi sync command: {e}")

    if not stats_updater.is_running():
        stats_updater.start()

    if not rule_scanner.is_running():
        rule_scanner.start()

    if VERIFY_API_SECRET:
        if not verification_queue_worker.is_running():
            verification_queue_worker.start()
        guild = bot.get_guild(ALLOWED_GUILD_ID)
        if guild is not None:
            try:
                await publish_guild_presences(guild)
            except Exception as exc:
                print(f"Could not sync initial presence cache: {type(exc).__name__}: {exc}")
    elif not VERIFY_API_SECRET:
        print("VERIFY_API_SECRET is missing; automatic website verification is disabled.")

    print("=" * 40)
    print(f"Bot: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print(f"Server được phép: {ALLOWED_GUILD_ID}")
    print("=" * 40)


@bot.event
async def on_guild_join(guild):
    if guild.id != ALLOWED_GUILD_ID:
        try:
            await guild.leave()
            print(f"Đã rời server không được phép: {guild.name} ({guild.id})")
        except Exception as e:
            print(f"Lỗi khi rời server: {e}")


@bot.tree.command(
    name="ping",
    description="Kiểm tra độ trễ của bot",
    guild=GUILD
)
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)

    embed = discord.Embed(
        title="Owner",
        description=f"**Pong**\nĐộ trễ: `{latency}ms`",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="help",
    description="Xem danh sách lệnh",
    guild=GUILD
)
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Owner Help",
        description="Danh sách các lệnh hiện có của Owner.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Thông tin",
        value=(
            "`/ping` — Kiểm tra độ trễ\n"
            "`/help` — Xem danh sách lệnh"
        ),
        inline=False
    )

    embed.add_field(
        name="Quản lý",
        value=(
            "`!ban @user [lý do]`\n"
            "`!unban <user_id>`\n"
            "`!mute @user [phút] [lý do]`\n"
            "`!unmute @user`\n"
            "`!afk [lý do]`"
        ),
        inline=False
    )

    embed.add_field(
        name="Thiết lập",
        value=(
            "`/start` — Tạo các kênh thống kê server\n"
            "`/birthday` — Thiết lập sinh nhật\n"
            "`/boost` — Thiết lập thông báo Boost\n"
            "`/verify` — Gửi bảng xác minh OAuth2"
        ),
        inline=False
    )

    embed.set_footer(text="by ph.huyy.")
    await interaction.response.send_message(embed=embed)


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    await member.ban(reason=reason)
    embed = discord.Embed(
        description=f"{member.mention} đã bị đá khỏi Guild",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, delete_after=30)


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        embed = discord.Embed(
            description=f"{user.mention} đã được sự khoan hồng để trở lại Guild",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed, delete_after=30)
    except discord.NotFound:
        await ctx.send("❌ Không tìm thấy người dùng hoặc người dùng chưa bị ban.", delete_after=30)
    except discord.HTTPException:
        await ctx.send("❌ Không thể unban người dùng này.", delete_after=30)


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason: str = "Không có lý do"):
    if minutes < 1:
        await ctx.send("❌ Số phút phải lớn hơn 0.", delete_after=30)
        return

    duration = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(
        description=f"{member.mention} đã bị khoá mõm trong {minutes} phút",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, delete_after=30)


@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    embed = discord.Embed(
        description=f"{member.mention} đã mở khóa mõm",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, delete_after=30)


@bot.command(name="av")
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author

    embed = discord.Embed(
        title=f"Avatar của {member.display_name}",
        color=discord.Color.blurple()
    )
    embed.set_image(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")

    await ctx.send(embed=embed)


@bot.command(name="afk")
async def afk(ctx, *, reason: str = "AFK"):
    target = ctx.author
    reason = reason.strip() or "AFK"

    if not hasattr(bot, "afk_users"):
        bot.afk_users = {}

    bot.afk_users[target.id] = reason

    embed = discord.Embed(
        description=f"{target.mention} đang AFK: {reason}",
        color=discord.Color.blurple()
    )
    await ctx.send(
        embed=embed,
        delete_after=30,
        allowed_mentions=discord.AllowedMentions(users=True)
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is not None and message.guild.id == ALLOWED_GUILD_ID:
        if isinstance(message.author, discord.Member) and message.author.is_timed_out():
            return

        violation_reason = None

        if is_spam(message):
            violation_reason = (
                f"Gửi quá nhiều tin nhắn trong thời gian ngắn "
                f"({SPAM_MESSAGE_LIMIT} tin / {SPAM_WINDOW_SECONDS} giây)."
            )

        if violation_reason is None:
            blocked, reason = contains_blocked_link(message.content)
            if blocked:
                violation_reason = reason

        if violation_reason is None:
            blocked, reason = contains_rule_violation_text(message.content)
            if blocked:
                violation_reason = reason

        if violation_reason is None:
            blocked, reason = contains_nsfw_attachment(message)
            if blocked:
                violation_reason = reason

        if violation_reason:
            try:
                await message.delete(reason=f"AutoMod: {violation_reason}")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

            await notify_and_mute(message.author, violation_reason)
            return

    if hasattr(bot, "afk_users") and message.author.id in bot.afk_users:
        del bot.afk_users[message.author.id]

        embed = discord.Embed(
            description=f"{message.author.mention} đã trở lại",
            color=discord.Color.green()
        )
        try:
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True),
                delete_after=30
            )
        except discord.HTTPException:
            pass

    if hasattr(bot, "afk_users") and message.mentions:
        notified_users = set()

        for mentioned_user in message.mentions:
            if mentioned_user.id in notified_users:
                continue

            if mentioned_user.id in bot.afk_users:
                reason = bot.afk_users[mentioned_user.id]

                embed = discord.Embed(
                    description=(
                        f"{mentioned_user.mention} đang ở chế độ AFK"
                        f"\n**Lý do:** {reason}"
                        f"\n**Thời lượng:** 30 giây"
                    ),
                    color=discord.Color.blurple()
                )
                embed.set_footer(text="by ph.huyy.")

                try:
                    await message.channel.send(
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(users=True),
                        delete_after=30
                    )
                except discord.HTTPException:
                    pass

                notified_users.add(mentioned_user.id)

    await bot.process_commands(message)


RULE_SCAN_INTERVAL = 5
RULE_SCAN_MESSAGE_LIMIT = 10
bot.rule_scan_seen = set()


async def scan_message_for_rules(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None or message.guild.id != ALLOWED_GUILD_ID:
        return

    if not isinstance(message.author, discord.Member):
        return

    if message.author.is_timed_out():
        return

    violation_reason = None

    if violation_reason is None:
        blocked, reason = contains_blocked_link(message.content)
        if blocked:
            violation_reason = reason

    if violation_reason is None:
        blocked, reason = contains_rule_violation_text(message.content)
        if blocked:
            violation_reason = reason

    if violation_reason is None:
        blocked, reason = contains_nsfw_attachment(message)
        if blocked:
            violation_reason = reason

    if violation_reason:
        try:
            await message.delete(reason=f"AutoMod: {violation_reason}")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        await notify_and_mute(message.author, violation_reason)


@tasks.loop(seconds=RULE_SCAN_INTERVAL)
async def rule_scanner():
    for guild in bot.guilds:
        if guild.id != ALLOWED_GUILD_ID:
            continue

        for channel in guild.text_channels:
            try:
                messages = [m async for m in channel.history(
                    limit=RULE_SCAN_MESSAGE_LIMIT
                )]
            except (discord.Forbidden, discord.HTTPException):
                continue

            for message in reversed(messages):
                if message.id in bot.rule_scan_seen:
                    continue

                bot.rule_scan_seen.add(message.id)
                await scan_message_for_rules(message)

    if len(bot.rule_scan_seen) > 10000:
        bot.rule_scan_seen = set(list(bot.rule_scan_seen)[-5000:])


@rule_scanner.before_loop
async def before_rule_scanner():
    await bot.wait_until_ready()


bot.stats_channels = {}

_DIGIT_MAP = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")

def format_stats_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


async def update_server_stats(guild: discord.Guild):
    channel_map = bot.stats_channels.get(guild.id, {})

    if not channel_map:
        base_names = [
            "╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥",
            "⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫",
            "⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭",
            "⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞",
            "╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭",
        ]
        for base_name in base_names:
            channel = next(
                (
                    vc for vc in guild.voice_channels
                    if vc.name == base_name
                    or vc.name.startswith(base_name + " ﹕")
                ),
                None
            )
            if channel is not None:
                channel_map[base_name] = channel.id

        if channel_map:
            bot.stats_channels[guild.id] = channel_map

    if not channel_map:
        return

    members = guild.members
    total = len(members)
    bots = sum(1 for member in members if member.bot)
    online = sum(1 for member in members if member.status != discord.Status.offline)
    humans = total - bots
    boost_count = guild.premium_subscription_count

    values = {
        "╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥": total,
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫": humans,
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭": bots,
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞": online,
        "╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭": boost_count,
    }

    for base_name, channel_id in channel_map.items():
        channel = guild.get_channel(channel_id)
        if channel is None:
            continue

        new_name = f"{base_name} ﹕{format_stats_digits(str(values[base_name]))}"
        if channel.name != new_name:
            try:
                await channel.edit(name=new_name, reason="Update server statistics")
            except discord.HTTPException:
                pass


@tasks.loop(seconds=60)
async def stats_updater():
    for guild in bot.guilds:
        if guild.id == ALLOWED_GUILD_ID:
            await update_server_stats(guild)


@stats_updater.before_loop
async def before_stats_updater():
    await bot.wait_until_ready()


@bot.tree.command(
    name="start",
    description="Tạo các kênh thống kê server",
    guild=GUILD
)
async def start(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Bạn cần quyền Administrator.",
            ephemeral=True
        )
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "❌ Lệnh này chỉ dùng trong server.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    channel_names = [
        "╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞",
        "╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭",
    ]

    created = []

    for name in channel_names:
        channel = next(
            (
                vc for vc in guild.voice_channels
                if vc.name == name or vc.name.startswith(name + " ﹕")
            ),
            None
        )
        if channel is None:
            channel = await guild.create_voice_channel(
                name=name,
                reason=f"Setup server stats by {interaction.user}"
            )

        await channel.set_permissions(
            guild.default_role,
            connect=False,
            reason="Lock server statistics voice channel"
        )
        created.append(channel)

    bot.stats_channels[guild.id] = {channel_names[i]: created[i].id for i in range(5)}

    await update_server_stats(guild)

    if not stats_updater.is_running():
        stats_updater.start()

    await interaction.followup.send(
        "✅ Đã tạo/kiểm tra 5 kênh thống kê, khóa quyền vào kênh và bật cập nhật mỗi 1 phút.",
        ephemeral=True
    )


BOOST_CONFIG_FILE = "boost_config.json"

def load_boost_config():
    try:
        with open(BOOST_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_boost_config(data):
    with open(BOOST_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@bot.tree.command(
    name="boost",
    description="Chọn kênh và nội dung thông báo Boost",
    guild=GUILD
)
@discord.app_commands.describe(
    channel="Kênh gửi thông báo Boost",
    content="Nội dung thông báo; dùng {user} để tag người boost"
)
async def boost(interaction: discord.Interaction, channel: discord.TextChannel, content: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Bạn cần quyền Administrator.", ephemeral=True)
        return

    config = load_boost_config()
    config[str(interaction.guild.id)] = {
        "channel_id": channel.id,
        "content": content
    }
    save_boost_config(config)

    await interaction.response.send_message(
        f"✅ Đã cài đặt thông báo Boost tại {channel.mention}.\n"
        f"**Nội dung:** {content}",
        ephemeral=True
    )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.premium_since is None and after.premium_since is not None:
        config = load_boost_config().get(str(after.guild.id))
        if not config:
            return

        channel = after.guild.get_channel(config.get("channel_id"))
        if channel is None:
            return

        content = config.get("content", "🚀 Cảm ơn {user} đã boost server!")
        content = content.replace("{user}", after.mention)
        try:
            await channel.send(content)
        except discord.HTTPException:
            pass


BIRTHDAY_FILE = "birthdays.json"


def load_birthdays():
    try:
        with open(BIRTHDAY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"settings": {}, "users": {}}


def save_birthdays(data):
    with open(BIRTHDAY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class BirthdayModal(discord.ui.Modal, title="Đăng ký sinh nhật"):
    birth_date = discord.ui.TextInput(
        label="Ngày tháng năm sinh",
        placeholder="DD/MM/YYYY",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed = datetime.datetime.strptime(str(self.birth_date.value).strip(), "%d/%m/%Y")
            if parsed.year < 1900 or parsed.date() > datetime.datetime.now().date():
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Vui lòng nhập đúng định dạng DD/MM/YYYY.", ephemeral=True
            )
            return

        data = load_birthdays()
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        data.setdefault("users", {}).setdefault(guild_id, {})[user_id] = {
            "day": parsed.day,
            "month": parsed.month,
            "year": parsed.year
        }
        save_birthdays(data)

        await interaction.response.send_message(
            "✅ Đăng ký sinh nhật thành công! Thông tin của bạn được giữ riêng tư.",
            ephemeral=True
        )


class BirthdayRegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Đăng ký",
        style=discord.ButtonStyle.primary,
        emoji="🎂",
        custom_id="birthday_register_button"
    )
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())


@bot.tree.command(
    name="birthday",
    description="Thiết lập kênh đăng ký và kênh thông báo sinh nhật",
    guild=GUILD
)
@discord.app_commands.describe(
    setup_channel="Kênh hiển thị bảng đăng ký sinh nhật",
    notify_channel="Kênh gửi thông báo sinh nhật"
)
async def birthday(
    interaction: discord.Interaction,
    setup_channel: discord.TextChannel,
    notify_channel: discord.TextChannel
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Bạn cần quyền Administrator.", ephemeral=True
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Lệnh này chỉ dùng trong server.", ephemeral=True
        )
        return

    data = load_birthdays()
    guild_id = str(interaction.guild.id)
    data.setdefault("settings", {})[guild_id] = {
        "setup_channel_id": setup_channel.id,
        "notify_channel_id": notify_channel.id
    }
    save_birthdays(data)

    embed = discord.Embed(
        description="**Các mem hãy bấm vào nút đăng ký để nhập ngày/tháng/năm sinh của mình**",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="by ph.huyy.")
    await setup_channel.send(embed=embed, view=BirthdayRegisterView())
    await interaction.response.send_message(
        f"✅ Đã gửi bảng đăng ký tại {setup_channel.mention}.\n"
        f"📢 Kênh thông báo: {notify_channel.mention}",
        ephemeral=True
    )


# =========================
# TICKET • BirthdayTime
# =========================
STAFF_ROLE_ID = 1555595948430729286
TICKET_CATEGORY_NAME = "🎫・TICKET"


def ticket_is_staff(member: discord.Member) -> bool:
    return any(role.id == STAFF_ROLE_ID for role in member.roles)


async def get_ticket_category(guild: discord.Guild):
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category is not None:
        return category
    try:
        return await guild.create_category(
            TICKET_CATEGORY_NAME,
            reason="BirthdayTime ticket category"
        )
    except discord.HTTPException:
        return None


async def find_open_ticket(guild: discord.Guild, user_id: int):
    for channel in guild.text_channels:
        topic = channel.topic or ""
        if topic.startswith("birthdaytime-ticket:") and f"user={user_id}" in topic and "status=closed" not in topic:
            return channel
    return None


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Đổi thẻ cào / USDT → Tiền mặt",
        style=discord.ButtonStyle.secondary,
        custom_id="birthdaytime_ticket_cashout"
    )
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketCashoutModal())

    @discord.ui.button(
        label="Tiền mặt → Mua thẻ",
        style=discord.ButtonStyle.secondary,
        custom_id="birthdaytime_ticket_buycard"
    )
    async def buycard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketBuyCardModal())


class TicketCashoutModal(discord.ui.Modal, title="Đổi thẻ cào / USDT → Tiền mặt"):
    amount = discord.ui.TextInput(
        label="Số tiền / mệnh giá",
        placeholder="Nhập số tiền hoặc mệnh giá",
        required=True,
        max_length=100
    )
    information = discord.ui.TextInput(
        label="Thông tin giao dịch",
        placeholder="Nhập thông tin giao dịch",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await create_ticket(
            interaction,
            "Đổi thẻ cào / USDT → Tiền mặt",
            f"Số tiền / mệnh giá: {self.amount.value}\nThông tin giao dịch: {self.information.value}"
        )


class TicketBuyCardModal(discord.ui.Modal, title="Tiền mặt → Mua thẻ"):
    card_type = discord.ui.TextInput(
        label="Loại thẻ",
        placeholder="Nhập loại thẻ cần mua",
        required=True,
        max_length=100
    )
    amount = discord.ui.TextInput(
        label="Mệnh giá / số lượng",
        placeholder="Nhập mệnh giá và số lượng",
        required=True,
        max_length=100
    )
    information = discord.ui.TextInput(
        label="Thông tin giao dịch",
        placeholder="Nhập thông tin giao dịch",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await create_ticket(
            interaction,
            "Tiền mặt → Mua thẻ",
            f"Loại thẻ: {self.card_type.value}\nMệnh giá / số lượng: {self.amount.value}\nThông tin giao dịch: {self.information.value}"
        )


async def create_ticket(interaction: discord.Interaction, ticket_type: str, ticket_content: str):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Lệnh này chỉ dùng trong server.", ephemeral=True)
        return

    existing = await find_open_ticket(guild, interaction.user.id)
    if existing is not None:
        await interaction.response.send_message(
            f"Bạn đã có Ticket đang mở: {existing.mention}",
            ephemeral=True
        )
        return

    category = await get_ticket_category(guild)
    if category is None:
        await interaction.response.send_message(
            "Không thể tạo danh mục Ticket.",
            ephemeral=True
        )
        return

    staff_role = guild.get_role(STAFF_ROLE_ID)
    if staff_role is None:
        await interaction.response.send_message(
            "Không tìm thấy role Staff. Hãy kiểm tra ID role Staff.",
            ephemeral=True
        )
        return

    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", interaction.user.name.lower()).strip("-") or "user"
    name = name[:70]
    channel_name = f"🎫・ticket-{name}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        staff_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True
        )
    }

    try:
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"birthdaytime-ticket:user={interaction.user.id};type={ticket_type};status=open;staff=0",
            reason="BirthdayTime ticket created"
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "Bot không có quyền tạo Ticket.",
            ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message(
            "Không thể tạo Ticket lúc này.",
            ephemeral=True
        )
        return

    ticket_embed = discord.Embed(
        description=(
            f"**@Người tạo**: {interaction.user.mention}\n"
            f"**Loại giao dịch**: {ticket_type}\n"
            f"**Trạng thái**: Chờ tiếp nhận\n"
            f"**Nhân viên phụ trách**: Chưa có"
        ),
        color=discord.Color.blue()
    )

    staff_embed = discord.Embed(
        description=(
            f"**Người tạo**: {interaction.user.mention}\n"
            f"**Nội dùng Ticket**: {ticket_content}\n\n"
            "**Staff có thể sử dụng các nút bên dưới để xử lý Ticket này.**"
        ),
        color=discord.Color.blue()
    )

    try:
        await channel.send(
            content=f"{interaction.user.mention} <@&{STAFF_ROLE_ID}>",
            embed=ticket_embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True)
        )
        await channel.send(embed=staff_embed, view=TicketStaffView())
        await interaction.response.send_message(
            f"Ticket của bạn đã được tạo: {channel.mention}",
            ephemeral=True
        )
    except discord.HTTPException:
        try:
            await channel.delete(reason="BirthdayTime ticket setup failed")
        except discord.HTTPException:
            pass
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Không thể gửi bảng Ticket.",
                ephemeral=True
            )


async def update_ticket_main_embed(channel: discord.TextChannel, status: str, staff_mention: str):
    async for message in channel.history(limit=20, oldest_first=True):
        if message.author == bot.user and message.embeds:
            embed = message.embeds[0]
            if embed.description and "Người tạo" in embed.description and "Loại giao dịch" in embed.description:
                lines = embed.description.split("\n")
                new_lines = []
                for line in lines:
                    if line.startswith("**Trạng thái**:"):
                        new_lines.append(f"**Trạng thái**: {status}")
                    elif line.startswith("**Nhân viên phụ trách**:"):
                        new_lines.append(f"**Nhân viên phụ trách**: {staff_mention}")
                    else:
                        new_lines.append(line)
                embed.description = "\n".join(new_lines)
                await message.edit(embed=embed)
                return


class TicketStaffView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member) or not ticket_is_staff(interaction.user):
            await interaction.response.send_message(
                "Bạn không có quyền sử dụng bảng Staff.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Nhận ticket", style=discord.ButtonStyle.secondary, custom_id="birthdaytime_ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_staff(interaction):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Không thể xử lý Ticket này.", ephemeral=True)
            return
        topic = channel.topic or ""
        if "status=closed" in topic:
            await interaction.response.send_message("Ticket này đã đóng.", ephemeral=True)
            return
        topic = re.sub(r"status=[^;]+", "status=processing", topic)
        topic = re.sub(r"staff=[^;]+", f"staff={interaction.user.id}", topic)
        await channel.edit(topic=topic)
        await update_ticket_main_embed(channel, "Đang xử lý", interaction.user.mention)
        await interaction.response.send_message("Ticket đã được nhận.", ephemeral=True)

    @discord.ui.button(label="Hoàn thành", style=discord.ButtonStyle.secondary, emoji="<a:verify:1548178353859596320>", custom_id="birthdaytime_ticket_done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_staff(interaction):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return
        await update_ticket_main_embed(channel, "Đã hoàn thành", interaction.user.mention)
        await interaction.response.send_message("Ticket đã được đánh dấu hoàn thành.", ephemeral=True)

    @discord.ui.button(label="Từ chối", style=discord.ButtonStyle.secondary, emoji="<a:failed:1548973085741547580>", custom_id="birthdaytime_ticket_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_staff(interaction):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return
        await update_ticket_main_embed(channel, "Đã từ chối", interaction.user.mention)
        await interaction.response.send_message("Ticket này đã bị từ chối xử lý.", ephemeral=True)

    @discord.ui.button(label="Đóng ticket", style=discord.ButtonStyle.secondary, custom_id="birthdaytime_ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_staff(interaction):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return
        topic = channel.topic or ""
        topic = re.sub(r"status=[^;]+", "status=closed", topic)
        await channel.edit(topic=topic)

        user_id_match = re.search(r"user=(\d+)", topic)
        if user_id_match:
            member = interaction.guild.get_member(int(user_id_match.group(1)))
            if member:
                overwrite = channel.overwrites_for(member)
                overwrite.view_channel = False
                overwrite.send_messages = False
                await channel.set_permissions(member, overwrite=overwrite)

        await update_ticket_main_embed(channel, "Đã đóng", interaction.user.mention)

        button.disabled = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message("Ticket đã được đóng.", ephemeral=True)

        await channel.send(
            embed=discord.Embed(
                description=f"**Trạng thái**: Đã đóng\n**Ticket đã được đóng bởi**: {interaction.user.mention}",
                color=discord.Color.blue()
            ),
            allowed_mentions=discord.AllowedMentions(users=True)
        )


@bot.tree.command(
    name="ticket",
    description="Thiết lập bảng Ticket",
    guild=GUILD
)
@discord.app_commands.describe(
    channel="Kênh sẽ hiển thị bảng Ticket",
    image="Ảnh hiển thị trên bảng Ticket"
)
async def ticket(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    image: discord.Attachment
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Bạn cần quyền Administrator.",
            ephemeral=True
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "Lệnh này chỉ dùng trong server.",
            ephemeral=True
        )
        return

    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message(
            "Vui lòng chọn một tệp ảnh.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        description=(
            "> Chào mừng bạn đến với hệ thống hỗ trợ của BirthdayTime.\n"
            "> Vui lòng chọn loại giao dịch bên dưới để mở Ticket.\n"
            "> Sau khi chọn, bạn sẽ được yêu cầu nhập thông tin giao dịch."
        ),
        color=discord.Color.blue()
    )
    embed.set_image(url=image.url)

    try:
        await channel.send(embed=embed, view=TicketPanelView())
    except discord.Forbidden:
        await interaction.response.send_message(
            f"Bot không có quyền gửi tin nhắn tại {channel.mention}.",
            ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message(
            "Không thể gửi bảng Ticket vào kênh này.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"Đã gửi bảng Ticket tại {channel.mention}.",
        ephemeral=True
    )


@bot.event
async def setup_hook():
    bot.add_view(BirthdayRegisterView())
    bot.add_view(VerifyView())
    bot.add_view(TicketPanelView())
    bot.add_view(TicketStaffView())


# =========================
# VERIFY • BirthdayTime (LINK OAUTH2)
# =========================

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Nút bấm dạng Link dẫn thẳng đến liên kết Discord OAuth2
        self.add_item(
            discord.ui.Button(
                label="Verify BirthdayTime",
                style=discord.ButtonStyle.link,
                url=DISCORD_OAUTH_URL,
                emoji="<a:verify:1548178353859596320>"
            )
        )


@bot.tree.command(
    name="verify",
    description="Thiết lập kênh và gửi bảng Verify • BirthdayTime",
    guild=GUILD
)
@discord.app_commands.describe(
    channel="Kênh sẽ hiển thị bảng Verify",
    image="Ảnh hiển thị trên bảng Verify"
)
async def verify(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    image: discord.Attachment
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Bạn cần quyền Administrator.",
            ephemeral=True
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Lệnh này chỉ dùng trong server.",
            ephemeral=True
        )
        return

    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message(
            "❌ Vui lòng chọn một tệp ảnh.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Verify • BirthdayTime",
        description=(
            "> Bấm vào nút **Verify** bên dưới để chuyển hướng đến trang xác minh OAuth2.\n"
            "> Sau khi xác minh thành công, bạn sẽ nhận được quyền truy cập server."
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="by ph.huyy.")
    embed.set_image(url=image.url)

    try:
        await channel.send(embed=embed, view=VerifyView())
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Bot không có quyền gửi tin nhắn tại {channel.mention}.",
            ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message(
            "❌ Không thể gửi bảng Verify vào kênh này.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✅ Đã thiết lập bảng Verify tại {channel.mention}.",
        ephemeral=True
    )


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    if VERIFY_API_SECRET:
        try:
            approved_ids = await approved_verification_ids(member.id)
            if member.id in approved_ids:
                await process_approved_verification(member.id)
        except Exception as exc:
            print(f"Could not verify joining member {member.id}: {type(exc).__name__}: {exc}")

    verify_role = member.guild.get_role(VERIFY_ROLE_ID)
    has_verify_role = verify_role is not None and verify_role in member.roles
    try:
        join_embed = discord.Embed(
            title="Chào mừng bạn đến server!",
            description=(
                f"Xác minh BirthdayTime thành công. Bot đã cấp role verify cho bạn."
                if has_verify_role
                else (
                    f"Bạn hãy xác minh tài khoản để nhận role tại **{member.guild.name}**."
                    f"\n🔗 [Mở trang Verify]({DISCORD_OAUTH_URL})"
                )
            ),
            color=discord.Color.blurple()
        )
        join_embed.set_footer(text="by ph.huyy.")

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Vào Verify",
                style=discord.ButtonStyle.link,
                url=DISCORD_OAUTH_URL
            )
        )

        if has_verify_role:
            await member.send(embed=join_embed)
        else:
            await member.send(embed=join_embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bạn không có quyền sử dụng lệnh này.", delete_after=30)
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Thiếu tham số. Hãy kiểm tra cú pháp lệnh.", delete_after=30)
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send("❌ Tham số không hợp lệ. Hãy kiểm tra lại.", delete_after=30)
        return
    print(f"Command error: {type(error).__name__}: {error}")


bot.run(TOKEN)
