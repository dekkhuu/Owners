import os
import json
import datetime
import secrets
import re
import time
from pathlib import Path
import discord
from discord.ext import commands, tasks

ALLOWED_GUILD_ID = 1503922700408586240
TOKEN = os.getenv("DISCORD_TOKEN")

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

# Số tin nhắn tối đa trong khoảng thời gian ngắn trước khi coi là spam.
SPAM_MESSAGE_LIMIT = 3
SPAM_WINDOW_SECONDS = 2

# Các domain/link thường được dùng để quảng cáo, redirect hoặc link lạ.
# Có thể bổ sung thêm domain vào danh sách này.
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

# Từ khóa thường xuất hiện trong tên file/URL NSFW.
NSFW_KEYWORDS = {
    "porn", "xxx", "nsfw", "sex", "nude", "nudity",
    "hentai", "pornhub", "xvideos", "xnxx",
}

bot.spam_tracker = {}
bot.muted_users = set()


def normalize_domain(url: str) -> str:
    url = url.lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("/", 1)[0].split(":", 1)[0]


def contains_blocked_link(content: str) -> tuple[bool, str]:
    """Rule BirthdayTime: chỉ cho phép blazemarket.online trong nhóm link kiếm tiền."""
    urls = re.findall(r"(?:https?://|www\.)[^\s<>()]+", content.lower())
    lower = content.lower()

    for raw_url in urls:
        domain = normalize_domain(raw_url)

        # Ngoại lệ duy nhất.
        if domain == "blazemarket.online" or domain.endswith(".blazemarket.online"):
            continue

        if domain in BLOCKED_DOMAINS:
            return True, "Gửi link lạ hoặc link có dấu hiệu scam."

        if any(k in lower for k in GAMBLING_KEYWORDS):
            return True, "Gửi/quảng bá link tài xỉu hoặc cờ bạc không được phép."

        if any(k in lower for k in MONEY_LINK_KEYWORDS):
            return True, "Gửi link kiếm tiền không được phép. Ngoại lệ duy nhất là blazemarket.online."

        # Theo Rule, URL khác blazemarket.online đều bị chặn.
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
    """Mute 24h và DM embed riêng cho người vi phạm."""
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

    # Reset bộ đếm spam sau khi bị xử lý.
    bot.spam_tracker.pop(member.id, None)
    return True



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
            "`/boost` — Thiết lập thông báo Boost"
        ),
        inline=False
    )

    embed.set_footer(text="by ph.huyy.")
    await interaction.response.send_message(embed=embed)

# =========================
# Các lệnh quản lý
# =========================

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    await member.ban(reason=reason)
    embed = discord.Embed(
        description=f"{member.mention} đã bị đá khỏi Guid",
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
            description=f"{user.mention} đã được sự khoan hồng để trở lại Guid",
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

    duration = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=minutes)
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
    """Xem avatar của người được tag; nếu không tag ai thì xem avatar của mình."""
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
    # !afk [lý do] — không bắt buộc phải nhập member, tránh lỗi
    # khi lý do bị Discord hiểu nhầm là tham số Member.
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

    # Chỉ AutoMod trong server được phép của bot.
    if message.guild is not None and message.guild.id == ALLOWED_GUILD_ID:
        # Không xử lý người đã bị timeout.
        if isinstance(message.author, discord.Member) and message.author.is_timed_out():
            return

        violation_reason = None

        # 1) Spam tin nhắn.
        if is_spam(message):
            violation_reason = (
                f"Gửi quá nhiều tin nhắn trong thời gian ngắn "
                f"({SPAM_MESSAGE_LIMIT} tin / {SPAM_WINDOW_SECONDS} giây)."
            )

        # 2) Link lạ/scam/tài xỉu/link kiếm tiền.
        if violation_reason is None:
            blocked, reason = contains_blocked_link(message.content)
            if blocked:
                violation_reason = reason

        # 3) Nội dung chữ bị cấm.
        if violation_reason is None:
            blocked, reason = contains_rule_violation_text(message.content)
            if blocked:
                violation_reason = reason

        # 4) File/ảnh/video có dấu hiệu vi phạm.
        if violation_reason is None:
            blocked, reason = contains_nsfw_attachment(message)
            if blocked:
                violation_reason = reason

        if violation_reason:
            # Tự động xóa ngay tin nhắn vi phạm.
            deleted = False
            try:
                await message.delete(reason=f"AutoMod: {violation_reason}")
                deleted = True
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

            # Sau khi xử lý tin nhắn, mute người vi phạm 24 giờ.
            await notify_and_mute(message.author, violation_reason)
            return

    # Nếu người gửi đang AFK và đã nhắn tin trở lại thì xóa trạng thái AFK.
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

    # Khi ai đó ping một người đang AFK, thông báo trạng thái AFK.
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


# =========================
# Slash commands thiết lập
# =========================

# =========================
# BIRTHDAYTIME RULE SCANNER • QUÉT MỖI 1 GIÂY
# =========================
RULE_SCAN_INTERVAL = 5
RULE_SCAN_MESSAGE_LIMIT = 10
bot.rule_scan_seen = set()


async def scan_message_for_rules(message: discord.Message):
    """Kiểm tra một message theo Rule BirthdayTime và mute nếu vi phạm."""
    if message.author.bot:
        return

    if message.guild is None or message.guild.id != ALLOWED_GUILD_ID:
        return

    if not isinstance(message.author, discord.Member):
        return

    if message.author.is_timed_out():
        return

    violation_reason = None

    # Không kiểm tra spam ở scanner. on_message đã kiểm tra spam ngay khi tin nhắn tới.
    # Nếu kiểm tra lại ở đây, cùng một message sẽ bị tính 2 lần và có thể mute nhầm.

    # Link.
    if violation_reason is None:
        blocked, reason = contains_blocked_link(message.content)
        if blocked:
            violation_reason = reason

    # Nội dung chữ.
    if violation_reason is None:
        blocked, reason = contains_rule_violation_text(message.content)
        if blocked:
            violation_reason = reason

    # File/ảnh/video dựa trên tên file.
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
    """Mỗi 1 giây quét các message gần nhất trong các kênh text."""
    for guild in bot.guilds:
        if guild.id != ALLOWED_GUILD_ID:
            continue

        for channel in guild.text_channels:
            # Chỉ quét các kênh bot có thể đọc lịch sử.
            try:
                messages = [m async for m in channel.history(
                    limit=RULE_SCAN_MESSAGE_LIMIT
                )]
            except (discord.Forbidden, discord.HTTPException):
                continue

            for message in reversed(messages):
                # Không quét lại cùng một message.
                if message.id in bot.rule_scan_seen:
                    continue

                bot.rule_scan_seen.add(message.id)
                await scan_message_for_rules(message)

    # Giới hạn bộ nhớ ID đã quét.
    if len(bot.rule_scan_seen) > 10000:
        bot.rule_scan_seen = set(list(bot.rule_scan_seen)[-5000:])


@rule_scanner.before_loop
async def before_rule_scanner():
    await bot.wait_until_ready()

# =========================
# Thống kê server
# =========================

bot.stats_channels = {}

# Chuyển chữ số thường sang chữ số kiểu đặc biệt cho tên kênh thống kê.
_DIGIT_MAP = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")

def format_stats_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


async def update_server_stats(guild: discord.Guild):
    channel_map = bot.stats_channels.get(guild.id, {})

    # Sau khi bot khởi động lại, tự tìm các kênh thống kê hiện có
    # theo phần tên gốc, không tạo lại kênh và không đổi kiểu tên.
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

        # Giữ nguyên toàn bộ kiểu tên kênh, chỉ thay phần số ở cuối.
        new_name = f"{base_name} ﹕{format_stats_digits(str(values[base_name]))}"
        if channel.name != new_name:
            try:
                await channel.edit(name=new_name, reason="Update server statistics")
            except discord.HTTPException:
                pass


@tasks.loop(seconds=60)
async def stats_updater():
    # Mỗi 1 phút quét toàn bộ server được phép để tìm và cập nhật
    # tất cả 5 kênh thống kê, kể cả sau khi bot khởi động lại.
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

        # Không cho @everyone kết nối vào các kênh thống kê.
        # Thành viên có Administrator vẫn có thể bỏ qua channel overwrite.
        await channel.set_permissions(
            guild.default_role,
            connect=False,
            reason="Lock server statistics voice channel"
        )
        created.append(channel)

    # Lưu các kênh để task cập nhật mỗi phút.
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

        # Chỉ phản hồi riêng tư; không gửi ngày sinh ra kênh công khai.
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
            ">Chào mừng bạn đến với hệ thống hỗ trợ của BirthdayTime.\n"
            "Vui lòng chọn loại giao dịch bên dưới để mở Ticket.\n"
            "Sau khi chọn, bạn sẽ được yêu cầu nhập thông tin giao dịch."
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
# VERIFY • BirthdayTime
# =========================

VERIFY_ROLE_ID = 1515041455805304953
VERIFY_EMOJI = "<a:verify:1548178353859596320>"
FAILED_EMOJI = "<a:failed:1548973085741547580>"

# Lưu code đang có hiệu lực theo từng user.
# Khi mở Modal mới, code cũ của user sẽ bị thay bằng code mới.
bot.verify_codes = {}


def generate_verify_code() -> str:
    # 6 chữ số, dùng secrets để tạo mã khó đoán.
    return f"{secrets.randbelow(1_000_000):06d}"



class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        custom_id="birthdaytime_verify_button"
    )
    async def verify(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        # Đã có role Verify thì đã xác minh rồi, không cho xác minh lại.
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Lệnh này chỉ dùng trong server.",
                ephemeral=True
            )
            return

        role = guild.get_role(VERIFY_ROLE_ID)
        if role is None:
            await interaction.response.send_message(
                "❌ Không tìm thấy role xác minh. Hãy kiểm tra ID role.",
                ephemeral=True
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                f"{VERIFY_EMOJI} Bạn đã xác minh trước đó rồi, không thể xác minh lại.",
                ephemeral=True
            )
            return

        # Chỉ người chưa xác minh mới được tạo code.
        code = generate_verify_code()
        bot.verify_codes[interaction.user.id] = code

        # Code chỉ hiển thị trong Modal/ephemeral, không gửi công khai.
        # Người dùng cần nhập đúng code được hiển thị trên bảng.
        class UserCodeModal(discord.ui.Modal, title="Verify • BirthdayTime"):
            code_input = discord.ui.TextInput(
                label=f"Code của bạn: {code}",
                placeholder="Nhập code trên bảng",
                min_length=6,
                max_length=6,
                required=True
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                expected = bot.verify_codes.get(modal_interaction.user.id)
                entered = str(self.code_input.value).strip()

                if expected is None or entered != expected:
                    await modal_interaction.response.send_message(
                        f"{FAILED_EMOJI}Bạn chưa nhập đúng code trên bảng",
                        ephemeral=True
                    )
                    return

                guild = modal_interaction.guild
                if guild is None:
                    await modal_interaction.response.send_message(
                        "❌ Lệnh này chỉ dùng trong server.",
                        ephemeral=True
                    )
                    return

                role = guild.get_role(VERIFY_ROLE_ID)
                if role is None:
                    await modal_interaction.response.send_message(
                        "❌ Không tìm thấy role xác minh. Hãy kiểm tra ID role.",
                        ephemeral=True
                    )
                    return

                # Kiểm tra lại ngay trước khi cấp role để tránh xác minh lần 2.
                if role in modal_interaction.user.roles:
                    bot.verify_codes.pop(modal_interaction.user.id, None)
                    await modal_interaction.response.send_message(
                        f"{VERIFY_EMOJI} Bạn đã xác minh trước đó rồi, không thể xác minh lại.",
                        ephemeral=True
                    )
                    return

                try:
                    if role not in modal_interaction.user.roles:
                        await modal_interaction.user.add_roles(
                            role,
                            reason="BirthdayTime verification"
                        )
                except discord.Forbidden:
                    await modal_interaction.response.send_message(
                        "❌ Bot không có quyền cấp role xác minh. "
                        "Hãy kéo role bot cao hơn role xác minh.",
                        ephemeral=True
                    )
                    return
                except discord.HTTPException:
                    await modal_interaction.response.send_message(
                        "❌ Không thể cấp role xác minh lúc này.",
                        ephemeral=True
                    )
                    return

                bot.verify_codes.pop(modal_interaction.user.id, None)

                # Thông báo xác minh thành công trong server.
                await modal_interaction.response.send_message(
                    f"{VERIFY_EMOJI}Bạn đã xác minh thành công",
                    ephemeral=True
                )

                # Gửi riêng cho người dùng một Embed sau khi xác minh thành công.
                try:
                    success_embed = discord.Embed(
                        title="Chúc mừng bạn đã xác minh thành công",
                        description=(
                            f"Chúc mừng bạn đã xác minh thành công của Guid {guild.name}, Hãy vào Server để nói chuyện cùng mọi người nhé!"
                        ),
                        color=discord.Color.green()
                    )
                    success_embed.set_footer(text="by ph.huyy.")
                    await modal_interaction.user.send(embed=success_embed)
                except (discord.Forbidden, discord.HTTPException):
                    # Người dùng có thể đã tắt DM hoặc Discord đang lỗi tạm thời.
                    pass

        await interaction.response.send_modal(UserCodeModal())


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
            ">Hãy bấm nút \"Verify\" để được xác minh.\n"
            "Sau khi bấm, hãy nhập đúng mã xác minh được cung cấp cho bạn."
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
    # Chỉ gửi DM cho thành viên mới trong server được phép.
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    VERIFY_LINK = "https://discord.gg/Nvmh4D7VCX"

    try:
        join_embed = discord.Embed(
            title="Chào mừng bạn đến server!",
            description=(
                f"Bạn hãy vào kênh verify của **{member.guild.name}** để xác minh."
                f"🔗 [Vào kênh Verify]({VERIFY_LINK})"
            ),
            color=discord.Color.blurple()
        )
        join_embed.set_footer(text="by ph.huyy.")

        # Nút bấm mở trực tiếp link Verify.
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Vào Verify",
                style=discord.ButtonStyle.link,
                url=VERIFY_LINK
            )
        )

        await member.send(embed=join_embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        # Người dùng có thể đã tắt DM.
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
