import discord
from discord.ext import commands
import datetime
import json
import os
import random
import io
import csv

# ───── 기본 설정 ─────
with open("token.txt", "r") as f:
    TOKEN = f.read().strip()

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ───── 전역 변수 초기화 ─────
user_join_times = {}           # 음성 접속 시간 기록
user_mic_history = {}          # 마이크 상태 이력
user_points = {}               # 현재 보유 포인트
activity_xp = {}               # 디스코드 활동으로 얻은 경험치
admin_xp = {}                  # 관리자가 지급한 경험치
gamble_points = {}             # 도박으로 얻은 포인트
gamble_losses = {}             # 도박으로 잃은 포인트
user_levels = {}               # 레벨 상태
checkin_log = {}               # 출석 기록
point_log = {}                 # 포인트 히스토리 로그
daily_gamble_log = {}          # 도박 일일 기록

POINTS_FILE = "database.json"
INVENTORY_FILE = "inventory.json"
ITEMS_FILE = "items.json"
USERS_FILE = "users.json"
POINT_LOG_FILE = "point_log.json"

# ───── 유저 이름 저장 ─────
def save_username(member):
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
    except:
        users = {}
    uid = str(member.id)
    users[uid] = member.display_name
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

# ───── 음성 상태 추적 ─────
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    now = datetime.datetime.utcnow()

    try:
        with open(POINTS_FILE, "r", encoding="utf-8") as f:
            user_points.update(json.load(f))
    except:
        pass

    if before.channel is None and after.channel:
        user_join_times[uid] = now
        user_mic_history[uid] = [(now, not after.self_mute)]
    elif before.channel and after.channel:
        if uid in user_mic_history:
            user_mic_history[uid].append((now, not after.self_mute))
    elif before.channel and after.channel is None:
        join_time = user_join_times.pop(uid, None)
        mic_changes = user_mic_history.pop(uid, [])
        if join_time:
            mic_changes.append((now, mic_changes[-1][1] if mic_changes else False))
            mic_changes = [(t, m) for t, m in mic_changes if t >= join_time]
            total_points = 0.0
            for i in range(len(mic_changes) - 1):
                t1, mic_on = mic_changes[i]
                t2, _ = mic_changes[i + 1]
                minutes = (t2 - t1).total_seconds() / 60
                if mic_on:
                    total_points += minutes * 2.0
                else:
                    total_points += minutes * 1.0
            earned = int(total_points)
            user_points[uid] = user_points.get(uid, 0) + earned
            activity_points[uid] = activity_points.get(uid, 0) + earned

            with open(POINTS_FILE, "w", encoding="utf-8") as f:
                json.dump(user_points, f, indent=2)

# ───── 랭킹 출력 ─────
@bot.command()
async def 랭킹(ctx):
    try:
        with open(POINTS_FILE, "r", encoding="utf-8") as f:
            user_points.update(json.load(f))
    except:
        pass

    if not user_points:
        await ctx.send("📉 아직 데이터가 없습니다.")
        return

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
    top10 = sorted_users[:10]

    embed = discord.Embed(
    title="🌞 TOP 10 랭킹",
    description="\n".join([f"**{i+1}.** <@{uid}> — {pt}점" for i, (uid, pt) in enumerate(top10)]),
    color=0xFFD700
)
    await ctx.send(embed=embed)

@bot.command()
async def 꼴찌(ctx):
    try:
        with open(POINTS_FILE, "r", encoding="utf-8") as f:
            user_points.update(json.load(f))
    except:
        pass

    if not user_points or len(user_points) < 10:
        await ctx.send("🔽 하위 10 유저를 볼 수 없습니다.")
        return

    sorted_users = sorted(user_points.items(), key=lambda x: x[1])
    bottom10 = sorted_users[:10]

    embed = discord.Embed(
    title="🌑 하위 10 랭킹",
    description="\n".join([f"**{i+1}.** <@{uid}> — {pt}점" for i, (uid, pt) in enumerate(bottom10)]),
    color=0xAAAAAA
)
    await ctx.send(embed=embed)

@bot.command()
async def 평균(ctx):
    try:
        with open(POINTS_FILE, "r", encoding="utf-8") as f:
            user_points.update(json.load(f))
    except:
        pass

    if not user_points:
        await ctx.send("📉 아직 데이터가 없습니다.")
        return

    total = sum(user_points.values())
    avg = total // len(user_points)

    embed = discord.Embed(
    title="📈 전체 평균 포인트",
    description=(
        f"• **인원 수**: {len(user_points)}명\n"
        f"• **총합**: {total:,}점\n"
        f"• **1인 평균**: {avg:,}점"
    ),
    color=0x00AAFF
)
    await ctx.send(embed=embed)

# ───── 포인트 및 레벨 출력 명령어 ─────
# 허용된 관리자 닉네임 리스트
allowed_admin_ids = [518697602774990859, 1335240110358265967]

# 관리자만 활동 포인트 부여
@bot.command()
async def 활동추가(ctx, member: discord.Member, 점수: int):
    if ctx.author.id not in allowed_admin_ids:
        await ctx.send("🚫 이 명령어는 등록된 관리자만 사용할 수 있습니다.")
        return

    uid = str(member.id)
    user_points[uid] = user_points.get(uid, 0) + 점수
    activity_points[uid] = activity_points.get(uid, 0) + 점수
    await ctx.send(f"✅ {member.display_name}님에게 활동 포인트 {점수}점을 부여했습니다!")

@bot.command()
async def 포인트(ctx):
    uid = str(ctx.author.id)
    member = ctx.author

    activity = activity_xp.get(uid, 0)
    admin = admin_xp.get(uid, 0)
    total_xp = activity + admin
    gamble = gamble_points.get(uid, 0)
    loss = gamble_losses.get(uid, 0)
    total_point = user_points.get(uid, 0)

    def calculate_level(xp):
        thresholds = {1: 50, 2: 100, 3: 300, 4: 450, 5: 600, 6: 750, 7: 900, 8: 1100, 9: 1300, 10: float('inf')}
        level = 0
        for lvl, req in thresholds.items():
            if xp >= req:
                level = lvl
                xp -= req
            else:
                next_xp = req - xp
                break
        else:
            next_xp = 0
        return level, next_xp

    level, next_level_xp = calculate_level(total_xp)

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (u, _) in enumerate(sorted_users) if u == uid), None)

    embed = discord.Embed(
        title=f"{member.display_name} 님의 포인트 & 레벨 정보",
        description=(
    f"• 🧬 레벨 : {level}레벨\n"
    f"• 🔼 다음 레벨까지 : {next_level_xp:,} 포인트\n\n"
    f"• 📊 순위 : {rank}위 / {len(sorted_users)}명 중\n"
    f"• 📦 총합 : {total_point:,} 포인트\n"
    f"• 🛠 활동포인트 : {activity:,} 포인트\n"
    f"• 🎲 도박포인트 : {gamble:,} 포인트\n"
    f"⤷ 💸 잃은 포인트 : {loss:,} 포인트"
),
        color=0x55CCFF
    )
    await ctx.send(embed=embed)

    if uid in user_levels and level > user_levels[uid]:
        await ctx.send(f"💥 {member.display_name}님은 메카살인기의 축복을 받아 {user_levels[uid]} ➡️ {level} 레벨로 진화했습니다! ⚙️")

    user_levels[uid] = level

# ───── 도박 기능 ─────
@bot.command()
async def 도박(ctx, 배팅: int):
    uid = str(ctx.author.id)
    mention = ctx.author.mention

    if user_points.get(uid, 0) < 배팅 or 배팅 <= 0:
        await ctx.send(f"{mention} ❌ 유효하지 않은 배팅 금액입니다.")
        return

    user_points[uid] -= 배팅
    chance = random.randint(1, 100)
    result_msg = ""

    if chance <= 65:
        result_msg = f"{mention} 💀 실패! {배팅:,}점 잃었습니다."
        gamble_losses[uid] = gamble_losses.get(uid, 0) + 배팅
    elif chance <= 90:
        gain = 배팅 * 2
        user_points[uid] += gain
        gamble_points[uid] = gamble_points.get(uid, 0) + gain
        result_msg = f"{mention} ✨ 2배 당첨! {gain:,}점 획득!"
    elif chance <= 98:
        gain = 배팅 * 3
        user_points[uid] += gain
        gamble_points[uid] = gamble_points.get(uid, 0) + gain
        result_msg = f"{mention} 🎉 3배 당첨! {gain:,}점 획득!"
    else:
        gain = 배팅 * 10
        user_points[uid] += gain
        gamble_points[uid] = gamble_points.get(uid, 0) + gain
        result_msg = f"{mention} 🌟 10배 전설 당첨! {gain:,}점 획득!!"

    await ctx.send(f"{result_msg}\n💰 보유 포인트: {user_points[uid]:,}점")

# ───── 슬롯머신 ─────
slot_jackpot = 0  # 누적 잭팟
slot_attempts = {}  # 시도 기록

@bot.command()
async def 슬롯(ctx):
    
    # 🔄 포인트 데이터 최신화
    try:
        with open(POINTS_FILE, "r", encoding="utf-8") as f:
            user_points.update(json.load(f))
    except FileNotFoundError:
        pass
    global slot_jackpot, slot_attempts
    uid = str(ctx.author.id)
    bet = 5

    # 디버깅용 로그
    print(f"[슬롯 호출됨] 유저: {ctx.author.display_name}, UID: {uid}")

    if user_points.get(uid, 0) < bet:
        await ctx.send("❌ 포인트가 부족합니다. (5점 필요)")
        return

    user_points[uid] -= bet
    slot_jackpot += bet
    slot_attempts[uid] = slot_attempts.get(uid, 0) + 1

    symbols = ["☀️"] + ["🌙"] * 3 + ["⭐"] * 3 + ["🍀"] * 2 + ["💣"]
    result = [random.choice(symbols) for _ in range(5)]
    most_common = max(set(result), key=result.count)
    match_count = result.count(most_common)

    msg = ""

    if most_common == "☀️" and match_count == 5:
        sorted_attempts = sorted(slot_attempts.items(), key=lambda x: x[1], reverse=True)
        top_investors = [uid for uid, _ in sorted_attempts[:3]]
        bonus_pool = int(slot_jackpot * 0.2)
        jackpot_winner_reward = slot_jackpot - bonus_pool

        user_points[uid] = user_points.get(uid, 0) + jackpot_winner_reward

        share = bonus_pool // max(len(top_investors), 1)
        bonus_recipients = []
        for investor_uid in top_investors:
            user_points[investor_uid] = user_points.get(investor_uid, 0) + share
            bonus_recipients.append(f"<@{investor_uid}> (+{share:,}점)")

        msg = f"""🌞 해 5개! <@{uid}>님이 잭팟을 터뜨렸습니다!
🏆 당첨 보상: {jackpot_winner_reward:,}점
🎁 보너스 분배(20%): {' / '.join(bonus_recipients)}"""

        slot_jackpot = 0
        slot_attempts.clear()
    else:
        msg = "💀 꽝! 누적 상금은 계속 쌓입니다..."

    with open(POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_points, f, indent=2)

    embed = discord.Embed(title="🎰 슬롯머신 결과", color=0xFFA500)
    embed.add_field(name="🎞 결과", value=" ".join(result), inline=False)
    embed.add_field(name="📢 메시지", value=msg, inline=False)
    embed.add_field(name="💰 현재 포인트", value=f"{user_points[uid]:,}점", inline=False)
    embed.add_field(name="💼 누적 잭팟", value=f"{slot_jackpot:,}점", inline=False)

    print(f"[슬롯 결과] {result} | 유저: {ctx.author.display_name} | 메시지: {msg}")
    await ctx.send(embed=embed)

# ───── 보내기 기능 ─────
@bot.command()
async def 보내기(ctx, member: discord.Member, 금액: int):
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    if 금액 <= 0:
        await ctx.send("❌ 0보다 큰 금액을 입력하세요.")
        return

    if sender_id == receiver_id:
        await ctx.send("❗ 자기 자신에게는 보낼 수 없습니다.")
        return

    if user_points.get(sender_id, 0) < 금액:
        await ctx.send("😢 포인트가 부족합니다.")
        return

    user_points[sender_id] -= 금액
    user_points[receiver_id] = user_points.get(receiver_id, 0) + 금액

    with open(POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_points, f, indent=2)

    await ctx.send(f"📤 <@{sender_id}>님이 <@{receiver_id}>님에게 {금액:,}점을 보냈습니다!")

# ───── 상점 출력 및 구매 ─────
@bot.command()
async def 상점(ctx):
    try:
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except FileNotFoundError:
        await ctx.send("❌ 상점 아이템 파일이 없습니다.")
        return

    if not items:
        await ctx.send("📦 상점에 등록된 아이템이 없습니다.")
        return

    msg = "\n".join([f"{item['name']} — {item['price']}점" for item in items])
    await ctx.send(f"🛒 **상점 목록**\n{msg}")

@bot.command()
async def 구매(ctx, *, 아이템명):
    uid = str(ctx.author.id)

    try:
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except FileNotFoundError:
        await ctx.send("❌ 상점 정보가 없습니다.")
        return

    item = next((i for i in items if i["name"] == 아이템명), None)
    if not item:
        await ctx.send("❗ 해당 아이템을 찾을 수 없습니다.")
        return

    if user_points.get(uid, 0) < item["price"]:
        await ctx.send("😢 포인트가 부족합니다.")
        return

    user_points[uid] -= item["price"]

    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            inv = json.load(f)
    except:
        inv = {}

    inv.setdefault(uid, []).append(item["name"])

    with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=2, ensure_ascii=False)

    with open(POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_points, f, indent=2)

    await ctx.send(f"🎉 `{item['name']}` 아이템을 구매했습니다!")

# ───── 포인트 기록 저장 및 다운로드 ─────
@bot.command()
async def 기록저장(ctx):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    try:
        with open(POINT_LOG_FILE, "r", encoding="utf-8") as f:
            point_log.update(json.load(f))
    except:
        point_log.clear()

    point_log[today] = {}
    for uid in user_points:
        point_log[today][uid] = {
            "total": user_points.get(uid, 0),
            "activity": activity_points.get(uid, 0),
            "gamble": gamble_points.get(uid, 0)
        }

    with open(POINT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(point_log, f, indent=2, ensure_ascii=False)

    await ctx.send(f"📦 {today} 기준 포인트 기록이 저장되었습니다!")

@bot.command()
async def 기록다운(ctx, 월: str):
    try:
        with open(POINT_LOG_FILE, "r", encoding="utf-8") as f:
            log_data = json.load(f)
    except FileNotFoundError:
        await ctx.send("❌ 저장된 포인트 기록이 없습니다.")
        return

    filtered = {date: data for date, data in log_data.items() if date.startswith(월)}
    if not filtered:
        await ctx.send(f"❌ '{월}' 에 해당하는 기록이 없습니다.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["날짜", "유저ID", "총합", "활동점수", "도박점수"])

    for date, users in filtered.items():
        for uid, vals in users.items():
            writer.writerow([date, uid, vals.get("total", 0), vals.get("activity", 0), vals.get("gamble", 0)])

    buffer.seek(0)
    file = discord.File(fp=io.BytesIO(buffer.read().encode()), filename=f"포인트기록_{월}.csv")
    await ctx.send(file=file)

# 관리자 권한 ID 리스트
allowed_admin_ids = [518697602774990859, 1335240110358265967]

# 출석 체크 기능
@bot.command()
async def 출석(ctx):
    uid = str(ctx.author.id)
    today = datetime.datetime.utcnow() + datetime.timedelta(hours=9)  # 한국 시간 기준
    date_key = today.strftime("%Y-%m-%d")

    if uid not in checkin_log:
        checkin_log[uid] = []

    if date_key in checkin_log[uid]:
        await ctx.send(f"❗ 이미 {date_key}에 출석하셨습니다.")
        return

    base_reward = 10
    bonus = 0
    bonus_msg = ""

    chance = random.randint(1, 100)
    if chance <= 5:
        bonus = 40
        bonus_msg = "💥 당신의 출석은 메카살인기의 심장을 깨웠습니다.\n🎉 대박! 추가로 40포인트와 경험치를 획득했습니다!"
    elif chance <= 30:
        bonus = random.randint(1, 5)
        bonus_msg = f"✨ 보너스 {bonus}포인트와 경험치를 추가로 획득했습니다!"

    total = base_reward + bonus
    user_points[uid] = user_points.get(uid, 0) + total
    activity_xp[uid] = activity_xp.get(uid, 0) + total
    checkin_log[uid].append(date_key)

    if bonus_msg:
        await ctx.send(f"📅 {date_key} 출석체크 완료! {base_reward}포인트를 획득했습니다.\n{bonus_msg}")
    else:
        await ctx.send(f"📅 {date_key} 출석체크 완료! {base_reward}포인트를 획득했습니다.")

# 관리자 수동 지급
@bot.command()
async def 지급(ctx, member: discord.Member, 점수: int):
    if ctx.author.id not in allowed_admin_ids:
        await ctx.send("🚫 이 명령어는 등록된 관리자만 사용할 수 있습니다.")
        return

    uid = str(member.id)
    user_points[uid] = user_points.get(uid, 0) + 점수
    admin_xp[uid] = admin_xp.get(uid, 0) + 점수

    with open("admin_point_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{ctx.author.display_name} → {member.display_name}: {점수}점\n")

    await ctx.send(f"✅ {member.display_name}님에게 지급 경험치 {점수}점을 부여했습니다!")

# 도움말 명령어
@bot.command()
async def 도움말(ctx):
    embed = discord.Embed(
        title="[(๑•̀ㅂ•́)و✧ 메카살인기 봇 명령어 설명서]",
        description=(
            "• **!출석** : 하루 1회 출석 체크 - 랜덤 보너스 포함\n"
            "• **!포인트** : 내 포인트, 경험치, 순위, 레벨 확인\n"
            "• **!슬롯** : 5포인트로 잭팟 도전\n"
            "• **!도박 금액** : 포인트를 걸고 2~10배 도전\n"
            "• **!보내기 @유저 금액** : 다른 유저에게 포인트 선물\n\n"
            "**💡 포인트는 어떻게 얻나요?**\n"
            "• 디스코드 음성 채널 접속 시 자동 누적\n"
            "  └ 마이크 켜짐: 1분당 2 포인트\n"
            "  └ 마이크 꺼짐: 1분당 1 포인트\n"
            "• !출석으로 하루 1회 기본 10 포인트 + 랜덤 보너스\n"
            "• 슬롯 / 도박 명령어로 포인트 획득 가능\n"
            "• 친구에게 포인트 선물도 가능!\n\n"
            "**🏆 포인트 랭킹은 어떻게 확인하나요?**\n"
            "• !포인트 입력 시, 현재 내 순위가 자동으로 표시됩니다.\n"
            "• 랭킹은 보유 포인트 기준으로 계산됩니다!"
        ),
        color=0xFF4444
    )
    await ctx.send(embed=embed)

# ───── 실행 ─────
print("🤖 디스코드 봇 실행 준비 완료! 로그인 중...")
bot.run(TOKEN)
