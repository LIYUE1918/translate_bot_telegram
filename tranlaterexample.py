"""翻译库使用示例脚本

演示如何使用 translators 库进行 Google/Bing 翻译，并统计耗时。
可直接作为独立脚本运行。
"""
import translators as ts
import time

def google_translate(text,fl,tl):
    """使用 Google 引擎进行翻译

    参数：
    - text: 待翻译文本
    - fl: 源语言，例如 'en'，可用 'auto' 自动检测
    - tl: 目标语言，例如 'zh'
    """
    result = ts.translate_text(text, from_language=fl, to_language=tl)
    return result

# 切换成必应
def bing_translate(text,fl,tl):
    """使用 Bing 引擎进行翻译"""
    result = ts.translate_text(text, from_language=fl, to_language=tl, translator="bing")
    return result

def translate_mode(text,fl,tl,mode,count):
    """根据 mode 选择翻译引擎，并可选择打印耗时"""
    if mode == "google":
        start = time.perf_counter()
        res = google_translate(text,fl,tl)
        elapsed = time.perf_counter() - start
        label = "google"
    elif mode == "bing":
        start = time.perf_counter()
        res = bing_translate(text,fl,tl)
        elapsed = time.perf_counter() - start
        label = "bing"
    else:
        raise ValueError("mode must be 'google' or 'bing'")
    if count:
        print(f"{label}: {elapsed:.3f}s")
    print(res)

if __name__ == "__main__":
    # 简单示例：使用 Bing 将英文翻译为中文，并打印耗时
    translate_mode("Hello world", "en", "zh", "bing", True)
