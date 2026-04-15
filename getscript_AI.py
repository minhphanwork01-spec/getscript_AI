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
    st.subheader("Thông tin kỹ thuật")
    st.write("- **Engine:** Google Translate via Deep Translator")
    st.write("- **Format:** UTF-8 Text")
    st.write("- **Xử lý:** Tách dòng giữ mốc thời gian")

# 3. Giao diện nhập liệu
url_input = st.text_input("Nhập liên kết âm thanh Missevan:", placeholder="https://www.missevan.com/sound/11339811")

if 'final_result' not in st.session_state:
    st.session_state['final_result'] = None

# --- HÀM XỬ LÝ DỊCH THUẬT ---
def translate_script(cn_text):
    try:
        translator = GoogleTranslator(source='zh-CN', target='vi')
        lines = cn_text.split('\n')
        translated_lines = []
        
        # Thanh tiến trình xử lý
        progress_bar = st.progress(0)
        content_lines = [l for l in lines if l.strip() and not l.startswith(('TITLE:', 'NGUỒN:', 'SỐ DÒNG:', '---'))]
        total_to_translate = len(content_lines)
        count = 0
        
        for line in lines:
            if not line.strip():
                continue
            
            # Giữ nguyên các dòng tiêu đề không dịch
            if any(key in line for key in ['TITLE:', 'NGUỒN:', 'SỐ DÒNG:', '---']):
                translated_lines.append(line)
                continue
                
            # Xử lý dịch dòng thoại có mốc thời gian
            match = re.match(r'(\[.*?\])\s*(.*)', line)
            if match:
                timestamp, content = match.groups()
                if content.strip():
                    translated_content = translator.translate(content)
                    translated_lines.append(f"{timestamp} {translated_content}")
                else:
                    translated_lines.append(line)
                
                count += 1
                if total_to_translate > 0:
                    progress_bar.progress(min(count / total_to_translate, 1.0))
            else:
                translated_lines.append(line)
        
        return "\n".join(translated_lines)
    except Exception as e:
        return f"[Lỗi xử lý dịch thuật: {str(e)}]"

# 4. Logic xử lý dữ liệu
if st.button("🚀 Khởi chạy bóc tách và dịch thuật", use_container_width=True):
    if not url_input:
        st.warning("Vui lòng nhập liên kết hợp lệ.")
    else:
        with st.spinner("Đang truy xuất dữ liệu từ Missevan..."):
            try:
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
                    
                    # FORMAT NỘI DUNG GỐC (Y chang yêu cầu của Khai)
                    cn_output = f"TITLE: {title}\n"
                    cn_output += f"NGUỒN: {url_input}\n"
                    cn_output += f"SỐ DÒNG: {len(final)}\n"
                    cn_output += "-"*30 + "\n"
                    
                    for item in final:
                        m, s = divmod(int(item['t']), 60)
                        cn_output += f"[{m:02d}:{s:02d}] {item['txt']}\n"
                    
                    # Thực hiện dịch thuật
                    vi_output = translate_script(cn_output)
                    
                    st.session_state['final_result'] = {
                        'title': title,
                        'cn': cn_output,
                        'vi': vi_output,
                        'file_name': f"Sub_{re.sub(r'[\\\\/*?:\u0022<>|]', '', title)}.txt"
                    }
                else:
                    st.error("Truy xuất API thất bại. Vui lòng kiểm tra Cookie hoặc ID âm thanh.")
            except Exception as e:
                st.error(f"Lỗi hệ thống: {e}")

# 5. Hiển thị kết quả
if st.session_state['final_result']:
    res = st.session_state['final_result']
    st.success(f"Xử lý hoàn tất: {res['title']}")
    
    st.download_button(
        label="📥 Tải tệp bản dịch (.txt)",
        data=res['vi'],
        file_name=res['file_name'],
        mime="text/plain",
        use_container_width=True
    )
    
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Dữ liệu gốc (CN)")
        st.code(res['cn'], language="text")
    with col2:
        st.subheader("Dữ liệu dịch (VI)")
        st.code(res['vi'], language="text")import streamlit as st
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
    st.subheader("Thông tin kỹ thuật")
    st.write("- **Engine:** Google Translate via Deep Translator")
    st.write("- **Format:** UTF-8 Text")
    st.write("- **Xử lý:** Tách dòng giữ mốc thời gian")

# 3. Giao diện nhập liệu
url_input = st.text_input("Nhập liên kết âm thanh Missevan:", placeholder="https://www.missevan.com/sound/11339811")

if 'final_result' not in st.session_state:
    st.session_state['final_result'] = None

# --- HÀM XỬ LÝ DỊCH THUẬT ---
def translate_script(cn_text):
    try:
        translator = GoogleTranslator(source='zh-CN', target='vi')
        lines = cn_text.split('\n')
        translated_lines = []
        
        # Thanh tiến trình xử lý
        progress_bar = st.progress(0)
        content_lines = [l for l in lines if l.strip() and not l.startswith(('TITLE:', 'NGUỒN:', 'SỐ DÒNG:', '---'))]
        total_to_translate = len(content_lines)
        count = 0
        
        for line in lines:
            if not line.strip():
                continue
            
            # Giữ nguyên các dòng tiêu đề không dịch
            if any(key in line for key in ['TITLE:', 'NGUỒN:', 'SỐ DÒNG:', '---']):
                translated_lines.append(line)
                continue
                
            # Xử lý dịch dòng thoại có mốc thời gian
            match = re.match(r'(\[.*?\])\s*(.*)', line)
            if match:
                timestamp, content = match.groups()
                if content.strip():
                    translated_content = translator.translate(content)
                    translated_lines.append(f"{timestamp} {translated_content}")
                else:
                    translated_lines.append(line)
                
                count += 1
                if total_to_translate > 0:
                    progress_bar.progress(min(count / total_to_translate, 1.0))
            else:
                translated_lines.append(line)
        
        return "\n".join(translated_lines)
    except Exception as e:
        return f"[Lỗi xử lý dịch thuật: {str(e)}]"

# 4. Logic xử lý dữ liệu
if st.button("🚀 Khởi chạy bóc tách và dịch thuật", use_container_width=True):
    if not url_input:
        st.warning("Vui lòng nhập liên kết hợp lệ.")
    else:
        with st.spinner("Đang truy xuất dữ liệu từ Missevan..."):
            try:
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
                    
                    # FORMAT NỘI DUNG GỐC (Y chang yêu cầu của Khai)
                    cn_output = f"TITLE: {title}\n"
                    cn_output += f"NGUỒN: {url_input}\n"
                    cn_output += f"SỐ DÒNG: {len(final)}\n"
                    cn_output += "-"*30 + "\n"
                    
                    for item in final:
                        m, s = divmod(int(item['t']), 60)
                        cn_output += f"[{m:02d}:{s:02d}] {item['txt']}\n"
                    
                    # Thực hiện dịch thuật
                    vi_output = translate_script(cn_output)
                    
                    st.session_state['final_result'] = {
                        'title': title,
                        'cn': cn_output,
                        'vi': vi_output,
                        'file_name': f"Sub_{re.sub(r'[\\\\/*?:\u0022<>|]', '', title)}.txt"
                    }
                else:
                    st.error("Truy xuất API thất bại. Vui lòng kiểm tra Cookie hoặc ID âm thanh.")
            except Exception as e:
                st.error(f"Lỗi hệ thống: {e}")

# 5. Hiển thị kết quả
if st.session_state['final_result']:
    res = st.session_state['final_result']
    st.success(f"Xử lý hoàn tất: {res['title']}")
    
    st.download_button(
        label="📥 Tải tệp bản dịch (.txt)",
        data=res['vi'],
        file_name=res['file_name'],
        mime="text/plain",
        use_container_width=True
    )
    
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Dữ liệu gốc (CN)")
        st.code(res['cn'], language="text")
    with col2:
        st.subheader("Dữ liệu dịch (VI)")
        st.code(res['vi'], language="text")
