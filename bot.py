import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# =========================
# 基本設定
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
JST = pytz.timezone("Asia/Tokyo")

# =========================
# 永続化用（簡易テスト版）
# =========================
vote_data = {}        # メッセージIDごとの投票
confirmed_dates = {}  # 日程確定フラグ

# =========================
# ボタン形式投票ビュー
# =========================
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        msg_id = str(interaction.message.id)
        user = interaction.user.display_name
        if msg_id not in vote_data:
            vote_data[msg_id] = {}
        if self.date_str not in vote_data[msg_id]:
            vote_data[msg_id][self.date_str] = {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}

        # 同じステータスなら解除
        for k in vote_data[msg_id][self.date_str]:
            if user in vote_data[msg_id][self.date_str][k]:
                vote_data[msg_id][self.date_str][k].remove(user)
        vote_data[msg_id][self.date_str][status].append(user)

        # Embed更新
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[msg_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# =========================
# Step1: 週チャンネル作成
# =========================
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]  # テスト用：最初のサーバー取得

    # カテゴリ名
    categories = {"初級": ["初級", "管理者"], "中級": ["中級", "管理者"]}
    
    for key, roles in categories.items():
        category = discord.utils.get(guild.categories, name=key)
        if not category:
            category = await guild.create_category(name=key)

        # 日付文字列例（今週のテスト用）
        today = datetime.datetime.now(JST)
        date_str = today.strftime("%m月%d日_テスト週")
        overwrites = {}
        for role_name in roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        # everyoneは不可
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

        channel_name = f"{date_str}"
        await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

    print("✅ Step1: 週チャンネル作成完了")

# =========================
# Step2: 投票リマインド（簡易テスト）
# =========================
async def send_step2_remind():
    await bot.wait_until_ready()
    print("⏰ Step2: 投票リマインド（テスト用）")
    # テストなのでコンソール出力のみ

# =========================
# Step3: 確定通知（簡易テスト）
# =========================
async def send_step3_confirm():
    await bot.wait_until_ready()
    print("📌 Step3: 確定通知・管理者判断（テスト用）")
    # テストなのでコンソール出力のみ

# =========================
# on_ready + テストスケジュール
# =========================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

    now = datetime.datetime.now(JST)
    scheduler = AsyncIOScheduler(timezone=JST)

    # 秒単位テスト
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=now + datetime.timedelta(seconds=10)))
    scheduler.add_job(send_step2_remind,   DateTrigger(run_date=now + datetime.timedelta(seconds=20)))
    scheduler.add_job(send_step3_confirm,  DateTrigger(run_date=now + datetime.timedelta(seconds=30)))

    scheduler.start()
    print("✅ Scheduler started (テスト用)")

# =========================
# メイン
# =========================
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
