p = 'client/src/pages/Chat/components/ChatSessionDropdown/index.tsx'
s = open(p, encoding='utf-8').read()
old = "        active={session.id === data.currentSessionId}"
new = (
    "        active={\n"
    "          data.currentBackendId\n"
    "            ? getBackendId(session) === data.currentBackendId\n"
    "            : session.id === data.currentSessionId\n"
    "        }"
)
assert s.count(old) == 1, s.count(old)
open(p, 'w', encoding='utf-8').write(s.replace(old, new))
print("active patch applied")
