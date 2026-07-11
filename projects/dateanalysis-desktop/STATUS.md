# STATUS.md - 项目状态看板

> PM 会话实时状态文件。所有进行中任务、阻塞项、下一步动作以此为准。
> 最后更新：2026-07-06 21:45 (GMT+8) 巡检

---

## 项目概况
- **项目名**：DateAnalysis（本地数据分析与图表展示软件）
- **路径**：E:\DEMO\DateAnalysis
- **技术栈**：Python 3.12 + PySide6 + pandas + numpy + pyqtgraph
- **当前版本**：V1.6.1
- **状态**：🟢 可运行，核心功能全绿；无在途工人

---

## 当前里程碑
- **V1.6.1** ✅ 已完成
  - 数值缩放为 mm：支持排除列（自动时间列 / 手动指定列 / 不排除）+ float32 单精度乘法 + 自动加 (mm) 后缀
  - 描述统计基础层（直方图/KDE/箱线图/QQ图/相关矩阵/散点矩阵）
  - 分析模式切换（折线趋势 / 描述统计 / 时序监控）
  - 数据处理、时间聚合、多文件、临时储存区

---

## 任务看板

### ✅ Done（最近）
| 日期 | 任务 | 验证 |
|------|------|------|
| 2026-07-06 | V1.6.1 缩放功能增强：排除列 + float32 单精度 | compileall ✅ / 14 项缩放测试 ✅ / descriptive ✅ / UI 冒烟 ✅ |
| 2026-07-06 | PROJECT.md + 关于对话框同步更新 | py_compile ✅ |
| 2026-07-06 | STATUS.md 初始化 | ✅ |

### 🔄 Doing
- 无（最近 Codex 工人 keen-fjord / crisp-claw 均已正常退出）

### 📋 Todo（优先级排序）
| 优先级 | 任务 | 备注 |
|--------|------|------|
| P0 | **上传项目到 GitHub** | 用户 10:41 提了需求，需确认：新建/已有仓库、仓库名 |
| P1 | 扩展数据处理动作：替换中位数、替换0、替换固定值 | V1.3 候选 |
| P1 | 排序、筛选、重复值删除 | V1.3 候选 |
| P2 | 每条Y序列单独控制均值线 | |
| P2 | 大文件表格虚拟滚动/分页 | 性能优化 |
| P2 | `.xls` 完整兼容测试 | |
| P3 | 更多图表类型 | |
| P3 | PROJECT.md 整理（底部有重复段落） | 文档清理 |

---

## ⚠️ 阻塞 / 风险
- **GitHub 上传待用户确认**（阻塞，不可自主推进）：用户要求上传全部文件到 GitHub，但未提供：
  1. 新建仓库还是推送到已有仓库？
  2. 仓库名称 / GitHub 账户？
  3. `.venv`、`__pycache__`、`logs/`、`_screenshots/`、`tests/ui_smoke_out/` 等建议默认排除。

---

## 🧪 验证基线
- `python -m compileall app tests` → 全绿
- `tests/test_scale_feature.py` → 14/14 PASS
- `tests/test_descriptive_service.py` → all tests passed
- `tests/ui_smoke_test.py` (offscreen) → 全部通过（导入→描述统计→折线→时间粒度→处理→清空）

---

## 巡检日志
| 时间 | 检查项 | 结果 |
|------|--------|------|
| 2026-07-06 16:18 | 活跃 Codex 工人 | 无在途进程 |
| 2026-07-06 16:18 | 测试基线 | 全绿 |
| 2026-07-06 20:38 | Sub 工人 | 0 active / 0 recent（60min） |
| 2026-07-06 20:38 | STATUS.md 格式 | 修复路径换行/反引号显示问题 |
| 2026-07-06 21:10 | Sub 工人 | 0 active / 0 recent（60min）；无需要重派任务 |
| 2026-07-06 21:45 | 巡检 | 0 active / 0 recent；无重派任务；P0 GitHub 上传仍等用户输入仓库信息 |
| 2026-07-06 21:10 | 可自主推进任务 | 无；P0 GitHub 上传仍等用户输入仓库信息 |

---

## 📁 关键文件索引
| 文件 | 用途 |
|------|------|
| `app/main.py` | 入口 |
| `app/ui/main_window.py` | 主窗口（含关于对话框） |
| `app/ui/widgets/processing_panel.py` | 数据处理面板（缩放/排除列 UI） |
| `app/services/data_processing.py` | 数据处理核心逻辑（缩放/mm/排除列） |
| `app/models/processing_rule.py` | 处理规则数据模型 |
| `tests/test_scale_feature.py` | 缩放功能专项测试 |
| `PROJECT.md` | 项目唯一事实来源（SSOT） |
| `STATUS.md` | 本文件，PM 实时状态看板 |

---

## 📝 决策记录（最近）
- **ADR-014**：缩放乘法统一使用 float32 单精度语义（先转 float32 相乘再回 float64），满足"单像素精度"需求。
- **ADR-015**：批量缩放默认自动排除时间/日期列（含文本日期，转换成功率 ≥80% 判定为日期列），用户可手动覆盖。
- **ADR-016**：ProcessingRule 新增 `exclude_mode`/`exclude_columns` 可选字段，默认值保持向后兼容。
