你是负责V1.6.1小迭代的开发工人。本项目目录即当前工作目录 E:\DEMO\DateAnalysis（codex已-C到该目录）。shell 是 PowerShell，注意跑命令时不要在一行里串太多带特殊字符的内容，跑Python代码一律写到.py文件再执行。\n\n【项目背景】\nPython+PySide6+pandas+pyqtgraph 桌面数据分析软件，入口 app\main.py。
数据处理模块：
- app/models/processing_rule.py : ProcessingRule(column, operator, threshold, action)
- app/services/data_processing.py : apply_rules(df, rules) -> (df, logs)
- app/ui/widgets/processing_panel.py : 处理面板UI
- app/ui/main_window.py _apply_processing(rules) 调用apply_rules

【需求：新增"按系数缩放(转mm)"处理动作】
目标：让用户可以给所有数值列（除时间列）乘以一个单精度浮点系数，比如像素到mm的换算系数，使最终显示数据都带(mm)单位后缀。

1) 模型层 processing_rule.py
- ProcessingRule 字段不变，新增 action 取值 'scale_by_factor'
- column=='*' 表示作用于所有数值列
- threshold 携带float系数

2) 服务层 data_processing.py apply_rules
- 加 action=='scale_by_factor' 分支
- factor = float(rule.threshold)
- factor<=0 记日志"系数必须为正数，已跳过"，跳过
- factor==1.0 记日志"系数为1，无需缩放"，跳过
- 选列逻辑：
  * column=='*'：使用 df.select_dtypes(include=[np.number]) 选所有数值列，排除bool列；再过滤掉 datetime 列（防御式）
  * 指定具体列：若列不存在/是非数值/是datetime，记日志跳过
- 对选中列：df[col] = df[col] * factor（用pd.to_numeric先转一下保险）
- 重命名被缩放列：f"{col}(mm)"；若原名已以"(mm)"结尾不重复追加
- 日志例："规则N：将列 [虎口距,拇指距,中指距,中点x,中点y] 按系数 0.100000 缩放并重命名为 mm 单位。"
- 其他规则引用到旧列名时会走已有的"列不存在已跳过"逻辑，无需额外处理

3) UI层 processing_panel.py
- ACTION_ITEMS 增加 ("按系数缩放(转mm)", "scale_by_factor")
- 在form里加：
  * self.factor_spin = QDoubleSpinBox()；setRange(1e-9, 1e6)；setDecimals(6)；setValue(1.0)；setSingleStep(0.01)
  * 一行 form.addRow("缩放系数(像素→mm)：", self.factor_spin)
  * self.apply_all_checkbox = QCheckBox("应用到全部数值列(自动跳过时间列)")；默认勾选
  * 一行 layout.addWidget(self.apply_all_checkbox)
- 实现 _update_action_state() 或在 _update_threshold_state 中：
  * action=='scale_by_factor': operator_combo.setEnabled(False); threshold_spin.setEnabled(False); factor_spin.setEnabled(True); apply_all_checkbox.setEnabled(True); column_combo.setEnabled(not self.apply_all_checkbox.isChecked())
  * 其他动作：operator_combo.setEnabled(True); threshold_spin.setEnabled(True); factor_spin.setEnabled(False); apply_all_checkbox.setEnabled(False); column_combo.setEnabled(True)
- apply_all_checkbox.toggled.connect(lambda checked: self.column_combo.setEnabled(not checked) if self.action_combo.currentData()=='scale_by_factor' else None)  以及在切换action时同步调用
- _add_rule 中 action=='scale_by_factor' 分支：
  * factor = self.factor_spin.value()；factor<=0弹QMessageBox
  * col = '*' if self.apply_all_checkbox.isChecked() else self.column_combo.currentText()
  * rule = ProcessingRule(column=col, operator='none', threshold=factor, action='scale_by_factor')
  * 规则列表文本："全部数值列 ×0.100000 → 转mm单位" 或 "列[虎口距] ×0.100000 → 转mm单位"

4) main_window.py 尽量不改，保持 _apply_processing 原样。
5) 不破坏 V1.6.1 任何已有功能（删除整行/替换均值/折线/描述统计/导出/日志/降采样/后台线程）。
6) UI 中文文案用中文，不要出现问号乱码。

【必须亲自验证】
A. 语法检查：
   D:\VSCode\Python\python.exe -m py_compile app\models\processing_rule.py app\services\data_processing.py app\ui\widgets\processing_panel.py\n\nB. 单元测试：新建 tests\test_scale_feature.py（保留此文件），覆盖：
   1. 全部数值列 ×0.1：数值正确变化；列名加(mm)；时间列/字符串列不变
   2. 单列（虎口距）×0.5：只改虎口距
   3. factor=1：无变化，有日志
   4. factor=-1：跳过，有日志
   5. 指定非数值列：跳过，有日志
   6. 重复执行：列名不重复追加(mm)
   用assert，最后打印 VERIFY_SCALE_OK
   执行：D:\VSCode\Python\python.exe tests\test_scale_feature.py\n\nC. UI冒烟：写临时_smoke.py：\n   import sys\n   from PySide6.QtWidgets import QApplication\n   from app.ui.main_window import MainWindow
   app = QApplication(sys.argv)
   w = MainWindow()
   w.show()
   print("SMOKE_OK")
   执行：先 $env:QT_QPA_PLATFORM='offscreen'，再 D:\VSCode\Python\python.exe _smoke.py\n   如果offscreen插件缺失打印不了SMOKE_OK也没关系，但不能有Exception。\n\nD. 清理：删除_smoke.py。保留tests/test_scale_feature.py。\n\n【完成标志】\n打印 SCALE_FEATURE_DONE 并列出所有改动文件路径。
