# LINE@ AI VCR 評鑑機器人 — 專案文件

## 1. 專案說明

東森購物 LINE 群組專用的 AI 銷售影片評鑑系統。使用者上傳 VCR 影片，系統透過 Google Gemini 2.5 Flash 進行 AI 深度分析，輸出行銷五力評分、總裁視角點評、法規合規建議，並自動記錄到 Google Sheets。

**目標使用者**：東森購物行銷/製作團隊  
**使用場景**：LINE 群組銷售影片（SMS VCR）評鑑，目標受眾為 50-80 歲長輩

---

## 2. 技術架構

```
使用者瀏覽器（index.html）
    ↓ 上傳影片
Google Cloud Run（server.py）
    ↓ 上傳影片
Gemini Files API（影片處理）
    ↓ 分析
Gemini 2.5 Flash（AI 評鑑）
    ↓ 結果
前端顯示 + 寫入 Google Sheets（Apps Script）
```

| 元件 | 技術 | 說明 |
|------|------|------|
| 前端 | HTML/CSS/JS（單一檔案） | 上傳介面、評鑑結果顯示 |
| 後端 | Python 3.11（無第三方套件） | 影片代理上傳、Gemini 呼叫、JSON 正規化 |
| AI | Gemini 2.5 Flash | 影片分析、評分、法規審核 |
| 雲端 | Google Cloud Run（asia-east1 台灣） | 容器化部署 |
| 程式碼 | GitHub（loon0116/vcr-bot） | 原始碼托管、自動部署 |
| 記錄 | Google Sheets + Apps Script | 評鑑結果儲存 |

---

## 3. 主要檔案說明

### `server.py`
Python 後端伺服器，核心邏輯全在這裡。

**重要設定：**
```python
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')  # 只從環境變數讀取，不寫入程式碼
PORT = int(os.environ.get('PORT', 3000))
HOST = '0.0.0.0'  # 雲端部署必須
```

**主要功能：**
- `upload_to_gemini()` — Resumable upload 兩步驟上傳影片到 Gemini Files API，等待 ACTIVE 狀態
- `generate_content()` — 呼叫 Gemini 2.5 Flash 分析，包含完整法規 prompt
- `fix_newlines()` — 修正 Gemini 回傳 JSON 中的非法換行符
- `normalize_result()` — 修正 score_reasons 陣列→物件格式
- `save_to_sheets_direct()` — 代理寫入 Google Sheets（繞過 CORS）
- `/analyze` — 主要評鑑端點
- `/save-sheet` — Google Sheets 寫入端點
- 自動重試機制 — 評鑑失敗最多重試 3 次

**Prompt 結構：**
1. 系統角色設定（LINE 群組 VCR 評鑑專家）
2. 完整台灣廣告法規條文（食品、化粧品認定準則含附件一～四）
3. 輸出 JSON 格式要求

**輸出 JSON 欄位：**
```json
{
  "scores": {"hook": 0-20, "demo": 0-20, "synergy": 0-20, "ux": 0-20, "desire": 0-20},
  "score_reasons": {"hook": "...", "demo": "...", "synergy": "...", "ux": "...", "desire": "..."},
  "strengths": "1.優點\n2.優點\n3.優點",
  "improvements": "1.問題→建議\n2.問題→建議",
  "president_view": "總裁業務導向點評150字",
  "compliance": "1.【違規疑慮】...→【修正建議】...",
  "conclusion": "一句話總評25字"
}
```

### `index.html`
前端單頁應用，所有 HTML/CSS/JS 整合在一個檔案。

**重要常數：**
```javascript
const DIM_LABELS = ['前3秒吸睛力','商品展示說服力','影文銜接導流力','高齡UX友善度','購買渴望激發力'];
const DIM_KEYS   = ['hook','demo','synergy','ux','desire'];
const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbz1fq3D964ZerzVxNYccKWPSXCKAIp3UWvU3CgPhqRV7WfB77b2-Ag7GLMn2uh_0JhkUQ/exec';
```

**主要函數：**
- `submitEval()` — 主流程控制
- `parseResult()` — 解析 Gemini 回傳，包含 normalize() 格式修正
- `showResult()` — 渲染評鑑結果介面
- `saveToSheet()` — 透過 `/save-sheet` 代理寫入 Sheets
- `fmtList()` — 把數字條列格式轉為換行顯示
- `saveToLocal()` — 本機 localStorage 歷史記錄

### `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
EXPOSE 8080
CMD ["python", "server.py"]
```

### Apps Script（Google Sheets）
```javascript
const SHEET_NAME = '工作表1';
function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  sheet.appendRow(d.row);  // 接收陣列直接寫入
  return ok({ success: true });
}
```

---

## 4. 開發規則和注意事項

### API Key 安全
- **絕對不能把 GEMINI_API_KEY 寫入 server.py 程式碼**
- Key 只能存在 Cloud Run 環境變數
- GitHub 公開 repo 會被 Google 自動掃描，Key 出現就會被封鎖
- 傳 Key 給 Claude 時直接貼文字，不要截圖（截圖也可能被掃描）

### Python 相容性
- Cloud Run 使用 Python 3.13，**`cgi` 模組已移除**
- multipart/form-data 必須手動解析（已實作在 server.py）
- 使用 `import re` 等標準模組，不依賴第三方套件

### Gemini 回傳格式問題（常見）
- Gemini 有時在 JSON 字串值內插入真實換行符 → `fix_newlines()` 處理
- `score_reasons` 有時回傳陣列而非物件 → `normalize_result()` 處理
- JSON 解析失敗時有自動重試 3 次機制
- `responseMimeType: 'application/json'` 已移除，改用純文字回傳再解析

### Google Sheets 寫入
- 使用陣列方式 `sheet.appendRow(d.row)` 而非 key-value，確保欄位順序正確
- 寫入順序：`[timestamp, fileName, productName, targetAge, scoreHook, scoreDemo, scoreSynergy, scoreUx, scoreDesire, total, conclusion, presidentView, strengths, improvements]`
- server.py 負責代理寫入（繞過瀏覽器 CORS 限制）

### 更新部署流程
1. 修改 `server.py` 或 `index.html`
2. 上傳到 GitHub（鉛筆圖示編輯 → 替換內容 → Commit changes）
3. Cloud Run 偵測到 GitHub 更新後自動重新部署（約 3-5 分鐘）
4. 若有新 API Key，另外到 Cloud Run 環境變數更新

---

## 5. 目前已完成的功能

### 核心評鑑
- ✅ 影片上傳（MP4/MOV/AVI，建議 50MB 以內）
- ✅ Gemini 2.5 Flash 影片分析
- ✅ 新行銷五力評分（前3秒吸睛力、商品展示說服力、影文銜接導流力、高齡UX友善度、購買渴望激發力）
- ✅ 各維度評分理由顯示
- ✅ 影片優點條列（換行格式）
- ✅ 待改善與優化建議條列（換行格式）
- ✅ 王令麟總裁業務導向視角點評
- ✅ 一句話總評
- ✅ 法規合規建議區塊（依台灣食藥署完整法規審核）

### 介面
- ✅ LINE@ AI VCR 評鑑機器人標題（LINE@ 為綠色）
- ✅ 白色介面、深色文字
- ✅ 五力評分卡片（分數+進度條+描述整合）
- ✅ 總裁視角區塊（金色邊框）
- ✅ 法規合規建議區塊（紅色邊框）
- ✅ 歷史記錄頁籤（localStorage）
- ✅ 評鑑進度動畫

### 資料記錄
- ✅ 自動寫入 Google Sheets（工作表1）
- ✅ 14 個欄位完整記錄
- ✅ 寫入失敗自動回報錯誤訊息

### 雲端部署
- ✅ Google Cloud Run（asia-east1 台灣區）
- ✅ 公開網址：`https://vcr-bot-78310396130.asia-east1.run.app`
- ✅ GitHub 自動部署（push 後自動重建）
- ✅ GEMINI_API_KEY 從環境變數讀取

---

## 6. 尚未完成或待處理的功能

### 穩定性
- ⬜ 偶發性 JSON 解析錯誤（已加重試機制，但根本修正需要更穩健的 fix_newlines）
- ⬜ 影片超過 50MB 的處理方案

### 法規審核
- ⬜ 醫療器材廣告法規條文尚未完整嵌入（目前只有食品和化粧品）
- ⬜ 藥事法完整條文尚未嵌入
- ⬜ 法規審核準確度仍有偶發漏判情況（AI 模型本身的不確定性）

### Google Sheets
- ⬜ 重複寫入問題（目前已修正，但需持續觀察）
- ⬜ 無表頭自動建立功能（需手動貼上標題列）

### 其他
- ⬜ 商品名稱欄位若未填寫，C欄顯示檔案名稱（非正式商品名稱）
- ⬜ 無使用者身份識別（任何人拿到網址都能使用）
- ⬜ 無評鑑歷史的雲端同步（目前歷史記錄只存在個人瀏覽器 localStorage）

---

## 7. 重要連結和資訊

| 項目 | 資訊 |
|------|------|
| 雲端網址 | `https://vcr-bot-78310396130.asia-east1.run.app` |
| GitHub Repo | `github.com/loon0116/vcr-bot` |
| Google Cloud 專案 | AI VCR-test |
| Cloud Run 區域 | asia-east1（台灣） |
| Apps Script URL | `https://script.google.com/macros/s/AKfycbz1fq3D964ZerzVxNYccKWPSXCKAIp3UWvU3CgPhqRV7WfB77b2-Ag7GLMn2uh_0JhkUQ/exec` |
| Google Sheets | AI VCR 評分（工作表1） |
| Gemini 模型 | gemini-2.5-flash |

---

## 8. Google Sheets 欄位對照表

| 欄 | 欄位名稱 |
|----|----------|
| A | 提交時間 |
| B | 檔案名稱 |
| C | 商品名稱 |
| D | 目標受眾 |
| E | 前3秒吸睛力（0-20） |
| F | 商品展示說服力（0-20） |
| G | 影文銜接導流力（0-20） |
| H | 高齡UX友善度（0-20） |
| I | 購買渴望激發力（0-20） |
| J | 總分（0-100） |
| K | 一句話總評 |
| L | 總裁視角點評 |
| M | 影片優點 |
| N | 待改善與優化建議 |
