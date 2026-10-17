"""Initial database schema for MedLearn AI

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-02 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension if on Postgres
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. sources table
    op.create_table(
        'sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('published_date', sa.DateTime(), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sources_org', 'sources', ['org'])

    # 3. document_chunks table
    if conn.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector
        embedding_col = sa.Column('embedding', Vector(1536), nullable=False)
    else:
        embedding_col = sa.Column('embedding', sa.JSON(), nullable=False)

    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        embedding_col,
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_document_chunks_source_id', 'document_chunks', ['source_id'])

    # 4. users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='student'),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # 5. lessons table
    op.create_table(
        'lessons',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('level', sa.String(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()) if conn.dialect.name == "postgresql" else sa.JSON(), nullable=False),
        sa.Column('model_versions', postgresql.JSONB(astext_type=sa.Text()) if conn.dialect.name == "postgresql" else sa.JSON(), nullable=False),
        sa.Column('safety_flags', postgresql.JSONB(astext_type=sa.Text()) if conn.dialect.name == "postgresql" else sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "level IN ('child','high_school','college','medical_student','general_public')",
            name='valid_level'
        ),
    )
    op.create_index('ix_lessons_topic_level', 'lessons', ['topic', 'level'])

    # 6. user_lesson_history table
    op.create_table(
        'user_lesson_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lesson_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('viewed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('quiz_score', sa.Numeric(), nullable=True),
        sa.Column('quiz_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('bookmarked', sa.Boolean(), nullable=False, server_default='false'),
        sa.UniqueConstraint('user_id', 'lesson_id', name='uq_user_lesson'),
    )
    op.create_index('ix_user_lesson_history_user_id', 'user_lesson_history', ['user_id'])
    op.create_index('ix_user_lesson_history_lesson_id', 'user_lesson_history', ['lesson_id'])

    # 7. search_history table
    op.create_table(
        'search_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('query', sa.String(), nullable=False),
        sa.Column('level', sa.String(), nullable=False),
        sa.Column('found_result', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_search_history_user_id', 'search_history', ['user_id'])

    # 8. tutor_messages table
    op.create_table(
        'tutor_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('lesson_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user','assistant')", name='valid_role'),
    )
    op.create_index('ix_tutor_messages_lesson_id', 'tutor_messages', ['lesson_id'])

    # 9. feedback table
    op.create_table(
        'feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('lesson_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('open','reviewed','dismissed')", name='valid_feedback_status'),
    )
    op.create_index('ix_feedback_lesson_id', 'feedback', ['lesson_id'])

    # 10. topic_taxonomy table
    op.create_table(
        'topic_taxonomy',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('canonical_name', sa.String(), nullable=False, unique=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('synonyms', postgresql.JSONB(astext_type=sa.Text()) if conn.dialect.name == "postgresql" else sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('related_topics', postgresql.JSONB(astext_type=sa.Text()) if conn.dialect.name == "postgresql" else sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_topic_taxonomy_canonical_name', 'topic_taxonomy', ['canonical_name'], unique=True)
    op.create_index('ix_topic_taxonomy_category', 'topic_taxonomy', ['category'])

    # 11. audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('actor_email', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


    # 12. content_reviews table (lesson lifecycle tracking)
    op.create_table(
        'content_reviews',
        sa.Column('record_id', sa.String(), nullable=False),
        sa.Column('lesson_id', sa.String(), primary_key=True),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('content_version', sa.String(), nullable=False, server_default='1.0.0'),
        sa.Column('source_version', sa.String(), nullable=False, server_default='2026.1'),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','validation_failed','review_required','approved','published','archived')",
            name='ck_content_reviews_status',
        ),
    )
    op.create_index('ix_content_reviews_status', 'content_reviews', ['status'])


def downgrade() -> None:
    op.drop_table('content_reviews')
    op.drop_table('audit_logs')
    op.drop_table('topic_taxonomy')
    op.drop_table('feedback')
    op.drop_table('tutor_messages')
    op.drop_table('search_history')
    op.drop_table('user_lesson_history')
    op.drop_table('lessons')
    op.drop_table('users')
    op.drop_table('document_chunks')
    op.drop_table('sources')
