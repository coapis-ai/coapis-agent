p = 'client/src/pages/Chat/components/ChatSessionDropdown/index.tsx'
s = open(p, encoding='utf-8').read()

old1 = """  const rowHandlers = {
    sortedSessions,
    currentSessionId,"""
new1 = """  const rowHandlers = {
    sortedSessions,
    currentSessionId,
    currentBackendId: props.currentBackendId,"""
assert s.count(old1) == 1, ("old1", s.count(old1))
s = s.replace(old1, new1)

old2 = """                    extra={
                      props.renderItemExtra &&
                      session.id === currentSessionId
                        ? props.renderItemExtra(session, getBackendId(session))
                        : null
                    }"""
new2 = """                    extra={
                      props.renderItemExtra && isCurrentSession(session)
                        ? props.renderItemExtra(session, getBackendId(session))
                        : null
                    }"""
assert s.count(old2) == 1, ("old2", s.count(old2))
s = s.replace(old2, new2)

# 判定函数：左栏在 provider 之外，context 的 currentSessionId 是空值，
# 只有页面层传进来的后端 chatId 认得出当前会话。
old3 = """  const rowHandlers = {"""
new3 = """  const isCurrentSession = (session: ExtendedChatSession): boolean =>
    props.currentBackendId
      ? getBackendId(session) === props.currentBackendId
      : session.id === currentSessionId;

  const rowHandlers = {"""
assert s.count(old3) == 1, ("old3", s.count(old3))
s = s.replace(old3, new3)

open(p, 'w', encoding='utf-8').write(s)
print("patched rowHandlers + extra + isCurrentSession")
