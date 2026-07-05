import gradio as gr
import asyncio
import edge_tts
import re
import os
import datetime
from gradio_client import Client

try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
except ImportError:
    raise ImportError("ကျေးဇူးပြု၍ requirements.txt တွင် pydub ထည့်ပေးပါ။")

# ----------------- 🌐 CENTRAL VIP SERVER CONFIG -----------------
# ဗဟိုဆာဗာ၏ Space ID ကို တိုက်ရိုက်ချိတ်ဆက်ခြင်း
CENTRAL_SPACE_ID = "paing1213/my-central-vip-server"

def verify_login(user_pass):
    u_pass = user_pass.strip()
    if not u_pass: 
        raise gr.Error("⚠️ ကျေးဇူးပြု၍ VIP Password ကို ရိုက်ထည့်ပေးပါ။")
    
    try:
        # Gradio Client အားအသုံးပြု၍ ဗဟိုဆာဗာသို့ တရားဝင် လှမ်းစစ်ခြင်း
        client = Client(CENTRAL_SPACE_ID)
        result = client.predict(
            u_pass,
            api_name="/check_vip"
        )
        
        # ဗဟိုဆာဗာမှ 'valid' ဟု ပြန်ဖြေလာပါက ဝင်ခွင့်ပြုမည်
        if result == "valid":
            return gr.update(visible=False), gr.update(visible=True)
            
    except Exception as e:
        print("❌ ဗဟိုဆာဗာသို့ ချိတ်ဆက်၍မရပါ:", e)
        
    raise gr.Error("❌ Password မမှန်ကန်ပါ (သို့) ကုန်ဆုံးသွားပါပြီ")

# ----------------- 🌐 TTS LOGIC -----------------
EDGE_VOICES = ["သီဟ (🇲🇲 - အမျိုးသား ပုံမှန်)", "နီလာ (🇲🇲 - အမျိုးသမီး ပုံမှန်)", "မောင်မောင် (🇲🇲 - လူငယ်သံသစ်)", "ကြည်ပြာ (🇲🇲 - ချိုသာသံသစ်)", "ဖိုးသက် (🇲🇲 - ကလေးသံသစ်)", "ဦးမင်းဟန် (🇲🇲 - အဘိုးအိုသံသစ်)"]

def format_srt_time(seconds):
    if seconds < 0: seconds = 0
    millis = int(seconds * 1000)
    hours = millis // 3600000
    millis %= 3600000
    minutes = millis // 60000
    millis %= 60000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def segment_myanmar_text(raw_text, max_chars=40):
    for char in ["“", "”", '"', "‘", "’", "'", "--", "—", "…"]:
        raw_text = raw_text.replace(char, " ")
    raw_text = re.sub(r"[ \t]+", " ", raw_text).strip()
    split_pattern = re.split(r'([။၊!?\n]+)', raw_text)
    temp_chunks = []
    current_chunk = ""
    for item in split_pattern:
        current_chunk += item
        if any(p in item for p in ['။', '.,', '၊', '?', '!', '\n']):
            clean_chunk = current_chunk.strip()
            if len(re.sub(r'[\s၊။!?\-\"\']', '', clean_chunk)) > 0: temp_chunks.append(clean_chunk)
            current_chunk = ""
    if current_chunk.strip():
        clean_chunk = current_chunk.strip()
        if len(re.sub(r'[\s၊။!?\-\"\']', '', clean_chunk)) > 0: temp_chunks.append(clean_chunk)
    final_segments = []
    for chunk in temp_chunks:
        if len(chunk) <= max_chars: final_segments.append(chunk)
        else:
            sub_words = chunk.split(' ')
            line_buffer = ""
            for word in sub_words:
                if len(line_buffer) + len(word) + 1 <= max_chars: line_buffer += (" " if line_buffer else "") + word
                else:
                    if line_buffer: final_segments.append(line_buffer.strip())
                    if len(word) > max_chars:
                        for i in range(0, len(word), max_chars): final_segments.append(word[i:i+max_chars])
                        line_buffer = ""
                    else: line_buffer = word
            if line_buffer: final_segments.append(line_buffer.strip())
    return final_segments

async def process_voice_generation(
    text, surveyed_text, filename, selected_voice, srt_type, tone, speed, volume, progress=gr.Progress()
):
    if not text.strip(): return None, None, None

    processed_text = text.replace("--", " ").replace("—", " ").replace("…", " ")
    if surveyed_text.strip():
        for line in surveyed_text.strip().split("\n"):
            if "=" in line: key, val = line.split("=", 1); processed_text = processed_text.replace(key.strip(), val.strip())

    output_name = filename.strip() if filename.strip() else "Myanmar_TTS"
    output_mp3 = f"{output_name}.mp3"
    output_srt = f"{output_name}.srt"

    voice_config = {
        "သီဟ (🇲🇲 - အမျိုးသား ပုံမှန်)": {"base": "my-MM-ThihaNeural", "pitch_shift": 0, "speed_add": 20},
        "နီလာ (🇲🇲 - အမျိုးသမီး ပုံမှန်)": {"base": "my-MM-NilarNeural", "pitch_shift": 0, "speed_add": 45},
        "မောင်မောင် (🇲🇲 - လူငယ်သံသစ်)": {"base": "my-MM-ThihaNeural", "pitch_shift": 3, "speed_add": 25},
        "ကြည်ပြာ (🇲🇲 - ချိုသာသံသစ်)": {"base": "my-MM-NilarNeural", "pitch_shift": 2, "speed_add": 45},
        "ဖိုးသက် (🇲🇲 - ကလေးသံသစ်)": {"base": "my-MM-NilarNeural", "pitch_shift": 6, "speed_add": 35},
        "ဦးမင်းဟန် (🇲🇲 - အဘိုးအိုသံသစ်)": {"base": "my-MM-ThihaNeural", "pitch_shift": -4, "speed_add": 15}
    }
    
    selected_cfg = voice_config.get(selected_voice, {"base": "my-MM-ThihaNeural", "pitch_shift": 0, "speed_add": 20})
    lines = processed_text.split('\n')
    parsed_dialogues = []
    
    current_base_voice = selected_cfg["base"]
    current_pitch = selected_cfg["pitch_shift"]
    current_speed_add = selected_cfg["speed_add"]

    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith("ကျား:"):
            current_base_voice = "my-MM-ThihaNeural"
            current_pitch = 0 if "သီဟ" in selected_voice else selected_cfg["pitch_shift"]
            current_speed_add = 20
            sentence_text = line.replace("ကျား:", "").strip()
        elif line.startswith("မ:"):
            current_base_voice = "my-MM-NilarNeural"
            current_pitch = 4 if selected_cfg["pitch_shift"] <= 0 else selected_cfg["pitch_shift"]
            current_speed_add = 45
            sentence_text = line.replace("မ:", "").strip()
        else:
            current_base_voice = selected_cfg["base"]
            current_pitch = selected_cfg["pitch_shift"]
            current_speed_add = selected_cfg["speed_add"]
            sentence_text = line
            
        if sentence_text:
            max_srt_chars = 40 if srt_type == "TikTok" else 70
            sub_sentences = segment_myanmar_text(sentence_text, max_chars=max_srt_chars)
            for sub_s in sub_sentences:
                parsed_dialogues.append({
                    "voice": current_base_voice, 
                    "text": sub_s, 
                    "pitch": current_pitch, 
                    "speed_bonus": current_speed_add
                })

    total_sentences = len(parsed_dialogues)
    if total_sentences == 0: return None, None, None

    progress(0.2, desc="⏳ အသံထွက်များကို ဇာတ်ကောင်အလိုက် စီစစ်နေပါသည်...")
    sem = asyncio.Semaphore(15)

    async def fetch_audio_edge(idx, dialogue_item):
        async with sem:
            try:
                final_speed = speed + dialogue_item["speed_bonus"]
                speed_rate = f"{'+' if final_speed >= 0 else ''}{final_speed}%"
                volume_rate = "+100%"
                
                communicate = edge_tts.Communicate(text=dialogue_item["text"], voice=dialogue_item["voice"], rate=speed_rate, volume=volume_rate)
                chunk_audio = bytearray()
                async for msg in communicate.stream():
                    if msg["type"] == "audio": chunk_audio.extend(msg["data"])
                return idx, chunk_audio
            except: 
                return idx, b""

    tasks = [fetch_audio_edge(idx, item) for idx, item in enumerate(parsed_dialogues)]
    audio_results = await asyncio.gather(*tasks)
    audio_results.sort(key=lambda x: x[0])

    progress(0.6, desc="🚀 စက္ကန့်ပိုင်းအတွင်း အသံဖိုင်ကို အချောသတ် စီစဉ်ပေးနေပါပြီ...")
    combined_audio = AudioSegment.empty()
    subtitles = []
    current_time_sec = 0.0
    natural_pause = AudioSegment.silent(duration=180)

    for idx, chunk_audio in audio_results:
        if not chunk_audio: continue
        temp_file = f"temp_line_{idx}.mp3"
        with open(temp_file, "wb") as f: f.write(chunk_audio)
        try:
            segment = AudioSegment.from_mp3(temp_file)
            nonsilent_ranges = detect_nonsilent(segment, min_silence_len=50, silence_thresh=-50)
            if nonsilent_ranges: segment = segment[nonsilent_ranges[0][0]:nonsilent_ranges[-1][1]]
            
            p_shift = parsed_dialogues[idx]["pitch"]
            if p_shift != 0:
                new_sample_rate = int(segment.frame_rate * (2.0 ** (p_shift / 12.0)))
                segment = segment._spawn(segment.raw_data, overrides={'frame_rate': new_sample_rate})
                segment = segment.set_frame_rate(44100)
            
            segment = segment + 8
            segment = segment + natural_pause
            duration_sec = len(segment) / 1000.0
            if duration_sec > 0:
                subtitles.append({"start": current_time_sec, "end": current_time_sec + duration_sec - 0.15, "text": parsed_dialogues[idx]["text"]})
                current_time_sec += duration_sec
                combined_audio += segment
        except: 
            pass
        finally:
            if os.path.exists(temp_file): os.remove(temp_file)

    progress(0.9, desc="💾 ဖိုင်များကို အချောသတ် သိမ်းဆည်းနေပါသည်...")
    if len(combined_audio) == 0: return None, None, None
    combined_audio.export(output_mp3, format="mp3")

    with open(output_srt, "w", encoding="utf-8-sig") as f:
        for i, sub in enumerate(subtitles, start=1):
            f.write(f"{i}\n{format_srt_time(sub['start'])} --> {format_srt_time(sub['end'])}\n{sub['text'].strip()}\n\n")

    progress(1.0, desc="✅ အားလုံး ပြီးစီးပါပြီ!")
    return output_mp3, output_mp3, output_srt

def tts_wrapper(text, rules_text, filename, selected_voice, srt_type, tone, speed, volume, progress=gr.Progress()):
    return asyncio.run(process_voice_generation(text, rules_text, filename, selected_voice, srt_type, tone, speed, volume, progress))


# ----------------- 🎨 UI & APP LAUNCH -----------------
custom_css = ".large-btn { font-size: 24px !important; font-weight: bold !important; padding: 15px !important; margin-bottom: 15px !important; } .text-link-box { text-align: center; margin-bottom: 20px; padding: 15px; background-color: #1E293B; border-radius: 8px; border: 1px solid #38BDF8;} .text-link-box p { font-size: 18px !important; margin: 5px 0 !important; font-weight: 500; } .text-link-box a { color: #38BDF8 !important; text-decoration: underline !important; font-weight: bold !important; font-size: 24px !important; } .login-btn { font-size: 20px !important; font-weight: bold !important; padding: 10px !important; }"

with gr.Blocks(title="Myanmar Audio Studio", css=custom_css) as demo:
    
    with gr.Column(visible=True) as login_screen:
        gr.Markdown("<h1 style='text-align: center; color: #4F46E5; margin-bottom: 30px;'>🔐 Myanmar Audio Studio</h1>")
        with gr.Group():
            login_password = gr.Textbox(label="🔑 Password ရိုက်ထည့်ပါ", type="password", placeholder="Password ဖြည့်ပါ...")
            login_btn = gr.Button("🚀 လော့ဂ်အင် ဝင်မည် (Login)", variant="primary", elem_classes=["login-btn"])

        gr.Markdown("<br><hr style='margin: 30px 0;'>")
        # Admin Panel ကို လုံးဝ (လုံးဝ) ဖြတ်ထုတ်ထားပါပြီ

    with gr.Column(visible=False) as tts_content:
        gr.Markdown("<h1 style='text-align: center; color: #10B981;'>🎙️ Myanmar Audio & SRT Studio</h1>")
        
        with gr.Accordion("🔧 အသံထွက် ပြင်ဆင်ရန် (Pronunciation Rules)", open=False):
            rules = gr.TextArea(value="", placeholder="စာသား = အသံထွက်", lines=4, show_label=False)
            
        file_name = gr.Textbox(label="💾 သိမ်းဆည်းမည့် ဖိုင်အမည်", value="Myanmar_TTS")
        voice_dropdown = gr.Dropdown(choices=EDGE_VOICES, label="🎙️ ဇာတ်ကောင် / အသံ ရွေးချယ်ရန်", value=EDGE_VOICES[0])
        srt_type = gr.Radio(["TikTok", "YouTube"], label="စာတန်းထိုး အမျိုးအစား", value="TikTok")
            
        with gr.Accordion("⚙️ အဆင့်မြင့် ဆက်တင်များ", open=False):
            tone = gr.Slider(minimum=-50, maximum=50, value=0, step=1, label="Tone")
            speed = gr.Slider(minimum=-50, maximum=50, value=0, step=1, label="Speed")
            volume = gr.Slider(minimum=0, maximum=100, value=100, step=1, label="Volume")
            
        input_text = gr.Textbox(label="စာသား", placeholder="ကျား: မင်္ဂလာပါ။\nမ: ဟုတ်ကဲ့။", lines=6)
        generate_btn = gr.Button("🚀 အသံဖိုင် ဖန်တီးမည် (Generate)", variant="primary")
        
        output_audio = gr.Audio(label="🎧 ထွက်လာသော အသံဖိုင်", type="filepath")
        output_mp3_file = gr.File(label="💾 MP3 ဒေါင်းလုဒ်")
        output_srt_file = gr.File(label="📝 SRT ဒေါင်းလုဒ်")

        generate_btn.click(
            fn=tts_wrapper, 
            inputs=[input_text, rules, file_name, voice_dropdown, srt_type, tone, speed, volume], 
            outputs=[output_audio, output_mp3_file, output_srt_file]
        )

    login_btn.click(
        fn=verify_login,
        inputs=[login_password],
        outputs=[login_screen, tts_content]
    )

demo.launch()
