import discord
from discord import app_commands
import datetime
import asyncio
import os

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# -----------------------------
# VoteView（ボタン投票）簡易版
# -----------------------------
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.votes = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

    async def register_vote(self, interaction: discord.Interaction, status: str):
        user_id = str(interaction.user.id)
        # 他のステータスから削除
        for k in self.votes:
            if user_id in self.votes[k]:
                self.votes[k].remove(user_id)
        # 新しいステータスに追加
        self.votes[status].append(user_id)

        # Embed更新
        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            users = self.votes[k]
            embed.set_field_at(idx, name=k, value="\n".join(f"<@{uid}>" for uid in users) or "なし", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # 3人以上で確定通知
        if len(self.votes["参加(🟢)"]) >= 3:
            await interaction.channel.send(f"✅ {self.date_str} は3人以上が参加予定！日程確定です！")

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

# -----------------------------
# /test_send コマンド（手動テスト用）
# -----------------------------
@tree.command(name="test_send", description="手動送信テスト")
async def test_send(interaction: discord.Interaction):
    await interaction.response.send_message("✅ 手動送信テストです！", ephemeral=True)

# -----------------------------
# 自動スケジューラー
# -----------------------------
async def scheduler_task():
    await bot.wait_until_ready()
    sent_dates = set()  # 送信済み防止
    while not bot.is_closed():
        now = datetime.datetime.now()
        # 19:40になったら送信
        if now.hour == 19 and now.minute == 40:
            today = datetime.date.today()
            target = today + datetime.timedelta(weeks=3)
            days_to_sunday = (6 - target.weekday()) % 7
            start_date = target + datetime.timedelta(days=days_to_sunday)
            date_key = start_date.strftime("%Y-%m-%d")

            if date_key not in sent_dates:
                for guild in bot.guilds:
                    channel = discord.utils.get(guild.text_channels, name="wqwq")
                    if channel:
                        # 1週間分の日程候補を送信
                        dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
                        for d in dates:
                            embed = discord.Embed(title=f"【日程候補】{d}", description="投票してください")
                            embed.add_field(name="参加(🟢)", value="なし", inline=False)
                            embed.add_field(name="調整可(🟡)", value="なし", inline=False)
                            embed.add_field(name="不可(🔴)", value="なし", inline=False)
                            await channel.send(embed=embed, view=VoteView(d))
                        await channel.send("✅ 三週間後の日曜始まりの日程候補を送信しました！")
                        sent_dates.add(date_key)
        await asyncio.sleep(20)  # 20秒ごとにチェック

# -----------------------------
# Bot起動
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    bot.loop.create_task(scheduler_task())
    print("⏰ Scheduler task started")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
