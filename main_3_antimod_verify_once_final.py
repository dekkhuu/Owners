import os
import json
import datetime
import secrets
import re
import time
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
SPAM_MESSAGE_LIMIT = 6
SPAM_WINDOW_SECONDS = 8

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

# Từ khóa thường xuất hiện trong tên file/URL NSFW.
NSFW_KEYWORDS = {
    "porn", "xxx", "nsfw", "sex", "nude", "nudity",
    "hentai", "pornhub", "xvideos", "xnxx",
}

bot.spam_tracker = {}
bot.muted_users = set()


def contains_blocked_link(content: str) -> bool:
    urls = re.findall(r"(?:https?://|www\.)[^\s<>()]+", content.lower())
    for url in urls:
        clean = re.sub(r"^[^a-z0-9]+|[^a-z0-9./:_-]+$", "", url)
        domain_match = re.search(r"(?:https?://|www\.)([^/:?#\s]+)", clean)
        if not domain_match:
            continue
        domain = domain_match.group(1).lower().removeprefix("www.")
        if domain in BLOCKED_DOMAINS or any(domain.endswith("." + d) for d in BLOCKED_DOMAINS):
            return True

        # Chặn URL chứa từ khóa NSFW.
        if any(keyword in clean for keyword in NSFW_KEYWORDS):
            return True
    return False


def contains_nsfw_attachment(message: discord.Message) -> bool:
    for attachment in message.attachments:
        name = (attachment.filename or "").lower()
        content_type = (attachment.content_type or "").lower()

        # Chặn tên file rõ ràng là NSFW.
        if any(keyword in name for keyword in NSFW_KEYWORDS):
            return True

        # Nếu Discord đánh dấu attachment là image/video và tên có dấu hiệu NSFW.
        if content_type.startswith(("image/", "video/")):
            if any(keyword in name for keyword in NSFW_KEYWORDS):
                return True
    return False


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
            "`/birthday setup` — Thiết lập sinh nhật\n"
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
    await ctx.send(embed=embed, delete_after=30)


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

        # 2) Link bị chặn / link đáng ngờ.
        elif contains_blocked_link(message.content):
            violation_reason = "Gửi link bị hệ thống AutoMod chặn hoặc link đáng ngờ."

        # 3) File/ảnh có dấu hiệu NSFW rõ ràng từ tên file.
        elif contains_nsfw_attachment(message):
            violation_reason = "Gửi ảnh/tệp có dấu hiệu nội dung 18+."

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
            await message.channel.send(embed=embed)
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
                    ),
                    color=discord.Color.blurple()
                )
                embed.set_footer(text="by ph.huyy.")

                try:
                    await message.channel.send(embed=embed)
                except discord.HTTPException:
                    pass

                notified_users.add(mentioned_user.id)

    await bot.process_commands(message)


# =========================
# Slash commands thiết lập
# =========================

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


@bot.event
async def setup_hook():
    bot.add_view(BirthdayRegisterView())
    bot.add_view(VerifyView())


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
    channel="Kênh sẽ hiển thị bảng Verify"
)
async def verify(
    interaction: discord.Interaction,
    channel: discord.TextChannel
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

    embed = discord.Embed(
        title=f"{VERIFY_EMOJI}Verify • BirthdayTime",
        description=(
            "Cách dùng: bấm Verify, sau đó nhập code được hiển thị trên bảng."
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="by ph.huyy.")

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
