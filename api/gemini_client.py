import os
import google.generativeai as genai
from google.generativeai.types import ContentType, PartType
from dotenv import load_dotenv

load_dotenv() # .envファイルから環境変数を読み込む

def configure_genai():
    """環境変数からAPIキーを読み込み、Geminiクライアントを設定します。"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません。 .envファイルを確認してください。")
    genai.configure(api_key=api_key)


class GeminiClient:
    """Gemini APIとの通信を行うクライアントクラス"""

    def __init__(self, model_name: str = "gemini-1.5-flash"):
        """
        GeminiClientを初期化します。

        Args:
            model_name: 使用するGeminiモデルの名前。
        """
        configure_genai() # 初期化時に設定を確認・実行
        self.model = genai.GenerativeModel(model_name)

    def generate_content(self, history: list[ContentType], system_prompt: str | None = None) -> str:
        """
        指定された履歴とシステムプロンプトに基づいてコンテンツを生成します。

        Args:
            history: 会話履歴のリスト (google.generativeai.types.Content 型のリスト)。
            system_prompt: システムプロンプト (オプション)。

        Returns:
            生成されたコンテンツのテキスト。
        
        Raises:
            Exception: API呼び出し中にエラーが発生した場合。
        """
        generation_config = genai.types.GenerationConfig(
            # response_mime_type="text/plain" # 必要に応じて設定
        )

        system_instruction = None
        if system_prompt:
            system_instruction = genai.types.Part.from_text(system_prompt)

        try:
            # システムプロンプトと履歴を結合
            # contents = []
            # if system_instruction:
            #     # システムプロンプトは通常、最初のユーザーメッセージの前に追加しますが、
            #     # Gemini API の system_instruction パラメータを使う方が推奨されます。
            #     # ここでは history に user/model のやり取りのみが含まれる想定。
            #     pass
            # contents.extend(history)

            response = self.model.generate_content(
                contents=history, 
                generation_config=generation_config,
                system_instruction=system_instruction # system_instructionパラメータを使用
            )
            return response.text
        except Exception as e:
            print(f"Gemini API呼び出し中にエラーが発生しました: {e}")
            # ここでエラーを再raiseするか、デフォルトの応答を返すか、または特定の処理を行う
            raise # or return "エラーが発生しました。"

    def generate_content_stream(self, history: list[ContentType], system_prompt: str | None = None):
        """
        指定された履歴とシステムプロンプトに基づいてコンテンツをストリーミング生成します。

        Args:
            history: 会話履歴のリスト (google.generativeai.types.Content 型のリスト)。
            system_prompt: システムプロンプト (オプション)。

        Yields:
            生成されたコンテンツのチャンク (テキスト)。
        
        Raises:
            Exception: API呼び出し中にエラーが発生した場合。
        """
        generation_config = genai.types.GenerationConfig(
            # response_mime_type="text/plain" # 必要に応じて設定
        )

        system_instruction = None
        if system_prompt:
            system_instruction = genai.types.Part.from_text(system_prompt)

        try:
            stream = self.model.generate_content(
                contents=history, 
                generation_config=generation_config,
                system_instruction=system_instruction,
                stream=True
            )
            for chunk in stream:
                yield chunk.text
        except Exception as e:
            print(f"Gemini APIストリーミング呼び出し中にエラーが発生しました: {e}")
            raise # or yield "エラーが発生しました。"

# 使用例 (テスト用)
if __name__ == '__main__':
    try:
        client = GeminiClient(model_name="gemini-1.5-flash") # または "gemini-pro"
        
        # --- 通常の生成 ---
        print("--- 通常生成テスト ---")
        history_example = [
            {'role':'user', 'parts': ['Pythonでリストを逆順にする方法は？']},
            # {'role':'model', 'parts': ['list.reverse()を使うか、スライス[::-1]を使います。']}
        ]
        system_prompt_example = "あなたは親切なPythonアシスタントです。"
        
        response_text = client.generate_content(history=history_example, system_prompt=system_prompt_example)
        print("応答:", response_text)
        print("-"*20)

        # --- ストリーミング生成 ---
        print("--- ストリーミング生成テスト ---")
        history_stream_example = [
            {'role':'user', 'parts': ['Streamlitについて教えてください。']}
        ]
        system_prompt_stream = "あなたはWebフレームワークのエキスパートです。"
        
        print("ストリーミング応答:")
        full_response = ""
        for chunk_text in client.generate_content_stream(history=history_stream_example, system_prompt=system_prompt_stream):
            print(chunk_text, end="", flush=True)
            full_response += chunk_text
        print("\nストリーミング完了。")
        # print("完全な応答:", full_response)
        print("-"*20)

    except ValueError as ve:
        print(f"設定エラー: {ve}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}") 
