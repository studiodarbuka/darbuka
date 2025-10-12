import discord
from discord import app_commands
import asyncio
import datetime
import os

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# 投票データ・スケジュール（メモリ上のみ）
vote_data = {}
scheduled_weeks = []

# 環境変数からテストチャンネルID
TEST_CHANNEL_ID = int(os.getenv("TEST_CHANNEL_ID", "0"))
if TEST_CHANNEL_ID == 0:
    raise ValueError("⚠️ TEST_CHANNEL_ID を環境変数で設定してください")

# -----------------------------
# VoteView（ボタン投票用）
# -----------------------------
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def register_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        # 他の選択肢から削除
        for k in vote_data[message_id][self.date_str]:
            if user_id in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user_id)

        # 新しい選択肢に追加
        vote_data[message_id][self.date_str][status].append(user_id)

        # Embed更新
        def ids_to_display(ids):
            names = []
            for uid in ids:
                member = interaction.guild.get_member(int(uid))
                names.append(member.display_name if member else f"<@{uid}>")
            return "\n".join(names) if names else "なし"

        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            users = vote_data[message_id][self.date_str][k]
            embed.set_field_at(idx, name=k, value=ids_to_display(users), inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        # 参加3人以上で確定通知
        if len(vote_data[message_id][self.date_str]["参加(🟢)"]) >= 3:
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
# /event_now コマンド（任意のテストイベント作成）
# -----------------------------
@tree.command(name="event_now", description="突発テストイベント作成")
async def event_now(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel = bot.get_channel(TEST_CHANNEL_ID)
    if not channel:
        await interaction.followup.send("⚠️ チャンネルが見つかりません", ephemeral=True)
        return

    # 今日から1週間のテスト日程
    start_date = datetime.date.today()
    dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]

    for d in dates:
        embed = discord.Embed(title=f"【テストイベント】{d}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"🚨 テストイベントを作成しました！", ephemeral=True)

# -----------------------------
# バックグラウンドタスク（15:15に自動実行）
# -----------------------------
async def auto_run_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now()
        target_time = now.replace(hour=15, minute=15, second=0, microsecond=0)
        if now > target_time:
            target_time += datetime.timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        print(f"⏰ Auto run will start in {wait_seconds:.1f} seconds")
        await asyncio.sleep(wait_seconds)

        # 実行
        channel = bot.get_channel(TEST_CHANNEL_ID)
        if channel:
            start_date = datetime.date.today()
            dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
            for d in dates:
                embed = discord.Embed(title=f"【自動テストイベント】{d}", description="以下のボタンで投票してください")
                embed.add_field(name="参加(🟢)", value="なし", inline=False)
                embed.add_field(name="調整可(🟡)", value="なし", inline=False)
                embed.add_field(name="不可(🔴)", value="なし", inline=False)
                await channel.send(embed=embed, view=VoteView(d))
            print("✅ 自動テストイベントを送信しました")

        await asyncio.sleep(60)  # 念のため少し待って次のループ

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
    bot.loop.create_task(auto_run_task())
    print("⏰ Auto-run task started")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
