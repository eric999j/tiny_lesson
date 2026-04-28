# Tiny Lesson – Python Tkinter 語言學習 App

模仿 Google「Tiny Lesson」概念的桌面學習小工具：
**選語言 → 輸入情境 → 自動推薦單字／文法／句子 → 一鍵發音 → 自動寫入歷史**

支援語言：英文、日文、葡萄牙文。

## 功能
- 📚 **學習**：選擇語言（英 / 日 / 葡）+ 輸入情境（例：「在機場辦理登機」），由 Hugging Face Inference API 生成
  - 6 個單字（含中文翻譯）
  - 3 條文法重點（含中文說明 + 例句）
  - 5 個情境句（含中文翻譯）
  - 每張卡片旁邊有 🔊 按鈕，使用 gTTS 即時生成並播放
- 🕘 **歷史**：所有看過 / 生成過的內容自動存入 JSON，可分類瀏覽、重播、刪除、匯出
  - 同一語境下的歷史會在各分類頁以樹狀方式摺疊顯示
  - 歷史條目的 TTS 音檔會以內容 hash 快取在本地，重播時優先使用本地音檔
  - 刪除單一條目時，若對應音檔已無其他條目引用，會一併刪除本地 mp3
- ⚙ **設定**：管理 HF Token、模型、淺色 / 深色主題、TTS 慢速朗讀、清除歷史

## 安裝
需要 Python 3.10 以上。

```powershell
cd tiny_lesson
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 取得 Hugging Face Token（免費）
1. 註冊 / 登入 https://huggingface.co
2. 至 https://huggingface.co/settings/tokens
3. **New token → Fine-grained**
4. 勾選 **「Make calls to Inference Providers」** 一項即可（其他不用勾）
5. 複製產生的 `hf_xxx...` Token
6. 啟動 App 後到「設定」分頁貼上、按「儲存設定」

> 舊版的「Read」type 也可用，但 fine-grained 最安全。

## 執行
```powershell
python main.py
```

## 主題切換
- 到「設定」分頁可切換 `淺色 Light` 與 `深色 Dark`
- 按「儲存設定」後會立即套用，不需要重啟
- 主題偏好會寫入 `%APPDATA%\TinyLesson\settings.json`

## 資料位置
所有設定、歷史、TTS 音檔快取存在：
```
%APPDATA%\TinyLesson\
├── settings.json
├── history.json
└── tts_cache\*.mp3
```

## 疑難排解
- **第一次生成回 503 / 等很久**：模型冷啟動，程式會自動重試 3 次。
- **404 找不到模型**：到「設定」改用支援 Inference Providers 的模型，例如：
  - `meta-llama/Llama-3.3-70B-Instruct`（預設，需先到模型頁面同意條款）
  - `Qwen/Qwen2.5-7B-Instruct`
  - `mistralai/Mistral-7B-Instruct-v0.3`
- **402 額度用完**：免費額度月度有上限，等下個月或換模型。
- **聽不到聲音**：確認電腦音訊正常；本程式用 `pygame.mixer` 播放 mp3。
- **gTTS 無法使用**：需要網路。離線時播放按鈕會顯示錯誤。

## 技術
- GUI：tkinter / ttk
- LLM：Hugging Face Inference API
- TTS：gTTS + pygame
- 儲存：JSON
