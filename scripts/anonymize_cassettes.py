#!/usr/bin/env python3
"""Anonymize real client IDs in VCR cassette files."""
import re
import glob
import os

REPLACEMENTS = [
    # === Длинные числа первыми (во избежание частичных замен) ===

    # Ad IDs (11 цифр)
    ("17692564248", "30000000001"),
    ("17692565308", "30000000002"),

    # Keyword/Bid IDs (11 цифр)
    ("57019292002", "40000000001"),
    ("57019292280", "40000000002"),
    ("57019293955", "40000000003"),
    ("57020317358", "40000000004"),

    # Ad Group IDs (10 цифр)
    ("5743529158", "2000000001"),
    ("5743529188", "2000000002"),
    ("5743529259", "2000000003"),
    ("5743529277", "2000000004"),
    ("5743529417", "2000000005"),
    ("5743529462", "2000000006"),
    ("5743542755", "2000000007"),
    ("5743542801", "2000000008"),
    ("5743542961", "2000000009"),

    # Creative / Sitelinks IDs (10 цифр)
    ("1156472207", "1000000001"),
    ("1472003845", "1000000002"),

    # Campaign IDs (9 цифр)
    ("700011014", "100000001"),
    ("700011015", "100000002"),
    ("700011016", "100000003"),
    ("700011017", "100000004"),
    ("700011018", "100000005"),
    ("700011019", "100000006"),
    ("700011020", "100000007"),
    ("700011021", "100000008"),
    ("700011022", "100000009"),
    ("700011023", "100000010"),
    ("700011024", "100000011"),
    ("709163066", "100000012"),
    ("709163077", "100000013"),
    ("709163149", "100000014"),
    ("709163160", "100000015"),
    ("709163171", "100000016"),
    ("709163239", "100000017"),
    ("709163259", "100000018"),
    ("709165094", "100000019"),
    ("709165101", "100000020"),
    ("709165115", "100000021"),

    # Bid Modifier ID (8 цифр)
    ("10177172", "10000001"),

    # Smart Ad Target IDs (7 цифр)
    ("3286108", "1000001"),
    ("3286111", "1000002"),

    # Ad Group IDs (7 цифр)
    ("4794478", "2000001"),
    ("4794479", "2000002"),
    ("4794480", "2000003"),
    ("4794481", "2000004"),
    ("4794482", "2000005"),
    ("4794483", "2000006"),

    # VCard / Negative KW IDs (6 цифр)
    ("340674", "100001"),
    ("420556", "100002"),

    # Ad Extension / Retargeting IDs (5 и 4 цифры)
    ("10655", "10001"),
    ("5263", "1001"),
    ("5264", "1002"),

    # Feed IDs (3 цифры)
    ("173", "101"),
    ("174", "102"),

    # String Video IDs (28 символов)
    ("69e6fcdeaf0e44cf15081eec005", "aabbccdd1122334455667700001"),
    ("69e6fce2af0e44cf1508230e005", "aabbccdd1122334455667700002"),
]

REQUEST_ID_RE = re.compile(r"(- ')(\d{19})(')")
DATE_RE = re.compile(r"(- (?:')?)(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} \w+ \d{4} \d{2}:\d{2}:\d{2} GMT('?)")
XACCEL_REQID_RE = re.compile(r"(reqid:)\d+")
# Matches Content-Length lines in request blocks that have <REDACTED> body
CONTENT_LENGTH_RE = re.compile(r"(      Content-Length:\n      - ')(\d+)(')")


def anonymize_file(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        content = f.read()

    original = content

    for real, fake in REPLACEMENTS:
        content = content.replace(real, fake)

    # RequestId в заголовках ответов
    content = REQUEST_ID_RE.sub(r"\g<1>0000000000000000000\g<3>", content)

    # Date в заголовках ответов
    content = DATE_RE.sub(r"\g<1>Mon, 01 Jan 2024 00:00:00 GMT\g<3>", content)

    # reqid: в X-Accel-Info заголовках
    content = XACCEL_REQID_RE.sub(r"\g<1>0000000000000000000", content)

    # Найти все блоки request и пересчитать Content-Length если тело содержит <REDACTED>
    def fix_request_block(block_match):
        block = block_match.group(0)
        if "<REDACTED>" not in block:
            return block
        # Найти body строку
        body_match = re.search(r"    body: '(.+)'", block)
        if not body_match:
            return block
        body_str = body_match.group(1)
        new_len = str(len(body_str.encode("utf-8")))
        block = re.sub(r"(      Content-Length:\n      - ')\d+(')", rf"\g<1>{new_len}\2", block)
        return block

    content = re.sub(
        r"- request:.*?(?=- request:|- response:)",
        fix_request_block,
        content,
        flags=re.DOTALL,
    )


    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return 1
    return 0


def main():
    pattern = os.path.join(
        os.path.dirname(__file__), "..", "tests", "cassettes", "**", "*.yaml"
    )
    files = glob.glob(pattern, recursive=True)
    changed = sum(anonymize_file(f) for f in sorted(files))
    print(f"Обработано файлов: {len(files)}, изменено: {changed}")


if __name__ == "__main__":
    main()
