import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/shared"))
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
sys.path.insert(0, str(ROOT / "services/api/identity"))
import data_contracts
from bsv_catalog_contract import semantic_attributes
import config as identity_config


class DataContractTests(unittest.TestCase):
    def test_registry_reuses_ownership_and_marks_postgres_schema_pending(self):
        registry = data_contracts.load_registry()
        self.assertEqual(registry["database"]["primary_url_env"], "BSV_DB_URL")
        self.assertEqual(registry["database"]["database_name"], "bsv_all_prod")
        self.assertEqual(registry["database"]["schema_status"], "BLOCKED_WORKBUDDY_FIELD_DICTIONARY_REVIEW")
        self.assertTrue(registry["registry_refs"]["ownership_is_authoritative"])
        identity_sources = json.loads((ROOT / "config/modules/identity-data-sources.json").read_text())
        self.assertEqual(identity_sources["routes"]["A"]["primary_url_env"], "BSV_DB_URL")
        self.assertEqual(identity_sources["routes"]["A"]["compatibility_url_env"], "BSV_DB_A_URL")
        change_routing = json.loads((ROOT / "config/change-routing.json").read_text())
        self.assertEqual(change_routing["data_source_namespaces"]["identity.A"]["runtime_env"], "BSV_DB_URL")
        for ref in registry["registry_refs"]["module_data_sources"]:
            self.assertTrue((ROOT / ref).is_file(), ref)
        for domain in registry["domains"].values():
            ref = domain.get("api_contract_ref")
            if ref:
                self.assertTrue((ROOT / ref.split("#", 1)[0]).is_file(), ref)

    def test_database_url_targets_only_registered_postgres_name_without_connecting(self):
        result = data_contracts.resolve_database(
            module="pos", environ={"BSV_DB_URL": "postgresql://user:password@localhost/bsv_all_prod"})
        self.assertEqual(result["kind"], "central")
        self.assertEqual(result["database"], "bsv_all_prod")
        self.assertNotIn("value", result)
        with self.assertRaises(ValueError):
            data_contracts.resolve_database(module="pos", environ={"BSV_DB_URL": "sqlite:///bsv_all_prod"})
        with self.assertRaises(ValueError):
            data_contracts.resolve_database(module="pos", environ={"BSV_DB_URL": "postgresql://u:p@localhost/bsv_identity_isolated_internal"})

    def test_legacy_configuration_remains_explicit_and_semantic_mapping_is_header_keyed(self):
        legacy = data_contracts.resolve_database(module="pos", environ={"BSV_DB_PATH": "/srv/data/pos.sqlite3"})
        self.assertEqual(legacy["kind"], "legacy")
        self.assertEqual(legacy["env_name"], "BSV_DB_PATH")
        self.assertNotIn("value", legacy)
        identity_legacy = data_contracts.resolve_database(module="identity", environ={"BSV_DB_A_URL": "sqlite:///isolated.db"})
        self.assertEqual(identity_legacy["env_name"], "BSV_DB_A_URL")
        mapped = semantic_attributes("C_现场成品", {
            "商品名称": "演示产品", "配方文字": "朗姆酒 30ml", "完整制作步骤": "摇匀"
        })
        self.assertEqual(mapped["name"], "演示产品")
        self.assertEqual(mapped["recipe_text"], "朗姆酒 30ml")
        self.assertEqual(mapped["recipe_steps"], "摇匀")
        self.assertNotIn("excel_column", json.dumps(mapped))

    def test_identity_a_uses_central_dsn_when_set_and_keeps_legacy_alias(self):
        central = "postgresql+psycopg://service:secret@localhost/bsv_all_prod"
        with patch.dict("os.environ", {"BSV_DB_URL": central, "BSV_APP_ENV": "staging",
                "BSV_SESSION_SECRET": "s"*40,"BSV_PRIVACY_PEPPER": "p"*40,
                "BSV_REGISTRATION_ENTITIES_JSON": '["DEMO_LEGAL"]'}, clear=True):
            self.assertEqual(identity_config.load_settings().db_a_url, central)
        legacy = "sqlite+pysqlite:///./runtime/identity-isolated.db"
        with patch.dict("os.environ", {"BSV_DB_A_URL": legacy, "BSV_APP_ENV": "isolated"}, clear=True):
            self.assertEqual(identity_config.load_settings().db_a_url, legacy)
        with patch.dict("os.environ", {"BSV_DB_URL": "postgresql://localhost/not_bsv_all_prod"}, clear=True):
            with self.assertRaises(RuntimeError):
                identity_config.load_settings()


if __name__ == "__main__":
    unittest.main()
