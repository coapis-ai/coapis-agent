import io

TEXTS = {
    "zh": {
        "time": "更新时间",
        "versionTitle": "版本",
        "delete": "删除",
        "deleteConfirm": "在台账中标记为已删除（磁盘文件保留，可在「我的空间」彻底删除）？",
        "deleteDone": "已标记删除",
        "deleteFailed": "删除失败",
    },
    "en": {
        "time": "Updated",
        "versionTitle": "Version",
        "delete": "Delete",
        "deleteConfirm": "Mark as deleted in the ledger (the file stays on disk; delete it for good in My Space)?",
        "deleteDone": "Marked as deleted",
        "deleteFailed": "Delete failed",
    },
    "ja": {
        "time": "更新日時",
        "versionTitle": "版",
        "delete": "削除",
        "deleteConfirm": "台帳上で「削除済み」にします（実体は残ります。「マイスペース」で完全削除できます）。実行しますか？",
        "deleteDone": "削除済みとして記録",
        "deleteFailed": "削除に失敗",
    },
    "ru": {
        "time": "Обновлено",
        "versionTitle": "Версия",
        "delete": "Удалить",
        "deleteConfirm": "Пометить в журнале как удалённый (файл останется на диске; полностью — в «Моём пространстве»)?",
        "deleteDone": "Помечен как удалённый",
        "deleteFailed": "Не удалось удалить",
    },
}

for loc, txt in TEXTS.items():
    path = "client/src/locales/%s.json" % loc
    lines = open(path, encoding="utf-8").read().split("\n")
    vi = next(i for i, l in enumerate(lines) if '"v{{n}}"' in l)
    indent = lines[vi][: len(lines[vi]) - len(lines[vi].lstrip())]
    # 1) 更新时间：只改 resources 块内、version 之前最近的那一条 "time":
    for i in range(vi - 1, max(vi - 60, 0), -1):
        if '"time":' in lines[i]:
            key = '"time": "%s",' % txt["time"]
            lines[i] = indent + key
            break
    # 2) 新增键（紧跟 version 之后，同一缩进层级）
    add = [
        indent + '"versionTitle": "%s",' % txt["versionTitle"],
        indent + '"delete": "%s",' % txt["delete"],
        indent + '"deleteConfirm": "%s",' % txt["deleteConfirm"],
        indent + '"deleteDone": "%s",' % txt["deleteDone"],
        indent + '"deleteFailed": "%s",' % txt["deleteFailed"],
    ]
    lines[vi + 1 : vi + 1] = add
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print(loc, "ok")

# 校验 JSON 合法性 + 键可见
import json

for loc in TEXTS:
    d = json.load(open("client/src/locales/%s.json" % loc, encoding="utf-8"))
    r = d["chat"]["resources"]
    for k in ("time", "versionTitle", "delete", "deleteConfirm", "deleteDone", "deleteFailed"):
        assert k in r, (loc, k)
    print(loc, "json ok:", r["time"], r["versionTitle"], r["delete"])
