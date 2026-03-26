import http.server
import json
import os
import re
import time
import urllib.request
import urllib.parse
import io

# ================================================================
# ★ 設定區 — 只需修改這裡
# ================================================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyCR0tveWh_qfkvb-6rxMDT3lZ9UAuJh7yw')
PORT           = int(os.environ.get('PORT', 3000))
# ================================================================

GEMINI_BASE = 'https://generativelanguage.googleapis.com'


def https_request(url, method='GET', data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def upload_to_gemini(file_data, filename, mime_type):
    print(f'[Gemini] 上傳影片：{filename}（{len(file_data)/1024/1024:.1f} MB）')

    # Step 1: 初始化 resumable upload
    init_body = json.dumps({'file': {'display_name': filename}}).encode()
    status, headers, _ = https_request(
        f'{GEMINI_BASE}/upload/v1beta/files?uploadType=resumable&key={GEMINI_API_KEY}',
        method='POST',
        data=init_body,
        headers={
            'Content-Type': 'application/json',
            'Content-Length': str(len(init_body)),
            'X-Goog-Upload-Protocol': 'resumable',
            'X-Goog-Upload-Command': 'start',
            'X-Goog-Upload-Header-Content-Length': str(len(file_data)),
            'X-Goog-Upload-Header-Content-Type': mime_type,
        }
    )

    upload_url = headers.get('X-Goog-Upload-URL') or headers.get('x-goog-upload-url')
    if not upload_url:
        raise Exception(f'Gemini 未回傳上傳 URL，HTTP {status}')
    print('[Gemini] 取得上傳 URL，開始上傳…')

    # Step 2: 上傳檔案本體
    status2, _, body2 = https_request(
        upload_url,
        method='POST',
        data=file_data,
        headers={
            'Content-Length': str(len(file_data)),
            'Content-Type': mime_type,
            'X-Goog-Upload-Offset': '0',
            'X-Goog-Upload-Command': 'upload, finalize',
        }
    )
    upload_result = json.loads(body2)
    file_uri  = upload_result.get('file', {}).get('uri')
    file_name = upload_result.get('file', {}).get('name')
    if not file_uri:
        raise Exception(f'Gemini 未回傳 fileUri：{body2[:200]}')
    print(f'[Gemini] 上傳完成，fileUri: {file_uri}')

    # Step 3: 等待 ACTIVE
    if file_name:
        print('[Gemini] 等待影片處理…')
        for i in range(40):
            time.sleep(3)
            _, _, status_body = https_request(
                f'{GEMINI_BASE}/v1beta/{file_name}?key={GEMINI_API_KEY}'
            )
            status_data = json.loads(status_body)
            state = status_data.get('file', {}).get('state') or status_data.get('state')
            print(f'[Gemini] 狀態: {state}（{(i+1)*3}s）')
            if state == 'ACTIVE':
                break
            if state == 'FAILED':
                raise Exception('Gemini 影片處理失敗，請確認格式（建議 MP4 H.264）')

    return file_uri


def normalize_result(obj, keys):
    """確保 score_reasons 和 scores 都是物件格式（不是陣列）"""
    # scores 陣列 → 物件
    sc = obj.get('scores', {})
    if isinstance(sc, list):
        obj['scores'] = {keys[i]: (sc[i] if i < len(sc) else 0) for i in range(len(keys))}
    elif not isinstance(sc, dict):
        obj['scores'] = {k: 0 for k in keys}

    # score_reasons 陣列 → 物件
    sr = obj.get('score_reasons', {})
    if isinstance(sr, list):
        obj['score_reasons'] = {keys[i]: (sr[i] if i < len(sr) else '') for i in range(len(keys))}
    elif not isinstance(sr, dict):
        obj['score_reasons'] = {k: '' for k in keys}

    return obj


def generate_content(file_uri, mime_type, prompt):
    import json as _json, re as _re
    DIM_KEYS = ['clarity', 'promo', 'language', 'visual', 'cta']

    print('[Gemini] 開始 AI 分析…')

    # 強制 prompt 要求繁體中文輸出
    # 覆蓋 prompt：整合版，減少重複輸出
    forced_prompt = '''你是東森購物LINE群組VCR評鑑專家，精通50-80歲長輩行銷心理學。請仔細觀看影片，全程使用繁體中文，輸出以下JSON（所有字串值必須在同一行，禁止在字串內換行）：

{
  "scores": {"hook": 整數0-20, "demo": 整數0-20, "synergy": 整數0-20, "ux": 整數0-20, "desire": 整數0-20},
  "score_reasons": {
    "hook": "前3秒吸睛力評分理由：標題字體大小、視覺衝擊、是否立刻切入長輩核心問題（一句話）",
    "demo": "商品展示說服力評分理由：特寫、使用前後對比、見證是否讓長輩覺得品質好（一句話）",
    "synergy": "影文銜接導流力評分理由：結尾是否有語音或字幕引導往下看文字（一句話）",
    "ux": "高齡UX友善度評分理由：字幕大小、語速節奏、色調明亮度（一句話）",
    "desire": "購買渴望激發力評分理由：是否塑造美好願景或不買可惜的心理暗示（一句話）"
  },
  "strengths": "條列3-5項影片優點，每項說明清楚重點，每項30字以內，各項之間用\n分隔，格式：1.優點說明\n2.優點說明\n3.優點說明",
  "improvements": "條列3-5項待改善問題並附具體建議，每項說明清楚重點，每項30字以內，各項之間用\n分隔，格式：1.問題→建議\n2.問題→建議\n3.問題→建議",
  "president_view": "以東森購物業務導向為最高原則，從業績、轉單率、ROI角度直接點評：此影片在LINE群組能不能賣給50-80歲長輩？賣點夠不夠強？哪裡會讓長輩划走？改哪裡最能提升業績？語氣直接犀利不客氣，150字以內",
  "conclusion": "一句話總評25字內，聚焦LINE群組長輩轉單效果"
}

注意：所有字串值必須是單行文字，禁止在字串內換行。'''

    req_body = _json.dumps({
        'contents': [{
            'parts': [
                {'file_data': {'mime_type': mime_type, 'file_uri': file_uri}},
                {'text': forced_prompt}
            ]
        }],
        'generationConfig': {
            'maxOutputTokens': 8192,
            'temperature': 0.2
        }
    }).encode('utf-8')

    status, _, body = https_request(
        f'{GEMINI_BASE}/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}',
        method='POST',
        data=req_body,
        headers={
            'Content-Type': 'application/json',
            'Content-Length': str(len(req_body))
        }
    )

    if status != 200:
        raise Exception(f'Gemini 分析失敗 HTTP {status}：{body[:300].decode()}')

    raw = body.decode('utf-8')
    print('[Gemini] 原始回傳前300字：' + raw[:300])

    def fix_newlines(s):
        """把字串值內的真實換行符轉成合法跳脫序列"""
        result = []
        in_str = False
        i = 0
        while i < len(s):
            c = s[i]
            if c == '"' and (i == 0 or s[i-1] != '\\'):
                in_str = not in_str
            if in_str and c == '\n':
                result.append('\\n')
            elif in_str and c == '\r':
                result.append('\\r')
            else:
                result.append(c)
            i += 1
        return ''.join(result)

    # Step1: 解析外層（candidates 包裝）
    try:
        outer = _json.loads(raw)
    except Exception:
        outer = None

    # Step2: 取出實際 JSON 文字
    if outer and 'candidates' in outer:
        text = outer['candidates'][0]['content']['parts'][0].get('text', '')
    elif outer and 'scores' in outer:
        result = normalize_result(outer, DIM_KEYS)
        return _json.dumps(result, ensure_ascii=False).encode('utf-8')
    else:
        text = raw

    # Step3: 清理 markdown fence
    text = text.strip()
    text = _re.sub(r'(?i)^```json\s*', '', text)
    text = _re.sub(r'^```\s*', '', text)
    text = _re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Step4: 修正 text 內的非法換行符，再解析
    text_fixed = fix_newlines(text)
    try:
        parsed = _json.loads(text_fixed)
    except Exception as e:
        raise Exception(f'JSON 解析失敗：{e}，原始：{text[:200]}')

    result = normalize_result(parsed, DIM_KEYS)
    return _json.dumps(result, ensure_ascii=False).encode('utf-8')


APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbz1fq3D964ZerzVxNYccKWPSXCKAIp3UWvU3CgPhqRV7WfB77b2-Ag7GLMn2uh_0JhkUQ/exec'

def save_to_sheets_direct(payload_bytes):
    """接收前端 payload，重組成正確欄位順序後寫入 Google Sheets"""
    import urllib.request as _ur, json as _j
    try:
        d = _j.loads(payload_bytes.decode('utf-8'))

        # 直接建立有序陣列，完全避免 key 名稱對應問題
        row = [
            d.get('timestamp', ''),
            d.get('fileName', ''),
            d.get('productName', ''),
            d.get('targetAge', ''),
            d.get('scoreHook', 0),
            d.get('scoreDemo', 0),
            d.get('scoreSynergy', 0),
            d.get('scoreUx', 0),
            d.get('scoreDesire', 0),
            d.get('total', 0),
            d.get('conclusion', ''),
            d.get('presidentView', ''),
            d.get('strengths', ''),
            d.get('improvements', '')
        ]
        print('[Sheets] 傳送陣列（' + str(len(row)) + '欄）：' + str(row))

        body_out = _j.dumps({'row': row}, ensure_ascii=False).encode('utf-8')
        req = _ur.Request(
            APPS_SCRIPT_URL,
            data=body_out,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with _ur.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8')
            print('[Sheets] 寫入成功，回應：' + body)
            return {'success': True}
    except Exception as e:
        print('[Sheets] 寫入失敗：' + str(e))
        return {'success': False, 'error': str(e)}


def save_to_sheets(result_bytes, filename):
    import json as _j, urllib.request as _ur, urllib.error as _ue
    try:
        data = _j.loads(result_bytes.decode('utf-8'))
        scores = data.get('scores', {})
        payload = _j.dumps({
            'timestamp':    __import__('datetime').datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'productName':  filename,
            'videoId':      '',
            'videoType':    '簡訊發送銷售影片（SMS VCR）',
            'targetAge':    '50-80歲（既有會員）',
            'price':        '',
            'scoreClarity': scores.get('clarity', 0),
            'scorePromo':   scores.get('promo', 0),
            'scoreLanguage':scores.get('language', 0),
            'scoreVisual':  scores.get('visual', 0),
            'scoreCta':     scores.get('cta', 0),
            'total':        sum(scores.get(k, 0) for k in ['clarity','promo','language','visual','cta']),
            'conclusion':   data.get('conclusion', ''),
            'presidentView':str(data.get('president_view', ''))[:300],
            'fileName':     filename,
            'videoMode':    '影片分析'
        }, ensure_ascii=False).encode('utf-8')

        req = _ur.Request(
            APPS_SCRIPT_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with _ur.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8')
            print('[Sheets] 寫入成功，回應：' + body)
    except Exception as e:
        print('[Sheets] 寫入失敗：' + str(e))



class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # 關掉預設 log，用自訂的

    def send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(os.path.join(os.path.dirname(__file__), 'index.html'), 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.send_cors()
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'index.html not found')
        elif self.path == '/save-sheet':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body   = self.rfile.read(length)
                result = save_to_sheets_direct(body)
                out    = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(out)))
                self.send_cors()
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                out = json.dumps({'success': False, 'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(out)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/analyze':
            try:
                # 解析 multipart/form-data
                ct = self.headers.get('Content-Type', '')
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)

                # 手動解析 multipart/form-data
                boundary = re.search(r'boundary=([^\s;]+)', ct)
                if not boundary:
                    raise Exception('找不到 multipart boundary')
                boundary_str = boundary.group(1).encode()

                parts = {}
                for part in body.split(b'--' + boundary_str):
                    if b'\r\n\r\n' not in part:
                        continue
                    header_raw, _, part_body = part.partition(b'\r\n\r\n')
                    part_body = part_body.rstrip(b'\r\n--')
                    header_str = header_raw.decode('utf-8', errors='ignore')

                    name_match = re.search(r'name="([^"]+)"', header_str)
                    if not name_match:
                        continue
                    name = name_match.group(1)

                    fname_match = re.search(r'filename="([^"]+)"', header_str)
                    ct_match = re.search(r'Content-Type:\s*([^\r\n]+)', header_str)

                    parts[name] = {
                        'data': part_body,
                        'filename': fname_match.group(1) if fname_match else None,
                        'content_type': ct_match.group(1).strip() if ct_match else 'application/octet-stream'
                    }

                if 'video' not in parts:
                    raise Exception('未收到影片檔案')
                if 'prompt' not in parts:
                    raise Exception('未收到 prompt')

                filename  = parts['video']['filename'] or 'video.mp4'
                mime_type = parts['video']['content_type']
                file_data = parts['video']['data']
                prompt    = parts['prompt']['data'].decode('utf-8')

                print(f'\n[Server] 收到評鑑請求：{filename}')

                file_uri = upload_to_gemini(file_data, filename, mime_type)
                result   = generate_content(file_uri, mime_type, prompt)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(result)))
                self.send_cors()
                self.end_headers()
                self.wfile.write(result)

            except Exception as e:
                print(f'[Server] 錯誤：{e}')
                err = json.dumps({'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(err)))
                self.send_cors()
                self.end_headers()
                self.wfile.write(err)
        elif self.path == '/save-sheet':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body   = self.rfile.read(length)
                result = save_to_sheets_direct(body)
                out    = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(out)))
                self.send_cors()
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                out = json.dumps({'success': False, 'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors()
                self.end_headers()
                self.wfile.write(out)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print('')
    print('====================================')
    print('  VCR 評鑑機器人 伺服器已啟動')
    print(f'  請開啟瀏覽器前往：')
    print(f'  http://localhost:{PORT}')
    print('====================================')
    print('')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[Server] 已停止')
    input('\n按 Enter 關閉視窗…')
