import base64
import os
from google import genai
from google.genai import types


def generate():
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )

    model = "gemini-2.5-pro-exp-03-25"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""PythonでGUIアプリを作るときのライブラリの候補をあげてください。
シンプルなチャットと履歴の管理ができる画面を作りたいです。その他設定画面を少し。
要件に会うものを探して提案してください。
"""),
            ],
        ),
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""INSERT_INPUT_HERE"""),
            ],
        ),
    ]
    tools = [
        types.Tool(google_search=types.GoogleSearch())
    ]
    generate_content_config = types.GenerateContentConfig(
        tools=tools,
        response_mime_type="text/plain",
        system_instruction=[
            types.Part.from_text(text="""あなたはWeb検索エージェントです。
1. ユーザーの質問の意図を分析します。
2. 何を知りたいのかよく分析します。
3. ユーザーの知りたいこと検索します
4. 検索から分かったことをわかりやすくまとめます。"""),
        ],
    )

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        print(chunk.text, end="")

if __name__ == "__main__":
    generate()
