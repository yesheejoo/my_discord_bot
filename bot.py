import os
import io
import json
import csv
import random
import datetime
import time

import discord
from discord.ext import commands
from discord import Embed

# ───── 파일 경로 정의 ─────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POINTS_FILE = os.path.join(BASE_DIR, "database.json")
BANK_FILE = os.path.join(BASE_DIR, "bank.json")
POINT_LOG_FILE = os.path.join(BASE_DIR, "point_log.json")
INVENTORY_FILE = os.path.join(BASE_DIR, "inventory.json")
ITEMS_FILE = os.path.join(BASE_DIR, "items.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")
CRIME_LOG_FILE = os.path.join(BASE_DIR, "crime_log.json")

# ───── 전역 변수 초기화 ─────
user_join_times = {}    # 음성 채널 입장 시간 기록
user_mic_history = {}   # (timestamp, mic_on) 이력
user_points = {}        # 지갑 포인트
bank_data = {}          # 은행 포인트
activity_xp = {}        # 활동으로 획득한 경험치
admin_xp = {}           # 관리자가 지급한 경험치
gamble_points = {}      # 도박으로 얻은 포인트
gamble_losses = {}      # 도박으로 잃은 포인트
user_levels = {}        # 레벨 상태
checkin_log = {}        # 출석 기록
point_log = {}          # 날짜별 포인트 기록
daily_gamble_log = {}   # 도박 일별 기록
crime_log = {}          # 범죄 시도 기록

# 관리자 권한 ID 리스트
allowed_admin_ids = [518697602774990859, 1335240110358265967]

# ───── JSON 읽기/쓰기 헬퍼 ─────
def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ───── 포인트 & 은행 로드/저장 함수 ─────
def load_points():
    global user_points
    data = read_json(POINTS_FILE)
    user_points.clear()
    user_points.update(data)

def save_points():
    write_json(POINTS_FILE, user_points)

def load_bank():
    global bank_data
    data = read_json(BANK_FILE)
    bank_data.clear()
    bank_data.update(data)

def save_bank():
    write_json(BANK_FILE, bank_data)

def load_point_log():
    global point_log
    data = read_json(POINT_LOG_FILE)
    point_log.clear()
    point_log.update(data)

def save_point_log():
    write_json(POINT_LOG_FILE, point_log)

def load_crime_log():
    global crime_log
    data = read_json(CRIME_LOG_FILE)
    crime_log.clear()
    crime_log.update(data)

def save_crime_log():
    write_json(CRIME_LOG_FILE, crime_log)

def load_usernames():
    global_users = read_json(USERS_FILE)
    # 반환하지 않고 USERS_FILE에 저장된 상태를 글로 읽어둘 뿐

def save_username(member):
    users = read_json(USERS_FILE)
    uid = str(member.id)
    users[uid] = member.display_name
    write_json(USERS_FILE, users)

# ───── 봇 설정 ─────
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❗ BOT_TOKEN 환경변수가 설정되지 않았습니다.")

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ───── 음성 이탈 시 포인트 계산 함수 ─────
def process_voice_leave(uid, leave_time):
    """
    user_join_times와 user_mic_history에 남은 기록을 기반으로
    포인트를 계산하여 user_points와 activity_xp에 반영하고 저장한다.
    """
    join_time = user_join_times.pop(uid, None)
    mic_changes = user_mic_history.pop(uid, [])
    if not join_time:
        return

    # 마지막 기록으로 leave_time 추가
    mic_changes.append((leave_time, mic_changes[-1][1] if mic_changes else False))
    # join_time 이후의 기록만 남김
    mic_changes = [(t, m) for t, m in mic_changes if t >= join_time]

    total_points = 0.0
    for i in range(len(mic_changes) - 1):
        t1, mic_on = mic_changes[i]
        t2, _ = mic_changes[i + 1]
        minutes = (t2 - t1).total_seconds() / 60
        total_points += minutes * (2.0 if mic_on else 1.0)
    earned = int(total_points)

    # 기존 포인트 불러오기
    load_points()
    user_points[uid] = user_points.get(uid, 0) + earned
    activity_xp[uid] = activity_xp.get(uid, 0) + earned
    save_points()

# ───── 음성 상태 업데이트 ─────
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    now = datetime.datetime.utcnow()

    # 새로운 사용자라면 닉네임 저장
    save_username(member)

    # before.channel 및 after.channel 비교
    before_chan = before.channel
    after_chan = after.channel

    # 1) 완전 입장: before=None, after!=None
    if before_chan is None and after_chan:
        user_join_times[uid] = now
        user_mic_history[uid] = [(now, not after.self_mute)]

    # 2) 채널 이동: before!=None, after!=None, 채널 ID 다름
    elif before_chan and after_chan and before_chan.id != after_chan.id:
        # 이전 채널 이탈 처리
        process_voice_leave(uid, now)
        # 새 채널 입장 처리
        user_join_times[uid] = now
        user_mic_history[uid] = [(now, not after.self_mute)]

    # 3) 같은 채널 내부 마이크 상태 변화: before!=None, after!=None, 채널 ID 동일
    elif before_chan and after_chan and before_chan.id == after_chan.id:
        if uid in user_mic_history:
            user_mic_history[uid].append((now, not after.self_mute))

    # 4) 완전 이탈: before!=None, after=None
    elif before_chan and after_chan is None:
        process_voice_leave(uid, now)

# ───── 랭킹 관련 명령어 ─────
@bot.command()
async def 랭킹(ctx):
    load_points()
    if not user_points:
        await ctx.send("📉 아직 데이터가 없습니다.")
        return

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
    top10 = sorted_users[:10]
    description = "\n".join([f"**{i+1}.** <@{uid}> — {pt}점" for i, (uid, pt) in enumerate(top10)])

    embed = discord.Embed(
        title="🌞 TOP 10 랭킹",
        description=description,
        color=0xFFD700
    )
    await ctx.send(embed=embed)

@bot.command()
async def 꼴찌(ctx):
    load_points()
    if not user_points or len(user_points) < 10:
        await ctx.send("🔽 하위 10 유저를 볼 수 없습니다.")
        return

    sorted_users = sorted(user_points.items(), key=lambda x: x[1])
    bottom10 = sorted_users[:10]
    description = "\n".join([f"**{i+1}.** <@{uid}> — {pt}점" for i, (uid, pt) in enumerate(bottom10)])

    embed = discord.Embed(
        title="🌑 하위 10 랭킹",
        description=description,
        color=0xAAAAAA
    )
    await ctx.send(embed=embed)

@bot.command()
async def 평균(ctx):
    load_points()
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

# ───── 포인트 & 레벨 정보 ─────
@bot.command()
async def 포인트(ctx):
    uid = str(ctx.author.id)
    member = ctx.author

    load_points()
    load_bank()
    # 활동·관리자 XP 불러오기 (메모리 상 이미 있거나 없으면 0)
    activity = activity_xp.get(uid, 0)
    admin = admin_xp.get(uid, 0)
    total_xp = activity + admin

    wallet = user_points.get(uid, 0)
    bank = bank_data.get(uid, 0)
    total_point = wallet + bank

    # 레벨 계산
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
            f"• 🏃🏻 레벨 : {level}레벨\n"
            f"• 🔼 다음 레벨까지 : {next_level_xp:,} 포인트\n"
            f"• 📊 순위 : {rank}위 / {len(sorted_users)}명 중\n\n"
            f"• 💰 총 자산 : 지갑 {wallet:,} + 은행 {bank:,} = {total_point:,} 포인트\n\n"
            f"• 🎧 디스코드 활동 포인트 : {activity:,} 포인트\n"
            f"• 🧧 관리자 지급 포인트 : {admin:,} 포인트"
        ),
        color=0x55CCFF
    )
    await ctx.send(embed=embed)

    # 레벨업 메시지
    previous_level = user_levels.get(uid, 0)
    if level > previous_level:
        await ctx.send(f"💥 {member.display_name}님은 메카살인기의 축복을 받아 {previous_level} ➡️ {level} 레벨로 진화했습니다! ⚙️")

    user_levels[uid] = level

# ───── 도박 기능 ─────
@bot.command()
async def 도박(ctx, 배팅: int):
    load_points()
    uid = str(ctx.author.id)
    mention = ctx.author.mention

    if 배팅 <= 0 or user_points.get(uid, 0) < 배팅:
        await ctx.send(f"{mention} ❌ 유효하지 않은 배팅 금액입니다.")
        return

    user_points[uid] -= 배팅
    chance = random.randint(1, 100)
    gain = 0
    result_msg = ""

    if chance <= 65:
        result_msg = f"💀 실패! {배팅:,}점 잃었습니다."
        gamble_losses[uid] = gamble_losses.get(uid, 0) + 배팅
    elif chance <= 90:
        gain = 배팅 * 2
        result_msg = f"✨ 2배 당첨! {gain:,}점 획득!"
    elif chance <= 98:
        gain = 배팅 * 3
        result_msg = f"🎉 3배 당첨! {gain:,}점 획득!"
    else:
        gain = 배팅 * 10
        result_msg = f"🌟 10배 전설 당첨! {gain:,}점 획득!!"

    user_points[uid] += gain
    if gain > 0:
        gamble_points[uid] = gamble_points.get(uid, 0) + gain

    save_points()

    result_text = (
        f"{mention}님\n"
        f"{result_msg}\n"
        f"💰 보유 포인트: {user_points.get(uid, 0):,}점"
    )
    await ctx.send(result_text)

# ───── 슬롯머신 ─────
slot_jackpot = 0
slot_attempts = {}

@bot.command()
async def 슬롯(ctx):
    global slot_jackpot, slot_attempts
    load_points()

    uid = str(ctx.author.id)
    bet = 5

    if user_points.get(uid, 0) < bet:
        await ctx.send("❌ 포인트가 부족합니다. (5점 필요)")
        return

    # 베팅 차감 및 잭팟 누적
    user_points[uid] -= bet
    slot_jackpot += bet
    slot_attempts[uid] = slot_attempts.get(uid, 0) + 1

    jackpot_emojis = ["☀️", "🌙", "⭐", "🍀", "💣"]
    chance = random.random()

    if chance < 0.01:
        result = ["☀️"] * 5
    elif chance < 0.025:
        symbol = random.choice(["🌙", "⭐", "🍀", "💣"])
        result = [symbol] * 5
    else:
        while True:
            result = [random.choice(jackpot_emojis) for _ in range(5)]
            if len(set(result)) > 1:
                break

    most_common = max(set(result), key=result.count)
    match_count = result.count(most_common)
    lines = [f"🎰 결과 : {' '.join(result)}"]

    if match_count == 5:
        base_reward = int(slot_jackpot * 0.8)
        bonus_msg = ""
        is_solar = (most_common == "☀️")
        if is_solar:
            base_reward += 500
            bonus_msg = "• ☀️ **솔라잭팟!** 500포인트 추가 보너스!"

        user_points[uid] += base_reward

        # 20% 보너스 분배
        bonus_pool = slot_jackpot - int(slot_jackpot * 0.8)
        top_attempts = sorted(slot_attempts.items(), key=lambda x: x[1], reverse=True)
        recipients = [u for u, _ in top_attempts if u != uid][:2]
        share = bonus_pool // max(len(recipients), 1) if recipients else 0
        distributed = []

        for rid in recipients:
            user_points[rid] = user_points.get(rid, 0) + share
            distributed.append(f"<@{rid}> (+{share:,}점)")

        lines.append(f"• 🌟 {most_common} 5개! {ctx.author.mention}님이 잭팟을 터뜨렸습니다!")
        if bonus_msg:
            lines.append(bonus_msg)
        lines.append(f"• 🏆 당첨 보상 : {base_reward:,}점")
        if distributed:
            lines.append(f"• 🎁 보너스 분배 (20%) : {' / '.join(distributed)}")

        slot_jackpot = 0
        slot_attempts.clear()
    else:
        lines.append("• 💀 꽝! 누적 상금은 계속 쌓입니다...")
        lines.append(f"• 💰 남은 내 포인트 : {user_points[uid]:,}점")
        lines.append(f"• 💸 누적 잭팟 : {slot_jackpot:,}점")

    save_points()
    embed = Embed(
        title="**[슬롯머신 결과]**",
        description="\n".join(lines),
        color=0xf1c40f
    )
    await ctx.send(embed=embed)

# ───── 보내기 기능 ─────
@bot.command()
async def 보내기(ctx, member: discord.Member, 금액: int):
    load_points()
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
    save_points()

    await ctx.send(f"📤 <@{sender_id}>님이 <@{receiver_id}>님에게 {금액:,}점을 보냈습니다!")

# ───── 상점 출력 및 구매 ─────
@bot.command()
async def 상점(ctx):
    items = read_json(ITEMS_FILE)
    if not items:
        await ctx.send("📦 상점에 등록된 아이템이 없습니다.")
        return

    msg = "\n".join([f"{item['name']} — {item['price']}점" for item in items])
    await ctx.send(f"🛒 **상점 목록**\n{msg}")

@bot.command()
async def 구매(ctx, *, 아이템명):
    load_points()
    items = read_json(ITEMS_FILE)
    if not items:
        await ctx.send("❌ 상점 정보가 없습니다.")
        return

    item = next((i for i in items if i["name"] == 아이템명), None)
    if not item:
        await ctx.send("❗ 해당 아이템을 찾을 수 없습니다.")
        return

    uid = str(ctx.author.id)
    price = item["price"]
    if user_points.get(uid, 0) < price:
        await ctx.send("😢 포인트가 부족합니다.")
        return

    user_points[uid] -= price
    inv = read_json(INVENTORY_FILE)
    inv.setdefault(uid, []).append(item["name"])
    write_json(INVENTORY_FILE, inv)

    save_points()
    await ctx.send(f"🎉 `{item['name']}` 아이템을 구매했습니다!")

# ───── 포인트 기록 저장 및 다운로드 ─────
@bot.command()
async def 기록저장(ctx):
    load_points()
    load_point_log()
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    point_log[today] = {}
    for uid, pts in user_points.items():
        point_log[today][uid] = {
            "total": pts,
            "activity": activity_xp.get(uid, 0),
            "gamble": gamble_points.get(uid, 0)
        }

    save_point_log()
    await ctx.send(f"📦 {today} 기준 포인트 기록이 저장되었습니다!")

@bot.command()
async def 기록다운(ctx, 월: str):
    load_point_log()
    filtered = {date: data for date, data in point_log.items() if date.startswith(월)}
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

# ───── 전체 초기화 (관리자 전용) ─────
@bot.command()
async def 전체초기화(ctx):
    if ctx.author.id not in allowed_admin_ids:
        await ctx.send("🚫 이 명령어는 등록된 관리자만 사용할 수 있습니다.")
        return

    global user_points, activity_xp, admin_xp, gamble_points, gamble_losses, user_levels
    global checkin_log, point_log, daily_gamble_log, slot_jackpot, slot_attempts, bank_data, crime_log

    user_points.clear()
    activity_xp.clear()
    admin_xp.clear()
    gamble_points.clear()
    gamble_losses.clear()
    user_levels.clear()
    checkin_log.clear()
    point_log.clear()
    daily_gamble_log.clear()
    slot_jackpot = 0
    slot_attempts.clear()
    bank_data.clear()
    crime_log.clear()

    write_json(POINTS_FILE, {})
    write_json(POINT_LOG_FILE, {})
    write_json(BANK_FILE, {})
    write_json(INVENTORY_FILE, {})
    write_json(ITEMS_FILE, {})
    write_json(USERS_FILE, {})
    write_json(CRIME_LOG_FILE, {})

    await ctx.send("🔄 모든 유저 데이터가 초기화되었습니다. (포인트, 레벨, 기록 등)")

# ───── 출석 체크 기능 ─────
@bot.command()
async def 출석(ctx):
    load_points()
    uid = str(ctx.author.id)
    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    date_key = now_kst.strftime("%Y-%m-%d")

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
    save_points()

    if bonus_msg:
        await ctx.send(f"📅 {date_key} 출석체크 완료! {base_reward}포인트를 획득했습니다.\n{bonus_msg}")
    else:
        await ctx.send(f"📅 {date_key} 출석체크 완료! {base_reward}포인트를 획득했습니다.")

# ───── 관리자 수동 지급 ─────
@bot.command()
async def 지급(ctx, member: discord.Member, 점수: int):
    if ctx.author.id not in allowed_admin_ids:
        await ctx.send("🚫 이 명령어는 등록된 관리자만 사용할 수 있습니다.")
        return

    load_points()
    uid = str(member.id)
    user_points[uid] = user_points.get(uid, 0) + 점수
    admin_xp[uid] = admin_xp.get(uid, 0) + 점수
    save_points()

    with open(os.path.join(BASE_DIR, "admin_point_log.txt"), "a", encoding="utf-8") as f:
        f.write(f"{ctx.author.display_name} → {member.display_name}: {점수}점\n")

    await ctx.send(f"✅ {member.display_name}님에게 {점수}포인트를 지급했습니다!")

# ───── 도움말 ─────
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

# ───── 범죄 명령어 ─────
MAX_CRIMES_PER_DAY = 5

@bot.command()
async def 범죄(ctx, 유형: str = None, 대상: discord.Member = None):
    load_points()
    load_bank()
    load_crime_log()

    uid = str(ctx.author.id)
    now_ts = int(time.time())
    today_date = datetime.datetime.utcnow().date()

    # 오늘 자 범죄 기록만 남기기
    crime_log.setdefault(uid, [])
    crime_log[uid] = [
        ts for ts in crime_log[uid]
        if datetime.datetime.utcfromtimestamp(ts).date() == today_date
    ]

    if len(crime_log[uid]) >= MAX_CRIMES_PER_DAY:
        await ctx.send("🚨 하루 5번까지만 범죄를 시도할 수 있어요.")
        return

    msg = ""
    # 현재 유저 지갑 잔액
    user_wallet = user_points.get(uid, 0)

    if 유형 == "구걸":
        if random.random() < 0.85:
            gain = random.randint(10, 30)
            user_points[uid] = user_wallet + gain
            msg = f"🙏 {ctx.author.display_name}님이 구걸해서 {gain}포인트를 받았습니다!"
        else:
            fail_msgs = [
                "지나가던 인기가 침만 뱉고 갔습니다... 😢",
                "창대곤듀가 \"포인트 없어!\" 라고 말했습니다... 💨",
                "YESJ어르신이 지갑을 꺼내는 척만 했습니다... 🤥",
                "길에서 일규박에게 무시당했습니다. 현실입니다... 🧍",
            ]
            msg = f"❌ 구걸 실패! {random.choice(fail_msgs)}"

    elif 유형 == "뺏기" and 대상:
        target_id = str(대상.id)
        target_wallet = user_points.get(target_id, 0)

        # 30% 확률로 성공, 성공 시 총액의 10~30%를 탈취
        if random.random() < 0.3 and target_wallet > 0:
            percentage = random.uniform(0.1, 0.3)
            stolen = int(target_wallet * percentage)
            if stolen < 1:
                stolen = 1

            # 훔치기 성공
            user_points[uid] = user_wallet + stolen
            user_points[target_id] = max(target_wallet - stolen, 0)
            msg = f"🎯 {ctx.author.display_name}님이 {대상.display_name}의 지갑에서 {stolen}포인트를 훔쳤습니다!"
        else:
            # 뺏기 실패 시 보유 포인트의 10% 손실 (최소 1포인트)
            loss = max(int(user_wallet * 0.10), 1)
            user_points[uid] = max(user_wallet - loss, 0)
            msg = f"💥 뺏기 실패! {loss}포인트를 잃었습니다."

    elif 유형 == "강탈" and 대상:
        target_id = str(대상.id)
        target_wallet = user_points.get(target_id, 0)

        if random.random() < 0.05 and target_wallet > 0:
            # 강탈 성공: 지갑 전체 탈취
            stolen = target_wallet
            user_points[uid] = user_wallet + stolen
            user_points[target_id] = 0
            msg = f"😈 {ctx.author.display_name}님이 {대상.display_name}의 지갑을 털어 {stolen}포인트를 빼앗았습니다!"
        else:
            # 강탈 실패 시 보유 포인트의 20% 손실 (최소 1포인트)
            loss = max(int(user_wallet * 0.20), 1)
            user_points[uid] = max(user_wallet - loss, 0)
            msg = f"💥 강탈 실패! {loss}포인트를 잃었습니다."

    elif 유형 == "은행털기":
        # 전체 은행 잔액(자신 제외)
        total_bank = sum(v for u, v in bank_data.items() if u != uid)

        if random.random() < 0.01 and total_bank > 0:
            # 은행털기 성공: 전체 은행 자산의 절반을 훔치기
            steal_amount = total_bank // 2
            for u in list(bank_data.keys()):
                if u != uid:
                    bank_data[u] = int(bank_data[u] * 0.5)
            user_points[uid] = user_wallet + steal_amount
            msg = f"💣 {ctx.author.display_name}님이 은행을 털어 {steal_amount:,}포인트를 훔쳤습니다!"
        else:
            # 은행털기 실패 시 보유 포인트의 30% 손실 (최소 1포인트)
            loss = max(int(user_wallet * 0.30), 1)
            user_points[uid] = max(user_wallet - loss, 0)
            msg = f"💥 은행털기 실패! {loss}포인트를 잃었습니다."

    else:
        await ctx.send("사용 가능한 범죄 유형: `구걸`, `뺏기 @유저`, `강탈 @유저`, `은행털기`")
        return

    crime_log[uid].append(now_ts)
    save_crime_log()
    save_points()
    save_bank()
    await ctx.send(msg)


# ───── 은행 명령어 ─────
@bot.command()
async def 은행(ctx, *args):
    load_points()
    load_bank()
    uid = str(ctx.author.id)
    wallet = user_points.get(uid, 0)
    bank = bank_data.get(uid, 0)

    action, amount = None, 0
    if len(args) == 2:
        if args[0].isdigit():
            amount = int(args[0])
            action = args[1]
        elif args[1].isdigit():
            action = args[0]
            amount = int(args[1])
    elif len(args) == 1 and args[0] in ["입금", "출금"]:
        action = args[0]

    if action == "입금":
        if amount <= 0 or amount > wallet:
            await ctx.send("❌ 지갑에 충분한 포인트가 없어요.")
        else:
            user_points[uid] = wallet - amount
            bank_data[uid] = bank + amount
            save_points()
            save_bank()
            await ctx.send(f"🏦 {amount}포인트를 은행에 입금했습니다.")
    elif action == "출금":
        if amount <= 0 or amount > bank:
            await ctx.send("❌ 은행에 충분한 포인트가 없어요.")
        else:
            bank_data[uid] = bank - amount
            user_points[uid] = wallet + amount
            save_points()
            save_bank()
            await ctx.send(f"💼 {amount}포인트를 출금했습니다.")
    else:
        await ctx.send(
            f"📊 <@{uid}>님의 자산 현황\n"
            f"• 지갑: {wallet:,}포인트\n"
            f"• 은행: {bank:,}포인트\n\n"
            "예시: `!은행 입금 500`, `!은행 500 입금`, `!은행 출금 200`"
        )


@bot.command()
async def 은행도움말(ctx):
    embed = discord.Embed(
        title="🏦 [PERSO 은행 시스템 & 범죄 설명서]",
        description=(
            "**💼 은행이란?**\n"
            "• 당신의 포인트를 안전하게 보관하는 금고입니다.\n"
            "• 지갑 포인트는 도둑맞지만, 은행 포인트는 안전합니다.\n\n"
            "**🛠 사용법 예시**\n"
            "• `!은행` : 내 잔액 보기\n"
            "• `!은행 입금 500` 또는 `!은행 500 입금`\n"
            "• `!은행 출금 200` 또는 `!은행 200 출금`\n\n"
            "**🚨 범죄로부터 보호하세요!**\n"
            "다른 유저는 `!범죄` 명령어로 당신의 **지갑 포인트**를 훔칠 수 있어요!\n"
            "• `!범죄 구걸` → 85% 확률로 10~30포인트 획득\n"
            "• `!범죄 뺏기 @유저` → 30% 확률로 대상 지갑 보유 포인트의 10~30% 탈취\n"
            "    • 실패 시 자신의 지갑 보유 포인트의 **10%** 손실\n"
            "• `!범죄 강탈 @유저` → 5% 확률로 지갑 전체 탈취\n"
            "    • 실패 시 자신의 지갑 보유 포인트의 **20%** 손실\n"
            "• `!범죄 은행털기` → 전체 은행 자산의 절반을 훔치는 도전 (1% 확률)\n"
            "    • 실패 시 자신의 지갑 보유 포인트의 **30%** 손실\n\n"
            "**✅ 안전한 전략**\n"
            "1. `!출석`, `!도박` 등으로 포인트 획득\n"
            "2. `!은행 입금`으로 안전하게 보관\n"
            "3. 사용할 때만 `!은행 출금`으로 꺼내쓰기"
        ),
        color=0x88CFFA
    )
    await ctx.send(embed=embed)

# ───── 봇 실행 ─────
print("🤖 디스코드 봇 실행 준비 완료! 로그인 중...")
bot.run(TOKEN)
