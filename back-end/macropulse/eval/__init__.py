"""Eval harness（第四周）。

三件套：
1. 结构/校准回归——跑 committed golden 快照，CI 安全（无 API/S3），每次提交都跑
2. 漂移测试——改 prompt 后真实重打校准子集、与 golden 比对，gated（花 API，手动/定时）
3. 人工裁决队列——低置信/needs_review/价格冲突样本进队列，裁决回流为校准依据
"""
