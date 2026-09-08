import json
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.repositories.service import repo_for_project

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.database.agent import DatabaseAgent
from apps.database.parsing import parse_schema
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

SCHEMA_JSON = json.dumps(
    {
        "models": [
            {
                "name": "User",
                "description": "Account",
                "fields": [
                    {"name": "email", "type": "varchar", "nullable": False},
                    {"name": "created_at", "type": "timestamp"},
                ],
                "relations": ["has_many Task"],
            },
            {"name": "Task", "description": "Work item", "fields": [{"name": "title", "type": "text"}]},
        ]
    }
)


def _fake(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(50, 110))

    return _inner


def _sequence(*texts, model="claude-opus-5"):
    calls = {"n": 0}

    def _inner(request, provider=None):
        i = min(calls["n"], len(texts) - 1)
        calls["n"] += 1
        return CompletionResponse(text=texts[i], model=model, provider="anthropic", usage=Usage(50, 110))

    return _inner


class CapabilityRegistryTests(SimpleTestCase):
    def test_relational_capabilities(self):
        from apps.database.capabilities import Category, get_database
        pg = get_database("postgresql")
        self.assertEqual(pg.category, Category.RELATIONAL)
        for cap in ("sql", "transactions", "foreign_keys", "joins", "migrations", "json"):
            self.assertTrue(pg.supports(cap), cap)

    def test_key_value_has_no_relational_capabilities(self):
        from apps.database.capabilities import Category, get_database
        redis = get_database("redis")
        self.assertEqual(redis.category, Category.KEY_VALUE)
        for cap in ("sql", "foreign_keys", "joins", "migrations", "fixed_schema"):
            self.assertFalse(redis.supports(cap), cap)

    def test_document_store_shape(self):
        from apps.database.capabilities import Category, get_database
        mongo = get_database("mongodb")
        self.assertEqual(mongo.category, Category.DOCUMENT)
        self.assertFalse(mongo.supports("sql"))
        self.assertFalse(mongo.supports("foreign_keys"))
        self.assertTrue(mongo.supports("json"))

    def test_registry_is_extensible_across_categories(self):
        from apps.database.capabilities import Category, databases_by_category
        self.assertTrue(databases_by_category(Category.SEARCH))   # elasticsearch
        self.assertTrue(databases_by_category(Category.GRAPH))    # neo4j
        self.assertTrue(databases_by_category(Category.DISTRIBUTED_SQL))

    def test_unknown_capability_raises(self):
        from apps.database.capabilities import get_database
        with self.assertRaises(ValueError):
            get_database("sqlite").supports("time_travel")


class ProviderTests(SimpleTestCase):
    def test_sqlite_provider_is_real(self):
        from apps.database.providers import get_provider
        p = get_provider("sqlite")  # in-memory
        self.assertTrue(p.health_check()["ok"])
        p.execute_query("CREATE TABLE task (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        schema = p.inspect_schema()
        self.assertIn("task", schema["tables"])
        cols = {c["name"] for c in schema["tables"]["task"]["columns"]}
        self.assertEqual(cols, {"id", "title"})
        self.assertEqual(schema["tables"]["task"]["primary_key"], ["id"])
        p.disconnect()

    def test_unimplemented_provider_fails_honestly(self):
        from apps.database.providers import ProviderUnavailable, get_provider
        with self.assertRaises(ProviderUnavailable):
            get_provider("postgresql")   # capabilities known, adapter not built yet
        with self.assertRaises(ProviderUnavailable):
            get_provider("does-not-exist")


class SelectionTests(SimpleTestCase):
    def test_requirement_driven_not_always_postgres(self):
        from apps.database.selection import recommend_database
        cases = {
            "invoicing, payments and financial reporting": "postgresql",
            "a simple local prototype": "sqlite",
            "high-volume session cache and rate limiting": "redis",
            "store unstructured documents with a flexible schema": "mongodb",
            "search-heavy full-text product catalogue": "elasticsearch",
        }
        for text, expected in cases.items():
            self.assertEqual(recommend_database(text)["database"], expected, text)

    def test_generic_default_is_flagged_unmatched(self):
        from apps.database.selection import recommend_database
        rec = recommend_database("an application")
        self.assertEqual(rec["database"], "postgresql")
        self.assertFalse(rec["matched"])  # a stated default, not a requirement match


class MigrationClassifyTests(SimpleTestCase):
    def test_create_is_low_risk_no_approval(self):
        from apps.database.migration_service import classify
        from apps.database.models import MigrationOp, RiskLevel
        risk, approval = classify("CREATE TABLE t (id INTEGER)", MigrationOp.CREATE)
        self.assertEqual(risk, RiskLevel.LOW)
        self.assertFalse(approval)

    def test_destructive_sql_forces_approval(self):
        from apps.database.migration_service import classify
        from apps.database.models import MigrationOp, RiskLevel
        for sql in ("DROP TABLE users", "ALTER TABLE t DROP COLUMN c",
                    "DELETE FROM t", "TRUNCATE t"):
            risk, approval = classify(sql, MigrationOp.ALTER)
            self.assertEqual(risk, RiskLevel.HIGH, sql)
            self.assertTrue(approval, sql)

    def test_drop_operation_requires_approval(self):
        from apps.database.migration_service import classify
        _, approval = classify("DROP INDEX idx", "drop")
        self.assertTrue(approval)


class MigrationServiceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        from apps.database.providers import get_provider
        self.provider = get_provider("sqlite")  # one in-memory connection for the test

    def _plan(self, **kw):
        from apps.database.migration_service import plan_migration
        defaults = dict(project=self.project, database_id="sqlite", operation="create")
        defaults.update(kw)
        return plan_migration(**defaults)

    def test_plan_rejects_non_migration_database(self):
        from apps.database.migration_service import MigrationError, plan_migration
        with self.assertRaises(MigrationError):
            plan_migration(project=self.project, database_id="redis", operation="create",
                           description="x", up_sql="SET k v")

    def test_apply_creates_table_for_real(self):
        from apps.database.models import MigrationStatus
        m = self._plan(
            description="create task",
            up_sql="CREATE TABLE task (id INTEGER PRIMARY KEY, title TEXT)",
            down_sql="DROP TABLE task",
        )
        self.assertEqual(m.status, MigrationStatus.PLANNED)  # non-destructive
        from apps.database.migration_service import apply
        apply(m, self.provider)
        m.refresh_from_db()
        self.assertEqual(m.status, MigrationStatus.APPLIED)
        self.assertIsNotNone(m.execution_ms)
        self.assertIn("task", self.provider.inspect_schema()["tables"])

    def test_destructive_blocked_until_approved(self):
        from apps.database.migration_service import MigrationError, apply, approve
        from apps.database.models import MigrationStatus
        # seed a table to drop
        self.provider.execute_query("CREATE TABLE old (id INTEGER)")
        m = self._plan(operation="drop", description="drop old",
                       up_sql="DROP TABLE old", down_sql="")
        self.assertEqual(m.status, MigrationStatus.AWAITING_APPROVAL)
        self.assertTrue(m.requires_approval)
        with self.assertRaises(MigrationError):
            apply(m, self.provider)                       # blocked: not approved
        user = get_user_model().objects.create_user(email="a@b.com", password="x")
        approve(m, user)
        apply(m, self.provider)                           # now allowed
        m.refresh_from_db()
        self.assertEqual(m.status, MigrationStatus.APPLIED)
        self.assertNotIn("old", self.provider.inspect_schema()["tables"])

    def test_rollback_reverses_the_change(self):
        from apps.database.migration_service import apply, rollback
        from apps.database.models import MigrationStatus
        m = self._plan(description="add widget",
                       up_sql="CREATE TABLE widget (id INTEGER)",
                       down_sql="DROP TABLE widget")
        apply(m, self.provider)
        self.assertIn("widget", self.provider.inspect_schema()["tables"])
        rollback(m, self.provider)
        m.refresh_from_db()
        self.assertEqual(m.status, MigrationStatus.ROLLED_BACK)
        self.assertNotIn("widget", self.provider.inspect_schema()["tables"])

    def test_irreversible_migration_cannot_rollback(self):
        from apps.database.migration_service import MigrationError, rollback
        m = self._plan(description="no down", up_sql="CREATE TABLE t (id INTEGER)")
        with self.assertRaises(MigrationError):
            rollback(m, self.provider)


class ParsingTests(SimpleTestCase):
    def test_parses_models_and_fields(self):
        models = parse_schema(SCHEMA_JSON)["models"]
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["fields"][0]["name"], "email")
        self.assertFalse(models[0]["fields"][0]["nullable"])

    def test_accepts_entities_key_and_string_fields(self):
        payload = json.dumps({"entities": [{"name": "X", "fields": ["a", "b"]}]})
        models = parse_schema(payload)["models"]
        self.assertEqual(len(models[0]["fields"]), 2)

    def test_garbage_empty(self):
        self.assertEqual(parse_schema("[stub] db")["models"], [])


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("database"), DatabaseAgent)

    def test_no_prod_data_capability(self):
        caps = {c.value for c in DatabaseAgent.capabilities}
        self.assertIn("write_migrations", caps)
        self.assertNotIn("access_production_secrets", caps)


class DatabaseFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "tasks", title="Tasks", content="CRUD tasks"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="database", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_models(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCHEMA_JSON)):
            task = self._run()
        self.assertEqual(task.output["models_written"], 2)
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.SCHEMA).count(), 2)

    def test_offline_zero(self):
        self.assertEqual(self._run().output["models_written"], 0)

    def test_generates_and_verifies_model_files(self):
        payload = json.dumps(
            {
                "models": [{"name": "Task", "fields": [{"name": "title", "type": "text"}]}],
                "files": [
                    {
                        "path": "backend/apps/core/models.py",
                        "content": "class Task:\n    title = ''\n",
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete",
                    side_effect=_fake(payload),
                ):
                    orch = Orchestrator()
                    task = orch.create_task(
                        project=self.project, agent_key="database", input={}
                    )
                    orch.run_task(task)
                    task.refresh_from_db()
                    files = repo_for_project(self.project).list_files()
        self.assertEqual(task.output["models_written"], 1)
        self.assertEqual(task.output["files_generated"], 1)
        self.assertTrue(task.output["verified"])
        self.assertIn("backend/apps/core/models.py", files)

    def test_compile_repair_fixes_broken_model_code(self):
        # First attempt's model file has a syntax error; the repair round fixes it.
        broken = json.dumps({
            "models": [{"name": "Task", "fields": [{"name": "title", "type": "text"}]}],
            "files": [{"path": "backend/apps/core/models.py", "content": "class Task(:\n  pass\n"}],
        })
        fixed = json.dumps({
            "models": [{"name": "Task", "fields": [{"name": "title", "type": "text"}]}],
            "files": [{"path": "backend/apps/core/models.py", "content": "class Task:\n    title = ''\n"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete",
                    side_effect=_sequence(broken, fixed),
                ):
                    orch = Orchestrator()
                    task = orch.create_task(project=self.project, agent_key="database", input={})
                    orch.run_task(task)
                    task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertTrue(task.output["verified"])          # compiled after repair
        self.assertEqual(task.output["repair_rounds"], 1)  # one compile-repair round
        self.assertEqual(task.output["files_generated"], 1)

    def test_recommends_database_when_none_chosen(self):
        # No database in the technology profile → recommend one + record it.
        task = self._run()  # offline; setUp requirement is generic ("CRUD tasks")
        self.assertTrue(task.output["database_recommended"])
        self.assertEqual(task.output["database"], "postgresql")
        self.assertEqual(task.output["database_category"], "relational")
        decision = ProjectContext(self.project).get(
            ContextKind.TECH_DECISION, "database-recommendation"
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.data["database"], "postgresql")

    def test_non_relational_recommendation_notes_capabilities(self):
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "cache", title="Cache",
            content="high-volume session cache and rate limiting",
        )
        task = self._run()
        self.assertEqual(task.output["database"], "redis")
        self.assertEqual(task.output["database_category"], "key_value")
        self.assertFalse(task.output["database_capabilities"]["migrations"])
        self.assertTrue(any("migrations do not apply" in m for m in task.messages))

    def test_chosen_database_is_not_overridden(self):
        self.project.technology = {"database": "mysql"}
        self.project.save(update_fields=["technology"])
        task = self._run()
        self.assertEqual(task.output["database"], "mysql")
        self.assertFalse(task.output["database_recommended"])  # respected the choice

    def test_non_django_backend_records_schema_only(self):
        # A backend DevForge can't generate yet -> design recorded, no code, honest.
        self.project.technology = {"backend": "fastapi", "database": "postgresql"}
        self.project.save(update_fields=["technology"])
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCHEMA_JSON)):
            task = self._run()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["models_written"], 2)  # schema still designed
        self.assertFalse(task.output["code_generated"])  # no Django code generated
        self.assertEqual(task.output["files_generated"], 0)
        self.assertEqual(task.output["backend_stack"], "fastapi")

    def test_fails_without_upstream(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="database", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
