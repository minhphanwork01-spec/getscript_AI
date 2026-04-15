import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs
import google.generativeai as genai

# 1. Cấu hình giao diện
st.set_page_config(page_title="Missevan AI Sub Tool", page_icon="🎙️", layout="wide")

st.title("🎙️ Missevan AI Sub Tool")
st.caption("Chuyên bóc tách script và dịch thuật bằng AI (Gemini 1.5 Flash)")

# 2. Thanh cấu hình bên hông
with st.sidebar:
    st.header("⚙️ Cấu hình")
    api_key = st.text_input("Gemini API Key:", type="password", help="Lấy tại aistudio.google.com")
    cookie = st.text_input("Cookie Missevan (nếu có):", type="password")
    st.divider()
    genre = st.selectbox(
        "Văn phong dịch AI:",
        ["Hiện đại (Tôi - Bạn)", "Cổ phong (Hán Việt, Ta - Đồ nhi)", "Sát nghĩa (Học tập)", "Tự nhập yêu cầu..."]
    )
    custom_req = ""
    if genre == "Tự nhập yêu cầu...":
        custom_req = st.text_input("Nhập yêu cầu riêng:")

# 3. Giao diện chính
url_input = st.text_input("Dán link Missevan vào đây:", placeholder="https://www.missevan.com/sound/11339811")

# Khởi tạo session_state để lưu kết quả khi bấm nút tải
if 'final_result' not in st.session_state:
    st.session_state['final_result'] = None

# --- HÀM DỊCH AI ---
def translate_now(text_block, key, style, manual_req):
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
        
        instructions = {
            "Hiện đại (Tôi - Bạn)": "Dịch kịch truyền thanh hiện đại, xưng hô Anh/Em, Tôi/Bạn linh hoạt.",
            "Cổ phong (Hán Việt, Ta - Đồ nhi)": "Dịch văn phong cổ trang, tiên hiệp. Dùng từ Hán Việt, xưng hô Ta - Ngươi/Đồ nhi/Sư tôn.",
            "Sát nghĩa (Học tập)": "Dịch sát nghĩa từng từ để hỗ trợ học ngữ pháp và từ vựng tiếng Trung."
        }
        selected = manual_req if style == "Tự nhập yêu cầu..." else instructions.get(style, "")
        
        prompt = f"Bạn là biên dịch viên kịch truyền thanh Trung-Việt. Yêu cầu: {selected}\nQUY TẮC: Giữ nguyên mốc [mm:ss] ở đầu mỗi dòng. KHÔNG gộp dòng.\n\nNội dung:\n{text_block}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"[Lỗi AI: {str(e)}]"

# 4. Xử lý chính
if st.button("🚀 Bắt đầu bóc tách và dịch AI", use_container_width=True):
    if not url_input or not api_key:
        st.warning("Vui lòng nhập đầy đủ Link và API Key!")
    else:
        with st.spinner("Đang xử lý dữ liệu..."):
            try:
                # Logic nhận diện ID (Giữ nguyên của Khai)
                parsed_url = urlparse(url_input)
                query_params = parse_qs(parsed_url.query)
                sound_id = query_params.get('id', [None])[0] or next((p for p in reversed(parsed_url.path.split('/')) if p.isdigit()), None)
                
                headers = {"User-Agent": "Mozilla/5.0", "Referer": url_input, "Cookie": cookie}
                info = requests.get(f"https://www.missevan.com/sound/getsound?soundid={sound_id}", headers=headers).json()
                
                if info.get('success'):
                    title = info['info']['sound']['soundstr']
                    dm_resp = requests.get(f"https://www.missevan.com/sound/getdm?soundid={sound_id}", headers=headers)
                    root = ET.fromstring(dm_resp.content)
                    
                    items, uids_45 = [], []
                    for d in root.findall('.//d'):
                        p = d.get('p').split(',')
                        if d.text:
                            items.append({'t': float(p[0]), 'm': p[1], 'uid': p[6], 'txt': d.text.strip()})
                            if p[1] in ['4', '5']: uids_45.append(p[6])
                    
                    sub_uids = [uid for uid, c in Counter(uids_45).items() if c > 5]
                    final = [i for i in items if i['uid'] in sub_uids and i['m'] in ['4', '5']] if sub_uids else items
                    final.sort(key=lambda x: x['t'])
                    
                    # Tạo block tiếng Trung
                    cn_text = ""
                    for item in final:
                        m, s = divmod(int(item['t']), 60)
                        cn_text += f"[{m:02d}:{s:02d}] {item['txt']}\n"
                    
                    # Dịch AI
                    vi_text = translate_now(cn_text, api_key, genre, custom_req)
                    
                    # Lưu kết quả
                    st.session_state['final_result'] = {
                        'title': title,
                        'cn': cn_text,
                        'vi': vi_text,
                        'file_name': f"AI_Sub_{re.sub(r'[\\\\/*?:\u0022<>|]', '', title)}.txt"
                    }
                else:
                    st.error("Không lấy được dữ liệu. Kiểm tra lại Link hoặc Cookie.")
            except Exception as e:
                st.error(f"Lỗi: {e}")

# 5. Hiển thị kết quả
if st.session_state['final_result']:
    res = st.session_state['final_result']
    st.success(f"Hoàn tất: {res['title']}")
    
    # Nút tải đặt lên đầu
    st.download_button(
        label="📥 Tải Bản Dịch AI (.txt)",
        data=res['vi'],
        file_name=res['file_name'],
        mime="text/plain",
        use_container_width=True
    )
    
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🇨🇳 Gốc (Trung)")
        st.code(res['cn'], language="text")
    with col2:
        st.subheader("🇻🇳 Dịch AI (Việt)")
        st.code(res['vi'], language="text")