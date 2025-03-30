import unittest
import sys
import os
# プロジェクトルートを Python パスに追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from api.gemini_client import GeminiClient # GeminiClient をインポート
from google.genai import types # types をインポート
import traceback # traceback をインポート

class TestGeminiClient(unittest.TestCase):
    """GeminiClient クラスのテストケース"""

    client_instance = None # クラス変数としてクライアントを保持

    @classmethod
    def setUpClass(cls):
        """テストクラスのセットアップ (クラスごとに一度だけ実行)"""
        print("\n--- Setting up TestGeminiClient ---")
        try:
            # クライアントを初期化
            cls.client_instance = GeminiClient()
            print("GeminiClient initialized successfully.")
        except ValueError as ve:
            # APIキーがない場合はテスト全体を失敗させる
            raise cls.failureException(f"Setup failed: {ve}")
        except Exception as e:
            raise cls.failureException(f"Unexpected error during setup: {e}\n{traceback.format_exc()}")

    @classmethod
    def tearDownClass(cls):
        """テストクラスのティアダウン (クラスごとに一度だけ実行)"""
        print("\n--- Tearing down TestGeminiClient ---")
        cls.client_instance = None # クリーンアップ

    def test_generate_content(self):
        """generate_content メソッドのテスト"""
        print("\n--- Testing generate_content ---")
        self.assertIsNotNone(self.client_instance, "Client instance should not be None")

        history_example = [
            types.Content(role='user', parts=[types.Part(text='Pythonでリストを逆順にする方法は？')]),
        ]
        system_prompt_example = "あなたは親切なPythonアシスタントです。"
        model_to_test = "gemini-2.0-flash" # アプリで使用可能なモデルを使う

        try:
            response_text = self.client_instance.generate_content(
                model_name=model_to_test,
                history=history_example,
                system_prompt=system_prompt_example
            )
            print("Response received (first 100 chars):", repr(response_text[:100])) # 長い応答を切り詰めて表示

            # アサーション: 応答が文字列であり、空でないことを確認
            self.assertIsInstance(response_text, str)
            self.assertTrue(len(response_text) > 0, "Response should not be empty")

        except Exception as e:
            # テスト中に例外が発生したらフェイルさせる
            self.fail(f"generate_content failed with exception: {e}\n{traceback.format_exc()}")

    def test_generate_content_stream(self):
        """generate_content_stream メソッドのテスト"""
        print("\n--- Testing generate_content_stream ---")
        self.assertIsNotNone(self.client_instance, "Client instance should not be None")

        history_stream_example = [
             types.Content(role='user', parts=[types.Part(text='Streamlitについて簡単に教えてください。')])
        ]
        system_prompt_stream = "あなたはWebフレームワークのエキスパートです。"
        model_to_test = "gemini-2.0-flash" # アプリで使用可能なモデルを使う

        try:
            stream_generator = self.client_instance.generate_content_stream(
                model_name=model_to_test,
                history=history_stream_example,
                system_prompt=system_prompt_stream
            )

            full_response = ""
            chunk_count = 0
            print("Streaming response (first ~5 chunks):", end=" ")
            for chunk_text in stream_generator:
                # アサーション: 各チャンクが文字列であることを確認
                self.assertIsInstance(chunk_text, str)
                full_response += chunk_text
                chunk_count += 1
                if chunk_count <= 5: # 最初の数チャンクだけ表示
                    print(repr(chunk_text), end=" ", flush=True)
            print("... Streaming complete.")
            print("Full response length:", len(full_response))

            # アサーション: 結合された応答が空でなく、チャンクが1つ以上あったことを確認
            self.assertTrue(len(full_response) > 0, "Full streaming response should not be empty")
            self.assertTrue(chunk_count > 0, "Stream should yield at least one chunk")

        except Exception as e:
            # テスト中に例外が発生したらフェイルさせる
            self.fail(f"generate_content_stream failed with exception: {e}\n{traceback.format_exc()}")

if __name__ == '__main__':
    unittest.main()
