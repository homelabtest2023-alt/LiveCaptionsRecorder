# Code Review Report - Live Captions Recorder

我對 `live-captions-recorder` 專案進行了完整的代碼審查，發現了以下需要注意的地方以及可以優化的項目：

## 🛑 發現的 Bugs 與嚴重問題

### 1. uiautomation 在多執行緒下的 COM 初始化錯誤
在根目錄的 `@AutomationLog.txt` 中可以看到大量報錯：
`[WinError -2147221008] CoInitialize has not been called. Can not load UIAutomationCore.dll...`
**原因：** `RecorderWorker._run` 是在獨立的背景執行緒中運行。雖然使用了 `pythoncom.CoInitialize()`，但 `uiautomation` 為了確保安全，內部必須使用自己的方式來初始化背景執行緒。
**解決方案：** 根據 `uiautomation` 的官方建議與 log 錯誤提示，應該使用 `UIAutomationInitializerInThread` 替換原本的 `pythoncom` 呼叫：
```python
def _run(self) -> None:
    # 移除原本的 pythoncom.CoInitialize() 和 pythoncom.CoUninitialize()
    with auto.UIAutomationInitializerInThread():
        missing_window_reported = False
        # ... 接原本的 try...while 迴圈
```

### 2. 遺漏了 SRT 與 JSONL 匯出功能
在 `README.md` 中寫道「同步輸出 `jsonl`、`txt`、`srt`」，且 `app.py` 內已經寫好了 `format_srt_timestamp` 與 `TranscriptSegment.to_dict` 這些輔助函式。但是，`SessionExporter.save` 方法**實際上只實作了輸出 `.txt` 檔案**。
**解決方案：** 需要在 `app.py` 的 `SessionExporter.save` 中補齊另外兩種格式的實作：
```python
def save(self, segments: list[TranscriptSegment], finished_at: datetime) -> list[Path]:
    stamp = finished_at.strftime("%Y%m%d_%H%M%S")
    files_created = []

    # 1. 儲存 TXT
    txt_path = self.output_dir / f"captions_{stamp}.txt"
    with txt_path.open("w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(f"[{segment.start_text} -> {segment.end_text}] {segment.text}\n")
    files_created.append(txt_path)

    # 2. 儲存 SRT
    srt_path = self.output_dir / f"captions_{stamp}.srt"
    with srt_path.open("w", encoding="utf-8") as handle:
        for i, segment in enumerate(segments, 1):
            handle.write(f"{i}\n")
            handle.write(f"{format_srt_timestamp(segment.start_at)} --> {format_srt_timestamp(segment.end_at)}\n")
            handle.write(f"{segment.text}\n\n")
    files_created.append(srt_path)

    # 3. 儲存 JSONL
    jsonl_path = self.output_dir / f"captions_{stamp}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(json.dumps(segment.to_dict(), ensure_ascii=False) + "\n")
    files_created.append(jsonl_path)

    return files_created
```

---

## ⚡ 潛在風險與邊界條件 (Edge Cases)

### Race Condition 風險
在 `RecorderWorker.stop` 方法中：
```python
    self._thread.join(timeout=3)
    self._thread = None
    # 接著準備匯出檔案
```
因為 `join` 設定了 `timeout=3`，如果底層的 `uiautomation` API 被 Windows 卡住超過 3 秒，主執行緒就會超時放棄等待並往下執行，準備讀取 `self.builder` 匯出檔案。這時如果背景執行緒還在寫入，就會發生資源競爭錯誤。
不過考慮到 `uiautomation` 超時的機率不高，這一點對腳本工具來說尚可接受。建議將來若發現崩潰，可以把 `timeout=3` 拿掉，改用 UI 等待。

---

## 🚀 程式碼品質與效能優化建議

### 1. 避免重複的字串與正則表達式運算 (效能優化)
- **Regex 重複編譯**：在 `CaptionExtractor.normalize_text` 當中，`re.sub(r"\s+", " ", line)` 會在每次迴圈（預設 0.7 秒一次）與每個 Control 節點對文字進行處理時重複編譯。建議把正則表達式拉到類別常數：
  ```python
  class CaptionExtractor:
      _SPACES_RE = re.compile(r"\s+")
      
      @classmethod
      def normalize_text(cls, text: str) -> str:
          text = text.replace("\r", "\n")
          lines = [cls._SPACES_RE.sub(" ", line).strip() for line in text.splitlines()]
          return "\n".join(line for line in lines if line)
  ```
- **字串搜尋無須重新轉小寫**：`LiveCaptionsFinder._matches` 也是極高頻呼叫的函式，但目前每次都在迴圈裡呼叫 `keyword.lower()`。可以改在 `update_keywords()` 時直接將陣列預存為小寫即可。

### 2. 空白異常捕捉
在 `app.py` 第 113行與 165行，捕捉了寬泛的 Exception `except Exception as exc: # noqa: BLE001`。雖然註解了 `BLE001` 讓 linter 放行，但抓取所有例外可能會因為預期外的問題（比如記憶體耗盡）而導致無窮迴圈，實務上可捕捉更明確的 `COMError`，或者列印到 debug 日誌再 `continue`。

---

## 🌟 值得肯定的優點

1. **架構分層優良**：UI 的職責 (`App`) 與業務邏輯職責 (`RecorderWorker`, `CaptionExtractor`) 嚴格分離，非常乾淨。
2. **執行緒資料連通**：使用了 `queue.Queue` 和 `root.after` 機制，確保了安全的跨執行緒 UI 刷新，寫法專業。
3. **Typing 和封裝**：善用 `dataclass` 定義 `TranscriptSegment` 結構，並且提供了完整的 Type Hinting，維持了很好的程式碼可維護性。
4. **PyInstaller 相容性細節**：專門寫了 `configure_tk_runtime()` 來修復 PyInstaller 尋找 Tk/Tcl 資源的路徑問題，解決了很多開發者最頭痛的問題！
