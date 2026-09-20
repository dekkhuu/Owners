import os
import json
import datetime
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
        title="Owens",
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
        title="Owens Help",
        description="Danh sách các lệnh hiện có của Owens.",
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

    embed.set_footer(text="by ph.huyy • giờ VN")
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

    if hasattr(bot, "afk_users") and message.author.id in bot.afk_users:
        del bot.afk_users[message.author.id]

        embed = discord.Embed(
            description=f"{message.author.mention} đã trở lại",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)

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
    channel_map = bot.stats_channels.get(guild.id)
    if not channel_map:
        return

    # members phải được bật intent members để có danh sách đầy đủ.
    members = guild.members
    total = len(members)
    bots = sum(1 for member in members if member.bot)
    online = sum(
        1 for member in members
        if member.status != discord.Status.offline
    )
    humans = total - bots
    boost_count = guild.premium_subscription_count

    values = {
        "╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥": f"╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥 ﹕{total}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫 ﹕{humans}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭 ﹕{bots}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞 ﹕{online}",
        "╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭": f"╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭 ﹕{boost_count}",
    }

    for base_name, channel_id in channel_map.items():
        channel = guild.get_channel(channel_id)
        if channel is None:
            continue
        new_name = format_stats_digits(values[base_name])
        if channel.name != new_name:
            try:
                await channel.edit(
                    name=new_name,
                    reason="Update server statistics"
                )
            except discord.HTTPException:
                pass


@tasks.loop(minutes=1)
async def stats_updater():
    for guild_id in list(bot.stats_channels):
        guild = bot.get_guild(guild_id)
        if guild is not None:
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
        channel = discord.utils.get(guild.voice_channels, name=name)
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
