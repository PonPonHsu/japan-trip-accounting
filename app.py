import streamlit as st
import pandas as pd
from datetime import datetime
import json
import google.generativeai as genai
from PIL import Image

# --- 初始化設定與暫存區 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 設定 Gemini API
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
except Exception as e:
    st.error("⚠️ 尚未設定 Gemini API Key，請至 Streamlit Secrets 中設定。")

if 'expense_db' not in st.session_state:
    st.session_state.expense_db = []
if 'ai_processed' not in st.session_state:
    st.session_state.ai_processed = False
if 'current_receipt_data' not in st.session_state:
    st.session_state.current_receipt_data = None

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

def get_payer(method):
    if method in ["現金", "小君卡"]:
        return "小君"
    elif method == "阿鵬卡":
        return "阿鵬"
    return "未知"

st.title("🧾 旅費拆帳小幫手")
tab1, tab2, tab3 = st.tabs(["📸 收據辨識", "✍️ 手動輸入", "📊 結算與匯出"])

# === 分頁 1：收據辨識模式 ===
with tab1:
    st.markdown("### 📤 上傳收據檔案")
    uploaded_file = st.file_uploader("請選擇收據圖片", type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="收據預覽", use_container_width=True)
        st.divider()
        
        if st.button("🤖 交給 AI 辨識收據", use_container_width=True):
            with st.spinner('AI 正在努力辨識品項與翻譯中，請稍候...'):
                prompt = """
                你是一個專業的日文收據辨識與記帳助理。請辨識圖片中的收據，並以 JSON 格式回傳以下資訊：
                1. "payment_method": 判斷是「現金」或「信用卡」。（若有SMCC, MASTERCARD, VISA等信用卡特徵請判定為信用卡，否則預設為現金）。
                2. "items": 包含所有消費品項的陣列。每個項目包含 "original_name" (日文原名)、"translated_name" (繁體中文翻譯) 與 "price" (日幣金額數字)。
                請只回傳純 JSON 字串，不要包含任何 Markdown 標記 (如 ```json) 或其他說明文字。
                """
                try:
                    response = model.generate_content([prompt, image])
                    # 清理可能夾帶的 Markdown 標籤
                    result_text = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                    st.session_state.current_receipt_data = json.loads(result_text)
                    st.session_state.ai_processed = True
                except Exception as e:
                    st.error(f"辨識發生錯誤，請重試。詳細錯誤：{e}")
                
        if st.session_state.ai_processed and st.session_state.current_receipt_data:
            st.subheader("🛒 辨識結果與品項分配")
            
            data = st.session_state.current_receipt_data
            
            # 將 AI 判斷的「信用卡」對應回表單選項 (預設先給小君卡，可手動改)
            default_method = "現金"
            if "信用卡" in data.get("payment_method", "") or "卡" in data.get("payment_method", ""):
                default_method = "小君卡" 
                
            payment_method = st.selectbox("確認付款方式", PAYMENT_METHODS, index=PAYMENT_METHODS.index(default_method))
            payer = get_payer(payment_method)
            st.info(f"👉 系統判定代墊者：**{payer}**")
            
            with st.form("receipt_form"):
                selections = []
                for i, item in enumerate(data.get("items", [])):
                    st.markdown(f"**{item['translated_name']}** ({item['original_name']})")
                    
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        st.write(f"¥ {item['price']}")
                    with c2:
                        consumer = st.selectbox(
                            "誰的消費？", options=CONSUMERS, key=f"r_item_{i}", label_visibility="collapsed"
                        )
                    
                    selections.append({
                        "日期": datetime.now().strftime("%Y-%m-%d"),
                        "品項": item['translated_name'],
                        "日幣金額": item['price'],
                        "付款方式": payment_method,
                        "代墊者": payer,
                        "消費者": consumer
                    })
                    st.write("---")
                    
                if st.form_submit_button("💾 儲存這筆收據", use_container_width=True):
                    st.session_state.expense_db.extend(selections)
                    st.success("✅ 收據明細已加入資料庫！請至「結算報表」查看。")
                    st.session_state.ai_processed = False

# === 分頁 2：手動輸入模式 ===
with tab2:
    st.subheader("✍️ 新增單筆無收據消費")
    with st.form("manual_form"):
        m_date = st.date_input("日期", datetime.now())
        m_item = st.text_input("消費品項名稱")
        m_price = st.number_input("日幣金額", min_value=0, step=100)
        m_method = st.selectbox("付款方式", PAYMENT_METHODS)
        m_consumer = st.selectbox("這筆是誰的消費？", CONSUMERS)
        
        if st.form_submit_button("💾 儲存", use_container_width=True) and m_item:
            st.session_state.expense_db.append({
                "日期": m_date.strftime("%Y-%m-%d"), "品項": m_item, "日幣金額": m_price,
                "付款方式": m_method, "代墊者": get_payer(m_method), "消費者": m_consumer
            })
            st.success("✅ 已新增！")

# === 分頁 3：結算與匯出 ===
with tab3:
    st.subheader("📊 目前累積帳單")
    if len(st.session_state.expense_db) == 0:
        st.write("目前還沒有紀錄喔！")
    else:
        df = pd.DataFrame(st.session_state.expense_db)
        st.dataframe(df, use_container_width=True)
        
        st.divider()
        st.subheader("💰 個人應付總額 (自動拆算)")
        totals = {"阿鵬": 0.0, "小君": 0.0, "阿杏": 0.0}
        
        for _, row in df.iterrows():
            price, consumer = row["日幣金額"], row["消費者"]
            if consumer == "三人分":
                totals["阿鵬"] += price / 3; totals["小君"] += price / 3; totals["阿杏"] += price / 3
            elif consumer == "金城舞":
                totals["阿鵬"] += price / 2; totals["小君"] += price / 2
            elif consumer in totals:
                totals[consumer] += price
                
        c_a, c_b, c_c = st.columns(3)
        c_a.metric("阿鵬", f"¥ {int(totals['阿鵬'])}")
        c_b.metric("小君", f"¥ {int(totals['小君'])}")
        c_c.metric("阿杏", f"¥ {int(totals['阿杏'])}")
        
        st.divider()
        st.download_button("📥 下載 CSV", df.to_csv(index=False).encode('utf-8-sig'), "expenses.csv", "text/csv", use_container_width=True)
        if st.button("🗑️ 清空紀錄", use_container_width=True, type="primary"):
            st.session_state.expense_db = []
            st.rerun()
