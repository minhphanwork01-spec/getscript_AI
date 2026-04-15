import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs
from deep_translator import GoogleTranslator

# 1. Cấu hình giao diện
st.set_page_config(page_title="Missevan Sub Tool", page_icon="🎙️", layout="wide")

st.title("🎙️ Missevan Sub Tool")
st.markdown("---")

# 2. Thanh cấu hình bên hông
with st.sidebar:
    st.header("Cấu hình hệ thống")
    cookie = st.text_input("Cookie xác thực (Missevan):", type="password")
    st.markdown("---")
    st.info("**Quy trình:** Bóc tách -> Hiện Text Gốc & Nút tải Gốc -> Dịch ngầm -> Hiện Nút tải Dịch.")

# 3. Giao diện nhập liệu
url_input = st.text_input("Nhập liên kết âm thanh Missevan:", placeholder="https://www.missevan.com/sound/11339811")

# Khởi tạo session_state
if 'cn_output' not in st.session_state:
    st.session_state['cn_output'] = None
if 'vi_output' not in st.session_state:
    st.session_state['vi_output'] = None
if 'title' not in st.session_state:
    st.session_state['title'] = "Sub_Missevan"

# --- HÀM XỬ LÝ DỊCH THUẬT ---
def translate_script(cn_text):
    try:
        translator = GoogleTranslator(source='zh-CN', target='vi')
        lines = cn_text.split('\n')
        translated_lines = []
        
        progress_bar = st.progress(0, text="Đang khởi tạo bản dịch...")
        
        # Lọc danh sách dòng cần dịch để tính % chính xác
        content_indices = [i for i, l in enumerate(lines) if re.match(r'\[.*?\]', l)]
        total = len(content_indices)
        
        for i, line in enumerate(lines):
            match = re.match(r'(\[.*?\])\s*(.*)', line)
            if match:
                timestamp, content = match.groups()
                if content.strip():
                    translated_content = translator.translate(content)
                    translated_lines.append(f"{timestamp} {translated_content}")
                else:
                    translated_lines.append(line)
                
                # Cập nhật tiến độ
                current_count = content_indices.index(i) + 1
                progress_bar.progress(current_count / total, text=f"Đang dịch: {current_count}/{total} dòng")
            else:
                translated_lines.append(line)
        
        progress_bar.empty()
        return "\n".join(translated_lines)
    except Exception as e:
        return f"[Lỗi dịch: {str(e)}]"

# 4. Logic bóc tách dữ liệu
if st.button("🚀 Khởi chạy bóc tách dữ liệu", use_container_width=True):
    if not url_input:
        st.warning("Vui lòng nhập liên kết.")
    else:
        with st.spinner("Đang truy xuất từ Missevan..."):
            try:
                parsed_url = urlparse(url_input)
                query_params = parse_qs(parsed_url.query)
                sound_id = query_params.get('id', [None])[0] or next((p for p in reversed(parsed_url.path.split('/')) if p.isdigit()), None)
                
                headers = {"User-Agent": "Mozilla/5.0", "Referer": url_input, "Cookie": cookie}
                info = requests.get(f"https://www.missevan.com/sound/getsound?soundid={sound_id}", headers=headers).json()
                
                if info.get('success'):
                    st.session_state['title'] = info['info']['sound']['soundstr']
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
                    
                    # Tạo nội dung gốc
                    cn_text = f"TITLE: {st.session_state['title']}\nNGUỒN: {url_input}\nSỐ DÒNG: {len(final)}\n" + "-"*30 + "\n"
                    for item in final:
                        m, s = divmod(int(item['t']), 60)
                        cn_text += f"[{m:02d}:{s:02d}] {item['txt']}\n"
                    
                    st.session_state['cn_output'] = cn_text
                    st.session_state['vi_output'] = None # Reset dịch
                    st.rerun()
                else:
                    st.error("Không tìm thấy dữ liệu âm thanh.")
            except Exception as e:
                st.error(f"Lỗi: {e}")

# 5. HIỂN THỊ UI (PHẦN QUAN TRỌNG NHẤT)
if st.session_state['cn_output']:
    safe_title = re.sub(r'[\\/*?:"<>|]', '', st.session_state['title'])
    
    # --- KHU VỰC NÚT TẢI PHÍA TRÊN ---
    dl_col1, dl_col2 = st.columns(2)
    
    with dl_col1:
        # Nút tải bản gốc luôn sẵn sàng
        st.download_button(
            label="📥 Tải Bản Gốc (CN)",
            data=st.session_state['cn_output'],
            file_name=f"CN_{safe_title}.txt",
            mime="text/plain",
            use_container_width=True
        )
        
    with dl_col2:
        # Kiểm tra trạng thái dịch để hiển thị nút
        if st.session_state['vi_output']:
            st.download_button(
                label="📥 Tải Bản Dịch (VI)",
                data=st.session_state['vi_output'],
                file_name=f"VI_{safe_title}.txt",
                mime="text/plain",
                use_container_width=True
            )
        else:
            # Nút giả bị làm mờ (disabled) khi chưa dịch xong
            st.button("📥 Tải Bản Dịch (Đang xử lý...)", disabled=True, use_container_width=True)

    st.divider()

    # --- KHU VỰC HIỂN THỊ TEXT ---
    txt_col1, txt_col2 = st.columns(2)
    
    with txt_col1:
        st.subheader("Văn bản gốc")
        st.code(st.session_state['cn_output'], language="text")
        
    with txt_col2:
        st.subheader("Văn bản dịch")
        if st.session_state['vi_output'] is None:
            # Chạy dịch ngầm nếu chưa có dữ liệu
            with st.container():
                vi_result = translate_script(st.session_state['cn_output'])
                st.session_state['vi_output'] = vi_result
                st.rerun()
        else:
            st.code(st.session_state['vi_output'], language="text")
