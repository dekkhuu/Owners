import os
import discord
from discord.ext import commands

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
            "`/setupstats` — Tạo thống kê server\n"
            "`/birthday setup` — Thiết lập sinh nhật\n"
            "`/boost` — Thiết lập thông báo Boost"
        ),
        inline=False
    )

    embed.set_footer(text="Owens")
    await interaction.response.send_message(embed=embed)


# =========================
# Các lệnh quản lý
# =========================

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Đã ban {member.mention}\nLý do: {reason}")


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"✅ Đã unban {user.mention}")
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
    await ctx.send(f"🔇 Đã mute {member.mention} trong `{minutes}` phút.\nLý do: {reason}")


@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"🔊 Đã unmute {member.mention}")


@bot.command(name="afk")
async def afk(ctx, *, reason: str = "AFK"):
    await ctx.send(f"💤 {ctx.author.mention} đang AFK: {reason}")


# =========================
# Slash commands thiết lập
# =========================

@bot.tree.command(
    name="setupstats",
    description="Tạo thống kê server",
    guild=GUILD
)
async def setupstats(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Bạn cần quyền Administrator.", ephemeral=True)
        return
    embed = discord.Embed(
        title="📊 Thống kê server",
        description="Đã tạo khu vực thống kê server.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)


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
