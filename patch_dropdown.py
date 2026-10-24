import io, sys

p = 'client/src/pages/Chat/components/ChatSessionDropdown/index.tsx'
s = open(p, encoding='utf-8').read()

# 1) SessionLine: active 判定加后端 id 兜底
old1 = "        active={session.id === data.currentSessionId}"
new1 = (
    "        active={\n"
    "          data.currentBackendId\n"
    "            ? getBackendId(session) === data.currentBackendId\n"
    "            : session.id === data.currentSessionId\n"
    "        }"
)
assert s.count(old1) == 1, ("old1", s.count(old1))
s = s.replace(old1, new1)

# 2) 左栏渲染：isCurrent 判定 + 传 currentBackendId
old2 = """                {filtered.map((session) => (
                  <SessionLine
                    key={session.id}
                    index={index}
                    data={{
                      sortedSessions,
                      currentSessionId,"""
new2 = """                {filtered.map((session) => (
                  <SessionLine
                    key={session.id}
                    index={index}
                    data={{
                      sortedSessions,
                      currentSessionId,
                      currentBackendId: props.currentBackendId,"""
assert s.count(old2) == 1, ("old2", s.count(old2))
s = s.replace(old2, new2)

# 3) extra 条件：用后端 id 判定当前会话
old3 = """                    extra={
                      props.renderItemExtra &&
                      session.id === currentSessionId
                        ? props.renderItemExtra(session, getBackendId(session))
                        : null
                    }"""
new3 = """                    extra={
                      props.renderItemExtra &&
                      (props.currentBackendId
                        ? getBackendId(session) === props.currentBackendId
                        : session.id === currentSessionId)
                        ? props.renderItemExtra(session, getBackendId(session))
                        : null
                    }"""
assert s.count(old3) == 1, ("old3", s.count(old3))
s = s.replace(old3, new3)

open(p, 'w', encoding='utf-8').write(s)
print("patched 3 sites")
