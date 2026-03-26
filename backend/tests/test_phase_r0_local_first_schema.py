from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from common.models import (
    ActionBatch,
    ActionBatchStatus,
    Area,
    ConversationDirection,
    ConversationEvent,
    ConversationSource,
    EntityType,
    Person,
    PlanSnapshot,
    PlanSnapshotType,
    Reminder,
    ReminderKind,
    ReminderStatus,
    ReminderVersion,
    Session,
    WorkItem,
    WorkItemAlias,
    WorkItemKind,
    WorkItemLink,
    WorkItemLinkType,
    WorkItemPersonLink,
    WorkItemPersonRole,
    WorkItemStatus,
    WorkItemVersion,
    VersionOperation,
)


def _ddl(table, dialect) -> str:
    return str(CreateTable(table).compile(dialect=dialect)).lower()


def test_local_first_enums_include_new_domain_values():
    assert EntityType.work_item.value == "work_item"
    assert EntityType.reminder.value == "reminder"
    assert WorkItemKind.project.value == "project"
    assert WorkItemKind.subtask.value == "subtask"
    assert WorkItemStatus.done.value == "done"
    assert WorkItemLinkType.depends_on.value == "depends_on"
    assert WorkItemPersonRole.waiting_on.value == "waiting_on"
    assert ReminderKind.follow_up.value == "follow_up"
    assert ReminderStatus.pending.value == "pending"
    assert PlanSnapshotType.urgent.value == "urgent"
    assert ConversationSource.telegram.value == "telegram"
    assert ConversationDirection.outbound.value == "outbound"
    assert ActionBatchStatus.reverted.value == "reverted"
    assert VersionOperation.reparent.value == "reparent"


def test_local_first_tables_are_registered_in_metadata():
    assert Session.__tablename__ == "sessions"
    assert Area.__tablename__ == "areas"
    assert Person.__tablename__ == "people"
    assert WorkItem.__tablename__ == "work_items"
    assert WorkItemAlias.__tablename__ == "work_item_aliases"
    assert WorkItemLink.__tablename__ == "work_item_links"
    assert WorkItemPersonLink.__tablename__ == "work_item_people"
    assert Reminder.__tablename__ == "reminders"
    assert ReminderVersion.__tablename__ == "reminder_versions"
    assert PlanSnapshot.__tablename__ == "plan_snapshots"
    assert ConversationEvent.__tablename__ == "conversation_events"
    assert ActionBatch.__tablename__ == "action_batches"
    assert WorkItemVersion.__tablename__ == "work_item_versions"


def test_work_item_schema_contains_hierarchy_and_planning_fields():
    columns = WorkItem.__table__.c

    assert columns.kind is not None
    assert columns.parent_id is not None
    assert columns.area_id is not None
    assert columns.attributes_json is not None
    assert columns.scheduled_for is not None
    assert columns.snooze_until is not None
    assert columns.estimated_minutes is not None
    assert columns.completed_at is not None
    assert columns.archived_at is not None


def test_session_schema_contains_explicit_state_fields():
    columns = Session.__table__.c

    assert columns.current_mode is not None
    assert columns.active_entity_refs_json is not None
    assert columns.pending_draft_id is not None
    assert columns.pending_clarification_json is not None
    assert columns.summary_metadata_json is not None


def test_new_tables_compile_for_sqlite_and_postgres():
    sqlite_dialect = sqlite.dialect()
    postgres_dialect = postgresql.dialect()

    for table in [
        Area.__table__,
        Person.__table__,
        WorkItem.__table__,
        WorkItemAlias.__table__,
        WorkItemLink.__table__,
        WorkItemPersonLink.__table__,
        Reminder.__table__,
        ReminderVersion.__table__,
        PlanSnapshot.__table__,
        ConversationEvent.__table__,
        ActionBatch.__table__,
        WorkItemVersion.__table__,
    ]:
        sqlite_ddl = _ddl(table, sqlite_dialect)
        postgres_ddl = _ddl(table, postgres_dialect)
        assert table.name in sqlite_ddl
        assert table.name in postgres_ddl
