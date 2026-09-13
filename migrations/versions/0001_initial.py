"""create RunSense domain tables"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Local development may have bootstrapped tables through ``create_all``.
    # Treat that schema as already initialized and let Alembic record the
    # revision instead of failing on duplicate tables.
    if sa.inspect(op.get_bind()).has_table("athletes"):
        return
    op.create_table("athletes", sa.Column("id", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False), sa.Column("guide_contacts", sa.JSON(), nullable=False), sa.Column("preferences", sa.JSON(), nullable=False))
    op.create_table("activities", sa.Column("id", sa.String(), primary_key=True), sa.Column("athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False), sa.Column("strava_id", sa.String()), sa.Column("date", sa.Date(), nullable=False), sa.Column("km", sa.Float(), nullable=False), sa.Column("avg_pace", sa.Float()), sa.Column("avg_hr", sa.Integer()), sa.Column("elevation", sa.Float()))
    op.create_table("plan_weeks", sa.Column("id", sa.String(), primary_key=True), sa.Column("athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False), sa.Column("week_start", sa.Date(), nullable=False), sa.Column("plan_json", sa.JSON(), nullable=False), sa.Column("rationale", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False))
    op.create_table("sessions", sa.Column("id", sa.String(), primary_key=True), sa.Column("athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False), sa.Column("plan_week_id", sa.String(), sa.ForeignKey("plan_weeks.id")), sa.Column("name", sa.String(), nullable=False), sa.Column("sport_type", sa.String(), nullable=False), sa.Column("kind", sa.String()), sa.Column("session_date", sa.Date()), sa.Column("km", sa.Float()), sa.Column("state", sa.String(), nullable=False), sa.Column("calendar_event_id", sa.String()), sa.Column("guide_status", sa.String(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("summary_json", sa.JSON()))
    op.create_table("alerts", sa.Column("id", sa.String(), primary_key=True), sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id")), sa.Column("ts", sa.DateTime(timezone=True), nullable=False), sa.Column("obj_class", sa.String(), nullable=False), sa.Column("zone", sa.String(), nullable=False), sa.Column("distance_bucket", sa.String(), nullable=False), sa.Column("tier", sa.String(), nullable=False), sa.Column("latency_ms", sa.Float()), sa.Column("spoken", sa.Boolean(), nullable=False))
    op.create_table("tool_traces", sa.Column("id", sa.String(), primary_key=True), sa.Column("run_id", sa.String()), sa.Column("step", sa.Integer(), nullable=False), sa.Column("tool", sa.String(), nullable=False), sa.Column("input_json", sa.JSON(), nullable=False), sa.Column("output_json", sa.JSON(), nullable=False), sa.Column("latency_ms", sa.Float()), sa.Column("retries", sa.Integer(), nullable=False), sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("tool_traces", "alerts", "sessions", "plan_weeks", "activities", "athletes"): op.drop_table(table)
