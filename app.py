import streamlit as st
import pandas as pd
from datetime import datetime
import json
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pypdf import PdfReader, PdfWriter
import io
import time

# --- 基礎設定 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 【請務必修改此處】你的 Google Sheets 網址
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1kECMoz7jzf-5-PLf9gVZJ4M38_NFFcCID4AILXAtTKk/edit?gid=0#gid=0"

# 【請務必修改此處】Google Drive 總收據資料夾 ID
DRIVE_ROOT_ID = "1PeLDeGLAvcKTYRLIiK-m_AAIKNDGzLll"

# --- 側邊欄設計 ---
with st.sidebar:
    st.title("🧳 旅程快捷鍵")
    st.link_button("📊 查看完整雲端帳單 ↗️", GSHEET_URL, use_container_width=True)
    st.metric("設定匯率", "0.203")
    st.divider()
    st.caption("提示：手動輸入適合沒收據的消費；批次辨識適合晚回飯店處理整疊收據。")

# --- 服務初始化函式 ---
def get_creds():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)

def get_gsheet_client():
    return gspread.authorize(get_creds())

def get_drive_service():
    return build('drive', 'v3', credentials=get_creds())

def sync_data():
    client = get_gsheet_client()
    sheet = client.open_by_url(GSHEET_URL).get_worksheet(0)
    data = sheet.get_all_records()
    return pd.DataFrame(data), sheet

def list_subfolders(parent_id):
    service = get_drive_service()
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return {f['name']: f['id'] for f in results.get('files', [])}

def list_files_in_folder(folder_id):
    service = get_drive_service()
    query = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType = 'application/pdf') and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def download_file(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        _, done = downloader.next_chunk()
    return fh.getvalue()

# --- 刪除對話框 ---
@st.dialog("⚠️ 確認刪除")
def confirm_delete_dialog(row_index, item_name, sheet):
    st.warning(f"確定要從雲端刪除「{item_name}」？")
    if st.button("🔥 確定刪除", use_container_width=True, type="primary"):
        sheet.delete_rows(row_index + 2)
        st.success("已刪除！")
        time.sleep(1)
        st.rerun()

# --- 初始化 Gemini ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
except:
    st.error("API Key 設定錯誤")

# --- 狀態初始化 ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

st.title("🧾 旅費拆帳完全體")

# 將「手動輸入」移到第一個，使其成為預設分頁
tab1, tab2, tab3 = st.tabs(["✍️ 手動輸入", "📸 批次收據辨識", "📊 雲端帳單結算"])

# === 分頁 1：手動輸入 (預設) ===
with tab1:
    st.subheader("✍️ 新增單筆隨手記")
    with st.form("manual_entry_form"):
        m_item = st.text_input("品項名稱 (例如：販賣機飲料)")
        m_price = st.number_input("日幣金額", min_value=0, step=10, value=0)
        m_method = st.selectbox("付款方式", PAYMENT_METHODS)
        m_cons = st.selectbox("這筆是誰的消費？", CONSUMERS)
        
        if st.form_submit_button("💾 儲存至雲端試算表", use_container_width=True):
            if m_item and m_price > 0:
                try:
                    _, sheet = sync_data()
                    payer = "阿鵬" if m_method == "阿鵬卡" else "小君"
                    sheet.append_row([datetime.now().strftime("%Y-%m-%d"), m_item, m_price, m_method, payer, m_cons])
                    st.success(f"✅ 已存入：{m_item} ¥{m_price}")
                except Exception as e:
                    st.error(f"存檔失敗：{e}")
            else:
                st.warning("請填寫品項名稱與金額。")

# === 分頁 2：批次收據辨識 (支援 PDF 拆頁) ===
with tab2:
    st.subheader("📂 雲端收據批次處理")
    try:
        subfolders = list_subfolders(DRIVE_ROOT_ID)
        folder_name = st.selectbox("選擇收據資料夾", ["直接讀取根目錄"] + list(subfolders.keys()))
        current_folder_id = subfolders[folder_name] if folder_name != "直接讀取根目錄" else DRIVE_ROOT_ID
        
        files = list_files_in_folder(current_folder_id)
        if not files:
            st.info("資料夾內沒有可辨識的檔案。")
        else:
            selected_files = []
            for f in files:
                if st.checkbox(f['name'], key=f"check_{f['id']}"):
                    selected_files.append((f['id'], f['name']))
            
            if selected_files:
                if st.button(f"🤖 開始辨識任務", use_container_width=True, type="primary"):
                    st.session_state.batch_results = []
                    
                    # 1. 將 PDF 拆頁並建立任務清單
                    task_list = []
                    for f_id, f_name in selected_files:
                        data = download_file(f_id)
                        if f_name.lower().endswith('.pdf'):
                            reader = PdfReader(io.BytesIO(data))
                            for p_num in range(len(reader.pages)):
                                writer = PdfWriter(); writer.add_page(reader.pages[p_num])
                                page_bytes = io.BytesIO(); writer.write(page_bytes)
                                task_list.append({"name": f"{f_name} (p{p_num+1})", "data": {"mime_type": "application/pdf", "data": page_bytes.getvalue()}})
                        else:
                            task_list.append({"name": f_name, "data": Image.open(io.BytesIO(data))})
                    
                    # 2. 逐頁執行 AI 辨識
                    prog = st.progress(0)
                    total = len(task_list)
                    st.info(f"預計處理 {total} 個頁面，約需 {total*15/60:.1f} 分鐘。")
                    
                    for i, task in enumerate(task_list):
                        with st.spinner(f"正在分析 {task['name']}..."):
                            prompt = "你是一個專業記帳助理。請辨識這張收據，回傳純 JSON 格式，包含 payment_method 與 items (original_name, translated_name, price)。translated_name 需為繁體中文或品牌音譯。"
                            response = model.generate_content([prompt, task['data']])
                            txt = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                            res = json.loads(txt)
                            res['file_name'] = task['name']
                            st.session_state.batch_results.append(res)
                        
                        prog.progress((i + 1) / total)
                        if i < total - 1: time.sleep(15) # 避開 API 限制
                    st.success("✅ 辨識完成！")

    except Exception as e:
        st.error(f"雲端連線問題：{e}")

    # 分配與存檔
    if st.session_state.batch_results:
        with st.form("batch_form"):
            all_rows = []
            for idx, res in enumerate(st.session_state.batch_results):
                st.markdown(f"**📄 {res['file_name']}**")
                def_m = "小君卡" if "卡" in res.get("payment_method","") else "現金"
                m = st.selectbox(f"付款方式", PAYMENT_METHODS, index=PAYMENT_METHODS.index(def_m), key=f"bm_{idx}")
                for j, item in enumerate(res.get('items', [])):
                    c1, c2 = st.columns([2, 1])
                    with c1: st.write(f"· {item['translated_name']} (¥{item['price']})")
                    with c2: cons = st.selectbox("誰的？", CONSUMERS, key=f"bc_{idx}_{j}", label_visibility="collapsed")
                    all_rows.append([datetime.now().strftime("%Y-%m-%d"), item['translated_name'], item['price'], m, "阿鵬" if m=="阿鵬卡" else "小君", cons])
                st.write("---")
            if st.form_submit_button("✅ 全部同步至試算表", use_container_width=True):
                _, sheet = sync_data(); sheet.append_rows(all_rows)
                st.success("已同步！"); st.session_state.batch_results = []

# === 分頁 3：雲端結算 ===
with tab3:
    if st.button("🔄 刷新雲端資料"): st.rerun()
    try:
        df, sheet = sync_data()
        if not df.empty:
            totals = {"阿鵬": 0.0, "小君": 0.0, "阿杏": 0.0}
            for _, r in df.iterrows():
                p, c = r["日幣金額"], r["消費者"]
                if c == "三人分":
                    for k in totals: totals[k] += p/3
                elif c == "金城舞":
                    totals["阿鵬"] += p/2; totals["小君"] += p/2
                elif c in totals: totals[c] += p
            
            c1, c2, c3 = st.columns(3)
            c1.metric("阿鵬", f"¥{int(totals['阿鵬'])}")
            c2.metric("小君", f"¥{int(totals['小君'])}")
            c3.metric("阿杏", f"¥{int(totals['阿杏'])}")
            
            st.divider()
            for index, row in df.iterrows():
                with st.container(border=True):
                    ci, cd = st.columns([4, 1])
                    with ci:
                        st.markdown(f"**{row['品項']}** (¥{row['日幣金額']})")
                        st.caption(f"{row['日期']} | {row['消費者']} | 代墊：{row['代墊者']}")
                    with cd:
                        if st.button("🗑️", key=f"del_{index}"): confirm_delete_dialog(index, row['品項'], sheet)
        else:
            st.info("目前雲端沒有紀錄。")
    except Exception as e:
        st.error(f"讀取失敗：{e}")
