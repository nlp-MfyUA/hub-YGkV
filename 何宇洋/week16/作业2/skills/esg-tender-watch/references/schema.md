# 结构化台账契约

输入为UTF-8 JSON数组；原文中未知字段为null，禁止凭空补造。

| 字段 | 含义 |
|---|---|
| id/title/url | 本地证据ID、项目标题、原始链接 |
| buyer/project_id/lot | 采购人、真实编号、标包；ALL表示已核实的项目总额，单包项目可按总额记录 |
| notice_type | award/tender/candidate/contract/correction/cancel |
| published_date/version_date | YYYY-MM-DD；最终公告/该版本日期，默认版本日为公告日 |
| corrects_award | 只有确认为中标更正时为true |
| amount_raw/amount_kind/currency | 原始金额；award/budget/ceiling/rate；明确人民币为CNY |
| verification | full_text/official_index/search_only；只有full_text进入默认统计 |
| relevant/scope/category | 人工或模型判断相关性true/false；core/extended；主题分类 |
| deadline/registration_deadline | 投标与报名/文件获取截止，ISO8601带+08:00时区 |
| budget_raw/winner/tax_status | 预算、中标人、含税状态；未知保留null或注明未核验 |

金额支持精确的“1,200,000元”“120万元”“0.012亿元”，不默猜单位。预算、费率、单价、框架上限与外币不纳入人民币中标总价。多年度服务总价不自动年化。脚本不从任意中文公告可靠抽取全部字段，需模型核验填表。更正必须携带更新后的完整字段，不是局部补丁；撤销与项目重编由模型核验后调整有效台账。

待发送箱状态以标题、编号、标包、公告类型/日期、版本、截止期、预算、要求、服务范围等业务字段哈希形成版本ID；抓取日期、本地ID与镜像URL变化不触发重复推送。业务字段变化形成新候选，模型决定实质更正是否值得再次通知。sent只在成功发送后ack。状态与输出用同目录临时文件原子替换，当前实现仅适合单实例运行，调度时禁止重叠。
