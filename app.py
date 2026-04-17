import streamlit as st
import pandas as pd
from datetime import datetime
import json
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
import time

# --- 基礎設定 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 【請務必修改此處】你的 Google Sheets 網址
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1kECMoz7jzf-5-PLf9gVZJ4M38_NFFcCID4AILXAtTKk/edit?usp=sharing"

# --- 初始化 Google Sheets 連線 ---
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def sync_data():
    client = get_gsheet_client()
    sheet = client.open_by_url(GSHEET_URL).get_worksheet(0)
    data = sheet.get_all_records()
    return pd.DataFrame(data), sheet

# --- 刪除確認對話框 ---
@st.dialog("⚠️ 確認刪除")
def confirm_delete_dialog(row_index, item_name, sheet):
    st.warning(f"您確定要從雲端刪除「{item_name}」這筆資料嗎？")
    st.write("刪除後將無法復原，需重新輸入。")
    if st.button("🔥 確定刪除", use_container_width=True, type="primary"):
        # DataFrame 的 index 從 0 開始，而 Google Sheets 的資料從第 2 列開始 (第 1 列是標題)
        sheet.delete_rows(row_index + 2)
        st.success("資料已成功刪除！")
        time.sleep(1) # 稍微暫停讓使用者看到成功訊息
        st.rerun()

# --- 初始化 Gemini ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash') 
except Exception as e:
    st.error(f"API Key 設定錯誤：{e}")

if 'ai_processed' not in st.session_state:
    st.session_state.ai_processed = False
if 'current_data' not in st.session_state:
    st.session_state.current_data = None

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

st.title("🧾 旅費拆帳完全體")

tab1, tab2, tab3 = st.tabs(["📸 收據辨識", "✍️ 手動輸入", "📊 雲端帳單結算"])

# === 分頁 1：收據辨識 ===
with tab1:
    uploaded_file = st.file_uploader("上傳收據", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, use_container_width=True)
        if st.button("🤖 AI 辨識", use_container_width=True):
            with st.spinner('辨識中...'):
                prompt = """
                請辨識收據，回傳JSON格式：
                1. "payment_method": 判斷「現金」或「信用卡」。
                2. "items": 包含 original_name, translated_name, price (純數字)。
                只需回傳純JSON。
                """
                try:
                    response = model.generate_content([prompt, image])
                    txt = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                    st.session_state.current_data = json.loads(txt)
                    st.session_state.ai_processed = True
                except Exception as e:
                    st.error("辨識失敗，請重試。")

        if st.session_state.ai_processed and st.session_state.current_data:
            data = st.session_state.current_data
            default_method = "現金"
            if "信用卡" in data.get("payment_method", "") or "卡" in data.get("payment_method", ""):
                default_method = "小君卡"
                
            method = st.selectbox("付款方式", PAYMENT_METHODS, index=PAYMENT_METHODS.index(default_method))
            with st.form("gs_form"):
                rows_to_add = []
                for i, item in enumerate(data.get('items', [])):
                    st.write(f"**{item['translated_name']}** (¥{item['price']})")
                    cons = st.selectbox("誰的消費？", CONSUMERS, key=f"r_{i}")
                    payer = "阿鵬" if method == "阿鵬卡" else "小君"
                    rows_to_add.append([datetime.now().strftime("%Y-%m-%d"), item['translated_name'], item['price'], method, payer, cons])
                
                if st.form_submit_button("✅ 存入雲端試算表", use_container_width=True):
                    try:
                        _, sheet = sync_data()
                        sheet.append_rows(rows_to_add)
                        st.success("已成功同步至 Google Sheets！")
                        st.session_state.ai_processed = False
                    except Exception as e:
                        st.error(f"存檔失敗，請確認 Google Sheets 權限設定。錯誤：{e}")

# === 分頁 2：手動輸入 ===
with tab2:
    with st.form("manual"):
        m_item = st.text_input("消費品項名稱")
        m_price = st.number_input("日幣金額", min_value=0, step=100)
        m_method = st.selectbox("付款方式", PAYMENT_METHODS)
        m_cons = st.selectbox("這筆是誰的？", CONSUMERS)
        if st.form_submit_button("💾 存入雲端", use_container_width=True):
            if m_item:
                try:
                    payer = "阿鵬" if m_method == "阿鵬卡" else "小君"
                    _, sheet = sync_data()
                    sheet.append_row([datetime.now().strftime("%Y-%m-%d"), m_item, m_price, m_method, payer, m_cons])
                    st.success("已成功存入雲端！")
                except Exception as e:
                    st.error("存檔失敗。")

# === 分頁 3：雲端結算 ===
with tab3:
    col_ref, col_sync = st.columns([4, 1])
    with col_sync:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()
    
    try:
        df, sheet = sync_data()
        if not df.empty:
            st.subheader("💰 個人應付總額 (自動拆算)")
            totals = {"阿鵬": 0, "小君": 0, "阿杏": 0}
            for _, r in df.iterrows():
                p, c = r["日幣金額"], r["消費者"]
                if c == "三人分":
                    for k in totals: totals[k] += p/3
                elif c == "金城舞":
                    totals["阿鵬"] += p/2; totals["小君"] += p/2
                elif c in totals:
                    totals[c] += p
            
            c1, c2, c3 = st.columns(3)
            c1.metric("阿鵬", f"¥{int(totals['阿鵬'])}")
            c2.metric("小君", f"¥{int(totals['小君'])}")
            c3.metric("阿杏", f"¥{int(totals['阿杏'])}")
            st.divider()

            st.markdown("#### 📜 詳細帳目明細與管理")
            # 使用卡片式排版，每筆資料旁邊附上專屬的刪除按鈕
            for index, row in df.iterrows():
                with st.container(border=True):
                    c_info, c_del = st.columns([4, 1])
                    with c_info:
                        st.markdown(f"**{row['品項']}** (¥{row['日幣金額']})")
                        st.caption(f"{row['日期']} | 付款：{row['付款方式']} | 對象：{row['消費者']}")
                    with c_del:
                        if st.button("🗑️", key=f"del_{index}", help="刪除此筆資料"):
                            confirm_delete_dialog(index, row['品項'], sheet)
            
            st.divider()
            st.download_button("📥 下載完整 CSV", df.to_csv(index=False).encode('utf-8-sig'), "expenses.csv", "text/csv", use_container_width=True)
            
        else:
            st.info("雲端試算表目前沒有紀錄，趕快去輸入第一筆吧！")
    except Exception as e:
        st.error(f"無法讀取雲端資料，請檢查 Secrets 與試算表共用設定。錯誤細節：{e}")
