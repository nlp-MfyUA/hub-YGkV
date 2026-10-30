# 测试样本图来源与授权

| 文件 | 内容 | 来源 | 授权 |
|---|---|---|---|
| `corridor_clutter_high_boxes.jpg` | 楼道口大量纸箱/木质家具堆积 | 胶州市融媒体中心《楼道堆杂物 难看又"惹"火》PDF（`http://jzrm.jiaozhou.gov.cn/resfile/2022-08-02/03/jjz-20220802-003.pdf`）第 5 张内嵌图 | 政务公开报道 |
| `corridor_door_clutter.jpg` | 单元门外堆放置物架、塑料筐、杂物 | 同上 PDF 第 7 张内嵌图 | 政务公开报道 |
| `corridor_scooter_chair.jpg` | 楼道内滑板车、折叠椅、购物袋 | 同上 PDF 第 8 张内嵌图 | 政务公开报道 |
| `stairwell_bicycle.jpg` | 楼梯间停放自行车 | 同上 PDF 第 6 张内嵌图 | 政务公开报道 |
| `noncorridor_black_frame.jpg` | 全黑图 | 同上 PDF 第 1 张内嵌图 | 政务公开报道 |
| `noncorridor_text_shortreview.jpg` | 「短评」文字截图 | 同上 PDF 第 2 张内嵌图 | 政务公开报道 |
| `noncorridor_text_icon.jpg` | 曝光台图标 | 同上 PDF 第 3 张内嵌图 | 政务公开报道 |
| `noncorridor_unreadable.jpg` | 不可辨图 | 同上 PDF 第 4 张内嵌图 | 政务公开报道 |
| `source_ebike_scooters_ccbysa4.jpg` | 建筑入口台阶与廊道下停放的踏板车 | Wikimedia Commons，文件 `DFC 2086 Exterior of 115 Food Villa at night showing steps up to the entrance parked scooters and a covered walkway along the side of the building.jpg` | **CC BY-SA 4.0** |
| `corridor_ebike_a.jpg` / `_b.jpg` / `_c.jpg` | 上图右侧「带顶廊道」区域的三种裁切 | 由上一行裁切生成 | **CC BY-SA 4.0** |
| `synthetic_corridor_ebike.jpg` | 楼道 + 电动车合成验证图 | 由 `tests/make_synthetic.py` 生成（底图 `corridor_door_clutter.jpg` + 素材 `source_ebike_scooters_ccbysa4.jpg`） | 派生自上述两图 |
| `non_corridor_pingpong.jpg` | 室内乒乓球活动 | 课程目录 `02-多模态大模型/pingpong.jpg`（课程随附素材） | 课程素材 |

## 说明

- 政务 PDF 的内嵌图是用脚本按 JPEG 起止标记（`FFD8FF` / `FFD9`）从 PDF 原始字节中切出的，
  该 PDF 内共 8 个图像对象（`/Subtype /Image` 计数一致），已全部提取。
- 合成图**仅作高风险档的功能验证素材**，不作演示素材、不对外发布。
- 本目录内图片仅用于自动化测试与回归比对，不进入前端静态资源目录。
