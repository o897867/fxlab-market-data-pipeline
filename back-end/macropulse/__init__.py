"""MacroPulse — 央行通讯抓取与归因系统。

第一期：Ingestion。从 Fed/RBA/ECB 官网抓取声明/纪要/讲话，去重后写入
S3 raw 层。复用 FXLab 既有的 S3 数据湖（bucket fxlab-data-lake）。
"""
