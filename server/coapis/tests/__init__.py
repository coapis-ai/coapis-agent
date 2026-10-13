# -*- coding: utf-8 -*-
"""coapis 内置测试包。

``coapis/tests`` 与仓库根的 ``server/tests`` 存在同名测试文件；没有
``__init__.py`` 时 pytest 走 prepend 导入，两个同名模块会撞
"import file mismatch"。声明为包后模块名带包前缀，互不冲突。
"""
