# 数据字段

证据为JSON数组。每项包含 id、title、url、publisher、published_date、event_date、retrieved_date、verification、section、note。日期为YYYY-MM-DD，未知用null。verification取full_text（已打开且核验支持字段）、official_index（官方索引线索）、search_only（搜索/商业线索）；脚本抓取结果的fetched_unreviewed不能作为已核验。

monthly只按发布日做机械分组，不能替代事件日期判断。网页更新时间、函署日期与事件日期分别记录，note说明冲突。summary支持自己概括，不必复制原文长段落。每项证据保留适用主体与状态。
