import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import datetime
import os
import logging

# ===== ログ設定 =====
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

# ===== Bot初期化 =====
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ===== データ保持 =====
vote_data = {}
schedule_tasks = {}

# ===== View定義 =====
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "✅ 参加")

    @discord.ui.button(label="未定", style=discord.ButtonStyle.secondary)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "❔ 未定")

    @discord.ui.button(label="不参加", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "❌ 不参加")

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        user = interaction.user.name
        vote_data.setdefault(self.date_str, {})
        vote_data[self.date_str][user] = status
        await self.safe_send(interaction.response.send_message, f"{user} さんが「{status}」に投票しました。", ephemeral=True)

    async def safe_send(self, func, *args, **kwargs):
        """RateLimit対策つき送信"""
        for _ in range(3):
            try:
                await func(*args, **kwargs)
                return
            except discord.errors.HTTPException as e:
                if e.status == 429:
                    logging.warning("Rate limit hit, waiting 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    raise

# ===== コマンド定義 =====
@tree.command(name="schedule", description="日程調整を開始します")
async def schedule(interaction: discord.Interaction, date: str):
    """日程投票を作成"""
    try:
        await interaction.response.send_message(
            f"📅 日程投票を作成しました！\n対象日: **{date}**",
            ephemeral=True
        )
        await asyncio.sleep(1)

        channel = interaction.channel
        embed = discord.Embed(
            title="🗓 日程調整投票",
            description=f"日付: **{date}**\n\n下のボタンから参加状況を選んでください！",
            color=0x00b0f4
        )
        await channel.send(embed=embed, view=VoteView(date))
        logging.info(f"Vote created for {date}")

    except Exception as e:
        logging.error(f"scheduleコマンドでエラー発生: {e}")

@tree.command(name="show_votes", description="投票状況を表示します")
async def show_votes(interaction: discord.Interaction, date: str):
    """投票結果を表示"""
    data = vote_data.get(date)
    if not data:
        await interaction.response.send_message("この日付の投票データはありません。", ephemeral=True)
        return

    summary = "\n".join([f"{user} → {status}" for user, status in data.items()])
    embed = discord.Embed(title=f"📊 {date} の投票結果", description=summary, color=0x00b0f4)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="remind_votes", description="投票催促を投稿します")
async def remind_votes(interaction: discord.Interaction, date: str):
    """投票催促メッセージを特定チャンネルに送信"""
    await interaction.response.send_message("📣 投票催促を投稿します。", ephemeral=True)
    await asyncio.sleep(1)

    guild = interaction.guild
    target_channel = discord.utils.get(guild.text_channels, name="投票催促")

    if not target_channel:
        await interaction.followup.send("⚠️ チャンネル「投票催促」が見つかりません。", ephemeral=True)
        return

    await target_channel.send(f"⏰ **{date}** の日程にまだ投票していない方は、早めに投票をお願いします！")

# ===== 起動処理 =====
@bot.event
async def on_ready():
    await tree.sync()
    logging.info(f"✅ Logged in as {bot.user}")
    logging.info("✅ Commands synced.")

# ===== メイン起動 =====
if __nam
