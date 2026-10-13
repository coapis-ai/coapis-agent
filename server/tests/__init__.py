# -*- coding: utf-8 -*-
"""后端测试树（``server/tests``）——**唯一**的一份。

历史上这里有两份：``server/coapis/tests``（长在发布包里）和 ``server/tests``。
同名文件（``test_external_auth.py`` / ``test_file_ledger.py``）各有一份、内容
还不一样，改了一边另一边继续红，是"测试通过"假阴性的来源之一。2026-10-13 合并：

* ``coapis/tests/test_external_auth.py`` → 删除（与 ``server/tests`` 那份同名且更旧）
* ``coapis/tests/test_file_ledger.py``   → ``server/tests/unit/test_file_ledger_roots.py``
  （两份覆盖不同：这份测双根目录归属/状态流转/交付列表，不是重复）
* ``coapis/tests/{agent_eval,plan_exec}`` → ``server/tests/{agent_eval,plan_exec}``

声明为包是为了给 pytest 唯一模块名（避免 basename 撞 "import file mismatch"）。
仓库根的 ``tests/`` 是另一类东西：打真实 dev 端口的脚本式探针，不走 pytest 收集。
"""
