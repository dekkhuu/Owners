import os
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
    await ctx.send(embed=embed)


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
        await ctx.send(embed=embed)
    except discord.NotFound:
        await ctx.send("❌ Không tìm thấy người dùng hoặc người dùng chưa bị ban.")
    except discord.HTTPException:
        await ctx.send("❌ Không thể unban người dùng này.")


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason: str = "Không có lý do"):
    if minutes < 1:
        await ctx.send("❌ Số phút phải lớn hơn 0.")
        return

    duration = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(
        description=f"{member.mention} đã bị khoá mõm trong {minutes} phút",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)


@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    embed = discord.Embed(
        description=f"{member.mention} đã mở khóa mõm",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@bot.command(name="afk")
async def afk(ctx, member: discord.Member = None, *, reason: str = "AFK"):
    target = member or ctx.author

    if not hasattr(bot, "afk_users"):
        bot.afk_users = {}

    bot.afk_users[target.id] = reason

    embed = discord.Embed(
        description=f"{target.mention} đang AFK: {reason}",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed)


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
        "╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥": f"╭ㆍ🍁ㆍ☆ㆍ﹕𝐀𝐥𝐥:{total}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐌𝐞𝐦𝐛𝐞𝐫:{humans}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐁𝐨𝐭:{bots}",
        "⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞": f"⌇ㆍ☆ㆍ✨ㆍ﹕𝐎𝐧𝐥𝐢𝐧𝐞:{online}",
        "╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭": f"╰ㆍ🍁ㆍ☆ㆍ﹕𝐁𝐨𝐨𝐬𝐭:{boost_count}",
    }

    for base_name, channel_id in channel_map.items():
        channel = guild.get_channel(channel_id)
        if channel is None:
            continue
        new_name = values[base_name]
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


@bot.tree.command(
    name="boost",
    description="Thiết lập thông báo Boost",
    guild=GUILD
)
async def boost(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Bạn cần quyền Administrator.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🚀 Boost",
        description="Đã thiết lập thông báo Boost.",
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="birthday",
    description="Thiết lập sinh nhật",
    guild=GUILD
)
@discord.app_commands.describe(action="Thao tác")
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="setup", value="setup")
    ]
)
async def birthday(interaction: discord.Interaction, action: discord.app_commands.Choice[str]):
    if action.value == "setup":
        await interaction.response.send_message(
            "🎂 Đã mở thiết lập sinh nhật."
        )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command error: {error}")


bot.run(TOKEN)
