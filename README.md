# Live Captions Recorder

![Windows 11 Live Captions](https://img.shields.io/badge/Windows_11-Live_Captions-blue?logo=windows)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

用于记录 Windows 11 内建 Live Captions (实时字幕) 内容的桌面辅助工具。通过 UIAutomation 技术无缝提取实时滚动的字幕，并将其自动整理为带有精确时间戳的记录。

## ✨ 核心特性

- 🎯 **智能捕捉**：自动锁定并跟踪 Windows 11 系统级“实时字幕”窗口。
- 📝 **多格式导出**：录制结束后自动生成 `.txt` (纯文本)、`.srt` (标准字幕文件) 和 `.jsonl` (结构化数据)。
- ⚡ **超低性能占用**：使用控件句柄缓存机制代替全局轮询，后台静默运行不影响系统性能。
- 🎨 **现代界面**：提供扁平化交互界面与悬停动画，支持一键直接开启系统字幕。
- 💾 **状态记忆**：自动保存您的偏好设置（导出目录、匹配关键字），下次打开即用。
- 👁️ **实时预览**：界面自带滚动上下文预览，清晰展示已记录字幕与正在识别中的实时长文本。

## 📥 安装与运行

### 方法一：便携版 (推荐)
直接前往 [Releases](../../releases) 下载最新打包好的 EXE 版本压缩包。
解压后运行 `LiveCaptionsRecorder.exe` 即可（无需安装 Python 环境）。

### 方法二：源码运行
请确保您使用的是 Windows 11，且已安装 Python 3.12 或 3.13。

```powershell
# 1. 克隆仓库
git clone https://github.com/homelabtest2023-alt/LiveCaptionsRecorder.git
cd LiveCaptionsRecorder

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行程序
python app.py
```

## 🚀 使用说明

1. 启动本程序。
2. 点击界面上的 **打开系统字幕** 按钮（或通过 `Win + Ctrl + L` 快捷键）开启 Windows 11 实时字幕。
3. 设定好您的**输出目录**。
4. 点击 **开始记录**。此时程序会变为红色的“停止记录”状态。
5. 当您需要结束本次会话时，点击 **停止记录**，所有的字幕文件会瞬间保存在您设定的目录下。

> **提示：** 如果系统字幕更新导致无法识别，您可以在界面点击“导出控件树”来诊断 UI 结构的变化，并修改匹配关键字。

## 🛠️ 构建可执行文件

如果您想自己打包免安装版（依赖 `PyInstaller`）：

```powershell
# 运行打包脚本
.\build_exe.bat
```
构建结果将输出在 `dist_v5/LiveCaptionsRecorder/` 目录下。

## 🆕 最近更新

- 2026-04-17: 同步更新 — 已将本地对 app.py 的更改提交并推送到 GitHub；增强了录制稳定性与导出格式兼容性（详见 commit）。

## 📄 许可协议

本项目采用 [MIT License](LICENSE) 许可协议。欢迎反馈与提交 PR！