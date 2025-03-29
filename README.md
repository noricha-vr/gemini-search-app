# Gemini Search Chat

Python と Streamlit を使用して Gemini API で検索ができる個人用 Web アプリケーションです。

## 概要

このアプリケーションは、Gemini API を利用して、ユーザーが入力した質問に対して回答を生成するシンプルなチャットインターフェースを提供します。
プロジェクト単位での会話管理、カスタマイズ可能なシステムプロンプト、履歴管理などの機能を備えています。

## 特徴

- Streamlit によるシンプルな UI/UX
- プロジェクト単位での会話コンテキスト管理
- カスタマイズ可能なシステムプロンプト
- 使用する Gemini モデルの選択
- SQLite を使用したローカルでの会話履歴保存
- スレッドごとの会話管理
- 会話履歴の CSV エクスポート機能
- 会話履歴のマークダウンファイルへのリアルタイム書き出し

## セットアップ

1.  **リポジトリをクローン:**
    ```bash
    git clone <repository-url>
    cd gemini-search-chat
    ```

2.  **仮想環境の作成と有効化:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/macOS
    # venv\Scripts\activate  # Windows
    ```

3.  **依存関係のインストール:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **環境変数の設定:**
    `.env.example` をコピーして `.env` ファイルを作成し、Gemini API Key を設定します。
    ```bash
    cp .env.example .env
    # .env ファイルを編集して API キーを設定
    ```

5.  **アプリケーションの実行:**
    ```bash
    streamlit run app.py
    ```

## 使い方

アプリケーションを起動後、サイドバーからプロジェクトを作成または選択し、スレッドを開始してチャットをお楽しみください。 
