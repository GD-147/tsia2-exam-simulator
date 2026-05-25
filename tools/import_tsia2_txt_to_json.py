#!/usr/bin/env python3
from pathlib import Path
import json
import re
import sys

SRC_DIR = Path("imports/tsia2_exams/txt")
OUT_DIR = Path("packs/tsia2/data")
CONFIG_PATH = Path("packs/tsia2/config.json")

ID_RE = re.compile(r"^TSIA2-(ES|E|M)(\d+)-(\d{3})$")
CHOICE_RE = re.compile(r"^([A-D])\)\s*(.*)$")

MCQ_KEY_RE = re.compile(
    r"^(TSIA2-[EM]\d+-\d{3})\s+[—–-]\s+Correct:\s+([A-D])\s+[—–-]\s+Correct Answer:\s+(.*?)\s+[—–-]\s+Explanation:\s+(.*)$"
)

ESSAY_KEY_RE = re.compile(
    r"^(TSIA2-ES\d+-001)\s+[—–-]\s+Model Guidance:\s+(.*?)\s+[—–-]\s+Rubric:\s+(.*)$"
)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip())


def comparable_answer(s: str) -> str:
    s = clean(s)
    s = s.replace(";", " ")
    s = re.sub(r"\s+", " ", s.strip())
    return s.lower()


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def split_sections(text: str):
    markers = [
        "PART B — ANSWER KEY + EXPLANATIONS",
        "PART B – ANSWER KEY + EXPLANATIONS",
        "PART B - ANSWER KEY + EXPLANATIONS",
    ]

    for marker in markers:
        if marker in text:
            q_text, k_text = text.split(marker, 1)
            return q_text, k_text

    raise ValueError("Missing PART B — ANSWER KEY + EXPLANATIONS section.")


def parse_key(key_text: str):
    mcq = {}
    essay = {}

    for raw in key_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = MCQ_KEY_RE.match(line)
        if m:
            qid, letter, correct_text, explanation = m.groups()
            mcq[qid] = {
                "correct": letter,
                "correctAnswerText": clean(correct_text),
                "explanation": clean(explanation),
            }
            continue

        m = ESSAY_KEY_RE.match(line)
        if m:
            qid, guidance, rubric = m.groups()
            essay[qid] = {
                "modelAnswer": clean(guidance),
                "scoringGuidance": clean(guidance),
                "rubric": clean(rubric),
            }
            continue

    return mcq, essay


def append_to_field(item, field, text):
    if item.get(field):
        item[field] += "\n" + text
    else:
        item[field] = text


def parse_question_block(qid: str, block_lines):
    item = {
        "id": qid,
        "section": "",
        "type": "",
        "itemType": "",
        "focus": "",
        "category": "",
        "prompt": "",
        "assignment": "",
        "choices": {},
        "correct": "",
        "correctAnswerText": "",
        "explanation": "",
        "modelAnswer": "",
        "scoringGuidance": "",
        "rubric": "",
        "credits": 1,
    }

    current_field = None
    current_choice = None

    for raw in block_lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            if current_field in {"prompt", "assignment", "modelAnswer", "scoringGuidance", "rubric"}:
                item[current_field] += "\n"
            elif current_choice:
                item["choices"][current_choice] += "\n"
            continue

        simple_fields = {
            "Section:": "section",
            "Type:": "type",
            "Focus:": "focus",
            "Category:": "category",
        }

        matched_simple = False
        for label, field in simple_fields.items():
            if stripped.startswith(label):
                item[field] = stripped.split(":", 1)[1].strip()
                current_field = None
                current_choice = None
                matched_simple = True
                break

        if matched_simple:
            continue

        if stripped == "Prompt:":
            current_field = "prompt"
            current_choice = None
            continue

        if stripped == "Assignment:":
            current_field = "assignment"
            current_choice = None
            continue

        if stripped.startswith("Model Guidance:"):
            item["modelAnswer"] = stripped.split(":", 1)[1].strip()
            item["scoringGuidance"] = item["modelAnswer"]
            current_field = "modelAnswer"
            current_choice = None
            continue

        if stripped.startswith("Scoring Guidance:"):
            item["scoringGuidance"] = stripped.split(":", 1)[1].strip()
            current_field = "scoringGuidance"
            current_choice = None
            continue

        if stripped.startswith("Rubric:"):
            item["rubric"] = stripped.split(":", 1)[1].strip()
            current_field = "rubric"
            current_choice = None
            continue

        cm = CHOICE_RE.match(stripped)
        if cm:
            letter, value = cm.groups()
            item["choices"][letter] = value.strip()
            current_choice = letter
            current_field = None
            continue

        if current_choice:
            item["choices"][current_choice] += "\n" + stripped
        elif current_field:
            append_to_field(item, current_field, stripped)
        else:
            pass

    for k in [
        "section",
        "type",
        "focus",
        "category",
        "prompt",
        "assignment",
        "explanation",
        "modelAnswer",
        "scoringGuidance",
        "rubric",
    ]:
        item[k] = clean(item.get(k, ""))

    item["choices"] = {k: clean(v) for k, v in item["choices"].items()}

    raw_type = item["type"].strip().lower()
    if raw_type in {"mcq", "multiple_choice", "multiple-choice"}:
        item["type"] = "mcq"
        item["itemType"] = "mcq"
    elif raw_type in {"essay", "writing", "writeplacer"}:
        item["type"] = "essay"
        item["itemType"] = "essay"
    else:
        item["itemType"] = raw_type

    if item["type"] == "essay" and item["assignment"]:
        item["prompt"] = clean(item["prompt"] + "\n\nAssignment:\n" + item["assignment"])

    item.pop("assignment", None)

    return item


def parse_questions(q_text: str):
    lines = q_text.splitlines()

    starts = []
    for i, line in enumerate(lines):
        s = line.strip()
        if ID_RE.match(s):
            starts.append((i, s))

    items = []
    for idx, (start_i, qid) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = lines[start_i + 1:end_i]
        items.append(parse_question_block(qid, block))

    return items


def expected_ids(prefix: str, exam_no: str, count: int):
    return [f"TSIA2-{prefix}{exam_no}-{n:03d}" for n in range(1, count + 1)]


def validate_mcq_group(items, mcq_key, prefix, exam_no, expected_count, label):
    errors = []

    ids = [x["id"] for x in items]
    exp_ids = expected_ids(prefix, exam_no, expected_count)

    if len(items) != expected_count:
        errors.append(f"{label} Exam {exam_no}: expected {expected_count} questions, found {len(items)}.")

    if ids != exp_ids:
        errors.append(f"{label} Exam {exam_no}: IDs must run exactly {exp_ids[0]} through {exp_ids[-1]}. Found: {ids}")

    for item in items:
        qid = item["id"]

        if item["type"] != "mcq":
            errors.append(f"{qid}: expected Type: mcq.")

        if set(item["choices"].keys()) != {"A", "B", "C", "D"}:
            errors.append(f"{qid}: MCQ must have exactly A, B, C, D choices.")

        if qid not in mcq_key:
            errors.append(f"{qid}: missing MCQ answer-key line.")
            continue

        key = mcq_key[qid]
        letter = key["correct"]
        answer_text = key["correctAnswerText"]

        if letter not in item["choices"]:
            errors.append(f"{qid}: correct letter {letter} is not a valid choice.")
        elif comparable_answer(item["choices"][letter]) != comparable_answer(answer_text):
            errors.append(
                f"{qid}: Correct Answer text does not match choice {letter}. "
                f"Choice='{item['choices'][letter]}', Key='{answer_text}'"
            )

        item["correct"] = letter
        item["correctAnswerText"] = answer_text
        item["explanation"] = key["explanation"]

        item.pop("modelAnswer", None)
        item.pop("scoringGuidance", None)
        item.pop("rubric", None)

    return errors


def validate_essay_group(items, essay_key, exam_no):
    errors = []

    expected_id = f"TSIA2-ES{exam_no}-001"
    ids = [x["id"] for x in items]

    if len(items) != 1:
        errors.append(f"Essay Exam {exam_no}: expected 1 prompt, found {len(items)}.")

    if ids != [expected_id]:
        errors.append(f"Essay Exam {exam_no}: expected ID {expected_id}. Found: {ids}")

    for item in items:
        qid = item["id"]

        if item["type"] != "essay":
            errors.append(f"{qid}: expected Type: essay.")

        if not item.get("prompt"):
            errors.append(f"{qid}: missing Prompt.")

        if qid in essay_key:
            item.update(essay_key[qid])

        if not item.get("modelAnswer"):
            errors.append(f"{qid}: missing Model Guidance / modelAnswer.")

        if not item.get("rubric"):
            errors.append(f"{qid}: missing Rubric.")

        item.pop("choices", None)
        item.pop("correct", None)
        item.pop("correctAnswerText", None)
        item.pop("explanation", None)

    return errors


def title_for(section_id, exam_no):
    if section_id == "elar":
        return f"TSIA2 ELAR Practice Test {int(exam_no):02d}"
    if section_id == "math":
        return f"TSIA2 Math Practice Test {int(exam_no):02d}"
    if section_id == "essay":
        return f"TSIA2 Essay Practice Prompt {int(exam_no):02d}"
    return f"TSIA2 Practice {int(exam_no):02d}"


def output_name(section_id, exam_no):
    n = int(exam_no)
    if section_id == "elar":
        return f"tsia2_elar_exam_{n:02d}.json"
    if section_id == "math":
        return f"tsia2_math_exam_{n:02d}.json"
    if section_id == "essay":
        return f"tsia2_essay_prompt_{n:02d}.json"
    raise ValueError(f"Unknown section id: {section_id}")


def write_json(section_id, exam_no, items):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = output_name(section_id, exam_no)
    payload = {
        "title": title_for(section_id, exam_no),
        "section": section_id,
        "questions": items,
    }
    out_path = OUT_DIR / fname
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return fname, out_path


def update_config(files_by_section):
    if not CONFIG_PATH.exists():
        print(f"WARNING: {CONFIG_PATH} not found; config not updated.")
        return

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    for section in cfg.get("sections", []):
        sid = section.get("id")
        if sid in files_by_section:
            section["examFiles"] = sorted(files_by_section[sid])
        else:
            section["examFiles"] = []

    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def group_items(items):
    groups = {}

    for item in items:
        m = ID_RE.match(item["id"])
        if not m:
            continue

        prefix, exam_no, num = m.groups()

        if prefix == "E":
            section_id = "elar"
        elif prefix == "M":
            section_id = "math"
        elif prefix == "ES":
            section_id = "essay"
        else:
            continue

        groups.setdefault((section_id, exam_no), []).append(item)

    for key in groups:
        groups[key].sort(key=lambda x: x["id"])

    return groups


def main():
    if not SRC_DIR.exists():
        print(f"ERROR: source directory not found: {SRC_DIR}", file=sys.stderr)
        sys.exit(1)

    txt_files = sorted(SRC_DIR.glob("*.txt"))

    if not txt_files:
        print(f"No .txt files found in {SRC_DIR}. Importer is ready.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for old in OUT_DIR.glob("tsia2_*.json"):
        old.unlink()

    all_errors = []
    written = []
    files_by_section = {"elar": [], "math": [], "essay": []}

    for src in txt_files:
        try:
            text = read_text(src)
            q_text, k_text = split_sections(text)
            mcq_key, essay_key = parse_key(k_text)
            items = parse_questions(q_text)
            groups = group_items(items)

            if not groups:
                all_errors.append(f"{src.name}: no TSIA2 item IDs found.")
                continue

            for (section_id, exam_no), group in sorted(groups.items()):
                if section_id == "elar":
                    errors = validate_mcq_group(group, mcq_key, "E", exam_no, 30, "ELAR")
                elif section_id == "math":
                    errors = validate_mcq_group(group, mcq_key, "M", exam_no, 20, "Math")
                elif section_id == "essay":
                    errors = validate_essay_group(group, essay_key, exam_no)
                else:
                    errors = [f"{src.name}: unknown section {section_id}"]

                if errors:
                    all_errors.extend([f"{src.name}: {e}" for e in errors])
                    continue

                fname, out_path = write_json(section_id, exam_no, group)
                files_by_section[section_id].append(fname)
                written.append(str(out_path))

        except Exception as e:
            all_errors.append(f"{src.name}: {e}")

    if all_errors:
        print("IMPORT FAILED.")
        for err in all_errors:
            print(f"- {err}")
        sys.exit(1)

    update_config(files_by_section)

    print("IMPORT OK.")
    for path in written:
        print(f"- {path}")

    print("")
    print("Config updated:")
    print(f"- {CONFIG_PATH}")


if __name__ == "__main__":
    main()
