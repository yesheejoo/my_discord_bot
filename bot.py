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
from collections import defaultdict

# ───── 파일 경로 정의 ─────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POINTS_FILE    = os.path.join(BASE_DIR, "database.json")
POINT_LOG_FILE = os.path.join(BASE_DIR, "point_log.json")
INVENTORY_FILE = os.path.join(BASE_DIR, "inventory.json")
ITEMS_FILE     = os.path.join(BASE_DIR, "items.json")
USERS_FILE     = os.path.join(BASE_DIR, "users.json")
TALENT_STORE_FILE = os.path.join(BASE_DIR, "talent_store.json")
DATA_FILE = "attendance_data.json"

# ───── 관리자 권한 ID 리스트 ─────
allowed_admin_ids = [518697602774990859, 1335240110358265967]

def is_admin():
    from discord.ext.commands import check
    def predicate(ctx):
        return ctx.author.id in allowed_admin_ids
    return check(predicate)

# ───── 전역 변수 초기화 ─────
user_join_times   = {}  # {uid: datetime}
user_mic_history  = {}  # {uid: [(timestamp, mic_on), ...]}
user_points       = {}  # dict[str, int]
activity_xp       = {}  # dict[str, int]
adm               = {}  # dict[str, int]
gamble_points     = {}  # dict[str, int]
gamble_losses     = {}  # dict[str, int]
user_levels       = {}  # dict[str, int]
checkin_log       = {}  # dict[str, list[str]]        # 출석 기록 (누적)
streak_log        = {}  # dict[str, int]       # 연속 출석 기록
point_log         = {}  # dict[str, dict]
beg_log           = {}  # dict[str, list[str]]
slot_jackpot      = 1000  # 슬롯머신 초기 잭팟 기본값 변경 (기본 1000포인트)
slot_attempts     = {}

# ───── 슬롯머신 참가 비용 설정 ─────
SLOT_COST         = 10    # 슬롯머신 1회 참가 비용 (기본값 10포인트)

# ───── JSON 헬퍼 ─────
def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ───── 포인트 로드/저장 ─────
def load_points():
    global data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
            data.update(loaded_data)
    except FileNotFoundError:
        save_points()

def save_points():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ───── 사용자 닉네임 저장 ─────
def save_username(member):
    users = read_json(USERS_FILE)
    users[str(member.id)] = member.display_name
    write_json(USERS_FILE, users)

# ───── 봇 설정 ─────
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN이 설정되지 않았습니다.")

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ───── 포인트/XP 비율 ─────
POINT_RATE = {"off": 1, "on": 2}

# ───── 레벨 계산 ─────
def xp_for_next(level: int) -> int:
    return 50 + (level - 1) * 10

def calculate_level(total_xp: int):
    lvl, xp = 1, total_xp
    while True:
        need = xp_for_next(lvl)
        if xp < need:
            return lvl, need - xp
        xp -= need
        lvl += 1

# ───── 랭크 매핑 (LoL) ─────
MAJOR_RANKS = [
    (9, "언랭크"), (19, "Iron"), (29, "Bronze"), (39, "Silver"),
    (49, "Gold"), (59, "Platinum"), (69, "Emerald"), (79, "Diamond"),
    (89, "Master"), (99, "GrandMaster"), (100, "Challenger")
]
def get_rank(level: int) -> str:
    if level <= 9:
        return "언랭크"
    if level == 100:
        return "Challenger"
    for max_lv, name in MAJOR_RANKS:
        if level <= max_lv:
            start = max_lv - 9
            off = level - start
            tier = "IV" if off <= 3 else "III" if off <= 6 else "II" if off <= 8 else "I"
            return f"{name} {tier}"
    return "언랭크"

# ───── 음성 이탈 처리 ─────
def process_voice_leave(uid, leave_time):
    join = user_join_times.pop(uid, None)
    hist = user_mic_history.pop(uid, [])
    if not join:
        return
    hist.append((leave_time, hist[-1][1] if hist else False))
    hist = [(t, m) for t, m in hist if t >= join]
    total = 0.0
    for (t1, on), (t2, _) in zip(hist, hist[1:]):
        mins = (t2 - t1).total_seconds() / 60
        total += mins * (POINT_RATE['on'] if on else POINT_RATE['off'])
    earned = int(total)
    load_points()
    user_points[uid] = user_points.get(uid, 0) + earned
    activity_xp[uid] = activity_xp.get(uid, 0) + earned
    save_points()

# ───── 음성 상태 업데이트 ─────
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    now = datetime.datetime.utcnow()
    save_username(member)
    prev, curr = before.channel, after.channel
    if not prev and curr:
        user_join_times[uid] = now
        user_mic_history[uid] = [(now, not after.self_mute)]
    elif prev and curr and prev.id != curr.id:
        process_voice_leave(uid, now)
        user_join_times[uid] = now
        user_mic_history[uid] = [(now, not after.self_mute)]
    elif prev and curr and prev.id == curr.id:
        user_mic_history.setdefault(uid, []).append((now, not after.self_mute))
    elif prev and not curr:
        process_voice_leave(uid, now)

# ───── 랭킹 ─────
@bot.command()
async def 랭킹(ctx):
    load_points()
    if not user_points:
        return await ctx.send("📉 아직 데이터가 없습니다.")
    top = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
    desc = "\n".join(f"**{i+1}.** <@{u}> — {p:,}포인트" for i, (u, p) in enumerate(top))
    await ctx.send(embed=Embed(title="**🌞 TOP 10 랭킹**", description=desc, color=0xFFD700))

# ───── 평균 ─────
@bot.command()
async def 평균(ctx):
    load_points()
    if not user_points:
        return await ctx.send("📉 아직 데이터가 없습니다.")
    total = sum(user_points.values())
    cnt = len(user_points)
    avg = total // cnt
    desc = (
        f"• **인원 수**: {cnt}명\n"
        f"• **총합**: {total:,}점\n"
        f"• **1인 평균**: {avg:,}점"
    )
    await ctx.send(embed=Embed(title="**📈 전체 평균 포인트**", description=desc, color=0x00AAFF))

# ───── 포인트 & 레벨 정보 ─────
@bot.command()
async def 포인트(ctx):
    load_points()
    uid = str(ctx.author.id)
    act = activity_xp.get(uid, 0)
    adm = admin_xp.get(uid, 0)
    txp = act + adm
    lvl, nxt = calculate_level(txp)
    pts = user_points.get(uid, 0)
    rank = next((i + 1 for i, (u, _) in enumerate(sorted(user_points.items(), key=lambda x: x[1], reverse=True)) if u == uid), None)
    cur = sum(xp_for_next(i) for i in range(1, lvl))
    prog = int((txp - cur) / xp_for_next(lvl) * 10)
    bar = "▰" * prog + "▱" * (10 - prog)
    e = Embed(title=f"**{ctx.author.display_name} 님의 포인트 & 레벨 정보**", color=0x55CCFF)
    e.description = (
        f"• 🏃🏻 레벨 : {get_rank(lvl)} ({lvl})\n"
        f"  📈 진척도 : {bar}\n\n"
        f"• 🔼 다음 레벨까지 : {nxt:,} 포인트\n"
        f"• 📊 순위 : {rank}위 / {len(user_points)}명 중\n\n\n"
        f"• 💰 총 포인트 : {pts:,} 포인트\n\n"
        f"• 🎧 활동 포인트:\n    • 디코 활동 : {act:,} 포인트\n    • 관리자 지급 : {adm:,} 포인트\n    • 도박 획득 : {gamble_points.get(uid, 0):,} 포인트"
    )
    await ctx.send(embed=e)
    prev_lvl = user_levels.get(uid, 0)
    if lvl > prev_lvl:
        await ctx.send(f"💥 {ctx.author.display_name}님은 메카살인기의 축복을 받아 {prev_lvl} ➡️ {lvl} 레벨로 진화했습니다! ⚙️")
    user_levels[uid] = lvl

# ───── 출석 체크 ─────
# 출석 보상 설정
milestone_rewards = {
    5: 50, 10: 100, 15: 150, 20: 200, 30: 300, 50: 500, 75: 750, 100: 1000
}

# 병맛 giver 리스트
givers = ["Margo", "지봄이", "노듀오", "리망쿠", "인영킴이", "영규", "슝슝이", "재앙이"]

# ───── 출석 체크 ─────
@bot.command()
async def 출석(ctx):
    load_points()
    uid = str(ctx.author.id)
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")

    data["checkin_log"].setdefault(uid, [])
    data["streak_log"].setdefault(uid, 0)
    data["user_points"].setdefault(uid, 0)
    data["activity_xp"].setdefault(uid, 0)

    if today in data["checkin_log"][uid]:
        return await ctx.send(f"❗ 이미 {today}에 출석하셨습니다.")

    yesterday = (datetime.datetime.utcnow() + datetime.timedelta(hours=9) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if yesterday in data["checkin_log"][uid]:
        data["streak_log"][uid] += 1
    else:
        data["streak_log"][uid] = 1

    # 기본 출석 보상
    base_reward = 50
    bonus = 0

    chance = random.randint(1, 100)
    if chance <= 5:
        bonus = 40
    elif chance <= 30:
        bonus = random.randint(1, 5)

    total = base_reward + bonus
    data["user_points"][uid] += total
    data["activity_xp"][uid] += total
    data["checkin_log"][uid].append(today)

    total_checkins = len(data["checkin_log"][uid])
    milestone_bonus = milestone_rewards.get(total_checkins, 0)
    milestone_msg = ""

    if milestone_bonus > 0:
        data["user_points"][uid] += milestone_bonus
        data["activity_xp"][uid] += milestone_bonus

        giver = random.choice(givers)
        meme_messages = [
            f"{giver}가 튀어나와 포인트를 던지고 사라졌습니다! 🏃‍♂️💨",
            f"{giver}가 '아 몰라~' 하고 포인트를 던졌습니다. 🤷‍♂️",
            f"{giver}가 '이 정도면 만족?' 하며 {milestone_bonus}포인트를 던져줬습니다. 😏",
            f"{giver}가 조용히 포인트를 밀어넣고 아무 일 없다는 듯 사라졌습니다. 🕶️"
        ]
        selected_meme = random.choice(meme_messages)
        milestone_msg = f"🎯 누적 {total_checkins}일 출석 보상! {selected_meme}"

    save_points()

    # 최종 출력
    message = (
        f"📅 출석 완료 : 출쳌 {total}포인트를 획득했습니다!\n"
        f"📖 누적 출석 일수: {total_checkins}일차 입니다!\n"
        f"🔥 현재 연속 출석: {data['streak_log'][uid]}일차 유지중입니다!"
    )
    if milestone_bonus > 0:
        message += f"\n{milestone_msg}"

    await ctx.send(message)

# ───── 출석 현황 ─────
@bot.command()
async def 출석현황(ctx):
    load_points()
    uid = str(ctx.author.id)

    total_days = len(data["checkin_log"].get(uid, []))
    streak_days = data["streak_log"].get(uid, 0)

    next_milestone = None
    for milestone in sorted(milestone_rewards.keys()):
        if total_days < milestone:
            next_milestone = milestone - total_days
            break

    message = f"📊 {ctx.author.display_name}님의 출석 현황\n"
    message += f"총 출석일: {total_days}일\n"
    message += f"연속 출석일: {streak_days}일\n"
    if next_milestone:
        message += f"다음 마일스톤까지 {next_milestone}일 남았습니다! 🔥"
    else:
        message += "최고 마일스톤 달성중입니다! 🎉"

    await ctx.send(message)

# ───── 월간 출석 랭킹 ─────
@bot.command()
async def 출석랭킹(ctx):
    load_points()
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    this_month = now.strftime("%Y-%m")

    monthly_counts = defaultdict(int)
    for uid, dates in data["checkin_log"].items():
        monthly_counts[uid] = sum(1 for d in dates if d.startswith(this_month))

    ranking = sorted(monthly_counts.items(), key=lambda x: x[1], reverse=True)

    message = f"🏆 {now.strftime('%Y년 %m월')} 출석 랭킹 🏆\n"
    for idx, (uid, count) in enumerate(ranking[:10], 1):
        try:
            member = await ctx.guild.fetch_member(int(uid))
            message += f"{idx}위: {member.display_name} - {count}일 출석\n"
        except:
            message += f"{idx}위: Unknown User - {count}일 출석\n"

    await ctx.send(message)

# ───── 관리자 지급 ─────
@bot.command()
async def 지급(ctx, member: discord.Member, 점수: int):
    if ctx.author.id not in allowed_admin_ids:
        return await ctx.send("🚫 관리자 전용 명령어입니다.")
    load_points()
    uid = str(member.id)
    user_points[uid] = user_points.get(uid, 0) + 점수
    admin_xp[uid] = admin_xp.get(uid, 0) + 점수
    save_points()
    with open(os.path.join(BASE_DIR, "admin_point_log.txt"), "a", encoding="utf-8") as f:
        f.write(f"{ctx.author.display_name} → {member.display_name}: {점수}점\n")
    await ctx.send(f"✅ {member.display_name}님에게 {점수}포인트 지급 완료.")

# ───── 구걸 ─────
@bot.command()
async def 구걸(ctx):
    load_points()
    uid = str(ctx.author.id)
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    if uid not in beg_log:
        beg_log[uid] = []
    if beg_log[uid].count(today) >= 5:
        return await ctx.send(f"❗ 하루 5번까지만 구걸할 수 있어요! (이미 {beg_log[uid].count(today)}회 시도)")
    success = random.random() < 0.85
    if success:
        gain = random.randint(10, 30)
        user_points[uid] = user_points.get(uid, 0) + gain
        msg = f"🙏 {ctx.author.display_name}님이 구걸해서 {gain}포인트를 받았습니다!"
    else:
        fail_msgs = [
            "지나가던 인기가 침만 뱉고 갔습니다... 😢",
            "창대곤듀가 \"포인트 없어!\" 라고 말했습니다... 💨",
            "YESJ어르신이 지갑을 꺼내는 척만 했습니다... 🤥",
            "길에서 일규박에게 무시당했습니다. 현실입니다... 🧍",
            "침형님도 '없다'고 하셨습니다... 🕳️",
            "코끼리가 '내가 다 쓸어갔다'라고 하더라고요… 🐘",
            "유나대장이 슬쩍 가져갔다는 소문이… 😏",
        ]
        reason = random.choice(fail_msgs)
        msg = f"{ctx.author.mention} ❌ 구걸 실패!\n{reason}"
    beg_log[uid].append(today)
    save_points()
    await ctx.send(msg)

# ───── 도박 ─────
@bot.command()
async def 도박(ctx, 배팅: int):
    load_points()
    uid = str(ctx.author.id)
    mention = ctx.author.mention

    if 배팅 <= 0 or user_points.get(uid, 0) < 배팅:
        return await ctx.send(f"{mention} ❌ 유효하지 않은 배팅 금액입니다.")

    user_points[uid] -= 배팅
    chance = random.uniform(0, 100)  # 실수 기반으로 더 정확한 분포
    gain = 0

    if chance < 58.5:
        result_msg = f"💀 실패! {배팅:,}점 잃었습니다."
        gamble_losses[uid] = gamble_losses.get(uid, 0) + 배팅

    elif chance < 94:  # 58.5 + 35.5
        gain = 배팅 * 2
        result_msg = f"✨ 2배 당첨! {gain:,}점 획득!"

    elif chance < 99:  # 94 + 5
        gain = 배팅 * 3
        result_msg = f"🎉 3배 당첨! {gain:,}점 획득!"

    else:  # 나머지 1%
        gain = 배팅 * 10
        result_msg = f"🌟 10배 전설 당첨! {gain:,}점 획득!!"

    user_points[uid] += gain
    if gain > 0:
        gamble_points[uid] = gamble_points.get(uid, 0) + gain

    save_points()
    await ctx.send(f"{mention}님\n{result_msg}\n💰 보유 포인트: {user_points.get(uid, 0):,}점")

@bot.command()
async def 도박랭킹(ctx):
    if not gamble_points:
        return await ctx.send("📉 아직 도박 승리 기록이 없습니다.")

    # 상위 10명 기준 정렬
    top = sorted(gamble_points.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for i, (uid, total_win) in enumerate(top, 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"유저({uid})"
        lines.append(f"**{i}.** {name} — 🎰 {total_win:,} 포인트")

    desc = "\n".join(lines)

    embed = Embed(
        title="**💸 도박으로 얻은 포인트 랭킹 TOP 10**",
        description=desc,
        color=0xF39C12  # 골드 톤
    )
    embed.set_footer(text="메카살인기 • 솔라리스")
    await ctx.send(embed=embed)

# ───── 슬롯머신 ─────
@bot.command()
async def 슬롯(ctx):
    global slot_jackpot, slot_attempts
    load_points()
    uid = str(ctx.author.id)
    bet = 10
    if user_points.get(uid, 0) < bet:
        return await ctx.send("❌ 포인트 부족 (10점 필요)")
    user_points[uid] -= bet
    slot_jackpot += bet
    slot_attempts[uid] = slot_attempts.get(uid, 0) + 1

    emojis = ["☀️", "🌙", "⭐", "🍀", "💣"]
    chance = random.random()

    if chance < 0.005:  # 솔라 잭팟 0.5%
        result = ["☀️"] * 5
    elif chance < 0.015:  # 다른 잭팟 1%
        sym = random.choice(emojis[1:])
        result = [sym] * 5
    else:
        while True:
            result = [random.choice(emojis) for _ in range(5)]
            if len(set(result)) > 1:
                break

    common = max(set(result), key=result.count)
    cnt = result.count(common)
    lines = [f"🎰 결과 : {' '.join(result)}"]

    if cnt == 5:
        reward = int(slot_jackpot * 0.8)
        bonus_msg = ""
        if common == "☀️":
            reward += 500
            bonus_msg = "• ☀️ **솔라잭팟!** 500포인트 추가 보너스!"
        user_points[uid] += reward
        pool = slot_jackpot - int(slot_jackpot * 0.8)
        top2 = sorted(slot_attempts.items(), key=lambda x: x[1], reverse=True)
        recip = [u for u, _ in top2 if u != uid][:2]
        share = pool // len(recip) if recip else 0
        dist = [f"<@{r}> (+{share:,}점)" for r in recip]
        lines.append(f"• 🌟 {common} 5개 잭팟! 획득: {reward:,}점")
        if bonus_msg:
            lines.append(bonus_msg)
        if dist:
            lines.append(f"• 🎁 분배: {' / '.join(dist)}")
        slot_jackpot = 1000 + sum(slot_attempts.values()) * bet
        slot_attempts.clear()
    else:
        lines.append("• 💀 꽝! 잭팟 누적 중...")
        lines.append(f"• 💰 남은 포인트: {user_points[uid]:,}점")
        lines.append(f"• 💸 잭팟: {slot_jackpot:,}점")

    save_points()
    await ctx.send(embed=Embed(title="**[슬롯머신 결과]**", description="\n".join(lines), color=0xf1c40f))

# ───── 보내기 ─────
@bot.command()
async def 보내기(ctx, member: discord.Member, 금액: int):
    load_points()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)
    if 금액 <= 0:
        return await ctx.send("❌ 0보다 큰 금액을 입력하세요.")
    if sender_id == receiver_id:
        return await ctx.send("❗ 자기 자신에게는 보낼 수 없습니다.")
    if user_points.get(sender_id, 0) < 금액:
        return await ctx.send("😢 포인트가 부족합니다.")
    user_points[sender_id] -= 금액
    user_points[receiver_id] = user_points.get(receiver_id, 0) + 금액
    save_points()
    await ctx.send(f"📤 <@{sender_id}>님이 <@{receiver_id}>님에게 {금액:,}점 보냈습니다!")

# ───── 전체 초기화 (관리자 전용) ─────
@bot.command()
@is_admin()
async def 전체초기화(ctx):
    user_points.clear()
    activity_xp.clear()
    admin_xp.clear()
    gamble_points.clear()
    gamble_losses.clear()
    user_levels.clear()
    checkin_log.clear()
    point_log.clear()
    beg_log.clear()
    slot_attempts.clear()
    global slot_jackpot
    slot_jackpot = 0
    write_json(POINTS_FILE, {})
    write_json(POINT_LOG_FILE, {})
    write_json(INVENTORY_FILE, {})
    write_json(ITEMS_FILE, {})
    write_json(USERS_FILE, {})
    await ctx.send("🔄 모든 유저 데이터 초기화 완료.")

# ───── 재능 상점 가격 모듈 ─────
TALENT_THEME_PRICING = {
    "game_coaching": 5000,
    "labor_hiring": 1000,
    "design_art": 10000,
    "writing": 1000,
    "music_production": 20000,
    "video_editing": 20000,
    "misc": 1000
}

def calculate_talent_price(theme: str, duration_min: int) -> int:
    return int(TALENT_THEME_PRICING.get(theme, 0) * (duration_min / 60.0))

# ───── 도움말 ─────
@bot.command()
async def 도움말(ctx):
    embed = Embed(
        title="메카살인기 • 솔라리스 봇 도움말",
        color=0xFFA500
    )
    embed.add_field(
        name="**💡 포인트 획득 방법**",
        value="• 음성채널: 마이크 켜짐 2포인트/분, 꺼짐 1포인트/분",
        inline=False
    )
    embed.add_field(
        name="**📅 출석 체크**",
        value="• `!출석` 하루 1회(자정 기준) 기본 50포인트 + 랜덤 보너스",
        inline=False
    )
    embed.add_field(
        name="**💰 포인트 & 레벨 조회**",
        value="• `!포인트` 내 포인트, XP, 레벨, 진척도 바, 순위 확인",
        inline=False
    )
    embed.add_field(
        name="**🏆 순위 및 통계**",
        value="• `!랭킹` TOP 10 순위 / `!평균` 인원 수 · 총합 · 1인 평균",
        inline=False
    )
    embed.add_field(
        name="**🙏 구걸**",
        value="• `!구걸` 하루 최대 5회, 성공 시 10~30포인트 획득 (XP 미획득)",
        inline=False
    )
    embed.add_field(
        name="**🎲 도박**",
        value="• `!도박 [금액]` 65% 실패 · 25% ×2배 · 8% ×3배 · 2% ×10배 (포인트만)",
        inline=False
    )
    embed.add_field(
        name="**🎰 슬롯머신**",
        value="• `!슬롯` 10포인트 참가, 기본 풀 1,000포인트 → 1.0% 솔라잭팟 / 1.5% 일반 잭팟 / 97.5% 꽝",
        inline=False
    )
    embed.add_field(
        name="**📤 포인트 전송**",
        value="• `!보내기 @유저 [금액]` 다른 유저에게 포인트 선물",
        inline=False
    )
    embed.set_footer(text="메카살인기 • 솔라리스")
    await ctx.send(embed=embed)

# ───── 재능 상점 ─────
# 테마 리스트
THEMES = [
    "게임 강의·코칭",
    "노동 인력 구인",
    "그림 및 디자인",
    "글귀 및 글쓰기",
    "음악 제작·믹싱",
    "영상 제작·편집",
    "잡동사니 재능"
]

# 파일 로드/저장 헬퍼

def load_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# 재능상점 판매 명령어
@bot.command()
async def 재능상점판매(ctx, action=None, *, args=None):
    user_id = str(ctx.author.id)
    store = load_file(TALENT_STORE_FILE)
    points = load_file(POINT_FILE)

    if user_id not in store:
        store[user_id] = {"theme": None, "items": []}

    if action == "상점테마결정":
        if args not in THEMES:
            return await ctx.send(f"❌ 잘못된 테마입니다. 가능 테마: {', '.join(THEMES)}")
        
        if points.get(user_id, 0) < 500:
            return await ctx.send("❌ 테마 설정을 위해 최소 500포인트가 필요합니다.")
        
        store[user_id]["theme"] = args
        points[user_id] = points.get(user_id, 0) - 500
        save_file(TALENT_STORE_FILE, store)
        save_file(POINT_FILE, points)
        await ctx.send(f"✨ 상점 테마가 '{args}'로 설정되었습니다. (500포인트 차감)")

    elif action == "판매상품등록":
        if store[user_id]["theme"] is None:
            return await ctx.send("❗ 먼저 상점테마결정을 해주세요.")

        parts = args.split()
        if len(parts) < 3:
            return await ctx.send("❗ 등록 형식: !재능상점판매 판매상품등록 상품이름 가격 판매여부(True/False)")

        name, price, active = parts[0], int(parts[1]), parts[2].lower() == 'true'
        
        if len(store[user_id]["items"]) >= 5:
            return await ctx.send("❗ 최대 5개 상품까지만 등록 가능합니다.")

        store[user_id]["items"].append({"name": name, "price": price, "active": active})
        save_file(TALENT_STORE_FILE, store)
        await ctx.send(f"✅ '{name}' 상품이 {price}코인으로 등록되었습니다. (판매상태: {'판매중' if active else '판매중지'})")

    elif action == "판매상품관리":
        if not store[user_id]["items"]:
            return await ctx.send("📦 등록된 상품이 없습니다.")
        lines = [f"• {it['name']} — {it['price']}코인 ({'판매중' if it['active'] else '판매중지'})" for it in store[user_id]['items']]
        await ctx.send("**내 상품 목록**\n" + "\n".join(lines))

    else:
        await ctx.send("사용법: !재능상점판매 상점테마결정/판매상품등록/판매상품관리 <args>")

# 재능상점 구경 명령어
@bot.command()
async def 재능상점구경(ctx):
    store = load_file(TALENT_STORE_FILE)
    if not store:
        return await ctx.send("📭 활성화된 재능 상점이 없습니다.")

    lines = []
    for sid, info in store.items():
        member = ctx.guild.get_member(int(sid))
        if not member: continue
        item_lines = []
        for it in info["items"]:
            if it["active"]:
                item_lines.append(f"- {it['name']} ({it['price']}코인)")
        if item_lines:
            lines.append(f"**{member.display_name}님의 상점 ({info['theme']})**\n" + "\n".join(item_lines))

    if lines:
        await ctx.send("**재능 상점 목록**\n" + "\n\n".join(lines))
    else:
        await ctx.send("📭 현재 판매중인 상품이 없습니다.")

# 재능상점 구매 명령어
@bot.command()
async def 재능상점구매(ctx, seller: discord.Member = None, *, item_name=None):
    if not seller or not item_name:
        return await ctx.send("사용법: !재능상점구매 @판매자 상품명")

    user_id = str(ctx.author.id)
    sid = str(seller.id)
    store = load_file(TALENT_STORE_FILE)
    points = load_file(POINT_FILE)

    if sid not in store:
        return await ctx.send("❌ 판매자를 찾을 수 없습니다.")

    product = next((it for it in store[sid]["items"] if it["name"] == item_name and it["active"]), None)
    if not product:
        return await ctx.send("❌ 상품이 존재하지 않거나 판매중이 아닙니다.")

    price = product["price"]
    if points.get(user_id, 0) < price:
        return await ctx.send("❌ 구매를 위한 포인트가 부족합니다.")

    # 포인트 이동
    points[user_id] = points.get(user_id, 0) - price
    points[sid] = points.get(sid, 0) + price

    save_file(POINT_FILE, points)
    await ctx.send(f"🎉 {seller.display_name}님의 상품 '{item_name}'을(를) {price}코인에 구매 완료!")

# ───── 봇 실행 ─────
print("🤖 메카살인기봇 준비 완료! 로그인 중...")
bot.run(TOKEN)
