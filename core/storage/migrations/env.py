from alembic import context


connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations with python -m core.storage.manage upgrade")
if connection.dialect.name != "postgresql":
    raise RuntimeError("Production migrations require PostgreSQL, not SQLite")

context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
