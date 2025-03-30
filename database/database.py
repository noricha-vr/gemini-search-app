import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import event
from sqlalchemy.engine import Engine
# from models.models import Base  # <-- 循環インポートの原因なので削除
from sqlalchemy import text
import logging # logging をインポート
from sqlalchemy import inspect

# ロガーの設定 (既にあれば不要)
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

DATABASE_URL = "sqlite:///gemini_chat.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# --- イベントリスナー: 接続ごとに PRAGMA を設定 --- 
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
# ----------------------------------------------------

def init_db():
    """データベースを初期化し、通常のテーブルと FTS 関連を作成します。"""
    import models.models # <-- モデル定義モジュールをここでインポート
    
    log.debug("init_db: Starting database initialization.")
    log.debug(f"init_db: Tables known by Base.metadata before create_all: {Base.metadata.tables.keys()}")

    with engine.connect() as connection:
        # 同じ接続/トランザクション内で全ての DDL を実行
        log.debug("init_db: Starting transaction.")
        try:
            # テーブルの存在確認
            inspector = inspect(engine)
            existing_tables = inspector.get_table_names()
            log.debug(f"init_db: Existing tables: {existing_tables}")
            
            # 'projects'テーブルが既に存在する場合はスキップ
            if 'projects' in existing_tables:
                log.info("init_db: Projects table already exists, skipping table creation.")
            else:
                # 1. SQLAlchemy のモデルに基づいて通常のテーブルを作成
                log.debug("init_db: Calling Base.metadata.create_all...")
                Base.metadata.create_all(bind=connection) # ここで connection を渡す
                log.debug("init_db: Base.metadata.create_all finished.")

            # 2. FTS 仮想テーブルとトリガーを直接作成
            log.debug("init_db: Creating FTS table...")
            # FTS5 仮想テーブル
            connection.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
                content, 
                content='messages', 
                content_rowid='id',
                tokenize = 'unicode61 remove_diacritics 2' -- Use built-in tokenizer
            );
            """))
            log.debug("init_db: FTS table created (or already exists).")

            log.debug("init_db: Creating INSERT trigger...")
            # トリガー: INSERT
            connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON messages BEGIN
                INSERT INTO message_fts (rowid, content) VALUES (new.id, new.content);
            END;
            """))
            log.debug("init_db: INSERT trigger created (or already exists).")

            log.debug("init_db: Creating DELETE trigger...")
            # トリガー: DELETE
            connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON messages BEGIN
                DELETE FROM message_fts WHERE rowid=old.id;
            END;
            """))
            log.debug("init_db: DELETE trigger created (or already exists).")
            
            log.debug("init_db: Creating UPDATE trigger...")
            # トリガー: UPDATE
            connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE ON messages BEGIN
                UPDATE message_fts SET content=new.content WHERE rowid=old.id;
            END;
            """))
            log.debug("init_db: UPDATE trigger created (or already exists).")
            
            # トランザクションをコミット
            log.debug("init_db: Committing transaction...")
            connection.commit()
            log.debug("init_db: Transaction committed.")

        except Exception as e:
            log.error(f"init_db: Error during initialization: {e}", exc_info=True)
            raise # エラーを再発生させる
        finally:
             log.debug("init_db: Transaction finished (committed or rolled back).")

    # TODOs は一旦削除 (必要なら後で復活)
    # # TODO: Import all modules here ...
    # # import models.models ...
    # # TODO: Add any additional ...
    # # TODO: Return a result ...

    log.debug("init_db: Database initialization finished successfully.")
    return True # Placeholder return, actual implementation needed
