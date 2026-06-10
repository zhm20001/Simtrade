# TODO

- [x] 移除 pandas 依赖：core/market.py 和 core/engine.py 中 pandas 仅用于 pd.DataFrame() 构造，可用标准库 list/dict 替代，消除 win32 构建兼容性问题
