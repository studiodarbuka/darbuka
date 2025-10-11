import discord
from discord import app_commands
from discord.ext import tasks
import datetime
import asyncio
import os

# ====== 設定 ======
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Render の環境変数で設定
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", 0))  # サーバーID（任意）
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))  # 投票を送るチャンネルID（任意）

# ====== Bot初期化 ======
intents = discord.Intents.default()
intents.message_content = True  # メッセージ内容を扱う場合のみ必要
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ====== 投票データ ======
vote_data = {}  # {date_str: {"votes": {"user": "option"}}}

# ====== 投票UI ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        vote_data.setdefault(self.date_str, {"votes": {}})
        vote_data[self.date_str]["votes"][user] = "参加"
        await interaction.response.send_message(f"{user} さんが『参加』に投票しました。", ephemeral=True)

    @discord.ui.button(label="未定", style=discord.ButtonStyle.gray)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        vote_data.setdefault(self.date_str, {"votes": {}})
        vote_data[self.date_str]["votes"][user] = "未定"
        await interaction.response.send_message(f"{user} さんが『未定』に投票しました。", ephemeral=True)

    @discord.ui.button(label="不参加", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        vote_data.setdefault(self.date_str, {"votes": {}})
        vote_data[self.date_str]["votes"][user] = "不参加"
        await interaction.response.send_message(f"{user} さんが『不参加』に投票しました。", ephemeral=True)

# ====== /schedule コマンド ======
@tree.command(name="schedule", description="3週間後の日程投票を開始します")
async def schedule(interaction: discord.Interaction):
    await interaction.response.send_message("3週間後の日程を作成します...", ephemeral=True)

    date = datetime.date.today() + datetime.timedelta(weeks=3)
    date_str = date.strftime("%Y-%m-%d")

    embed = discord.Embed(
        title=f"📅 {date_str} の予定調整",
        description="以下のボタンから出欠を入力してください。",
        color=0x2ECC71,
    )
    embed.set_footer(text="自動生成されたスケジュール投票です。")

    channel = interaction.guild.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(embed=embed, view=VoteView(date_str))
        await interaction.followup.send(f"{channel.mention} に投票を作成しました！", ephemeral=True)
    else:
        await interaction.followup.send("チャンネルが見つかりません。CHANNEL_IDを確認してください。", ephemeral=True)

# ====== /event_now コマンド ======
@tree.command(name="event_now", description="現在の投票状況を確認します")
async def event_now(interaction: discord.Interaction):
    if not vote_data:
        await interaction.response.send_message("まだ投票がありません。", ephemeral=True)
        return

    message = ""
    for date, data in vote_data.items():
        message += f"**{date} の投票状況：**\n"
        for user, choice in data["votes"].items():
            message += f"・{user} → {choice}\n"
        message += "\n"

    await interaction.response.send_message(message, ephemeral=True)

# ====== 自動タスク ======
@tasks.loop(hours=24)
async def auto_schedule_task():
    now = datetime.datetime.now()
    if now.weekday() == 6 and now.hour == 9:  # 日曜の9時に実行
        guild = bot.get_guild(GUILD_ID)
        if guild:
            channel = guild.get_channel(CHANNEL_ID)
            if channel:
                date = datetime.date.today() + datetime.timedelta(weeks=3)
                date_str = date.strftime("%Y-%m-%d")

                embed = discord.Embed(
                    title=f"📅 {date_str} の予定調整",
                    description="以下のボタンから出欠を入力してください。",
                    color=0x2ECC71,
                )
                embed.set_footer(text="自動生成されたスケジュール投票です。")

                await channel.send(embed=embed, view=VoteView(date_str))
                print(f"[AUTO] {date_str} の投票を作成しました。")

@bot.event
async def on_ready():
    await tree.sync()
    auto_schedule_task.start()
    print(f"✅ Bot {bot.user} がログインしました！")
    print("✅ Slash commands synced!")
    print("✅ 自動スケジュールタスク開始！")

# ====== 実行 ======
bot.run(TOKEN)
