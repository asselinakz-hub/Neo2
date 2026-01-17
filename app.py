# app.py
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st

# ВАЖНО: первый вызов Streamlit
st.set_page_config(
    page_title="💠 NEO Диагностика потенциалов (v8)",
    page_icon="💠",
    layout="centered",
)

# ======================
# STORAGE
# ======================
DATA_DIR = Path("data")
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

APP_VERSION = "mvp-8.0-positions-24"

MASTER_PASSWORD = st.secrets.get("MASTER_PASSWORD", os.getenv("MASTER_PASSWORD", ""))

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
DEFAULT_MODEL = st.secrets.get("OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))


# ======================
# HELPERS
# ======================
def utcnow_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"

def save_session(payload: dict):
    sid = payload["meta"]["session_id"]
    session_path(sid).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def load_session(session_id: str):
    p = session_path(session_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

def list_sessions():
    out = []
    for p in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


# ======================
# OPENAI
# ======================
def get_openai_client():
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None

def safe_model_name(model: str) -> str:
    if not model:
        return DEFAULT_MODEL
    m = model.strip()
    if m.startswith("gpt-5"):
        return DEFAULT_MODEL
    return m


# ======================
# POTENTIALS / SPHERES
# ======================
POTS = ["Янтарь","Шунгит","Цитрин","Изумруд","Рубин","Гранат","Сапфир","Гелиодор","Аметист"]

# Сферы для 1 потенциала (как ты описала)
SPHERE_MAP = {
    "emotions": ["Изумруд", "Гранат", "Рубин"],     # эмоции
    "matter":   ["Янтарь", "Шунгит", "Цитрин"],     # материя
    "meanings": ["Сапфир", "Гелиодор", "Аметист"],  # смыслы
}

COLUMNS = ["perception", "motivation", "instrument"]
COL_LABELS = {
    "perception": "Восприятие (как видит мир)",
    "motivation": "Мотивация (что включает)",
    "instrument": "Инструмент (как действует)",
}

POS_LABELS = {
    1: "Позиция 1 — главный фильтр восприятия",
    2: "Позиция 2 — что включает мотивацию",
    3: "Позиция 3 — главный способ действия",
    4: "Позиция 4 — второй фильтр восприятия",
    5: "Позиция 5 — второй слой мотивации",
    6: "Позиция 6 — второй инструмент действия",
}


# ======================
# QUESTION BANK (24)
# 6 позиций * 4 вопроса:
# Q1-2: sphere (emotions/matter/meanings)
# Q3-4: choose pot within that sphere
# ======================
def _sphere_q(position: int, column: str, qn: int, text: str):
    return {
        "id": f"p{position}_s{qn}",
        "position": position,
        "column": column,
        "stage": "sphere",
        "type": "single",
        "text": text,
        "options": [
            {"id": "emotions", "text": "Эмоции / атмосфера / красота / отношения"},
            {"id": "matter",   "text": "Действия / деньги / польза / результат"},
            {"id": "meanings", "text": "Смысл / идея / понимание / почему так"},
        ]
    }

def _pot_q(position: int, column: str, qn: int, sphere: str, text: str, options: list):
    # options: list of tuples (pot_name, option_text)
    return {
        "id": f"p{position}_p{qn}_{sphere}",
        "position": position,
        "column": column,
        "stage": "potential",
        "sphere": sphere,
        "type": "single",
        "text": text,
        "options": [{"id": pot, "text": opt} for pot, opt in options]
    }

def question_plan():
    # Колонки по позициям: 1/4 perception, 2/5 motivation, 3/6 instrument
    pos_col = {
        1: "perception",
        2: "motivation",
        3: "instrument",
        4: "perception",
        5: "motivation",
        6: "instrument",
    }

    plan = []

    # intake (короткий)
    plan += [
        {"id":"intake.name","position":0,"column":"perception","stage":"intake","type":"text","text":"Как тебя зовут? (или как удобно)"},
        {"id":"intake.request","position":0,"column":"motivation","stage":"intake","type":"text","text":"С каким запросом ты пришёл(пришла)? (1–2 фразы)"},
        {"id":"intake.contact","position":0,"column":"instrument","stage":"intake","type":"text","text":"Оставь телефон или email (куда отправить полный разбор)."},
    ]

    # 6 позиций
    for pos in range(1, 7):
        col = pos_col[pos]

        # 2 вопроса на сферу (бытом)
        plan.append(_sphere_q(pos, col, 1, f"({POS_LABELS[pos]}) Представь: ты в новой ситуации. Что у тебя включается ПЕРВЫМ?"))
        plan.append(_sphere_q(pos, col, 2, "Когда ты понимаешь, что это «твоё» — что решает?"))

        # 3 сферы -> по 2 вопроса на потенциал внутри сферы
        # meanings: Сапфир / Гелиодор / Аметист
        plan.append(_pot_q(
            pos, col, 3, "meanings",
            "Если речь про ИДЕЮ/смысл: что ты чаще делаешь автоматически?",
            [
                ("Сапфир",   "Слушаю/вникаю: логично ли это, «попадает ли в ноту», что тут не работает"),
                ("Гелиодор", "Понимаю: будет ли это интересно людям, как рассказать, чтобы «зашло»"),
                ("Аметист",  "Вижу ход событий: к чему это приведёт, как упаковать и куда вести людей"),
            ]
        ))
        plan.append(_pot_q(
            pos, col, 4, "meanings",
            "Как тебе проще находить правильный ответ по сложному вопросу?",
            [
                ("Сапфир",   "В тишине: послушать себя / убрать шум / понять смысл"),
                ("Гелиодор", "Проговорить вслух / обсудить / в диалоге «рождается истина»"),
                ("Аметист",  "По ощущению «я просто знаю» / предчувствую / вижу сценарий"),
            ]
        ))

        # emotions: Изумруд / Гранат / Рубин
        plan.append(_pot_q(
            pos, col, 5, "emotions",
            "Если про ЭМОЦИИ/атмосферу: что для тебя самый точный индикатор «да/нет»?",
            [
                ("Изумруд", "Картинка и чувство внутри: красиво/гармонично или нет"),
                ("Гранат",  "Мимика/отклик людей: хочется играть эмоцией, вовлекать, контакт"),
                ("Рубин",   "Внутренний всплеск/адреналин: «заводит/не заводит» на уровне тела"),
            ]
        ))
        plan.append(_pot_q(
            pos, col, 6, "emotions",
            "В компании людей ты чаще:",
            [
                ("Изумруд", "Замечаю детали/внешний вид/атмосферу и «собираю красоту»"),
                ("Гранат",  "Становлюсь душой компании: смеюсь, плачу, заряжаю эмоциями"),
                ("Рубин",   "Ловлю драйв, напряжение, химия, возбуждение/интерес"),
            ]
        ))

        # matter: Янтарь / Шунгит / Цитрин
        plan.append(_pot_q(
            pos, col, 7, "matter",
            "Если про ДЕЛА/деньги: что ты оцениваешь в первую очередь?",
            [
                ("Янтарь", "Система/механизм: что сломано и как починить, порядок и устройство"),
                ("Шунгит", "Форма/тело/пространство: «идёт/не идёт», тянет ли в действие"),
                ("Цитрин", "Выгода/эффективность: где больше результат за меньше усилий"),
            ]
        ))
        plan.append(_pot_q(
            pos, col, 8, "matter",
            "Когда надо быстро принять решение по делу, ты больше доверяешь:",
            [
                ("Янтарь", "Ощущению комфорта/дискомфорта в животе, внутренним ощущениям"),
                ("Шунгит", "Телу в движении: хочется идти/делать или «тело не тянет»"),
                ("Цитрин", "Кожным ощущениям/движению: приятное–неприятное, мурашки, динамика"),
            ]
        ))

    # Итого: 3 intake + 6*(2+6) = 3 + 48 = 51 — слишком много.
    # Поэтому мы оставляем РОВНО 4 вопроса на позицию:
    # 2 sphere + 2 pot (по выбранной сфере).
    # Ниже — отметим, что выше мы нагенерили расширенный список,
    # а реальный отбор сделаем в UI: после ответов sphere — покажем только соответствующие 2 pot.
    return plan


# ======================
# STATE
# ======================
def init_state():
    st.session_state.setdefault("session_id", str(uuid.uuid4()))
    st.session_state.setdefault("q_index", 0)
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("event_log", [])
    st.session_state.setdefault("master_authed", False)

def reset_diagnostic():
    for k in ["q_index","answers","event_log"]:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["q_index"] = 0
    st.session_state["answers"] = {}
    st.session_state["event_log"] = []


# ======================
# UI KEY (чтобы текст НЕ переносился)
# ======================
def ui_key_for_question(qid: str, session_id: str) -> str:
    return f"q_{session_id}_{qid}"


def render_question(q: dict, session_id: str):
    st.markdown(f"### {q['text']}")
    qtype = q["type"]
    key = ui_key_for_question(q["id"], session_id)

    if qtype == "text":
        return st.text_area("Ответ:", height=120, key=key)

    # single
    opts = q.get("options", [])
    labels = [o["text"] for o in opts]
    ids = [o["id"] for o in opts]
    pick = st.radio("Выбери вариант:", labels, key=key)
    return ids[labels.index(pick)]


def is_nonempty(q: dict, ans):
    if q["type"] == "text":
        return bool(str(ans or "").strip())
    return bool(ans)


def current_meta(answers: dict):
    return (
        str(answers.get("intake.name","") or "").strip(),
        str(answers.get("intake.request","") or "").strip(),
        str(answers.get("intake.contact","") or "").strip(),
    )
    # ======================
# CORE LOGIC:
# мы НЕ задаём 8 вопросов на позицию.
# Мы задаём 2 sphere + 2 pot только по выбранной сфере.
# Для этого делаем "динамический план" в рантайме.
# ======================

def build_dynamic_plan():
    """
    База:
    - intake: 3
    - позиции 1..6: на каждой позиции
        * 2 sphere вопроса
        * затем 2 pot вопроса в выбранной сфере (meanings/emotions/matter)
    Итого: 3 + 6*4 = 27 вопросов
    """
    pos_col = {1:"perception",2:"motivation",3:"instrument",4:"perception",5:"motivation",6:"instrument"}

    plan = [
        {"id":"intake.name","position":0,"column":"perception","stage":"intake","type":"text","text":"Как тебя зовут? (или как удобно)"},
        {"id":"intake.request","position":0,"column":"motivation","stage":"intake","type":"text","text":"С каким запросом ты пришёл(пришла)? (1–2 фразы)"},
        {"id":"intake.contact","position":0,"column":"instrument","stage":"intake","type":"text","text":"Оставь телефон или email (куда отправить полный разбор)."},
    ]

    for pos in range(1, 7):
        col = pos_col[pos]
        # sphere
        plan.append(_sphere_q(pos, col, 1, f"({POS_LABELS[pos]}) Представь: ты в новой ситуации. Что у тебя включается ПЕРВЫМ?"))
        plan.append(_sphere_q(pos, col, 2, "Когда ты понимаешь, что это «твоё» — что решает?"))

        # placeholder для 2 pot вопросов — добавим после того, как узнаем sphere
        plan.append({"id": f"p{pos}_potA", "position": pos, "column": col, "stage":"pot_placeholder", "type":"placeholder"})
        plan.append({"id": f"p{pos}_potB", "position": pos, "column": col, "stage":"pot_placeholder", "type":"placeholder"})

    return plan


def resolve_pot_questions_for_position(pos: int, chosen_sphere: str, column: str):
    """
    Возвращает ровно 2 вопроса на потенциал внутри выбранной сферы.
    """
    if chosen_sphere == "meanings":
        qA = _pot_q(
            pos, column, 1, "meanings",
            "С идеями ты чаще:",
            [
                ("Сапфир",   "Слышу/чувствую «работает/не работает», люблю тишину и смысл"),
                ("Гелиодор", "Начинаю говорить/объяснять, понимаю что «зайдёт» людям"),
                ("Аметист",  "Вижу сценарии и стратегию: к чему это приведёт"),
            ]
        )
        qB = _pot_q(
            pos, column, 2, "meanings",
            "Чтобы понять решение, тебе проще:",
            [
                ("Сапфир",   "Остановиться и осмыслить в тишине"),
                ("Гелиодор", "Проговорить/обсудить вслух"),
                ("Аметист",  "Поймать ощущение «я знаю» / предчувствие"),
            ]
        )
        return qA, qB

    if chosen_sphere == "emotions":
        qA = _pot_q(
            pos, column, 1, "emotions",
            "Про людей и атмосферу ты чаще:",
            [
                ("Изумруд", "Замечаю красоту/детали/картинку и чувствую гармонию"),
                ("Гранат",  "Читаю мимику/эмоции, люблю контакт и «движуху людей»"),
                ("Рубин",   "Ловлю драйв/химию/внутренний всплеск"),
            ]
        )
        qB = _pot_q(
            pos, column, 2, "emotions",
            "Когда тебе нравится идея/проект, это ощущается как:",
            [
                ("Изумруд", "«красиво и правильно внутри»"),
                ("Гранат",  "хочется делиться, играть эмоцией, выступать"),
                ("Рубин",   "включается адреналин/страсть/желание"),
            ]
        )
        return qA, qB

    # matter
    qA = _pot_q(
        pos, column, 1, "matter",
        "В делах/работе ты чаще:",
        [
            ("Янтарь", "вижу, что не работает в системе/механизме, чиню и навожу порядок"),
            ("Шунгит", "включаюсь через тело/движение/пространство"),
            ("Цитрин", "сразу считаю выгоду и эффективность"),
        ]
    )
    qB = _pot_q(
        pos, column, 2, "matter",
        "Как ты быстрее понимаешь «моё/не моё» по делу?",
        [
            ("Янтарь", "по ощущению комфорта/дискомфорта внутри (живот)"),
            ("Шунгит", "по телу: тянет действовать или «не тянет»"),
            ("Цитрин", "по ощущению динамики/мурашкам/приятно–неприятно"),
        ]
    )
    return qA, qB


def dynamic_question_plan(answers: dict):
    """
    Возвращает итоговый список вопросов с уже подставленными pot-вопросами.
    """
    base = build_dynamic_plan()
    out = []
    pos_col = {1:"perception",2:"motivation",3:"instrument",4:"perception",5:"motivation",6:"instrument"}

    for q in base:
        if q.get("type") != "placeholder":
            out.append(q)
            continue

        # placeholder -> подставляем 2 pot вопроса в зависимости от sphere
        # sphere выбираем по ответам p{pos}_s1 и p{pos}_s2 (берём большинство; если ничья — берём s1)
        pos = q["position"]
        s1 = answers.get(f"p{pos}_s1")
        s2 = answers.get(f"p{pos}_s2")
        chosen = s1 if s1 else s2
        if s1 and s2 and s1 != s2:
            chosen = s1  # простой tie-break

        if not chosen:
            # пока сферу не ответили — в план не вставляем pot-вопросы
            # но placeholder оставим как "заглушку" (чтобы индексы совпадали)
            # на UI мы просто не дадим дойти до них, т.к. sphere вопросы будут раньше
            continue

        col = pos_col[pos]
        qA, qB = resolve_pot_questions_for_position(pos, chosen, col)

        # Вставляем только один из двух (в зависимости от того, какой placeholder)
        if q["id"].endswith("potA"):
            out.append(qA)
        else:
            out.append(qB)

    return out


# ======================
# SCORING
# ======================
def score_all(answers: dict):
    pot_scores = {p: 0.0 for p in POTS}
    pos_scores = {str(i): {p: 0.0 for p in POTS} for i in range(1, 7)}
    col_scores = {c: {p: 0.0 for p in POTS} for c in COLUMNS}

    # динамический план нужен, чтобы мы знали position/column каждого реально заданного вопроса
    plan = dynamic_question_plan(answers)

    # быстрый индекс id -> meta
    idx = {q["id"]: q for q in plan if q.get("id")}

    for qid, ans in answers.items():
        q = idx.get(qid)
        if not q:
            continue
        if q.get("stage") != "potential":
            continue

        pot = ans  # ans = pot name (мы так вернули в render_question)
        if pot not in POTS:
            continue

        pos = q.get("position", 0)
        col = q.get("column", None)

        pot_scores[pot] += 1.0
        if pos in [1,2,3,4,5,6]:
            pos_scores[str(pos)][pot] += 1.0
        if col in COLUMNS:
            col_scores[col][pot] += 1.0

    return pot_scores, {}, col_scores, pos_scores


def top_list(scores: dict, n=3):
    ranked = sorted(scores.items(), key=lambda x: float(x[1]), reverse=True)
    return [{"pot": p, "score": float(s)} for p, s in ranked[:n]]


def build_payload(answers: dict, event_log: list, session_id: str):
    scores, evidence, col_scores, pos_scores = score_all(answers)
    name, request, contact = current_meta(answers)

    ranked = sorted(scores.items(), key=lambda x: float(x[1]), reverse=True)
    top3 = [{"pot": p, "score": float(s)} for p, s in ranked[:3]]
    top6 = [{"pot": p, "score": float(s)} for p, s in ranked[:6]]

    payload = {
        "meta": {
            "schema": "ai-neo.session.v8",
            "app_version": APP_VERSION,
            "timestamp": utcnow_iso(),
            "session_id": session_id,
            "name": name,
            "request": request,
            "contact": contact,
            "question_count": len(dynamic_question_plan(answers)),
            "answered_count": len(event_log),
        },
        "answers": answers,
        "scores": scores,
        "col_scores": col_scores,
        "pos_scores": pos_scores,
        "top3": top3,
        "top6": top6,
        "event_log": event_log,
        "ai_client_report": "",
        "ai_master_report": "",
    }
    return payload


def build_insight_table(payload: dict) -> dict:
    meta = payload.get("meta", {})
    scores = payload.get("scores", {})
    col_scores = payload.get("col_scores", {})
    pos_scores = payload.get("pos_scores", {})
    answers = payload.get("answers", {})

    # короткая выжимка ответов
    keys = ["intake.request", "intake.current_state", "intake.goal_3m"]
    excerpt = {k: answers.get(k) for k in keys if k in answers}

    return {
        "meta": meta,
        "top3": top_list(scores, 3),
        "top6": top_list(scores, 6),
        "columns": {
            c: top_list(col_scores.get(c, {}), 3) for c in COLUMNS
        },
        "positions": {
            f"pos_{i}": top_list(pos_scores.get(str(i), {}), 3) for i in range(1, 7)
        },
        "answers_excerpt": excerpt,
    }


# ======================
# REPORTS
# ======================
def call_openai_for_reports(client, model: str, payload: dict):
    table = build_insight_table(payload)
    sys = (
        "Ты — эксперт по диагностике потенциалов NEO.\n"
        "Сгенерируй 2 отчёта:\n"
        "A) CLIENT: 12–18 строк. Назови потенциалы (можно), пройдись по колонкам "
        "(восприятие/мотивация/инструмент) и по 1–2 рискам. "
        "Скажи, что отчёт предварительный и предложи консультацию.\n"
        "B) MASTER: структурно: топ-5, колонки, позиции, конфликты, что уточнить, "
        "и как вести к реализации/монетизации.\n"
        "Пиши по-русски, конкретно, без воды."
    )

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": sys},
            {"role": "user", "content": json.dumps(table, ensure_ascii=False)}
        ],
        response_format={"type": "json_object"},
    )

    txt = resp.output_text
    data = json.loads(txt) if txt else {}
    client_report = data.get("client_report", "")
    master_report = data.get("master_report", "")
    return client_report, master_report


# ======================
# CLIENT FLOW
# ======================
def render_client_flow():
    plan = dynamic_question_plan(st.session_state["answers"])
    total = len(plan)

    colA, colB = st.columns([3, 1])
    with colA:
        stage = plan[min(st.session_state["q_index"], total - 1)]["stage"] if total else "—"
        st.caption(f"Ход: вопрос {min(st.session_state['q_index']+1, total)} из {total} | этап: {stage}")

    with colB:
        if st.button("🔄 Сбросить", use_container_width=True):
            reset_diagnostic()
            st.rerun()

    done = st.session_state["q_index"] >= total

    if not done:
        q = plan[st.session_state["q_index"]]
        ans = render_question(q, st.session_state["session_id"])

        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Далее ➜", use_container_width=True):
                if not is_nonempty(q, ans):
                    st.warning("Заполни ответ.")
                else:
                    st.session_state["answers"][q["id"]] = ans
                    st.session_state["event_log"].append({
                        "timestamp": utcnow_iso(),
                        "question_id": q["id"],
                        "question_text": q["text"],
                        "answer_type": q["type"],
                        "answer": ans
                    })
                    st.session_state["q_index"] += 1

                    # пересчитаем план (после sphere ответы появятся pot вопросы)
                    st.rerun()

        with c2:
            if st.button("Завершить сейчас", use_container_width=True):
                payload = build_payload(st.session_state["answers"], st.session_state["event_log"], st.session_state["session_id"])
                save_session(payload)
                st.session_state["q_index"] = total
                st.rerun()

    else:
        payload = build_payload(st.session_state["answers"], st.session_state["event_log"], st.session_state["session_id"])
        try:
            save_session(payload)
        except Exception:
            pass

        st.success("Диагностика завершена ✅")
        st.markdown("### Предварительный результат (технический)")
        st.json(build_insight_table(payload))


# ======================
# MASTER PANEL
# ======================
def render_master_panel():
    st.subheader("🛠️ Мастер-панель")

    if not st.session_state.get("master_authed", False):
        pwd = st.text_input("Пароль мастера", type="password", key="master_pwd")
        if st.button("Войти", use_container_width=True):
            if not MASTER_PASSWORD:
                st.error("MASTER_PASSWORD не задан в secrets/env.")
            elif pwd == MASTER_PASSWORD:
                st.session_state["master_authed"] = True
                st.success("Ок ✅")
                st.rerun()
            else:
                st.error("Неверный пароль")
        st.stop()

    sessions = list_sessions()
    if not sessions:
        st.info("Пока нет сохранённых сессий.")
        st.stop()

    labels, ids = [], []
    for s in sessions:
        sid = s.get("meta", {}).get("session_id", "")
        name = s.get("meta", {}).get("name", "—")
        req = s.get("meta", {}).get("request", "—")
        ts = s.get("meta", {}).get("timestamp", "—")
        labels.append(f"{name} | {req} | {ts} | {sid[:8]}")
        ids.append(sid)

    pick = st.selectbox("Сессии:", labels, index=0, key="master_pick")
    chosen_id = ids[labels.index(pick)]
    payload = load_session(chosen_id)
    if not payload:
        st.error("Не удалось загрузить сессию.")
        st.stop()

    meta = payload.get("meta", {})
    st.markdown(
        f"**Имя:** {meta.get('name','—')}\n\n"
        f"**Контакт:** {meta.get('contact','—')}\n\n"
        f"**Запрос:** {meta.get('request','—')}\n\n"
        f"**Вопросов:** {meta.get('question_count','—')} | **Ответов:** {meta.get('answered_count','—')}\n"
    )

    st.download_button(
        "⬇️ Скачать JSON",
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"session_{chosen_id[:8]}.json",
        mime="application/json",
        use_container_width=True
    )

    with st.expander("📌 Таблица инсайтов (для мастера)"):
        st.json(build_insight_table(payload))

    st.markdown("---")
    st.subheader("🧠 AI-отчёты")

    model_in = st.text_input("Модель", value=DEFAULT_MODEL, key="master_model")

    if st.button("Сгенерировать AI-отчёт", use_container_width=True):
        client = get_openai_client()
        if not client:
            st.error("Нет OPENAI_API_KEY в secrets/env")
        else:
            try:
                model = safe_model_name(model_in)
                cr, mr = call_openai_for_reports(client, model, payload)

                st.markdown("### Клиентский отчёт")
                st.write(cr)
                st.markdown("### Мастерский отчёт")
                st.write(mr)

                payload["ai_client_report"] = cr
                payload["ai_master_report"] = mr
                save_session(payload)
                st.success("Готово ✅ сохранено в сессии.")
            except Exception as e:
                st.error(f"Ошибка генерации: {e}")

    if payload.get("ai_client_report") or payload.get("ai_master_report"):
        with st.expander("🗂️ Показать сохранённые AI-отчёты"):
            if payload.get("ai_client_report"):
                st.markdown("#### Клиентский")
                st.write(payload["ai_client_report"])
            if payload.get("ai_master_report"):
                st.markdown("#### Мастерский")
                st.write(payload["ai_master_report"])


# ======================
# MAIN
# ======================
init_state()

st.title("💠 NEO Диагностика потенциалов (v8)")

tab1, tab2 = st.tabs(["🧑‍💼 Клиент", "🛠️ Мастер"])

with tab1:
    render_client_flow()

with tab2:
    render_master_panel()