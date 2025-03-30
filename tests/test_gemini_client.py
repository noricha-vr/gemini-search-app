import sys
import os
# プロジェクトルートを Python パスに追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from api.gemini_client import GeminiClient # GeminiClient をインポート
from google.genai import types # types をインポート
import traceback # traceback をインポート

# --- 元の gemini_client.py の if __name__ == '__main__' ブロックの内容 ---
try:
    # Client の初期化方法を変更
    client_instance = GeminiClient() 
    
    # --- 通常の生成 ---
    print("--- 通常生成テスト ---")
    # history を types.Content と types.Part(text=...) で作成
    history_example = [
        types.Content(role='user', parts=[types.Part(text='Pythonでリストを逆順にする方法は？')]),
    ]
    system_prompt_example = "あなたは親切なPythonアシスタントです。"
    model_to_test = "gemini-2.0-flash" # テストするモデル名
    
    # メソッド呼び出しを変更
    response_text = client_instance.generate_content(
        model_name=model_to_test,
        history=history_example, 
        system_prompt=system_prompt_example
    )
    print("応答:", response_text)
    print("-"*20)

    # --- ストリーミング生成 ---
    print("--- ストリーミング生成テスト ---")
    history_stream_example = [
         types.Content(role='user', parts=[types.Part(text='Streamlitについて教えてください。')])
    ]
    system_prompt_stream = "あなたはWebフレームワークのエキスパートです。"
    
    print("ストリーミング応答:")
    full_response = ""
    # メソッド呼び出しを変更
    stream_generator = client_instance.generate_content_stream(
        model_name=model_to_test,
        history=history_stream_example, 
        system_prompt=system_prompt_stream
    )
    for chunk_text in stream_generator:
        print(chunk_text, end="", flush=True)
        full_response += chunk_text
    print("\nストリーミング完了。")
    print("-"*20)

except ValueError as ve:
    print(f"設定エラー: {ve}")
except Exception as e:
    print(f"予期せぬエラーが発生しました: {e}") 
    print(traceback.format_exc()) 
# --- ここまで --- 
