import os
# `google.generativeai` は `genai` としてインポートするのが一般的
from google import genai 
# `types` も明示的にインポート
from google.genai import types 
from dotenv import load_dotenv
from typing import List, Generator, Optional # 型ヒントをより明確に

load_dotenv() # .envファイルから環境変数を読み込む

class GeminiClient:
    """Gemini APIとの通信を行うクライアントクラス (gemini-sample.py ベース)"""

    def __init__(self):
        """
        GeminiClientを初期化します。
        APIキーを環境変数から読み込み、クライアントをセットアップします。
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEYが設定されていません。 .envファイルを確認してください。")
        
        # genai.Client を使用してクライアントを初期化
        self.client = genai.Client(api_key=api_key)

    def generate_content(self, 
                         model_name: str, 
                         history: List[types.Content],
                         system_prompt: Optional[str] = None) -> str:
        """
        指定されたモデル、履歴、システムプロンプトに基づいてコンテンツを生成します。

        Args:
            model_name: 使用するGeminiモデルの名前 (例: "gemini-1.5-flash")。
            history: 会話履歴のリスト (google.generativeai.types.Content のリスト)。
            system_prompt: システムプロンプト (オプション)。

        Returns:
            生成されたコンテンツのテキスト。
        
        Raises:
            Exception: API呼び出し中にエラーが発生した場合。
        """
        processed_model_name = model_name

        system_instruction_part = None
        if system_prompt:
            # サンプルに従い Part.from_text を使用 -> エラーのため元に戻す
            system_instruction_part = types.Part(text=system_prompt)
 
        # GenerationConfig を設定
        generation_config = types.GenerateContentConfig(
            # response_mime_type="text/plain" # 必要に応じて設定
            # サンプルに従い、system_instruction はリストで渡す
            system_instruction=[system_instruction_part] if system_instruction_part else None
        )

        try:
            # client.models.generate_content を使用
            response = self.client.models.generate_content(
                model=processed_model_name,
                contents=history, 
                config=generation_config,
                # system_instruction は config に含める
            )
            return response.text
        except Exception as e:
            print(f"Gemini API呼び出し中にエラーが発生しました: {e}")
            raise

    def generate_content_stream(self, 
                              model_name: str,
                              history: List[types.Content],
                              system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """
        指定されたモデル、履歴、システムプロンプトに基づいてコンテンツをストリーミング生成します。

        Args:
            model_name: 使用するGeminiモデルの名前 (例: "gemini-1.5-flash")。
            history: 会話履歴のリスト (google.generativeai.types.Content のリスト)。
            system_prompt: システムプロンプト (オプション)。

        Yields:
            生成されたコンテンツのチャンク (テキスト)。
        
        Raises:
            Exception: API呼び出し中にエラーが発生した場合。
        """
        processed_model_name = model_name

        system_instruction_part = None
        if system_prompt:
             # サンプルに従い Part.from_text を使用 -> エラーのため元に戻す
            system_instruction_part = types.Part(text=system_prompt)
 
        tools = [
            types.Tool(google_search=types.GoogleSearch())
        ]
        # GenerationConfig を設定
        generation_config = types.GenerateContentConfig(
            tools=tools,
            # response_mime_type="text/plain" # 必要に応じて設定
            # サンプルに従い、system_instruction はリストで渡す
            system_instruction=[system_instruction_part] if system_instruction_part else None
        )

        try:
            # client.models.generate_content_stream を使用
            stream = self.client.models.generate_content_stream(
                model=processed_model_name,
                contents=history, 
                config=generation_config,
                 # system_instruction は config に含める
            )
            for chunk in stream:
                if hasattr(chunk, 'text'):
                    yield chunk.text
        except Exception as e:
            print(f"Gemini APIストリーミング呼び出し中にエラーが発生しました: {e}")
            raise
