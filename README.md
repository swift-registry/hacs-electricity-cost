# 扬州电费预估 (Yangzhou Electricity Cost)

这是一个专为 Home Assistant 设计的自定义组件，用于实时预估扬州市居民阶梯+峰谷分时电费。

## ✨ 功能特点
- **网页 UI 管理**：支持通过 Home Assistant 界面添加与配置，无需改代码。
- **精准计算**：内置江苏/扬州居民峰谷电价标准（峰段 0.5583元，谷段 0.3583元），均可在界面调整。
- **智能阶梯**：根据当前月份自动推算年度阶梯额度，超出部分自动叠加二档/三档加价。
- **低资源消耗**：仅在电表读数发生变化时触发计算，不占用额外系统资源。

## 📦 安装步骤

### 方法一：通过 HACS 安装（推荐）
> HACS 只能添加 **GitHub** 上的仓库。请先将本仓库推送到 GitHub（仓库名建议用 `swift-registry`）。

1. 在 HACS 中点击 `Integrations` -> 右上角菜单 -> `Custom repositories`。
2. 填入 GitHub 仓库地址 `https://github.com/wangmengfan/swift-registry`，Category 选择 `Integration`。
3. 搜索 `Yangzhou Electricity Cost` 并下载安装，重启 Home Assistant。
4. 重启后进入 `设置` -> `设备与服务` -> `集成` -> 点击 `添加集成`，搜索 `Yangzhou Electricity Cost`。
5. 在弹出的界面中填写：
   - **名称**：默认即可
   - **源电表传感器**：选择你的智能电表电量实体（如 `sensor.zhi_neng_dian_biao_dian_li`）
   - **峰段占比(%)**、**峰段电价**、**谷段电价**

### 方法二：手动安装
1. 下载本仓库代码，将 `custom_components/yangzhou_electricity_cost` 文件夹复制到你的 HA 配置目录中。
2. 重启 Home Assistant。
3. 进入 `设置` -> `设备与服务` -> `集成` -> `添加集成`，搜索 `Yangzhou Electricity Cost` 完成配置。

## ⚙️ 配置与管理
添加完成后，可在 `设置` -> `设备与服务` -> `Yangzhou Electricity Cost` -> `配置` 中随时修改：
- 源电表传感器、名称
- 峰段占比（默认 65% 峰 / 35% 谷，因 Template 传感器无法读取历史峰谷电量，按比例估算）
- 峰段 / 谷段电价
- 第二档 / 第三档加价、第一档 / 第二档年累计上限

修改保存后立即生效，无需重启。
